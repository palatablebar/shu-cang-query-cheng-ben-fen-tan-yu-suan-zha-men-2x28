from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from src.config.database import get_db
from src.controllers import export_controller
from src.middlewares.rbac import READ_ROLES, require_roles

router = APIRouter(tags=["charges"])


@router.get("/charges")
def list_charges(
    run_id: int | None = None,
    team_id: int | None = None,
    limit: int = Query(50),
    offset: int = Query(0),
    db: Session = Depends(get_db),
    principal: dict = Depends(require_roles(*READ_ROLES)),
) -> dict:
    return export_controller.list_charges(
        db, principal, run_id=run_id, team_id=team_id, limit=limit, offset=offset
    )
