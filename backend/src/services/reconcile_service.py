"""供应商对账服务：账单导入 → 逐笔核对 → 差异处置 → 确认发布（只修差异账期）。

关键约束：
- 同一文件（SHA-256）重复导入返回 409，重跑同一账单不新增核对结果（成功批次幂等复用）；
- 核对失败只把账单/批次标 failed 并保留全部已写记录，不删除、不回滚事实；
- 差异清零前预算告警沿用旧值；确认后才按修正台账重算差异涉及账期并刷新团队分摊与告警。
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.constants.enums import (
    BILL_STATUS_LABELS,
    BillStatus,
    FindingStatus,
    ReconcileStatus,
)
from src.models.bill_adjustment import BillAdjustment
from src.models.query_log import QueryLog
from src.models.reconciliation_finding import ReconciliationFinding
from src.models.reconciliation_run import ReconciliationRun
from src.models.supplier_bill import SupplierBill
from src.models.supplier_bill_item import SupplierBillItem
from src.models.team import Team
from src.services import cost_run_service, reconcile_model, team_service
from src.utils.errors import AppError, bad_request, forbidden, not_found
from src.utils.timeutil import iso_utc, local_now, utcnow


def next_recon_no(db: Session) -> str:
    prefix = f"RC{local_now():%Y%m%d}"
    count = db.scalar(
        select(func.count()).select_from(ReconciliationRun).where(ReconciliationRun.recon_no.like(f"{prefix}%"))
    ) or 0
    return f"{prefix}-{count + 1:03d}"


def next_bill_no(db: Session, period: str) -> str:
    count = db.scalar(
        select(func.count()).select_from(SupplierBill).where(SupplierBill.bill_no.like(f"BILL-{period}-%"))
    ) or 0
    return f"BILL-{period}-{count + 1:03d}"


# ---------- 导入 ----------

def import_bill(db: Session, *, period: str, filename: str, csv_text: str, operator_email: str) -> SupplierBill:
    file_hash = reconcile_model.bill_file_hash(csv_text)
    duplicate = db.scalar(select(SupplierBill).where(SupplierBill.file_hash == file_hash))
    if duplicate is not None:
        raise AppError(
            "CONFLICT",
            409,
            {"reason": "bill_file_duplicated", "bill_id": duplicate.id, "bill_no": duplicate.bill_no},
        )
    try:
        rows = reconcile_model.parse_bill_csv(csv_text)
    except reconcile_model.BillParseError as exc:
        raise bad_request("VALIDATION", {"reason": "bill_parse_failed", "message": str(exc)}) from exc

    bill = SupplierBill(
        bill_no=next_bill_no(db, period),
        period=period,
        source_filename=filename or "paste.csv",
        file_hash=file_hash,
        line_count=len(rows),
        total_amount_yuan=round(sum(float(row["amount_yuan"]) for row in rows), 2),
        total_scanned_gb=round(sum(float(row["scanned_gb"]) for row in rows), 2),
        status=BillStatus.IMPORTED.value,
    )
    db.add(bill)
    db.flush()
    seq: dict[str, int] = {}
    for row in rows:
        seq[row["query_id"]] = seq.get(row["query_id"], 0) + 1
        db.add(
            SupplierBillItem(
                bill_id=bill.id,
                query_id=row["query_id"],
                team_code=row["team_code"],
                user_email=row["user_email"],
                scanned_gb=row["scanned_gb"],
                unit_price=row["unit_price"],
                amount_yuan=row["amount_yuan"],
                queried_at=row["queried_at"],
                duplicate_seq=seq[row["query_id"]],
                raw_line=row["raw_line"],
            )
        )
    db.flush()
    return bill


def get_bill(db: Session, bill_id: int) -> SupplierBill:
    bill = db.get(SupplierBill, bill_id)
    if bill is None:
        raise not_found("supplier_bill", bill_id)
    return bill


def _scope_team_code_with_db(db: Session, principal: dict) -> str | None:
    """viewer 的 JWT 只带 team_id，换算成团队编码用于账单行/差异过滤；其他角色返回 None。"""
    if principal.get("role") != "viewer":
        return None
    team_id = principal.get("team_id")
    if team_id is None:
        raise forbidden({"reason": "team_missing"})
    team = db.get(Team, int(team_id))
    if team is None:
        raise forbidden({"reason": "team_scope"})
    return team.code


def list_bills(db: Session, principal: dict, *, period: str | None, limit: int, offset: int) -> dict:
    stmt = select(SupplierBill)
    count_stmt = select(func.count()).select_from(SupplierBill)
    if period:
        stmt = stmt.where(SupplierBill.period == period)
        count_stmt = count_stmt.where(SupplierBill.period == period)
    total = db.scalar(count_stmt) or 0
    rows = db.scalars(stmt.order_by(SupplierBill.id.desc()).limit(limit).offset(offset)).all()
    items = [serialize_bill(row) for row in rows]
    return {"items": items, "total": total, "limit": limit, "offset": offset}


# ---------- 核对 ----------

def _platform_rows_for_period(db: Session, period: str) -> list[dict]:
    from src.utils.timeutil import period_bounds_utc

    start_utc, end_utc = period_bounds_utc(period)
    logs = db.scalars(
        select(QueryLog)
        .where(QueryLog.queried_at >= start_utc, QueryLog.queried_at < end_utc)
        .order_by(QueryLog.id)
    ).all()
    teams = {team.id: team.code for team in team_service.list_all(db)}
    return [
        {
            "query_id": log.query_id,
            "team_code": teams.get(log.team_id, str(log.team_id)),
            "user_email": log.user_email,
            "scanned_gb": float(log.scanned_gb),
            "cost_yuan": float(log.cost_yuan),
            "status": log.status,
            "cache_hit": bool(log.cache_hit),
        }
        for log in logs
    ]


def _bill_rows(db: Session, bill: SupplierBill) -> list[dict]:
    items = db.scalars(select(SupplierBillItem).where(SupplierBillItem.bill_id == bill.id)).all()
    return [
        {
            "query_id": item.query_id,
            "team_code": item.team_code,
            "user_email": item.user_email,
            "scanned_gb": float(item.scanned_gb),
            "unit_price": float(item.unit_price),
            "amount_yuan": float(item.amount_yuan),
        }
        for item in items
    ]


def _latest_success_run(db: Session, bill_id: int) -> ReconciliationRun | None:
    return db.scalar(
        select(ReconciliationRun)
        .where(ReconciliationRun.bill_id == bill_id, ReconciliationRun.status == ReconcileStatus.SUCCESS.value)
        .order_by(ReconciliationRun.id.desc())
        .limit(1)
    )


def latest_success_run(db: Session, bill_id: int) -> ReconciliationRun | None:
    """供控制器/序列化复用的公开入口。"""
    return _latest_success_run(db, bill_id)


def start_reconciliation(db: Session, bill: SupplierBill, operator_email: str) -> tuple[ReconciliationRun, bool]:
    """返回 (核对批次, 是否复用既有成功批次)。重跑同一账单不新增核对结果。"""
    # 幂等：成功批次直接复用，重跑同一账单不新增核对结果
    existing = _latest_success_run(db, bill.id)
    if existing is not None:
        return existing, True
    if bill.status == BillStatus.CHECKING.value:
        raise AppError("CONFLICT", 409, {"reason": "bill_checking", "bill_id": bill.id})

    run = ReconciliationRun(
        recon_no=next_recon_no(db),
        bill_id=bill.id,
        period=bill.period,
        operator_email=operator_email,
        status=ReconcileStatus.RUNNING.value,
    )
    bill.status = BillStatus.CHECKING.value
    bill.error_message = None
    db.add(run)
    db.flush()
    try:
        bill_rows = _bill_rows(db, bill)
        platform_rows = _platform_rows_for_period(db, bill.period)
        result = reconcile_model.reconcile(bill_rows, platform_rows, period=bill.period)
        for finding in result["findings"]:
            db.add(
                ReconciliationFinding(
                    run_id=run.id,
                    bill_id=bill.id,
                    period=bill.period,
                    query_id=finding["query_id"],
                    team_code=finding.get("team_code"),
                    user_email=finding.get("user_email"),
                    diff_type=finding["diff_type"],
                    duplicate_seq=finding["duplicate_seq"],
                    status=FindingStatus.OPEN.value,
                    bill_scanned_gb=finding["bill_scanned_gb"],
                    platform_scanned_gb=finding["platform_scanned_gb"],
                    bill_amount_yuan=finding["bill_amount_yuan"],
                    platform_amount_yuan=finding["platform_amount_yuan"],
                    diff_amount_yuan=finding["diff_amount_yuan"],
                    bill_unit_price=finding["bill_unit_price"],
                    platform_unit_price=finding["platform_unit_price"],
                    detail=finding["detail"],
                )
            )
        run.bill_total_yuan = result["bill_total_yuan"]
        run.platform_total_yuan = result["platform_total_yuan"]
        run.diff_total_yuan = result["diff_total_yuan"]
        run.diff_counts = result["counts"]
        run.status = ReconcileStatus.SUCCESS.value
        run.finished_at = utcnow()
        bill.status = BillStatus.MATCHED.value
        db.flush()
    except Exception as exc:  # noqa: BLE001 - 核对失败留痕，不丢记录
        run.status = ReconcileStatus.FAILED.value
        run.error_message = str(exc)[:1000]
        run.finished_at = utcnow()
        bill.status = BillStatus.FAILED.value
        bill.error_message = str(exc)[:1000]
        db.flush()
        raise
    return run, False


def list_runs(db: Session, bill_id: int) -> list[ReconciliationRun]:
    return list(
        db.scalars(
            select(ReconciliationRun).where(ReconciliationRun.bill_id == bill_id).order_by(ReconciliationRun.id.desc())
        ).all()
    )


def list_findings(
    db: Session,
    principal: dict,
    *,
    bill_id: int,
    diff_type: str | None = None,
    status: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict:
    conditions = [ReconciliationFinding.bill_id == bill_id]
    team_code = _scope_team_code_with_db(db, principal)
    if team_code is not None:
        conditions.append(ReconciliationFinding.team_code == team_code)
    if diff_type:
        conditions.append(ReconciliationFinding.diff_type == diff_type)
    if status:
        conditions.append(ReconciliationFinding.status == status)
    stmt = select(ReconciliationFinding)
    count_stmt = select(func.count()).select_from(ReconciliationFinding)
    for condition in conditions:
        stmt = stmt.where(condition)
        count_stmt = count_stmt.where(condition)
    total = db.scalar(count_stmt) or 0
    rows = db.scalars(
        stmt.order_by(ReconciliationFinding.diff_type, ReconciliationFinding.id).limit(limit).offset(offset)
    ).all()
    return {
        "items": [serialize_finding(row) for row in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


def get_open_finding_count(db: Session, bill_id: int) -> int:
    return db.scalar(
        select(func.count())
        .select_from(ReconciliationFinding)
        .where(
            ReconciliationFinding.bill_id == bill_id,
            ReconciliationFinding.status == FindingStatus.OPEN.value,
        )
    ) or 0


def resolve_finding(
    db: Session, finding: ReconciliationFinding, *, status: str, note: str | None, resolver: str
) -> ReconciliationFinding:
    if finding.status == FindingStatus.APPLIED.value:
        raise AppError("CONFLICT", 409, {"reason": "finding_already_applied", "id": finding.id})
    finding.status = status
    finding.note = note
    finding.resolver = resolver
    finding.resolved_at = utcnow()
    db.flush()
    return finding


def get_finding(db: Session, finding_id: int, principal: dict) -> ReconciliationFinding:
    finding = db.get(ReconciliationFinding, finding_id)
    if finding is None:
        raise not_found("reconciliation_finding", finding_id)
    team_code = _scope_team_code_with_db(db, principal)
    if team_code is not None and finding.team_code != team_code:
        raise forbidden({"reason": "team_scope"})
    return finding


# ---------- 确认发布 ----------

def confirm_bill(db: Session, bill: SupplierBill, operator_email: str) -> SupplierBill:
    if bill.status == BillStatus.CONFIRMED.value:
        return bill
    run = _latest_success_run(db, bill.id)
    if run is None:
        raise AppError("CONFLICT", 409, {"reason": "bill_not_reconciled", "bill_id": bill.id})
    open_count = get_open_finding_count(db, bill.id)
    if open_count:
        raise AppError("CONFLICT", 409, {"reason": "open_findings_remain", "open": open_count})

    findings = list(
        db.scalars(
            select(ReconciliationFinding).where(
                ReconciliationFinding.bill_id == bill.id,
                ReconciliationFinding.status == FindingStatus.APPLIED.value,
            )
        ).all()
    )
    if findings:
        adjustments = reconcile_model.aggregate_adjustments([serialize_finding(row) for row in findings])
        team_codes = {row["team_code"] for row in adjustments}
        code_to_team = {team.code: team for team in team_service.list_all(db)}
        unknown = sorted(code for code in team_codes if code not in code_to_team)
        if unknown:
            raise bad_request("VALIDATION", {"reason": "unknown_team_code", "team_codes": unknown})

        periods = sorted({row["period"] for row in adjustments})
        period_to_run: dict[str, int] = {}
        for period in periods:
            new_run = cost_run_service.create_reconcile_run(
                db, period=period, operator_email=operator_email, bill_id=bill.id
            )
            period_to_run[period] = new_run.id
        for adj in adjustments:
            db.add(
                BillAdjustment(
                    bill_id=bill.id,
                    run_id=period_to_run.get(adj["period"]),
                    period=adj["period"],
                    team_code=adj["team_code"],
                    diff_type=adj["diff_type"],
                    amount_yuan=round(adj["amount_yuan"], 2),
                    payable_delta_yuan=round(adj["payable_delta_yuan"], 2),
                    finding_count=adj["finding_count"],
                    status=FindingStatus.APPLIED.value,
                    created_by=operator_email,
                )
            )
        published_run_id = period_to_run.get(bill.period) or next(iter(period_to_run.values()))
    else:
        published_run_id = None

    bill.status = BillStatus.CONFIRMED.value
    bill.confirmed_at = utcnow()
    bill.confirmed_by = operator_email
    bill.published_run_id = published_run_id
    db.flush()
    return bill


def list_adjustments(db: Session, bill_id: int) -> list[dict]:
    rows = db.scalars(
        select(BillAdjustment).where(BillAdjustment.bill_id == bill_id).order_by(BillAdjustment.id)
    ).all()
    return [
        {
            "id": row.id,
            "bill_id": row.bill_id,
            "run_id": row.run_id,
            "period": row.period,
            "team_code": row.team_code,
            "diff_type": row.diff_type,
            "amount_yuan": round(row.amount_yuan, 2),
            "payable_delta_yuan": round(row.payable_delta_yuan, 2),
            "finding_count": row.finding_count,
            "status": row.status,
            "note": row.note,
            "created_by": row.created_by,
            "created_at": iso_utc(row.created_at),
        }
        for row in rows
    ]


# ---------- 序列化 ----------

def serialize_bill(bill: SupplierBill) -> dict:
    return {
        "id": bill.id,
        "bill_no": bill.bill_no,
        "vendor": bill.vendor,
        "period": bill.period,
        "source_filename": bill.source_filename,
        "line_count": bill.line_count,
        "total_amount_yuan": round(bill.total_amount_yuan, 2),
        "total_scanned_gb": round(bill.total_scanned_gb, 2),
        "status": bill.status,
        "status_label": BILL_STATUS_LABELS.get(bill.status, bill.status),
        "error_message": bill.error_message,
        "confirmed_at": iso_utc(bill.confirmed_at),
        "confirmed_by": bill.confirmed_by,
        "published_run_id": bill.published_run_id,
        "created_at": iso_utc(bill.created_at),
        "updated_at": iso_utc(bill.updated_at),
    }


def serialize_run(run: ReconciliationRun) -> dict:
    return {
        "id": run.id,
        "recon_no": run.recon_no,
        "bill_id": run.bill_id,
        "period": run.period,
        "operator_email": run.operator_email,
        "status": run.status,
        "bill_total_yuan": round(run.bill_total_yuan, 2),
        "platform_total_yuan": round(run.platform_total_yuan, 2),
        "diff_total_yuan": round(run.diff_total_yuan, 2),
        "diff_counts": run.diff_counts or {},
        "error_message": run.error_message,
        "started_at": iso_utc(run.started_at),
        "finished_at": iso_utc(run.finished_at),
    }


def serialize_finding(finding: ReconciliationFinding) -> dict:
    from src.constants.enums import DIFF_TYPE_LABELS, FINDING_STATUS_LABELS

    return {
        "id": finding.id,
        "run_id": finding.run_id,
        "bill_id": finding.bill_id,
        "period": finding.period,
        "query_id": finding.query_id,
        "team_code": finding.team_code,
        "user_email": finding.user_email,
        "diff_type": finding.diff_type,
        "diff_type_label": DIFF_TYPE_LABELS.get(finding.diff_type, finding.diff_type),
        "duplicate_seq": finding.duplicate_seq,
        "status": finding.status,
        "status_label": FINDING_STATUS_LABELS.get(finding.status, finding.status),
        "bill_scanned_gb": round(finding.bill_scanned_gb, 6),
        "platform_scanned_gb": round(finding.platform_scanned_gb, 6),
        "bill_amount_yuan": round(finding.bill_amount_yuan, 4),
        "platform_amount_yuan": round(finding.platform_amount_yuan, 4),
        "diff_amount_yuan": round(finding.diff_amount_yuan, 4),
        "bill_unit_price": round(finding.bill_unit_price, 6),
        "platform_unit_price": round(finding.platform_unit_price, 6),
        "detail": finding.detail or {},
        "note": finding.note,
        "resolver": finding.resolver,
        "resolved_at": iso_utc(finding.resolved_at),
        "created_at": iso_utc(finding.created_at),
    }
