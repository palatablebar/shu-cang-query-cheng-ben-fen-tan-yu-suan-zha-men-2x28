from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from src.config.database import get_db
from src.constants.roles import ALERT_REVIEW_ROLES
from src.controllers import export_controller
from src.middlewares.rbac import READ_ROLES, require_roles
from src.schemas.cost_run import AlertReviewIn

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get("")
def list_alerts(
    run_id: int | None = None,
    team_id: int | None = None,
    level: str | None = None,
    status: str | None = None,
    limit: int = Query(50),
    offset: int = Query(0),
    db: Session = Depends(get_db),
    principal: dict = Depends(require_roles(*READ_ROLES)),
) -> dict:
    return export_controller.list_alerts(
        db, principal, run_id=run_id, team_id=team_id, level=level, status=status, limit=limit, offset=offset
    )


@router.patch("/{alert_id}/review")
def review_alert(
    alert_id: int,
    payload: AlertReviewIn,
    request: Request,
    db: Session = Depends(get_db),
    principal: dict = Depends(require_roles(*ALERT_REVIEW_ROLES)),
) -> dict:
    return export_controller.review_alert(db, alert_id, payload.model_dump(), principal, request)
