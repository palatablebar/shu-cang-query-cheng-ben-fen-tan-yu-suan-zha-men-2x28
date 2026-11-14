"""总览：本月成本、预算进度、异常与告警、近 7 天成本曲线。

viewer 只统计本人团队（team 隔离）。
"""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.config.settings import settings
from src.constants.enums import ALERT_LEVEL_LABELS, AlertStatus, QueryStatus, Role
from src.models.budget_alert import BudgetAlert
from src.models.charge import Charge
from src.models.cost_run import CostRun
from src.models.query_log import QueryLog
from src.models.team import Team
from src.services import cost_model, team_service
from src.utils.timeutil import iso_utc, local_now, utcnow


def worker_alive() -> bool:
    try:
        import time

        import redis

        client = redis.Redis.from_url(settings.redis_url, decode_responses=True, socket_connect_timeout=2)
        value = client.get(f"{settings.app_name}:worker:heartbeat")
        return bool(value) and (time.time() - float(value)) < 120
    except Exception:
        return False


def _scoped_team_id(db: Session, principal: dict) -> int | None:
    if principal.get("role") != Role.VIEWER.value:
        return None
    own = principal.get("team_id")
    return int(own) if own is not None else -1


def _trend(db: Session, team_id: int | None, days: int = 7) -> list[dict]:
    offset = timedelta(minutes=settings.app_timezone_offset_minutes)
    today = local_now().date()
    since_local = today - timedelta(days=days - 1)
    since_utc = since_local - offset
    stmt = select(QueryLog).where(QueryLog.queried_at >= since_utc)
    if team_id is not None:
        stmt = stmt.where(QueryLog.team_id == team_id)
    rows = db.scalars(stmt).all()
    buckets = {today - timedelta(days=index): 0.0 for index in range(days - 1, -1, -1)}
    for row in rows:
        day = (row.queried_at + offset).date()
        if day in buckets:
            buckets[day] += row.cost_yuan
    return [{"date": day.isoformat(), "cost_yuan": round(value, 2)} for day, value in sorted(buckets.items())]


def overview(db: Session, principal: dict) -> dict:
    team_id = _scoped_team_id(db, principal)
    run = db.scalar(select(CostRun).order_by(CostRun.id.desc()).limit(1))

    team_stmt = select(Team).order_by(Team.id)
    if team_id is not None:
        team_stmt = team_stmt.where(Team.id == team_id)
    teams = db.scalars(team_stmt).all()
    team_ids = [team.id for team in teams]

    charges: list[Charge] = []
    alerts: list[BudgetAlert] = []
    if run is not None:
        charge_stmt = select(Charge).where(Charge.run_id == run.id)
        alert_stmt = select(BudgetAlert).where(BudgetAlert.run_id == run.id)
        if team_id is not None:
            charge_stmt = charge_stmt.where(Charge.team_id == team_id)
            alert_stmt = alert_stmt.where(BudgetAlert.team_id == team_id)
        charges = list(db.scalars(charge_stmt.order_by(Charge.amount_yuan.desc())).all())
        alerts = list(db.scalars(alert_stmt.order_by(BudgetAlert.ratio.desc())).all())

    charge_by_team = {charge.team_id: charge for charge in charges}
    alert_by_team = {alert.team_id: alert for alert in alerts}
    used_total = round(sum(charge.amount_yuan for charge in charges), 2)
    budget_total = round(sum(team.budget_yuan for team in teams), 2)

    anomaly_stmt = select(func.count()).select_from(QueryLog).where(QueryLog.is_anomaly.is_(True))
    total_stmt = select(func.count()).select_from(QueryLog)
    if team_id is not None:
        anomaly_stmt = anomaly_stmt.where(QueryLog.team_id == team_id)
        total_stmt = total_stmt.where(QueryLog.team_id == team_id)
    anomaly_count = db.scalar(anomaly_stmt) or 0
    query_total = db.scalar(total_stmt) or 0
    failed_stmt = select(func.count()).select_from(QueryLog).where(QueryLog.status != QueryStatus.SUCCESS.value)
    if team_id is not None:
        failed_stmt = failed_stmt.where(QueryLog.team_id == team_id)
    failed_count = db.scalar(failed_stmt) or 0

    pending_alerts = sum(1 for alert in alerts if alert.status == AlertStatus.PENDING.value)
    metrics = (run.metrics or {}) if run else {}
    remaining = int(metrics.get("remaining_days", 0) or 0)
    last7_stmt = (
        select(QueryLog.team_id, func.sum(QueryLog.cost_yuan))
        .where(QueryLog.queried_at >= utcnow() - timedelta(days=7))
        .group_by(QueryLog.team_id)
    )
    if team_id is not None:
        last7_stmt = last7_stmt.where(QueryLog.team_id == team_id)
    last7_by_team = {row[0]: float(row[1] or 0.0) for row in db.execute(last7_stmt).all()}

    allocation = []
    for team in teams:
        charge = charge_by_team.get(team.id)
        alert = alert_by_team.get(team.id)
        amount = round(charge.amount_yuan, 2) if charge else 0.0
        forecast = cost_model.forecast_budget(amount, last7_by_team.get(team.id, 0.0), remaining)["forecast_yuan"]
        forecast_ratio = round(forecast / team.budget_yuan, 4) if team.budget_yuan else None
        level = alert.level if alert else cost_model.alert_level(forecast_ratio or 0.0)
        allocation.append(
            {
                "team_id": team.id,
                "code": team.code,
                "name": team.name,
                "amount_yuan": amount,
                "ratio": round(charge.ratio, 4) if charge else 0.0,
                "query_count": charge.query_count if charge else 0,
                "budget_yuan": round(team.budget_yuan, 2),
                "used_ratio": round(amount / team.budget_yuan, 4) if team.budget_yuan else None,
                "forecast_yuan": forecast,
                "forecast_ratio": forecast_ratio,
                "level": level,
                "level_label": ALERT_LEVEL_LABELS.get(level, level),
            }
        )

    return {
        "total_cost_yuan": used_total if team_id is not None else round(run.total_cost_yuan, 2) if run else used_total,
        "used_yuan": used_total,
        "budget_total_yuan": budget_total,
        "budget_used_ratio": round(used_total / budget_total, 4) if budget_total else None,
        "anomaly_count": anomaly_count,
        "query_total": query_total,
        "failed_count": failed_count,
        "alert_count": len(alerts),
        "pending_alerts": pending_alerts,
        "team_count": len(teams),
        "worker_alive": worker_alive(),
        "metrics": {
            "p95_gb": metrics.get("p95_gb", 0.0),
            "mad_gb": metrics.get("mad_gb", 0.0),
            "threshold_gb": metrics.get("threshold_gb", 0.0),
            "remaining_days": metrics.get("remaining_days", 0),
            "cache_hit_ratio": metrics.get("cache_hit_ratio", 0.0),
            "avg_cost_yuan": metrics.get("avg_cost_yuan", 0.0),
        },
        "latest_run": {
            "id": run.id,
            "run_no": run.run_no,
            "period": run.period,
            "status": run.status,
            "started_at": iso_utc(run.started_at),
            "finished_at": iso_utc(run.finished_at),
            "total_cost_yuan": round(run.total_cost_yuan, 2),
            "input_count": run.input_count,
            "metrics": run.metrics or {},
        }
        if run
        else None,
        "allocation": allocation,
        "alerts": [
            {
                "id": alert.id,
                "team_id": alert.team_id,
                "team_name": next((team.name for team in teams if team.id == alert.team_id), ""),
                "forecast_yuan": round(alert.forecast_yuan, 2),
                "ratio": round(alert.ratio, 4),
                "level": alert.level,
                "level_label": ALERT_LEVEL_LABELS.get(alert.level, alert.level),
                "status": alert.status,
            }
            for alert in alerts
        ],
        "trend": _trend(db, team_id),
        "scope_team_id": team_id if team_id and team_id > 0 else None,
    }
