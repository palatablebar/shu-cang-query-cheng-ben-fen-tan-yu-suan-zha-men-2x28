"""供应商对账 HTTP 端到端测试（SQLite + FastAPI TestClient，不依赖 Postgres/Redis）。

覆盖：未登录 401、viewer 写操作 403、analyst 不能确认（403）、admin 全链路、
重跑幂等不新增、确认后发布状态与修正运行。
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.testclient import TestClient

import src.config.database as dbmod
from src.constants.enums import BillStatus
from src.models import Base
from src.models.cost_run import CostRun
from src.models.query_log import QueryLog
from src.models.supplier_bill import SupplierBill
from src.models.team import Team
from src.utils.security import create_access_token
from src.utils.timeutil import utcnow

PERIOD = "2026-11"


@pytest.fixture()
def context():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    dbmod.engine = engine
    dbmod.SessionLocal = sessionmaker(bind=engine, future=True)
    Base.metadata.create_all(engine)
    _seed()

    from src.config.app import create_app

    app = create_app()
    # 关闭 lifespan 里的 wait_for_db/seed（表已建好），直接用 TestClient 避免触发真实 DB 探测
    with TestClient(app) as client:
        yield client


def _seed() -> None:
    with dbmod.SessionLocal() as db:
        team = Team(code="team-a", name="A 组", budget_yuan=100000.0, cost_center="CC-1", owner="甲", prev_month_yuan=1000.0)
        db.add(team)
        db.flush()
        now = utcnow()
        db.add_all(
            [
                QueryLog(
                    query_id="qh-1", user_email="u@x.io", team_id=team.id, sql_digest="d",
                    scanned_gb=100.0, duration_ms=60000, cache_hit=False, status="success",
                    queried_at=now, cost_yuan=2.8,
                ),
                QueryLog(
                    query_id="qh-2", user_email="u@x.io", team_id=team.id, sql_digest="d",
                    scanned_gb=100.0, duration_ms=60000, cache_hit=False, status="failed",
                    queried_at=now, cost_yuan=0.0,
                ),
            ]
        )
        db.commit()


def _auth(role: str, team_id: int | None = None) -> dict:
    email = {"admin": "admin@costcharge.io", "analyst": "analyst@costcharge.io", "viewer": "viewer@costcharge.io"}[role]
    token, _ = create_access_token(email, role, team_id)
    return {"Authorization": f"Bearer {token}"}


def _csv() -> str:
    return (
        "查询ID,团队编码,用户邮箱,扫描量GB,单价(元/GB),金额(元)\n"
        "qh-1,team-a,u@x.io,100,0.028,2.8\n"
        "qh-2,team-a,u@x.io,100,0.028,2.8\n"
        "qh-3,team-a,u@x.io,50,0.028,1.4\n"
    )


def test_auth_required_and_rbac(context):
    client = context
    assert client.get("/api/supplier-bills").status_code == 401

    # viewer 只读，不能导入/核对/确认/处置
    viewer = _auth("viewer", team_id=1)
    assert client.get("/api/supplier-bills", headers=viewer).status_code == 200
    assert client.post("/api/supplier-bills", headers=viewer, json={"period": PERIOD, "csv_text": _csv()}).status_code == 403

    # analyst 能导入核对，但不能确认发布
    analyst = _auth("analyst")
    imp = client.post("/api/supplier-bills", headers=analyst, json={"period": PERIOD, "filename": "b.csv", "csv_text": _csv()})
    assert imp.status_code == 201
    bill_id = imp.json()["id"]
    rec = client.post(f"/api/supplier-bills/{bill_id}/reconcile", headers=analyst)
    assert rec.status_code == 200
    assert client.post(f"/api/supplier-bills/{bill_id}/confirm", headers=analyst).status_code == 403


def test_admin_full_flow_idempotent_and_publish(context):
    client = context
    admin = _auth("admin")

    # 非法账期 -> 422
    bad = client.post("/api/supplier-bills", headers=admin, json={"period": "2026/11", "csv_text": _csv()})
    assert bad.status_code == 422

    imp = client.post("/api/supplier-bills", headers=admin, json={"period": PERIOD, "filename": "b.csv", "csv_text": _csv()})
    assert imp.status_code == 201
    bill_id = imp.json()["id"]

    # 同文件重复导入 -> 409
    dup = client.post("/api/supplier-bills", headers=admin, json={"period": PERIOD, "filename": "b.csv", "csv_text": _csv()})
    assert dup.status_code == 409

    first = client.post(f"/api/supplier-bills/{bill_id}/reconcile", headers=admin).json()
    assert first["reused"] is False
    assert first["run"]["diff_counts"]["missing"] >= 1  # qh-2 失败不计费 + qh-3 平台无

    # 重跑同一账单 -> 复用，不新增批次
    second = client.post(f"/api/supplier-bills/{bill_id}/reconcile", headers=admin).json()
    assert second["reused"] is True
    assert second["run"]["id"] == first["run"]["id"]

    # 分页拉全量（page_params 把单页上限钳制在 200）
    all_findings = []
    offset = 0
    while True:
        page = client.get(
            f"/api/supplier-bills/{bill_id}/findings", headers=admin, params={"limit": 200, "offset": offset}
        ).json()
        all_findings.extend(page["items"])
        offset += len(page["items"])
        if offset >= page["total"]:
            break
    findings = {"items": all_findings, "total": offset}
    assert findings["total"] >= 2

    # 差异未清零 -> 确认被拒
    blocked = client.post(f"/api/supplier-bills/{bill_id}/confirm", headers=admin)
    assert blocked.status_code == 409

    # 全部处置为入账
    for finding in findings["items"]:
        review = client.patch(
            f"/api/supplier-bills/findings/{finding['id']}/review",
            headers=admin,
            json={"status": "applied", "note": "确认"},
        )
        assert review.status_code == 200

    runs_before = _count(CostRun)
    confirmed = client.post(f"/api/supplier-bills/{bill_id}/confirm", headers=admin)
    assert confirmed.status_code == 200
    body = confirmed.json()
    assert body["status"] == BillStatus.CONFIRMED.value
    assert body["open_findings"] == 0
    assert body["published_run_id"] is not None
    assert _count(CostRun) == runs_before + 1

    # 再次确认幂等：不新增运行
    client.post(f"/api/supplier-bills/{bill_id}/confirm", headers=admin)
    assert _count(CostRun) == runs_before + 1

    detail = client.get(f"/api/supplier-bills/{bill_id}", headers=admin).json()
    assert detail["latest_run"]["bill_total_yuan"] >= 0
    assert len(detail["adjustments"]) >= 1
    assert detail["runs"][0]["status"] == "success"


def test_failed_reconciliation_persists_and_is_retryable(context, monkeypatch):
    # 关闭服务端异常重抛，才能拿到 500 响应而非测试进程内抛错
    from src.config.app import create_app

    client = TestClient(create_app(), raise_server_exceptions=False)
    admin = _auth("admin")
    imp = client.post("/api/supplier-bills", headers=admin, json={"period": PERIOD, "csv_text": _csv()})
    bill_id = imp.json()["id"]

    # 在服务层注入故障，触发核对失败
    from src.services import reconcile_service

    def boom(*_a, **_k):
        raise RuntimeError("boom")

    monkeypatch.setattr(reconcile_service.reconcile_model, "reconcile", boom)
    failed = client.post(f"/api/supplier-bills/{bill_id}/reconcile", headers=admin)
    assert failed.status_code == 500

    # 账单与失败批次仍在
    with dbmod.SessionLocal() as db:
        bill = db.get(SupplierBill, bill_id)
        assert bill.status == BillStatus.FAILED.value
        assert bill.error_message and "boom" in bill.error_message

    monkeypatch.undo()
    ok = client.post(f"/api/supplier-bills/{bill_id}/reconcile", headers=admin)
    assert ok.status_code == 200
    assert ok.json()["run"]["status"] == "success"


def _count(model) -> int:
    with dbmod.SessionLocal() as db:
        return db.scalar(select(func.count()).select_from(model)) or 0
