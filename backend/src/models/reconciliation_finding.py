"""核对差异明细：逐笔对账的每一条漏计/重复/单价不符/平台多计，全程留痕不删除。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.models import Base
from src.utils.timeutil import utcnow


class ReconciliationFinding(Base):
    __tablename__ = "reconciliation_findings"
    __table_args__ = (
        # 含 run_id：失败批次的残留明细保留不删，重试批次可独立写入而不撞键；单批次内仍防重复
        UniqueConstraint("run_id", "bill_id", "query_id", "diff_type", "duplicate_seq", name="uq_finding_run_bill_query_type"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("reconciliation_runs.id", ondelete="CASCADE"), index=True)
    bill_id: Mapped[int] = mapped_column(ForeignKey("supplier_bills.id", ondelete="CASCADE"), index=True)
    period: Mapped[str] = mapped_column(String(20), index=True)
    query_id: Mapped[str] = mapped_column(String(64), index=True)
    team_code: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    user_email: Mapped[str | None] = mapped_column(String(160), nullable=True)
    diff_type: Mapped[str] = mapped_column(String(24), index=True)
    # 账单内重复序号，duplicate 差异用；其余类型为 1
    duplicate_seq: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(16), default="open", index=True)
    bill_scanned_gb: Mapped[float] = mapped_column(Float, default=0.0)
    platform_scanned_gb: Mapped[float] = mapped_column(Float, default=0.0)
    bill_amount_yuan: Mapped[float] = mapped_column(Float, default=0.0)
    platform_amount_yuan: Mapped[float] = mapped_column(Float, default=0.0)
    # 差异金额 = 供应商应付 - 平台已计；正为平台少付，负为平台多计
    diff_amount_yuan: Mapped[float] = mapped_column(Float, default=0.0)
    bill_unit_price: Mapped[float] = mapped_column(Float, default=0.0)
    platform_unit_price: Mapped[float] = mapped_column(Float, default=0.0)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolver: Mapped[str | None] = mapped_column(String(160), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
