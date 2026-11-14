"""分摊 / 告警 / 导出控制器。"""
from __future__ import annotations

from fastapi import Response
from sqlalchemy.orm import Session

from src.services import alert_service, audit_service, charge_service, export_service
from src.utils.csv_export import csv_response_headers


def list_charges(db: Session, principal: dict, **filters) -> dict:
    return charge_service.list_charges(db, principal, **filters)


def list_alerts(db: Session, principal: dict, **filters) -> dict:
    return alert_service.list_alerts(db, principal, **filters)


def review_alert(db: Session, alert_id: int, payload: dict, principal: dict, request) -> dict:
    alert = alert_service.get_alert(db, alert_id, principal)
    alert_service.review(db, alert, status=payload["status"], note=payload.get("note"), reviewer=principal["email"])
    audit_service.record(
        db,
        actor_email=principal["email"],
        actor_role=principal["role"],
        action="alert.review",
        entity="budget_alert",
        entity_id=alert.id,
        detail={"status": alert.status, "ratio": alert.ratio, "level": alert.level},
        ip=request.client.host if request.client else None,
    )
    db.commit()
    return alert_service.serialize(alert, None)


def list_charges(db: Session, principal: dict, **filters) -> dict:
    return charge_service.list_charges(db, principal, **filters)


def list_alerts(db: Session, principal: dict, **filters) -> dict:
    return alert_service.list_alerts(db, principal, **filters)


def charges_csv(db: Session, run_id: int | None, principal: dict, request) -> Response:
    content = export_service.charges_csv(db, run_id)
    audit_service.record(
        db,
        actor_email=principal["email"],
        actor_role=principal["role"],
        action="export.charges",
        entity="charge",
        entity_id=run_id,
        detail={"bytes": len(content)},
        ip=request.client.host if request.client else None,
    )
    db.commit()
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers=csv_response_headers("charges.csv"),
    )


def runs_csv(db: Session, principal: dict, request) -> Response:
    content = export_service.runs_csv(db)
    audit_service.record(
        db,
        actor_email=principal["email"],
        actor_role=principal["role"],
        action="export.charges",
        entity="cost_run",
        entity_id=None,
        detail={"bytes": len(content), "kind": "runs"},
        ip=request.client.host if request.client else None,
    )
    db.commit()
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers=csv_response_headers("cost-runs.csv"),
    )
