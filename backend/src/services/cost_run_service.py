"""成本运行服务：读取查询日志 → 算成本/异常 → 写分摊与告警。

算法实现全部在 services/cost_model.py（纯函数），本模块只负责取数、落库与快照。
"""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from src.constants.cost_model import (
    CACHE_DISCOUNT,
    COMPUTE_PRICE_PER_GB_SECOND,
    SCAN_PRICE_PER_GB,
    WATCH_RATIO,
)
from src.constants.enums import RUN_STATUS_LABELS, TRIGGER_LABELS
from src.models.budget_alert import BudgetAlert
from src.models.charge import Charge
from src.models.cost_run import CostRun
from src.models.query_log import QueryLog
from src.models.team import Team
from src.services import cost_model
from src.utils.errors import AppError, forbidden
from src.utils.timeutil import iso_utc, local_now, utcnow

DEFAULT_PRICES = {
    "scan_price": SCAN_PRICE_PER_GB,
    "compute_price": COMPUTE_PRICE_PER_GB_SECOND,
    "cache_discount": CACHE_DISCOUNT,
}


def next_run_no(db: Session) -> str:
    prefix = f"CR{local_now():%Y%m%d}"
    count = db.scalar(select(func.count()).select_from(CostRun).where(CostRun.run_no.like(f"{prefix}%"))) or 0
    return f"{prefix}-{count + 1:03d}"


def resolve_prices(payload: dict, role: str) -> dict:
    prices = dict(DEFAULT_PRICES)
    overrides = {key: payload.get(key) for key in DEFAULT_PRICES if payload.get(key) is not None}
    if overrides and role != "admin":
        raise forbidden({"reason": "price_config_admin_only", "fields": sorted(overrides)})
    prices.update(overrides)
    return prices


def summarize(logs: list[QueryLog], prices: dict, remaining_days: int) -> dict:
    """成本 + 异常 + 团队聚合（确定性；seed 预览与正式运行共用）。"""
    scanned_values = [float(log.scanned_gb) for log in logs]
    meta = cost_model.anomaly_threshold(scanned_values) if scanned_values else {
        "p95_gb": 0.0,
        "median_gb": 0.0,
        "mad_gb": 0.0,
        "threshold_gb": 0.0,
        "mad_factor": 3.0,
        "percentile": 0.95,
    }
    cutoff = utcnow() - timedelta(days=7)
    team_stats: dict[int, dict] = {}
    total_cost = 0.0
    billed = failed = cache_hits = 0
    scanned_total = 0.0
    anomaly_count = 0

    for log in logs:
        cost = cost_model.query_cost(
            log.scanned_gb,
            log.duration_ms,
            bool(log.cache_hit),
            log.status,
            scan_price=prices["scan_price"],
            compute_price=prices["compute_price"],
            cache_discount=prices["cache_discount"],
        )
        is_anom = cost_model.is_anomaly(log.scanned_gb, meta["threshold_gb"])
        log.cost_yuan = cost
        log.is_anomaly = is_anom
        log.anomaly_score = cost_model.anomaly_score(log.scanned_gb, meta["threshold_gb"])
        log.anomaly_reason = cost_model.anomaly_reason(log.scanned_gb, meta) if is_anom else None
        scanned_total += float(log.scanned_gb)
        if log.cache_hit:
            cache_hits += 1
        if log.status == "success":
            billed += 1
        else:
            failed += 1
        if is_anom:
            anomaly_count += 1
        total_cost += cost

        stats = team_stats.setdefault(
            log.team_id,
            {
                "amount": 0.0,
                "query_count": 0,
                "cached_saved": 0.0,
                "last7": 0.0,
                "anomalies": 0,
                "users": {},
                "top": None,
            },
        )
        if log.status == "success":
            stats["amount"] += cost
            stats["query_count"] += 1
            if log.queried_at >= cutoff:
                stats["last7"] += cost
            if log.cache_hit:
                full = float(log.scanned_gb) * prices["scan_price"] + float(log.scanned_gb) * (
                    int(log.duration_ms) / 1000.0
                ) * prices["compute_price"]
                stats["cached_saved"] += full - cost
            user = stats["users"].setdefault(log.user_email, {"amount": 0.0, "query_count": 0})
            user["amount"] += cost
            user["query_count"] += 1
            top = stats["top"]
            if top is None or cost > top["cost_yuan"]:
                stats["top"] = {
                    "query_id": log.query_id,
                    "user_email": log.user_email,
                    "scanned_gb": round(float(log.scanned_gb), 3),
                    "cost_yuan": round(cost, 2),
                }
        if is_anom:
            stats["anomalies"] += 1

    total_cost = round(total_cost, 2)
    amounts = {team_id: round(stats["amount"], 2) for team_id, stats in team_stats.items()}
    ratios = cost_model.allocate_amounts(amounts)
    for team_id, stats in team_stats.items():
        stats["amount"] = amounts[team_id]
        stats["ratio"] = ratios.get(team_id, 0.0)
        stats["cached_saved"] = round(stats["cached_saved"], 2)
        stats["last7"] = round(stats["last7"], 2)
        users = sorted(stats["users"].items(), key=lambda item: (-item[1]["amount"], item[0]))[:5]
        stats["user_split"] = [
            {"user_email": email, "amount_yuan": round(info["amount"], 2), "query_count": info["query_count"]}
            for email, info in users
        ]

    return {
        "total_cost": total_cost,
        "billed": billed,
        "failed": failed,
        "cache_hits": cache_hits,
        "scanned_total": scanned_total,
        "anomaly_count": anomaly_count,
        "meta": meta,
        "team_stats": team_stats,
        "remaining_days": remaining_days,
    }


def _write_charges_and_alerts(db: Session, run: CostRun, summary: dict, teams: dict[int, Team]) -> None:
    db.execute(delete(Charge).where(Charge.run_id == run.id))
    db.execute(delete(BudgetAlert).where(BudgetAlert.run_id == run.id))
    remaining = summary["remaining_days"]
    for team_id, stats in summary["team_stats"].items():
        team = teams.get(team_id)
        if team is None:
            continue
        db.add(
            Charge(
                run_id=run.id,
                team_id=team_id,
                amount_yuan=stats["amount"],
                ratio=stats["ratio"],
                query_count=stats["query_count"],
                cached_saved_yuan=stats["cached_saved"],
                mom_ratio=cost_model.mom_ratio(stats["amount"], team.prev_month_yuan),
                user_split=stats["user_split"],
                top_query=stats["top"] or {},
            )
        )
        forecast = cost_model.forecast_budget(stats["amount"], stats["last7"], remaining)
        ratio = round(forecast["forecast_yuan"] / team.budget_yuan, 4) if team.budget_yuan else 0.0
        if ratio > WATCH_RATIO:
            level = cost_model.alert_level(ratio)
            db.add(
                BudgetAlert(
                    run_id=run.id,
                    team_id=team_id,
                    forecast_yuan=forecast["forecast_yuan"],
                    ratio=ratio,
                    level=level,
                    gate_action=cost_model.gate_action(level, stats["anomalies"] > 0),
                    status="pending",
                )
            )
    db.flush()


def execute_run(db: Session, run: CostRun, *, remaining_days: int | None = None) -> CostRun:
    run.status = "running"
    logs = list(db.scalars(select(QueryLog).order_by(QueryLog.id)).all())
    teams = {team.id: team for team in db.scalars(select(Team)).all()}
    remaining = remaining_days if remaining_days is not None else cost_model.remaining_days_of_month(local_now().date())
    prices = {
        "scan_price": run.scan_price,
        "compute_price": run.compute_price,
        "cache_discount": run.cache_discount,
    }
    summary = summarize(logs, prices, remaining)
    _write_charges_and_alerts(db, run, summary, teams)

    alerts = db.scalar(select(func.count()).select_from(BudgetAlert).where(BudgetAlert.run_id == run.id)) or 0
    run.input_count = len(logs)
    run.output_count = len(summary["team_stats"]) + alerts
    run.total_cost_yuan = summary["total_cost"]
    run.metrics = cost_model.summary_metrics(
        total_cost_yuan=summary["total_cost"],
        billed_count=summary["billed"],
        failed_count=summary["failed"],
        cache_hits=summary["cache_hits"],
        scanned_gb=summary["scanned_total"],
        anomaly_meta=summary["meta"],
        anomaly_count=summary["anomaly_count"],
        remaining_days=remaining,
    )
    run.metrics["alerts"] = alerts
    run.metrics["teams"] = len(summary["team_stats"])
    run.status = "success" if logs else "partial"
    run.log_text = (
        f"读取查询日志 {len(logs)} 条（计费 {summary['billed']} / 未计费 {summary['failed']}）；"
        f"总成本 {summary['total_cost']:.2f} 元；异常 {summary['anomaly_count']} 条"
        f"（阈值 {summary['meta']['threshold_gb']:.1f} GB）；"
        f"写分摊 {len(summary['team_stats'])} 条、告警 {alerts} 条。"
    )
    run.finished_at = utcnow()
    db.flush()
    return run


def create_and_execute(
    db: Session,
    *,
    period: str | None,
    operator_email: str,
    payload: dict | None = None,
    seed_key: str | None = None,
) -> CostRun:
    if seed_key:
        existing = db.scalar(select(CostRun).where(CostRun.seed_key == seed_key))
        if existing is not None:
            return existing
    payload = payload or {}
    run = CostRun(
        run_no=next_run_no(db),
        period=period or f"{local_now():%Y-%m}",
        scan_price=payload.get("scan_price", SCAN_PRICE_PER_GB),
        compute_price=payload.get("compute_price", COMPUTE_PRICE_PER_GB_SECOND),
        cache_discount=payload.get("cache_discount", CACHE_DISCOUNT),
        status="running",
        trigger=payload.get("trigger", "manual"),
        operator_email=operator_email,
        seed_key=seed_key,
    )
    db.add(run)
    db.flush()
    return execute_run(db, run)


def serialize(run: CostRun) -> dict:
    return {
        "id": run.id,
        "run_no": run.run_no,
        "period": run.period,
        "scan_price": run.scan_price,
        "compute_price": run.compute_price,
        "cache_discount": run.cache_discount,
        "trigger": run.trigger,
        "trigger_label": TRIGGER_LABELS.get(run.trigger, run.trigger),
        "status": run.status,
        "status_label": RUN_STATUS_LABELS.get(run.status, run.status),
        "operator_email": run.operator_email,
        "input_count": run.input_count,
        "output_count": run.output_count,
        "total_cost_yuan": round(run.total_cost_yuan, 2),
        "metrics": run.metrics or {},
        "log_text": run.log_text,
        "started_at": iso_utc(run.started_at),
        "finished_at": iso_utc(run.finished_at),
    }


def list_runs(db: Session, status: str | None, limit: int, offset: int) -> dict:
    stmt = select(CostRun)
    count_stmt = select(func.count()).select_from(CostRun)
    if status:
        stmt = stmt.where(CostRun.status == status)
        count_stmt = count_stmt.where(CostRun.status == status)
    total = db.scalar(count_stmt) or 0
    rows = db.scalars(stmt.order_by(CostRun.id.desc()).limit(limit).offset(offset)).all()
    return {"items": [serialize(row) for row in rows], "total": total, "limit": limit, "offset": offset}


def get_run(db: Session, run_id: int) -> CostRun:
    run = db.get(CostRun, run_id)
    if run is None:
        raise AppError("NOT_FOUND", 404, {"entity": "cost_run", "id": run_id})
    return run
