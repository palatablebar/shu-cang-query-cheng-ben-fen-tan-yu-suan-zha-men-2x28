"""账期修正台账：确认发布时按差异涉及账期逐团队落地的修正金额，可审计、可重放。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.models import Base
from src.utils.timeutil import utcnow


class BillAdjustment(Base):
    __tablename__ = "bill_adjustments"
    __table_args__ = (
        UniqueConstraint("bill_id", "period", "team_code", "diff_type", name="uq_adjustment_bill_period_team_type"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    bill_id: Mapped[int] = mapped_column(ForeignKey("supplier_bills.id", ondelete="CASCADE"), index=True)
    run_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    period: Mapped[str] = mapped_column(String(20), index=True)
    team_code: Mapped[str] = mapped_column(String(40), index=True)
    diff_type: Mapped[str] = mapped_column(String(24), index=True)
    # 对团队分摊的修正金额（元）；duplicate 不改变平台分摊，恒为 0
    amount_yuan: Mapped[float] = mapped_column(Float, default=0.0)
    # 供应商应付口径修正金额（元），含 duplicate 冲红
    payable_delta_yuan: Mapped[float] = mapped_column(Float, default=0.0)
    finding_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="applied", index=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(String(160), default="system")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
