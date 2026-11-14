"""供应商账单行：账单内逐笔查询的扫描量、供应商计费与重复序号。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from src.models import Base
from src.utils.timeutil import utcnow


class SupplierBillItem(Base):
    __tablename__ = "supplier_bill_items"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    bill_id: Mapped[int] = mapped_column(ForeignKey("supplier_bills.id", ondelete="CASCADE"), index=True)
    query_id: Mapped[str] = mapped_column(String(64), index=True)
    team_code: Mapped[str] = mapped_column(String(40), index=True)
    user_email: Mapped[str] = mapped_column(String(160), default="")
    scanned_gb: Mapped[float] = mapped_column(Float, default=0.0)
    unit_price: Mapped[float] = mapped_column(Float, default=0.0)
    amount_yuan: Mapped[float] = mapped_column(Float, default=0.0)
    queried_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # 同一 query_id 在账单内第几次出现（从 1 开始）；> 1 即供应商重复计费
    duplicate_seq: Mapped[int] = mapped_column(Integer, default=1)
    raw_line: Mapped[str] = mapped_column(String(1000), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
