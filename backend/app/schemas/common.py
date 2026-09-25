"""通用分页响应与 PATCH 校验助手。"""
from collections.abc import Iterable
from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    """统一分页信封：items/total/skip/limit。"""

    items: list[T]
    total: int
    skip: int
    limit: int


def reject_explicit_nulls(model: BaseModel, fields: Iterable[str]) -> None:
    """PATCH 语义：未传=不改；显式传 null 的非空列直接 422，而不是落库时触发 NOT NULL 变 500。"""
    bad = sorted(f for f in fields if f in model.model_fields_set and getattr(model, f) is None)
    if bad:
        raise ValueError(f"以下字段不能置空：{', '.join(bad)}")
