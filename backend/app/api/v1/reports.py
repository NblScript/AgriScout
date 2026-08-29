"""PatrolReport 巡检 AI 农事报告：查询与手动生成（建议线 L1）。"""
import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import patrol_or_404
from app.core.db import get_db
from app.models import PatrolReport
from app.schemas.patrol_report import PatrolReportOut, ReportGenerateOut
from app.services.llm_report import generate_report

router = APIRouter(tags=["reports"])




@router.get("/patrols/{patrol_id}/report", response_model=PatrolReportOut)
def get_report(patrol_id: int, db: Session = Depends(get_db)):
    patrol_or_404(db, patrol_id)
    report = (
        db.query(PatrolReport)
        .filter_by(patrol_id=patrol_id)
        .one_or_none()
    )
    if report is None:
        raise HTTPException(status_code=404, detail="该巡检尚未生成 AI 报告")
    return report


@router.post("/patrols/{patrol_id}/report/generate", response_model=ReportGenerateOut)
def generate(patrol_id: int, db: Session = Depends(get_db)):
    """生成/重生成巡检 AI 报告（同步等待 LLM，通常 5-30 秒）。"""
    patrol_or_404(db, patrol_id)
    try:
        report = generate_report(db, patrol_id)
    except ValueError as exc:  # 未配置 LLM
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except LookupError as exc:  # prompt 模板缺失（巡检存在性已在路由预检）
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except httpx.HTTPError as exc:  # 上游 LLM 网络/接口错误
        raise HTTPException(status_code=502, detail=f"LLM 上游错误：{exc}") from exc
    return {
        "patrol_id": report.patrol_id,
        "report_id": report.id,
        "model": report.model,
        "prompt_version": report.prompt_version,
    }
