"""幂等 seed：3 账号 / 5 团队 / 1,200 条查询 / 1 次成本运行 / 5 条分摊 / 3 条预算告警。

自然键 upsert：
  users.email
  teams.code
  query_logs.query_id
  cost_runs.seed_key
  charges(run_id, team_id)
  budget_alerts(run_id, team_id)
  audit_logs.seed_key

重复执行不新增、不覆盖用户改过的预算与告警处置；SEED_SUMMARY 逐字一致。
"""
from __future__ import annotations

from sqlalchemy import func, select

from src.config.database import session_scope
from src.constants.cost_model import CACHE_DISCOUNT, COMPUTE_PRICE_PER_GB_SECOND, SCAN_PRICE_PER_GB
from src.models.audit import AuditLog
from src.models.budget_alert import BudgetAlert
from src.models.charge import Charge
from src.models.cost_run import CostRun
from src.models.query_log import QueryLog
from src.models.supplier_bill import SupplierBill
from src.models.team import Team
from src.models.user import User
from src.services import auth_service, cost_model, cost_run_service, reconcile_service, team_service
from src.utils.timeutil import local_now, utcnow

from scripts import demo_config
from scripts.demo_config import (
    DEMO_PASSWORD,
    DEMO_USERS,
    ORG,
    TEAM_SPECS,
)

SEED_RUN_KEY = "seed-run-2026-11"
DEFAULT_PRICES = {
    "scan_price": SCAN_PRICE_PER_GB,
    "compute_price": COMPUTE_PRICE_PER_GB_SECOND,
    "cache_discount": CACHE_DISCOUNT,
}


def ensure_teams(db) -> dict[str, Team]:
    for code, name, cost_center, owner, prev_month, _share, _count, _outliers, members in TEAM_SPECS:
        team_service.ensure_team(
            db,
            code=code,
            name=name,
            budget_yuan=0.0,
            cost_center=cost_center,
            owner=owner,
            prev_month_yuan=prev_month,
            member_count=len(members),
        )
    return {team.code: team for team in db.scalars(select(Team)).all()}


def ensure_users(db, teams: dict[str, Team]) -> int:
    for email, display_name, role, team_code in DEMO_USERS:
        team = teams.get(team_code) if team_code else None
        user = auth_service.get_user_by_email(db, email)
        if user is None:
            auth_service.ensure_user(
                db,
                email=email,
                password=DEMO_PASSWORD,
                display_name=display_name,
                role=role,
                org=ORG,
                team_id=team.id if team else None,
            )
        else:
            user.display_name = display_name
            if user.team_id is None and team is not None:
                user.team_id = team.id
    db.flush()
    return db.scalar(select(func.count()).select_from(User)) or 0


def ensure_query_logs(db, teams: dict[str, Team]) -> int:
    existing = set(db.scalars(select(QueryLog.query_id)).all())
    rows = demo_config.build_query_rows(utcnow())
    for row in rows:
        if row["query_id"] in existing:
            continue
        team = teams.get(row["team_code"])
        if team is None:
            continue
        db.add(
            QueryLog(
                query_id=row["query_id"],
                user_email=row["user_email"],
                team_id=team.id,
                sql_digest=row["sql_digest"],
                scanned_gb=row["scan"],
                duration_ms=row["duration_ms"],
                cache_hit=row["cache_hit"],
                status=row["status"],
                queried_at=row["queried_at"],
                seed_key=f"seed:{row['query_id']}",
            )
        )
    db.flush()
    return db.scalar(select(func.count()).select_from(QueryLog)) or 0


def ensure_run(db, teams: dict[str, Team]) -> CostRun:
    run = db.scalar(select(CostRun).where(CostRun.seed_key == SEED_RUN_KEY))
    if run is not None:
        return run

    remaining = cost_model.remaining_days_of_month(local_now().date())
    logs = list(db.scalars(select(QueryLog).order_by(QueryLog.id)).all())
    preview = cost_run_service.summarize(logs, DEFAULT_PRICES, remaining)
    for code, team in teams.items():
        stats = preview["team_stats"].get(team.id)
        if stats is None or (team.budget_yuan or 0) > 0:
            continue
        forecast = cost_model.forecast_budget(stats["amount"], stats["last7"], remaining)
        team.budget_yuan = demo_config.calibrate_budget(code, forecast["forecast_yuan"])
    db.flush()

    return cost_run_service.create_and_execute(
        db,
        period=f"{local_now():%Y-%m}",
        operator_email="admin@costcharge.io",
        payload={"trigger": "seed"},
        seed_key=SEED_RUN_KEY,
    )


def ensure_supplier_bill(db) -> dict | None:
    """幂等导入并核对一张供应商演示账单（差异保持 open，不自动确认发布）。

    使用固定时间锚点生成 CSV，保证文件哈希在重跑间稳定，从而靠 file_hash 去重。
    """
    period = f"{local_now():%Y-%m}"
    anchor = utcnow().replace(month=11, day=13, hour=6, minute=0, second=0, microsecond=0)
    csv_text = demo_config.supplier_bill_csv(anchor)
    file_hash = reconcile_service.reconcile_model.bill_file_hash(csv_text)
    if db.scalar(select(SupplierBill).where(SupplierBill.file_hash == file_hash)) is not None:
        return None
    bill = reconcile_service.import_bill(
        db,
        period=period,
        filename=f"supplier-bill-{period}-demo.csv",
        csv_text=csv_text,
        operator_email="admin@costcharge.io",
    )
    run, _ = reconcile_service.start_reconciliation(db, bill, "admin@costcharge.io")
    db.flush()
    return {"bill_id": bill.id, "recon_no": run.recon_no, "diff_total_yuan": run.diff_total_yuan}


def ensure_audit(db) -> None:
    seeds = [
        ("seed-audit-1", "admin@costcharge.io", "admin", "team.update", "team", {"budget_yuan": 21600}),
        ("seed-audit-2", "analyst@costcharge.io", "analyst", "run.create", "cost_run", {"run": SEED_RUN_KEY}),
    ]
    for seed_key, email, role, action, entity, detail in seeds:
        exists = db.scalar(select(AuditLog).where(AuditLog.seed_key == seed_key))
        if exists is None:
            db.add(
                AuditLog(
                    actor_email=email,
                    actor_role=role,
                    action=action,
                    entity=entity,
                    detail=detail,
                    layer="seed",
                    seed_key=seed_key,
                )
            )
    db.flush()


def seed_all() -> dict:
    with session_scope() as db:
        teams = ensure_teams(db)
        users = ensure_users(db, teams)
        ensure_query_logs(db, teams)
        ensure_run(db, teams)
        supplier = ensure_supplier_bill(db)
        ensure_audit(db)

        runs = db.scalar(select(func.count()).select_from(CostRun)) or 0
        charges = db.scalar(select(func.count()).select_from(Charge)) or 0
        bills = db.scalar(select(func.count()).select_from(SupplierBill)) or 0
        pending = db.scalar(select(func.count()).select_from(BudgetAlert).where(BudgetAlert.status == "pending")) or 0
        summary = (
            f"SEED_SUMMARY brand=costcharge users={users} sources={len(teams)} "
            f"runs={runs} findings={charges} pending={pending} bills={bills} "
            f"bill_diff={supplier['diff_total_yuan'] if supplier else 'reused'}"
        )
        print(summary, flush=True)
        return {
            "users": users,
            "teams": len(teams),
            "runs": runs,
            "charges": charges,
            "pending": pending,
            "bills": bills,
        }


if __name__ == "__main__":
    seed_all()
