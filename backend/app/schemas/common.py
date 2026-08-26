"""通用分页响应。"""
from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    """统一分页信封：items/total/skip/limit。"""

    items: list[T]
    total: int
    skip: int
    limit: int
