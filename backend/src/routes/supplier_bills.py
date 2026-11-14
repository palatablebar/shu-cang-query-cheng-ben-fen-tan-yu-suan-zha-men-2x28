from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from src.config.database import get_db
from src.constants.roles import (
    BILL_CONFIRM_ROLES,
    BILL_IMPORT_ROLES,
    BILL_READ_ROLES,
    BILL_RECONCILE_ROLES,
    BILL_RESOLVE_ROLES,
)
from src.controllers import reconcile_controller
from src.middlewares.rbac import require_roles
from src.schemas.reconcile import FindingReviewIn, SupplierBillIn
from src.utils.pagination import page_params

router = APIRouter(prefix="/supplier-bills", tags=["supplier-bills"])


@router.get("")
def list_bills(
    period: str | None = None,
    limit: int = Query(20),
    offset: int = Query(0),
    db: Session = Depends(get_db),
    principal: dict = Depends(require_roles(*BILL_READ_ROLES)),
) -> dict:
    page = page_params(limit, offset)
    return reconcile_controller.list_bills(db, principal, period=period, limit=page.limit, offset=page.offset)


@router.post("", status_code=201)
def import_bill(
    payload: SupplierBillIn,
    request: Request,
    db: Session = Depends(get_db),
    principal: dict = Depends(require_roles(*BILL_IMPORT_ROLES)),
) -> dict:
    return reconcile_controller.import_bill(db, payload.model_dump(), principal, request)


@router.get("/{bill_id}")
def get_bill(
    bill_id: int,
    db: Session = Depends(get_db),
    principal: dict = Depends(require_roles(*BILL_READ_ROLES)),
) -> dict:
    return reconcile_controller.get_bill(db, bill_id, principal)


@router.post("/{bill_id}/reconcile")
def reconcile_bill(
    bill_id: int,
    request: Request,
    db: Session = Depends(get_db),
    principal: dict = Depends(require_roles(*BILL_RECONCILE_ROLES)),
) -> dict:
    return reconcile_controller.reconcile_bill(db, bill_id, principal, request)


@router.get("/{bill_id}/findings")
def list_findings(
    bill_id: int,
    diff_type: str | None = None,
    status: str | None = None,
    limit: int = Query(100),
    offset: int = Query(0),
    db: Session = Depends(get_db),
    principal: dict = Depends(require_roles(*BILL_READ_ROLES)),
) -> dict:
    page = page_params(limit, offset)
    return reconcile_controller.list_findings(
        db,
        bill_id,
        principal,
        diff_type=diff_type,
        status=status,
        limit=page.limit,
        offset=page.offset,
    )


@router.patch("/findings/{finding_id}/review")
def resolve_finding(
    finding_id: int,
    payload: FindingReviewIn,
    request: Request,
    db: Session = Depends(get_db),
    principal: dict = Depends(require_roles(*BILL_RESOLVE_ROLES)),
) -> dict:
    return reconcile_controller.resolve_finding(db, finding_id, payload.model_dump(), principal, request)


@router.post("/{bill_id}/confirm")
def confirm_bill(
    bill_id: int,
    request: Request,
    db: Session = Depends(get_db),
    principal: dict = Depends(require_roles(*BILL_CONFIRM_ROLES)),
) -> dict:
    return reconcile_controller.confirm_bill(db, bill_id, principal, request)
