"""预算告警服务：分档列表、处置（复核）。"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.constants.enums import (
    ALERT_LEVEL_LABELS,
    ALERT_STATUS_LABELS,
    GATE_ACTION_LABELS,
    AlertStatus,
)
from src.models.budget_alert import BudgetAlert
from src.models.team import Team
from src.services import team_service
from src.utils.errors import not_found
from src.utils.timeutil import iso_utc, utcnow


def serialize(alert: BudgetAlert, team: Team | None) -> dict:
    return {
        "id": alert.id,
        "run_id": alert.run_id,
        "team_id": alert.team_id,
        "team_code": team.code if team else None,
        "team_name": team.name if team else None,
        "cost_center": team.cost_center if team else None,
        "owner": team.owner if team else None,
        "budget_yuan": round(team.budget_yuan, 2) if team else 0.0,
        "forecast_yuan": round(alert.forecast_yuan, 2),
        "ratio": round(alert.ratio, 4),
        "level": alert.level,
        "level_label": ALERT_LEVEL_LABELS.get(alert.level, alert.level),
        "gate_action": alert.gate_action,
        "gate_action_label": GATE_ACTION_LABELS.get(alert.gate_action, alert.gate_action),
        "status": alert.status,
        "status_label": ALERT_STATUS_LABELS.get(alert.status, alert.status),
        "note": alert.note,
        "reviewer": alert.reviewer,
        "reviewed_at": iso_utc(alert.reviewed_at),
        "created_at": iso_utc(alert.created_at),
    }


def list_alerts(
    db: Session,
    principal: dict,
    *,
    run_id: int | None = None,
    team_id: int | None = None,
    level: str | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    team_id = team_service.scoped_team_id(principal, team_id)
    if run_id is None:
        latest = team_service.latest_run(db)
        run_id = latest.id if latest else None
    if run_id is None:
        return {"items": [], "total": 0, "limit": limit, "offset": offset, "run_id": None}
    conditions = [BudgetAlert.run_id == run_id]
    if team_id:
        conditions.append(BudgetAlert.team_id == team_id)
    if level:
        conditions.append(BudgetAlert.level == level)
    if status:
        conditions.append(BudgetAlert.status == status)
    stmt = select(BudgetAlert)
    count_stmt = select(func.count()).select_from(BudgetAlert)
    for condition in conditions:
        stmt = stmt.where(condition)
        count_stmt = count_stmt.where(condition)
    total = db.scalar(count_stmt) or 0
    rows = db.scalars(stmt.order_by(BudgetAlert.ratio.desc()).limit(limit).offset(offset)).all()
    teams = {team.id: team for team in db.scalars(select(Team)).all()}
    return {
        "items": [serialize(row, teams.get(row.team_id)) for row in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
        "run_id": run_id,
    }


def get_alert(db: Session, alert_id: int, principal: dict) -> BudgetAlert:
    alert = db.get(BudgetAlert, alert_id)
    if alert is None:
        raise not_found("alert", alert_id)
    team_service.assert_team_scope(principal, alert.team_id)
    return alert


def review(db: Session, alert: BudgetAlert, *, status: str, note: str | None, reviewer: str) -> BudgetAlert:
    alert.status = status or AlertStatus.CONFIRMED.value
    alert.note = note
    alert.reviewer = reviewer
    alert.reviewed_at = utcnow()
    db.flush()
    return alert
