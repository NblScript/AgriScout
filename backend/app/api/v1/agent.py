"""Agent 诊断问答（建议线 L2）：提问 → function-calling 诊断 → 留痕。"""
import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models import AgentConversation, Patrol
from app.schemas.agent import AgentChatIn, AgentChatOut
from app.services.agent_chat import chat

router = APIRouter(tags=["agent"])


@router.post("/agent/chat", response_model=AgentChatOut)
def agent_chat(payload: AgentChatIn, db: Session = Depends(get_db)):
    if payload.patrol_id is not None:
        patrol = db.get(Patrol, payload.patrol_id)
        if patrol is None:
            raise HTTPException(status_code=404, detail="巡检任务不存在")
    try:
        result = chat(db, payload.question, payload.patrol_id)
    except ValueError as exc:  # 未配置 LLM
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except LookupError as exc:  # prompt 模板缺失
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except httpx.HTTPError as exc:  # 上游 LLM 错误
        raise HTTPException(status_code=502, detail=f"LLM 上游错误：{exc}") from exc

    row = AgentConversation(
        patrol_id=payload.patrol_id,
        question=payload.question,
        answer=result["answer"],
        tool_calls_trace=result["tool_calls_trace"],
        model=result["model"],
        prompt_version=result["prompt_version"],
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/agent/conversations", response_model=list[AgentChatOut])
def list_conversations(patrol_id: int | None = None, limit: int = 20, db: Session = Depends(get_db)):
    stmt = db.query(AgentConversation)
    if patrol_id is not None:
        stmt = stmt.filter(AgentConversation.patrol_id == patrol_id)
    return stmt.order_by(AgentConversation.created_at.desc()).limit(min(limit, 100)).all()
