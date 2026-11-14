"""团队分摊：一次成本运行里每个团队应承担的金额、占比与环比。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.models import Base
from src.utils.timeutil import utcnow


class Charge(Base):
    __tablename__ = "charges"
    __table_args__ = (UniqueConstraint("run_id", "team_id", name="uq_charges_run_team"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("cost_runs.id", ondelete="CASCADE"), index=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), index=True)
    amount_yuan: Mapped[float] = mapped_column(Float, default=0.0)
    ratio: Mapped[float] = mapped_column(Float, default=0.0)
    query_count: Mapped[int] = mapped_column(Integer, default=0)
    cached_saved_yuan: Mapped[float] = mapped_column(Float, default=0.0)
    mom_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    user_split: Mapped[list] = mapped_column(JSON, default=list)
    top_query: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
