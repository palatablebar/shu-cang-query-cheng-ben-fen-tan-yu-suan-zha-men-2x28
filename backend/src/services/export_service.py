"""导出服务：分摊账单 CSV（一次运行 = 5 行团队分摊）。"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.constants.enums import ALERT_LEVEL_LABELS, ALERT_STATUS_LABELS, GATE_ACTION_LABELS
from src.models.budget_alert import BudgetAlert
from src.models.charge import Charge
from src.models.team import Team
from src.services import team_service
from src.utils.csv_export import to_csv


def charges_csv(db: Session, run_id: int | None = None) -> bytes:
    if run_id is None:
        latest = team_service.latest_run(db)
        run_id = latest.id if latest else None
    charges = []
    alerts: dict[int, BudgetAlert] = {}
    if run_id is not None:
        charges = list(db.scalars(select(Charge).where(Charge.run_id == run_id).order_by(Charge.amount_yuan.desc())).all())
        alerts = {
            alert.team_id: alert
            for alert in db.scalars(select(BudgetAlert).where(BudgetAlert.run_id == run_id)).all()
        }
    teams = {team.id: team for team in db.scalars(select(Team)).all()}
    headers = [
        "团队",
        "成本中心",
        "负责人",
        "金额(元)",
        "占比",
        "查询数",
        "缓存节省(元)",
        "环比",
        "预算(元)",
        "预测(元)",
        "预测/预算",
        "分档",
        "闸门建议",
        "处置状态",
    ]
    rows = []
    for charge in charges:
        team = teams.get(charge.team_id)
        alert = alerts.get(charge.team_id)
        rows.append(
            [
                team.name if team else "",
                team.cost_center if team else "",
                team.owner if team else "",
                f"{charge.amount_yuan:.2f}",
                f"{charge.ratio * 100:.1f}%",
                charge.query_count,
                f"{charge.cached_saved_yuan:.2f}",
                f"{charge.mom_ratio * 100:+.1f}%" if charge.mom_ratio is not None else "—",
                f"{team.budget_yuan:.2f}" if team else "0.00",
                f"{alert.forecast_yuan:.2f}" if alert else "—",
                f"{alert.ratio * 100:.1f}%" if alert else "—",
                ALERT_LEVEL_LABELS.get(alert.level, "") if alert else "正常",
                GATE_ACTION_LABELS.get(alert.gate_action, "") if alert else "—",
                ALERT_STATUS_LABELS.get(alert.status, "") if alert else "—",
            ]
        )
    return to_csv(headers, rows)


def runs_csv(db: Session) -> bytes:
    from src.models.cost_run import CostRun

    runs = db.scalars(select(CostRun).order_by(CostRun.id)).all()
    headers = ["运行号", "账期", "状态", "查询数", "总成本(元)", "操作人", "开始时间", "结束时间"]
    rows = [
        [
            run.run_no,
            run.period,
            run.status,
            run.input_count,
            f"{run.total_cost_yuan:.2f}",
            run.operator_email,
            run.started_at.strftime("%Y-%m-%d %H:%M") if run.started_at else "",
            run.finished_at.strftime("%Y-%m-%d %H:%M") if run.finished_at else "",
        ]
        for run in runs
    ]
    return to_csv(headers, rows)
