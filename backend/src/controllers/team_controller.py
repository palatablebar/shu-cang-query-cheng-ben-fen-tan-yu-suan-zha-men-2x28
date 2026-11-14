"""团队控制器：预算调整记领域审计。"""
from __future__ import annotations

from fastapi import Request
from sqlalchemy.orm import Session

from src.services import audit_service, team_service


def list_teams(db: Session, principal: dict, **filters) -> dict:
    return team_service.list_teams(db, principal, **filters)


def get_team(db: Session, team_id: int, principal: dict) -> dict:
    team = team_service.get_team(db, team_id, principal)
    latest = team_service.latest_run(db)
    charge = alert = None
    if latest is not None:
        from sqlalchemy import select

        from src.models.budget_alert import BudgetAlert
        from src.models.charge import Charge

        charge = db.scalar(select(Charge).where(Charge.run_id == latest.id, Charge.team_id == team.id))
        alert = db.scalar(select(BudgetAlert).where(BudgetAlert.run_id == latest.id, BudgetAlert.team_id == team.id))
    return team_service.serialize(team, charge, alert)


def update_team(db: Session, team_id: int, payload: dict, principal: dict, request: Request) -> dict:
    team = team_service.get_team(db, team_id, principal)
    before = {"budget_yuan": team.budget_yuan, "cost_center": team.cost_center, "owner": team.owner}
    team_service.update_team(db, team, payload)
    audit_service.record(
        db,
        actor_email=principal["email"],
        actor_role=principal["role"],
        action="team.update",
        entity="team",
        entity_id=team.id,
        detail={"before": before, "after": {key: getattr(team, key) for key in before}},
        ip=request.client.host if request.client else None,
    )
    db.commit()
    return get_team(db, team.id, principal)
