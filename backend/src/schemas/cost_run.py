"""成本运行与告警入参。"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class CostRunIn(BaseModel):
    period: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}$")
    scan_price: float | None = Field(default=None, gt=0, le=1)
    compute_price: float | None = Field(default=None, gt=0, le=0.01)
    cache_discount: float | None = Field(default=None, gt=0, le=1)
    trigger: str = Field(default="manual", max_length=20)


class AlertReviewIn(BaseModel):
    status: Literal["pending", "confirmed", "dismissed"]
    note: str | None = Field(default=None, max_length=1000)
