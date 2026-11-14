from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from src.config.database import get_db
from src.constants.roles import TEAM_WRITE_ROLES
from src.controllers import team_controller
from src.middlewares.rbac import READ_ROLES, require_roles
from src.schemas.team import TeamPatch
from src.utils.pagination import page_params

router = APIRouter(prefix="/teams", tags=["teams"])


@router.get("")
def list_teams(
    limit: int = Query(50),
    offset: int = Query(0),
    db: Session = Depends(get_db),
    principal: dict = Depends(require_roles(*READ_ROLES)),
) -> dict:
    page = page_params(limit, offset)
    return team_controller.list_teams(db, principal, limit=page.limit, offset=page.offset)


@router.get("/{team_id}")
def get_team(
    team_id: int, db: Session = Depends(get_db), principal: dict = Depends(require_roles(*READ_ROLES))
) -> dict:
    return team_controller.get_team(db, team_id, principal)


@router.patch("/{team_id}")
def update_team(
    team_id: int,
    payload: TeamPatch,
    request: Request,
    db: Session = Depends(get_db),
    principal: dict = Depends(require_roles(*TEAM_WRITE_ROLES)),
) -> dict:
    return team_controller.update_team(db, team_id, payload.model_dump(exclude_unset=True), principal, request)
