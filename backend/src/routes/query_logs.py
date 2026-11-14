from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from src.config.database import get_db
from src.controllers import query_log_controller
from src.middlewares.rbac import READ_ROLES, require_roles
from src.utils.pagination import page_params

router = APIRouter(prefix="/query-logs", tags=["query-logs"])


@router.get("")
def list_logs(
    team_id: int | None = None,
    status: str | None = None,
    anomaly: bool | None = None,
    cache_hit: bool | None = None,
    q: str | None = None,
    limit: int = Query(20),
    offset: int = Query(0),
    db: Session = Depends(get_db),
    principal: dict = Depends(require_roles(*READ_ROLES)),
) -> dict:
    page = page_params(limit, offset)
    return query_log_controller.list_logs(
        db,
        principal,
        team_id=team_id,
        status=status,
        anomaly=anomaly,
        cache_hit=cache_hit,
        q=q,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/stats")
def log_stats(
    team_id: int | None = None,
    db: Session = Depends(get_db),
    principal: dict = Depends(require_roles(*READ_ROLES)),
) -> dict:
    return query_log_controller.stats(db, principal, team_id)


@router.get("/{log_id}")
def get_log(
    log_id: int, db: Session = Depends(get_db), principal: dict = Depends(require_roles(*READ_ROLES))
) -> dict:
    return query_log_controller.get_log(db, log_id, principal)
