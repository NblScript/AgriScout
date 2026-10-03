"""分析任务执行器：逐点分析 + analysis_status 流转。

红线：本模块运行于 BackgroundTasks（请求已返回），必须经注入的会话工厂自建
Session；逐点提交使 M6 前端轮询能看到渐进进度。
"""
import logging
from collections.abc import Callable

from PIL import Image
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session, selectinload

from app.models import Analysis, CapturePoint, Patrol
from app.services.analysis.base import Analyzer, CaptureContext
from app.services.analysis.image_quality import METHOD as IQ_METHOD
from app.services.analysis.image_quality import assess_image_quality
from app.services.storage import Storage

logger = logging.getLogger("agriscout.analysis")


def _build_context(point: CapturePoint, sowing_date, crop_name, crop_stages) -> CaptureContext:
    return CaptureContext(
        captured_at=point.captured_at,
        lng=point.lng,
        lat=point.lat,
        sowing_date=sowing_date,
        crop_name=crop_name,
        crop_stages=crop_stages,
    )


def run_patrol_analysis(
    patrol_id: int,
    analyzer: Analyzer,
    storage: Storage,
    session_factory: Callable[[], Session],
) -> None:
    """对整趟巡检执行逐点分析。异常只标记 error，不向外抛（后台任务无接收方）。"""
    db = session_factory()
    try:
        patrol = db.scalars(
            select(Patrol)
            .options(
                selectinload(Patrol.capture_points).selectinload(CapturePoint.analysis),
                selectinload(Patrol.planting),
                selectinload(Patrol.capture_points).selectinload(CapturePoint.weather),
            )
            .where(Patrol.id == patrol_id)
        ).first()
        if patrol is None:
            logger.warning("analysis skipped: patrol %s not found", patrol_id)
            return

        planting = patrol.planting
        crop = planting.crop if planting else None
        # 关联加载 crop（planting.crop 懒加载在会话内可用）
        sowing_date = planting.sowing_date if planting else None
        crop_name = None
        crop_stages: list[dict] = []
        if crop is not None:
            crop_name = crop.name
            crop_stages = list(crop.stages or [])

        # 原子抢占：仅当非 running 时翻转，防止并发重分析互相覆盖 Analysis 行
        claimed = db.execute(
            update(Patrol)
            .where(Patrol.id == patrol_id, Patrol.analysis_status != "running")
            .values(analysis_status="running")
        ).rowcount
        db.commit()
        if not claimed:
            logger.warning("analysis skipped: patrol %s already running", patrol_id)
            return

        analyzed = skipped = bad_image = 0
        for point in patrol.capture_points:
            image = storage.open(point.photo_url) if point.photo_url else None
            if image is None:
                skipped += 1
                continue
            try:
                result = analyzer.analyze(
                    image, _build_context(point, sowing_date, crop_name, crop_stages),
                )
            except (OSError, Image.DecompressionBombError):
                # 单张照片解不开（截断/非图片/超大）是该点的数据问题，跳过继续；
                # 模型缺失等系统性错误（RuntimeError 等）仍让整趟标记 error，不被静默吞掉
                bad_image += 1
                logger.warning(
                    "patrol %s point seq=%s photo undecodable: %s",
                    patrol_id, point.seq, point.photo_url, exc_info=True,
                )
                continue
            # 图像质量与分析器无关，每个分析的点都写（计划 0016 阶段 A6）
            try:
                image_quality = assess_image_quality(image)
            except (OSError, Image.DecompressionBombError) as exc:
                image_quality = {"method": IQ_METHOD, "ok": False, "reasons": [f"undecodable: {str(exc)[:120]}"]}
            # 重分析幂等：清掉旧结果再写新
            db.execute(delete(Analysis).where(Analysis.capture_point_id == point.id))
            db.add(
                Analysis(
                    capture_point_id=point.id,
                    # 用参数而非 patrol.id：逐点 commit 后 patrol 已过期，读它会把整趟采样点重载一遍（大包 O(n²)）
                    patrol_id=patrol_id,
                    analyzer_version=analyzer.version,
                    growth_stage=result.growth_stage,
                    vigor_level=result.vigor_level,
                    ndvi=result.ndvi,
                    disease_detections=result.disease_detections,
                    risk_score=result.risk_score,
                    detail={**(result.detail or {}), "crop": crop_name, "image_quality": image_quality},
                )
            )
            analyzed += 1
            db.commit()  # 逐点提交 → 进度可轮询

        if bad_image and not analyzed:
            # 一张都没解开更像是系统性问题（编码器/依赖异常），不当作正常完成
            raise RuntimeError(f"巡检 {patrol_id} 的 {bad_image} 张照片全部无法解码")

        # 分析完成 → 先生成建议（任务流水线阶段⑥，ARCHITECTURE.md「数据流」），再对外宣告 done：
        # 客户端（模拟器/前端）以 analysis_status=done 为「结果齐了」的信号，
        # 旧顺序先提交 done 再生成建议，轮询方会读到空建议列表。
        try:
            from app.services.advice import generate_advices_for_patrol

            stats = generate_advices_for_patrol(db, patrol.id)
            logger.info("patrol %s advices generated: %s", patrol_id, stats)
        except Exception:  # noqa: BLE001 建议失败不影响分析结论，仅记录
            db.rollback()
            logger.exception("patrol %s advice generation failed", patrol_id)

        patrol = db.get(Patrol, patrol_id)
        patrol.analysis_status = "done"
        # 系统统计写入 notes 头部；重分析时替换（否则旧 analyzer 版本的统计滞留）。
        # 用户手写过的 notes（非系统格式）不覆写，统计只进日志——不复用语义。
        stats_note = (
            f"analyzed={analyzed} skipped_no_photo={skipped} bad_image={bad_image} "
            f"analyzer={analyzer.version}"
        )
        if patrol.notes is None or patrol.notes.startswith("analyzed="):
            patrol.notes = stats_note
        else:
            logger.info("patrol %s stats (user notes kept): %s", patrol_id, stats_note)
        db.commit()
        logger.info(
            "patrol %s analyzed: %s points, %s skipped, %s bad image",
            patrol_id, analyzed, skipped, bad_image,
        )
    except Exception:
        db.rollback()
        try:
            patrol_ref = db.get(Patrol, patrol_id)
            if patrol_ref is not None:
                patrol_ref.analysis_status = "error"
                db.commit()
        except Exception:  # noqa: BLE001 标记失败也不能掩盖原始异常
            db.rollback()
        logger.exception("patrol %s analysis failed", patrol_id)
    finally:
        db.close()
