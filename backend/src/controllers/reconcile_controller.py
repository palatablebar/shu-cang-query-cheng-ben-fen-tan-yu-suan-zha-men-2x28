"""供应商对账控制器：导入 / 核对 / 差异处置 / 确认发布，每个写动作落领域审计。"""
from __future__ import annotations

from fastapi import Request
from sqlalchemy.orm import Session

from src.services import audit_service, reconcile_service


def list_bills(db: Session, principal: dict, *, period: str | None, limit: int, offset: int) -> dict:
    return reconcile_service.list_bills(db, principal, period=period, limit=limit, offset=offset)


def import_bill(db: Session, payload: dict, principal: dict, request: Request) -> dict:
    bill = reconcile_service.import_bill(
        db,
        period=payload["period"],
        filename=payload.get("filename") or "supplier-bill.csv",
        csv_text=payload["csv_text"],
        operator_email=principal["email"],
    )
    audit_service.record(
        db,
        actor_email=principal["email"],
        actor_role=principal["role"],
        action="bill.import",
        entity="supplier_bill",
        entity_id=bill.id,
        detail={"bill_no": bill.bill_no, "period": bill.period, "lines": bill.line_count, "amount": bill.total_amount_yuan},
        ip=request.client.host if request.client else None,
    )
    db.commit()
    return reconcile_service.serialize_bill(bill)


def get_bill(db: Session, bill_id: int, principal: dict) -> dict:
    bill = reconcile_service.get_bill(db, bill_id)
    data = reconcile_service.serialize_bill(bill)
    data["runs"] = [reconcile_service.serialize_run(row) for row in reconcile_service.list_runs(db, bill.id)]
    latest = reconcile_service.latest_success_run(db, bill.id)
    data["latest_run"] = reconcile_service.serialize_run(latest) if latest else None
    data["open_findings"] = reconcile_service.get_open_finding_count(db, bill.id)
    data["adjustments"] = reconcile_service.list_adjustments(db, bill.id)
    return data


def reconcile_bill(db: Session, bill_id: int, principal: dict, request: Request) -> dict:
    bill = reconcile_service.get_bill(db, bill_id)
    try:
        run, reused = reconcile_service.start_reconciliation(db, bill, principal["email"])
    except Exception:
        db.commit()  # 失败状态与已写事实一并落库，不丢记录
        raise
    if not reused:
        audit_service.record(
            db,
            actor_email=principal["email"],
            actor_role=principal["role"],
            action="bill.reconcile",
            entity="supplier_bill",
            entity_id=bill.id,
            detail={
                "recon_no": run.recon_no,
                "status": run.status,
                "diff_total_yuan": run.diff_total_yuan,
                "diff_counts": run.diff_counts,
            },
            ip=request.client.host if request.client else None,
        )
    db.commit()
    return {
        "bill": reconcile_service.serialize_bill(bill),
        "run": reconcile_service.serialize_run(run),
        "reused": reused,
    }


def list_findings(db: Session, bill_id: int, principal: dict, **filters) -> dict:
    reconcile_service.get_bill(db, bill_id)
    return reconcile_service.list_findings(db, principal, bill_id=bill_id, **filters)


def resolve_finding(db: Session, finding_id: int, payload: dict, principal: dict, request: Request) -> dict:
    finding = reconcile_service.get_finding(db, finding_id, principal)
    reconcile_service.resolve_finding(
        db, finding, status=payload["status"], note=payload.get("note"), resolver=principal["email"]
    )
    audit_service.record(
        db,
        actor_email=principal["email"],
        actor_role=principal["role"],
        action="bill.finding.resolve",
        entity="reconciliation_finding",
        entity_id=finding.id,
        detail={"bill_id": finding.bill_id, "query_id": finding.query_id, "diff_type": finding.diff_type, "status": finding.status},
        ip=request.client.host if request.client else None,
    )
    db.commit()
    return reconcile_service.serialize_finding(finding)


def confirm_bill(db: Session, bill_id: int, principal: dict, request: Request) -> dict:
    bill = reconcile_service.get_bill(db, bill_id)
    bill = reconcile_service.confirm_bill(db, bill, principal["email"])
    audit_service.record(
        db,
        actor_email=principal["email"],
        actor_role=principal["role"],
        action="bill.confirm",
        entity="supplier_bill",
        entity_id=bill.id,
        detail={
            "bill_no": bill.bill_no,
            "period": bill.period,
            "published_run_id": bill.published_run_id,
            "adjustments": len(reconcile_service.list_adjustments(db, bill.id)),
        },
        ip=request.client.host if request.client else None,
    )
    db.commit()
    return get_bill(db, bill.id, principal)
