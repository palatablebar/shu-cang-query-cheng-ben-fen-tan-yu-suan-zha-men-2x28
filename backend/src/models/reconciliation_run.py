"""核对批次：对一张供应商账单发起一次核对；成功批次幂等复用，失败批次留痕可重试。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.models import Base
from src.utils.timeutil import utcnow


class ReconciliationRun(Base):
    __tablename__ = "reconciliation_runs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    recon_no: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    bill_id: Mapped[int] = mapped_column(ForeignKey("supplier_bills.id", ondelete="CASCADE"), index=True)
    period: Mapped[str] = mapped_column(String(20), index=True)
    operator_email: Mapped[str] = mapped_column(String(160), default="system")
    status: Mapped[str] = mapped_column(String(20), default="running", index=True)
    bill_total_yuan: Mapped[float] = mapped_column(Float, default=0.0)
    platform_total_yuan: Mapped[float] = mapped_column(Float, default=0.0)
    diff_total_yuan: Mapped[float] = mapped_column(Float, default=0.0)
    diff_counts: Mapped[dict] = mapped_column(JSON, default=dict)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
