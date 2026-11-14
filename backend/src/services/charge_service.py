"""分摊服务：读取某次运行/最新一次运行的团队分摊明细。"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models.charge import Charge
from src.models.team import Team
from src.services import team_service
from src.utils.errors import not_found


def serialize(charge: Charge, team: Team | None) -> dict:
    return {
        "id": charge.id,
        "run_id": charge.run_id,
        "team_id": charge.team_id,
        "team_code": team.code if team else None,
        "team_name": team.name if team else None,
        "cost_center": team.cost_center if team else None,
        "owner": team.owner if team else None,
        "budget_yuan": round(team.budget_yuan, 2) if team else 0.0,
        "amount_yuan": round(charge.amount_yuan, 2),
        "ratio": round(charge.ratio, 4),
        "query_count": charge.query_count,
        "cached_saved_yuan": round(charge.cached_saved_yuan, 2),
        "mom_ratio": charge.mom_ratio,
        "user_split": charge.user_split or [],
        "top_query": charge.top_query or {},
        "created_at": charge.created_at.isoformat(timespec="seconds") + "Z" if charge.created_at else None,
    }


def list_charges(
    db: Session,
    principal: dict,
    *,
    run_id: int | None = None,
    team_id: int | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    team_id = team_service.scoped_team_id(principal, team_id)
    if run_id is None:
        latest = team_service.latest_run(db)
        run_id = latest.id if latest else None
    if run_id is None:
        return {"items": [], "total": 0, "limit": limit, "offset": offset, "run_id": None}
    stmt = select(Charge).where(Charge.run_id == run_id)
    if team_id:
        stmt = stmt.where(Charge.team_id == team_id)
    rows = db.scalars(stmt.order_by(Charge.amount_yuan.desc()).limit(limit).offset(offset)).all()
    teams = {team.id: team for team in db.scalars(select(Team)).all()}
    items = [serialize(row, teams.get(row.team_id)) for row in rows]
    return {
        "items": items,
        "total": len(items),
        "limit": limit,
        "offset": offset,
        "run_id": run_id,
        "total_amount_yuan": round(sum(item["amount_yuan"] for item in items), 2),
    }


def get_charge(db: Session, charge_id: int, principal: dict) -> Charge:
    charge = db.get(Charge, charge_id)
    if charge is None:
        raise not_found("charge", charge_id)
    team_service.assert_team_scope(principal, charge.team_id)
    return charge
