"""查询日志控制器。"""
from __future__ import annotations

from sqlalchemy.orm import Session

from src.services import query_log_service


def list_logs(db: Session, principal: dict, **filters) -> dict:
    return query_log_service.list_logs(db, principal, **filters)


def get_log(db: Session, log_id: int, principal: dict) -> dict:
    log = query_log_service.get_log(db, log_id, principal)
    return query_log_service.serialize(log)


def stats(db: Session, principal: dict, team_id: int | None = None) -> dict:
    return query_log_service.annotate_stats(db, principal, team_id)
