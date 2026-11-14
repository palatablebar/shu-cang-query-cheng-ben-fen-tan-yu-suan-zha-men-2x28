"""供应商对账入参。"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class SupplierBillIn(BaseModel):
    period: str = Field(pattern=r"^\d{4}-\d{2}$")
    filename: str = Field(default="supplier-bill.csv", max_length=255)
    csv_text: str = Field(min_length=1, max_length=5_000_000)


class FindingReviewIn(BaseModel):
    status: Literal["applied", "dismissed"]
    note: str | None = Field(default=None, max_length=1000)
