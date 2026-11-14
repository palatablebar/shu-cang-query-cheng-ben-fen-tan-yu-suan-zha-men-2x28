"""查询日志服务：筛选（团队/异常/缓存/状态）+ 序列化。"""
from __future__ import annotations

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from src.constants.enums import QUERY_STATUS_LABELS
from src.models.query_log import QueryLog
from src.models.team import Team
from src.services import team_service
from src.utils.errors import not_found
from src.utils.timeutil import iso_utc


def serialize(log: QueryLog, team: Team | None = None) -> dict:
    return {
        "id": log.id,
        "query_id": log.query_id,
        "user_email": log.user_email,
        "team_id": log.team_id,
        "team_name": team.name if team else None,
        "team_code": team.code if team else None,
        "sql_digest": log.sql_digest,
        "scanned_gb": round(log.scanned_gb, 3),
        "duration_ms": log.duration_ms,
        "cache_hit": log.cache_hit,
        "status": log.status,
        "status_label": QUERY_STATUS_LABELS.get(log.status, log.status),
        "queried_at": iso_utc(log.queried_at),
        "cost_yuan": round(log.cost_yuan, 4),
        "is_anomaly": log.is_anomaly,
        "anomaly_score": round(log.anomaly_score, 4),
        "anomaly_reason": log.anomaly_reason,
    }


def list_logs(
    db: Session,
    principal: dict,
    *,
    team_id: int | None = None,
    status: str | None = None,
    anomaly: bool | None = None,
    cache_hit: bool | None = None,
    q: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> dict:
    team_id = team_service.scoped_team_id(principal, team_id)
    stmt = select(QueryLog)
    count_stmt = select(func.count()).select_from(QueryLog)
    conditions = []
    if team_id:
        conditions.append(QueryLog.team_id == team_id)
    if status:
        conditions.append(QueryLog.status == status)
    if anomaly is not None:
        conditions.append(QueryLog.is_anomaly.is_(anomaly))
    if cache_hit is not None:
        conditions.append(QueryLog.cache_hit.is_(cache_hit))
    if q:
        like = f"%{q.strip()}%"
        conditions.append(
            or_(QueryLog.query_id.ilike(like), QueryLog.user_email.ilike(like), QueryLog.sql_digest.ilike(like))
        )
    for condition in conditions:
        stmt = stmt.where(condition)
        count_stmt = count_stmt.where(condition)
    total = db.scalar(count_stmt) or 0
    rows = db.scalars(stmt.order_by(QueryLog.scanned_gb.desc(), QueryLog.id).limit(limit).offset(offset)).all()
    teams = {team.id: team for team in db.scalars(select(Team)).all()}
    return {
        "items": [serialize(row, teams.get(row.team_id)) for row in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


def annotate_stats(db: Session, principal: dict, team_id: int | None = None) -> dict:
    team_id = team_service.scoped_team_id(principal, team_id)
    stmt = select(func.count()).select_from(QueryLog)
    if team_id:
        stmt = stmt.where(QueryLog.team_id == team_id)
    total = db.scalar(stmt) or 0
    anomaly_stmt = select(func.count()).select_from(QueryLog).where(QueryLog.is_anomaly.is_(True))
    if team_id:
        anomaly_stmt = anomaly_stmt.where(QueryLog.team_id == team_id)
    anomalies = db.scalar(anomaly_stmt) or 0
    return {"queries": total, "anomalies": anomalies}


def get_log(db: Session, log_id: int, principal: dict) -> QueryLog:
    log = db.get(QueryLog, log_id)
    if log is None:
        raise not_found("query_log", log_id)
    team_service.assert_team_scope(principal, log.team_id)
    return log
