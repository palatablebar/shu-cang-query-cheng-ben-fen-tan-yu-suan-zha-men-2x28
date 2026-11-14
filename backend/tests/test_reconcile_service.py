"""供应商对账服务集成测试（SQLite 内存库，不依赖 Postgres/Redis）。

覆盖：
- 导入幂等（同文件 409）、CSV 非法 422 风格错误；
- 核对产出四类差异、重跑同一账单不新增核对结果、核对失败保留记录；
- 差异清零前不能确认；确认后只重算差异涉及账期、生成修正台账与对账修正运行；
- 差异未清零前预算告警沿用旧值。
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.constants.enums import BillStatus, DiffType, FindingStatus, ReconcileStatus, TriggerKind
from src.models import Base
from src.models.bill_adjustment import BillAdjustment
from src.models.budget_alert import BudgetAlert
from src.models.charge import Charge
from src.models.cost_run import CostRun
from src.models.query_log import QueryLog
from src.models.reconciliation_finding import ReconciliationFinding
from src.models.reconciliation_run import ReconciliationRun
from src.models.supplier_bill import SupplierBill
from src.models.team import Team
from src.services import reconcile_service
from src.utils.errors import AppError
from src.utils.timeutil import utcnow

PERIOD = "2026-11"
ADMIN = {"email": "admin@costcharge.io", "role": "admin", "team_id": None}


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, future=True)
    session = Session()
    seed(session)
    try:
        yield session
    finally:
        session.close()


def seed(db) -> None:
    teams = [
        Team(code="team-a", name="A 组", budget_yuan=100000.0, cost_center="CC-1", owner="甲", prev_month_yuan=1000.0),
        Team(code="team-b", name="B 组", budget_yuan=100000.0, cost_center="CC-2", owner="乙", prev_month_yuan=1000.0),
    ]
    db.add_all(teams)
    db.flush()
    now = utcnow()
    # qh-match 两侧一致；qh-missing 平台失败不计费；qh-price 平台缓存 0.3 折；qh-extra 平台多计
    db.add_all(
        [
            QueryLog(
                query_id="qh-match", user_email="u@x.io", team_id=teams[0].id, sql_digest="d",
                scanned_gb=100.0, duration_ms=60000, cache_hit=False, status="success",
                queried_at=now, cost_yuan=2.8,
            ),
            QueryLog(
                query_id="qh-missing", user_email="u@x.io", team_id=teams[0].id, sql_digest="d",
                scanned_gb=100.0, duration_ms=60000, cache_hit=False, status="failed",
                queried_at=now, cost_yuan=0.0,
            ),
            QueryLog(
                query_id="qh-price", user_email="u@x.io", team_id=teams[0].id, sql_digest="d",
                scanned_gb=100.0, duration_ms=60000, cache_hit=True, status="success",
                queried_at=now, cost_yuan=0.84,
            ),
            QueryLog(
                query_id="qh-extra", user_email="u@x.io", team_id=teams[1].id, sql_digest="d",
                scanned_gb=100.0, duration_ms=60000, cache_hit=False, status="success",
                queried_at=now, cost_yuan=5.0,
            ),
        ]
    )
    db.commit()


def _csv(rows: list[tuple]) -> str:
    header = "查询ID,团队编码,用户邮箱,扫描量GB,单价(元/GB),金额(元)"
    body = "\n".join(",".join(str(cell) for cell in row) for row in rows)
    return f"{header}\n{body}\n"


def _standard_bill_csv() -> str:
    return _csv(
        [
            ("qh-match", "team-a", "u@x.io", 100, 0.028, 2.8),
            ("qh-missing", "team-a", "u@x.io", 100, 0.028, 2.8),
            ("qh-price", "team-a", "u@x.io", 100, 0.028, 2.8),
            ("qh-dup", "team-a", "u@x.io", 100, 0.028, 2.8),
            ("qh-dup", "team-a", "u@x.io", 100, 0.028, 2.8),
        ]
    )


def test_import_idempotent_by_file_hash(db):
    bill = reconcile_service.import_bill(
        db, period=PERIOD, filename="b.csv", csv_text=_standard_bill_csv(), operator_email=ADMIN["email"]
    )
    db.commit()
    assert bill.line_count == 5
    assert bill.total_amount_yuan == pytest.approx(14.0)
    with pytest.raises(AppError) as exc:
        reconcile_service.import_bill(
            db, period=PERIOD, filename="b.csv", csv_text=_standard_bill_csv(), operator_email=ADMIN["email"]
        )
    assert exc.value.status_code == 409
    assert exc.value.detail["reason"] == "bill_file_duplicated"
    assert db.scalar(select(func.count()).select_from(SupplierBill)) == 1


def test_import_rejects_bad_csv(db):
    with pytest.raises(AppError) as exc:
        reconcile_service.import_bill(
            db, period=PERIOD, filename="bad.csv", csv_text="foo,bar\n1,2\n", operator_email=ADMIN["email"]
        )
    assert exc.value.status_code == 400
    assert db.scalar(select(func.count()).select_from(SupplierBill)) == 0


def test_reconcile_classifies_four_diff_types_and_is_idempotent(db):
    bill = reconcile_service.import_bill(
        db, period=PERIOD, filename="b.csv", csv_text=_standard_bill_csv(), operator_email=ADMIN["email"]
    )
    db.commit()
    run, reused = reconcile_service.start_reconciliation(db, bill, ADMIN["email"])
    db.commit()
    assert reused is False
    assert run.status == ReconcileStatus.SUCCESS.value
    counts = run.diff_counts
    # qh-missing 平台失败不计费 + qh-dup 首行平台无此查询 -> 2 条漏计
    assert counts[DiffType.MISSING.value] == 2
    assert counts[DiffType.DUPLICATE.value] == 1        # qh-dup 第二行
    assert counts[DiffType.PRICE_MISMATCH.value] == 1   # qh-price 缓存折扣
    assert counts[DiffType.PLATFORM_EXTRA.value] == 1   # qh-extra 账单没有
    assert counts[DiffType.MATCHED.value] == 1          # qh-match
    assert bill.status == BillStatus.MATCHED.value

    # 重跑同一账单：复用成功批次，不新增核对结果
    run_again, reused_again = reconcile_service.start_reconciliation(db, bill, ADMIN["email"])
    assert reused_again is True
    assert run_again.id == run.id
    assert db.scalar(select(func.count()).select_from(ReconciliationRun).where(ReconciliationRun.bill_id == bill.id)) == 1
    assert db.scalar(select(func.count()).select_from(ReconciliationFinding)) == 5


def test_failed_reconciliation_keeps_records(db, monkeypatch):
    bill = reconcile_service.import_bill(
        db, period=PERIOD, filename="b.csv", csv_text=_standard_bill_csv(), operator_email=ADMIN["email"]
    )
    db.commit()

    def boom(*_args, **_kwargs):
        raise RuntimeError("simulated reconcile crash")

    monkeypatch.setattr(reconcile_service.reconcile_model, "reconcile", boom)
    with pytest.raises(RuntimeError):
        reconcile_service.start_reconciliation(db, bill, ADMIN["email"])
    db.commit()

    db.refresh(bill)
    assert bill.status == BillStatus.FAILED.value
    assert "simulated reconcile crash" in (bill.error_message or "")
    failed_run = db.scalar(select(ReconciliationRun).where(ReconciliationRun.bill_id == bill.id))
    assert failed_run.status == ReconcileStatus.FAILED.value
    # 账单头与失败批次都还在，没有丢记录
    assert db.get(SupplierBill, bill.id) is not None

    # 修复后允许重试：失败不阻塞，新批次成功
    monkeypatch.undo()
    run, reused = reconcile_service.start_reconciliation(db, bill, ADMIN["email"])
    db.commit()
    assert reused is False
    assert run.status == ReconcileStatus.SUCCESS.value
    assert db.scalar(
        select(func.count()).select_from(ReconciliationRun).where(ReconciliationRun.bill_id == bill.id)
    ) == 2


def test_confirm_blocked_until_findings_cleared_then_publishes(db):
    bill = reconcile_service.import_bill(
        db, period=PERIOD, filename="b.csv", csv_text=_standard_bill_csv(), operator_email=ADMIN["email"]
    )
    db.commit()
    run, _ = reconcile_service.start_reconciliation(db, bill, ADMIN["email"])
    db.commit()

    with pytest.raises(AppError) as exc:
        reconcile_service.confirm_bill(db, bill, ADMIN["email"])
    assert exc.value.detail["reason"] == "open_findings_remain"

    findings = list(db.scalars(select(ReconciliationFinding).where(ReconciliationFinding.bill_id == bill.id)).all())
    for finding in findings:
        reconcile_service.resolve_finding(db, finding, status=FindingStatus.APPLIED.value, note="ok", resolver=ADMIN["email"])
    db.commit()
    assert reconcile_service.get_open_finding_count(db, bill.id) == 0

    runs_before = db.scalar(select(func.count()).select_from(CostRun)) or 0
    confirmed = reconcile_service.confirm_bill(db, bill, ADMIN["email"])
    db.commit()
    assert confirmed.status == BillStatus.CONFIRMED.value
    assert confirmed.confirmed_by == ADMIN["email"]
    assert confirmed.published_run_id is not None

    # 生成一次 reconcile 触发的账期修正运行（只修 2026-11）
    new_run = db.get(CostRun, confirmed.published_run_id)
    assert new_run.trigger == TriggerKind.RECONCILE.value
    assert new_run.period == PERIOD
    assert (db.scalar(select(func.count()).select_from(CostRun)) or 0) == runs_before + 1
    # 修正台账落地，duplicate 不改团队分摊但计入应付修正
    adjustments = list(db.scalars(select(BillAdjustment).where(BillAdjustment.bill_id == bill.id)).all())
    types = {row.diff_type for row in adjustments}
    assert DiffType.MISSING.value in types
    dup = next(row for row in adjustments if row.diff_type == DiffType.DUPLICATE.value)
    assert dup.amount_yuan == 0.0
    assert dup.payable_delta_yuan == pytest.approx(2.8)

    # 确认幂等：再次确认不新增运行/台账
    reconcile_service.confirm_bill(db, db.get(SupplierBill, bill.id), ADMIN["email"])
    db.commit()
    assert db.scalar(
        select(func.count()).select_from(CostRun).where(CostRun.trigger == TriggerKind.RECONCILE.value)
    ) == 1


def test_budget_alerts_unchanged_before_confirmation(db):
    # 先做一次普通核算，冻结既有告警（旧值）
    from src.services import cost_run_service

    run = cost_run_service.create_and_execute(
        db, period=PERIOD, operator_email=ADMIN["email"], payload={"trigger": "manual"}
    )
    db.commit()
    alert_snapshot = {
        (row.team_id): (row.forecast_yuan, row.ratio, row.level)
        for row in db.scalars(select(BudgetAlert).where(BudgetAlert.run_id == run.id)).all()
    }
    charge_snapshot = {
        row.team_id: row.amount_yuan for row in db.scalars(select(Charge).where(Charge.run_id == run.id)).all()
    }

    bill = reconcile_service.import_bill(
        db, period=PERIOD, filename="b.csv", csv_text=_standard_bill_csv(), operator_email=ADMIN["email"]
    )
    db.commit()
    reconcile_service.start_reconciliation(db, bill, ADMIN["email"])
    db.commit()
    # 核对完成但未确认：最新运行仍是原 manual 运行，告警/分摊沿用旧值
    latest = db.scalar(select(CostRun).order_by(CostRun.id.desc()).limit(1))
    assert latest.id == run.id
    current_alerts = {
        row.team_id: (row.forecast_yuan, row.ratio, row.level)
        for row in db.scalars(select(BudgetAlert).where(BudgetAlert.run_id == run.id)).all()
    }
    assert current_alerts == alert_snapshot
    current_charges = {
        row.team_id: row.amount_yuan for row in db.scalars(select(Charge).where(Charge.run_id == run.id)).all()
    }
    assert current_charges == charge_snapshot


def test_all_dismissed_confirms_without_run_or_adjustment(db):
    bill = reconcile_service.import_bill(
        db, period=PERIOD, filename="b.csv", csv_text=_standard_bill_csv(), operator_email=ADMIN["email"]
    )
    db.commit()
    reconcile_service.start_reconciliation(db, bill, ADMIN["email"])
    findings = list(db.scalars(select(ReconciliationFinding).where(ReconciliationFinding.bill_id == bill.id)).all())
    assert findings  # 有差异
    for finding in findings:
        reconcile_service.resolve_finding(
            db, finding, status=FindingStatus.DISMISSED.value, note="供应商冲红", resolver=ADMIN["email"]
        )
    db.commit()

    runs_before = db.scalar(select(func.count()).select_from(CostRun)) or 0
    confirmed = reconcile_service.confirm_bill(db, bill, ADMIN["email"])
    db.commit()
    # 差异已清零（全部驳回）允许确认；无入账差异 -> 不产生修正运行与台账
    assert confirmed.status == BillStatus.CONFIRMED.value
    assert confirmed.published_run_id is None
    assert (db.scalar(select(func.count()).select_from(CostRun)) or 0) == runs_before
    assert reconcile_service.list_adjustments(db, bill.id) == []


def test_retry_after_partial_failure_does_not_collide(db):
    """失败批次若已残留部分明细，重试批次（不同 run_id）能独立写入，不撞唯一键、不丢记录。"""
    from src.constants.enums import ReconcileStatus
    from src.models.reconciliation_run import ReconciliationRun

    bill = reconcile_service.import_bill(
        db, period=PERIOD, filename="b.csv", csv_text=_standard_bill_csv(), operator_email=ADMIN["email"]
    )
    db.commit()

    # 模拟上一次核对在写明细中途失败：留下 failed 批次 + 一条 qh-missing 的残留明细
    failed = ReconciliationRun(
        recon_no=reconcile_service.next_recon_no(db),
        bill_id=bill.id,
        period=PERIOD,
        operator_email=ADMIN["email"],
        status=ReconcileStatus.FAILED.value,
        error_message="simulated partial write",
    )
    db.add(failed)
    db.flush()
    db.add(
        ReconciliationFinding(
            run_id=failed.id,
            bill_id=bill.id,
            period=PERIOD,
            query_id="qh-missing",
            team_code="team-a",
            diff_type=DiffType.MISSING.value,
            duplicate_seq=1,
            status=FindingStatus.OPEN.value,
            bill_amount_yuan=2.8,
            diff_amount_yuan=2.8,
        )
    )
    db.commit()

    # 重试：成功批次也要写 qh-missing/missing/seq1，靠 run_id 区分而不撞键
    run, reused = reconcile_service.start_reconciliation(db, bill, ADMIN["email"])
    db.commit()
    assert reused is False
    assert run.status == ReconcileStatus.SUCCESS.value
    assert run.id != failed.id

    new_count = db.scalar(
        select(func.count()).select_from(ReconciliationFinding).where(ReconciliationFinding.run_id == run.id)
    )
    failed_count = db.scalar(
        select(func.count())
        .select_from(ReconciliationFinding)
        .where(ReconciliationFinding.run_id == failed.id)
    )
    assert new_count >= 1
    assert failed_count == 1  # 失败批次残留明细保留，核对失败不丢记录
    # 同一业务键在两个批次各存一份
    assert (
        db.scalar(
            select(func.count())
            .select_from(ReconciliationFinding)
            .where(
                ReconciliationFinding.bill_id == bill.id,
                ReconciliationFinding.query_id == "qh-missing",
                ReconciliationFinding.diff_type == DiffType.MISSING.value,
            )
        )
        == 2
    )


def test_only_diff_period_is_recomputed(db):
    # 构造上月账期的查询，确认修正只动 2026-11，不碰 2026-10
    from src.utils.timeutil import period_bounds_utc

    oct_start, oct_end = period_bounds_utc("2026-10")
    team_a = db.scalar(select(Team).where(Team.code == "team-a"))
    old_time = oct_start
    db.add(
        QueryLog(
            query_id="qh-october", user_email="u@x.io", team_id=team_a.id, sql_digest="d",
            scanned_gb=50.0, duration_ms=30000, cache_hit=False, status="success",
            queried_at=old_time, cost_yuan=1.4,
        )
    )
    db.commit()

    bill = reconcile_service.import_bill(
        db, period=PERIOD, filename="b.csv", csv_text=_standard_bill_csv(), operator_email=ADMIN["email"]
    )
    db.commit()
    reconcile_service.start_reconciliation(db, bill, ADMIN["email"])
    findings = list(db.scalars(select(ReconciliationFinding).where(ReconciliationFinding.bill_id == bill.id)).all())
    for finding in findings:
        reconcile_service.resolve_finding(db, finding, status=FindingStatus.APPLIED.value, note=None, resolver=ADMIN["email"])
    db.commit()
    confirmed = reconcile_service.confirm_bill(db, bill, ADMIN["email"])
    db.commit()

    new_run = db.get(CostRun, confirmed.published_run_id)
    assert new_run.metrics.get("reconcile_period") == PERIOD
    # 修正运行的输入只含 11 月查询，不含 10 月
    assert new_run.input_count == db.scalar(
        select(func.count())
        .select_from(QueryLog)
        .where(QueryLog.queried_at >= period_bounds_utc(PERIOD)[0], QueryLog.queried_at < period_bounds_utc(PERIOD)[1])
    )
    assert all(adj.period == PERIOD for adj in db.scalars(select(BillAdjustment).where(BillAdjustment.bill_id == bill.id)).all())
