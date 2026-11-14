"""团队服务：预算台账 + 最近一次运行的分摊/告警快照 + 查看范围（team 隔离）。"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.constants.enums import ALERT_LEVEL_LABELS, AlertLevel, Role
from src.models.budget_alert import BudgetAlert
from src.models.charge import Charge
from src.models.cost_run import CostRun
from src.models.team import Team
from src.utils.errors import AppError, forbidden, not_found
from src.utils.timeutil import iso_utc


def assert_team_scope(principal: dict, team_id: int | None) -> None:
    """viewer 只能看自己团队；其他角色不受限。"""
    if principal.get("role") != Role.VIEWER.value:
        return
    own = principal.get("team_id")
    if team_id is not None and int(team_id) != int(own or -1):
        raise forbidden({"reason": "team_scope", "team_id": team_id})


def scoped_team_id(principal: dict, requested: int | None) -> int | None:
    if principal.get("role") != Role.VIEWER.value:
        return requested
    own = principal.get("team_id")
    if own is None:
        raise forbidden({"reason": "team_missing"})
    if requested is not None and int(requested) != int(own):
        raise forbidden({"reason": "team_scope", "team_id": requested})
    return int(own)


def list_all(db: Session) -> list[Team]:
    return list(db.scalars(select(Team).order_by(Team.id)).all())


def latest_run(db: Session) -> CostRun | None:
    return db.scalar(select(CostRun).order_by(CostRun.id.desc()).limit(1))


def serialize(
    team: Team,
    charge: Charge | None = None,
    alert: BudgetAlert | None = None,
) -> dict:
    used = round(charge.amount_yuan, 2) if charge else 0.0
    forecast = round(alert.forecast_yuan, 2) if alert else None
    budget_ratio = round(used / team.budget_yuan, 4) if team.budget_yuan else None
    return {
        "id": team.id,
        "code": team.code,
        "name": team.name,
        "budget_yuan": round(team.budget_yuan, 2),
        "cost_center": team.cost_center,
        "owner": team.owner,
        "prev_month_yuan": round(team.prev_month_yuan, 2),
        "member_count": team.member_count,
        "note": team.note,
        "used_yuan": used,
        "used_ratio": budget_ratio,
        "forecast_yuan": forecast,
        "forecast_ratio": round(alert.ratio, 4) if alert else None,
        "level": alert.level if alert else AlertLevel.NORMAL.value,
        "level_label": ALERT_LEVEL_LABELS.get(alert.level if alert else "", "正常"),
        "charge_ratio": round(charge.ratio, 4) if charge else 0.0,
        "mom_ratio": charge.mom_ratio if charge else None,
        "query_count": charge.query_count if charge else 0,
        "created_at": iso_utc(team.created_at),
    }


def list_teams(db: Session, principal: dict, *, limit: int = 50, offset: int = 0) -> dict:
    stmt = select(Team).order_by(Team.id)
    count_stmt = select(func.count()).select_from(Team)
    if principal.get("role") == Role.VIEWER.value:
        own = scoped_team_id(principal, None)
        stmt = stmt.where(Team.id == own)
        count_stmt = count_stmt.where(Team.id == own)
    total = db.scalar(count_stmt) or 0
    teams = db.scalars(stmt.limit(limit).offset(offset)).all()
    run = latest_run(db)
    charges: dict[int, Charge] = {}
    alerts: dict[int, BudgetAlert] = {}
    if run is not None:
        charges = {row.team_id: row for row in db.scalars(select(Charge).where(Charge.run_id == run.id)).all()}
        alerts = {row.team_id: row for row in db.scalars(select(BudgetAlert).where(BudgetAlert.run_id == run.id)).all()}
    items = [serialize(team, charges.get(team.id), alerts.get(team.id)) for team in teams]
    totals = {
        "budget_yuan": round(sum(item["budget_yuan"] for item in items), 2),
        "used_yuan": round(sum(item["used_yuan"] for item in items), 2),
    }
    totals["used_ratio"] = round(totals["used_yuan"] / totals["budget_yuan"], 4) if totals["budget_yuan"] else None
    return {"items": items, "total": total, "limit": limit, "offset": offset, "totals": totals, "run_id": run.id if run else None}


def get_team(db: Session, team_id: int, principal: dict) -> Team:
    assert_team_scope(principal, team_id)
    team = db.get(Team, team_id)
    if team is None:
        raise not_found("team", team_id)
    return team


def update_team(db: Session, team: Team, payload: dict) -> Team:
    for field in ("budget_yuan", "cost_center", "owner", "prev_month_yuan", "note"):
        if field in payload and payload[field] is not None:
            setattr(team, field, payload[field])
    db.flush()
    return team


def find_by_code(db: Session, code: str) -> Team | None:
    return db.scalar(select(Team).where(Team.code == code))


def ensure_team(
    db: Session,
    *,
    code: str,
    name: str,
    budget_yuan: float,
    cost_center: str,
    owner: str,
    prev_month_yuan: float,
    member_count: int = 0,
) -> Team:
    team = find_by_code(db, code)
    if team is None:
        team = Team(
            code=code,
            name=name,
            budget_yuan=budget_yuan,
            cost_center=cost_center,
            owner=owner,
            prev_month_yuan=prev_month_yuan,
            member_count=member_count,
        )
        db.add(team)
        db.flush()
    return team


def require_team(db: Session, team_id: int) -> Team:
    team = db.get(Team, team_id)
    if team is None:
        raise AppError("NOT_FOUND", 404, {"entity": "team", "id": team_id})
    return team
