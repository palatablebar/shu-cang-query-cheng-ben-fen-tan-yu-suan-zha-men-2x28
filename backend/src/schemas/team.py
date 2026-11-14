"""团队与查询日志入参。"""
from __future__ import annotations

from pydantic import BaseModel, Field


class TeamPatch(BaseModel):
    budget_yuan: float | None = Field(default=None, ge=0, le=10_000_000)
    cost_center: str | None = Field(default=None, min_length=3, max_length=40)
    owner: str | None = Field(default=None, min_length=2, max_length=80)
    prev_month_yuan: float | None = Field(default=None, ge=0, le=10_000_000)
    note: str | None = Field(default=None, max_length=1000)


class QueryLogIn(BaseModel):
    """单条查询导入（管理员补录场景）。"""

    query_id: str = Field(min_length=4, max_length=64, pattern=r"^[A-Za-z0-9:_-]+$")
    user_email: str = Field(min_length=5, max_length=160)
    team_id: int = Field(gt=0)
    sql_digest: str = Field(min_length=4, max_length=160)
    scanned_gb: float = Field(ge=0, le=100_000)
    duration_ms: int = Field(ge=0, le=86_400_000)
    cache_hit: bool = False
    status: str = "success"
