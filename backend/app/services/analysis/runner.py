"""分析任务执行器：逐点分析 + analysis_status 流转。

红线：本模块运行于 BackgroundTasks（请求已返回），必须经注入的会话工厂自建
Session；逐点提交使 M6 前端轮询能看到渐进进度。
"""
import logging
from collections.abc import Callable

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, selectinload

from app.models import Analysis, CapturePoint, Patrol
from app.services.analysis.base import Analyzer, CaptureContext
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

        patrol.analysis_status = "running"
        db.commit()

        analyzed = skipped = 0
        for point in patrol.capture_points:
            image = storage.open(point.photo_url) if point.photo_url else None
            if image is None:
                skipped += 1
                continue
            result = analyzer.analyze(
                image, _build_context(point, sowing_date, crop_name, crop_stages),
            )
            # 重分析幂等：清掉旧结果再写新
            db.execute(delete(Analysis).where(Analysis.capture_point_id == point.id))
            db.add(
                Analysis(
                    capture_point_id=point.id,
                    patrol_id=patrol.id,
                    analyzer_version=analyzer.version,
                    growth_stage=result.growth_stage,
                    vigor_level=result.vigor_level,
                    ndvi=result.ndvi,
                    disease_detections=result.disease_detections,
                    risk_score=result.risk_score,
                    detail={**(result.detail or {}), "crop": crop_name},
                )
            )
            analyzed += 1
            db.commit()  # 逐点提交 → 进度可轮询

        patrol.analysis_status = "done"
        patrol.notes = (
            f"analyzed={analyzed} skipped_no_photo={skipped} analyzer={analyzer.version}"
        ) if patrol.notes is None else patrol.notes
        db.commit()
        logger.info(
            "patrol %s analyzed: %s points, %s skipped", patrol_id, analyzed, skipped,
        )

        # 分析完成 → 触发建议生成（任务流水线阶段⑥，docs/05）
        try:
            from app.services.advice import generate_advices_for_patrol

            stats = generate_advices_for_patrol(db, patrol.id)
            logger.info("patrol %s advices generated: %s", patrol_id, stats)
        except Exception:  # noqa: BLE001 建议失败不影响分析结论，仅记录
            db.rollback()
            logger.exception("patrol %s advice generation failed", patrol_id)

        # 建议线 L1：LLM 巡检报告（主计划 §8.2）。未配置 LLM 静默跳过；失败只记日志
        try:
            from app.core.config import get_settings
            from app.services.llm_report import generate_report

            if get_settings().llm_enabled:
                report = generate_report(db, patrol.id)
                logger.info(
                    "patrol %s llm report generated (model=%s)", patrol_id, report.model,
                )
        except Exception:  # noqa: BLE001 报告失败不影响分析/建议结论
            db.rollback()
            logger.warning("patrol %s llm report generation failed", patrol_id, exc_info=True)
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
