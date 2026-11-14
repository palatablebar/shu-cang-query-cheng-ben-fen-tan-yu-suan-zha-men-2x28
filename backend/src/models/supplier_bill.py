"""供应商账单：云厂商按整月扫描量一口价结算的账单头（一口价 vs 平台逐条计费口径）。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.models import Base
from src.utils.timeutil import utcnow


class SupplierBill(Base):
    __tablename__ = "supplier_bills"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    bill_no: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    vendor: Mapped[str] = mapped_column(String(120), default="clickhouse-cloud")
    period: Mapped[str] = mapped_column(String(20), index=True)
    source_filename: Mapped[str] = mapped_column(String(255), default="")
    file_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    line_count: Mapped[int] = mapped_column(Integer, default=0)
    total_amount_yuan: Mapped[float] = mapped_column(Float, default=0.0)
    total_scanned_gb: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(20), default="imported", index=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    confirmed_by: Mapped[str | None] = mapped_column(String(160), nullable=True)
    published_run_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
