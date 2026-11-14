"""Celery 任务：心跳、每日成本重算（按当前账期生成一次成本运行）。"""
from __future__ import annotations

import time

from src.config.celery_app import TASK_DAILY, TASK_HEARTBEAT, celery_app
from src.config.settings import settings
from src.utils.logger import get_logger

logger = get_logger("tasks")


def _redis():
    import redis

    return redis.Redis.from_url(settings.redis_url, decode_responses=True)


@celery_app.task(name=TASK_HEARTBEAT)
def heartbeat() -> str:
    try:
        _redis().set(f"{settings.app_name}:worker:heartbeat", time.time())
        return "ok"
    except Exception as exc:  # noqa: BLE001
        logger.warning("heartbeat failed: %s", exc)
        return "error"


@celery_app.task(name=TASK_DAILY)
def daily_cost_recompute() -> dict:
    from src.config.database import session_scope
    from src.services import audit_service, cost_run_service
    from src.utils.timeutil import local_now

    with session_scope() as db:
        run = cost_run_service.create_and_execute(
            db,
            period=f"{local_now():%Y-%m}",
            operator_email="scheduler@" + settings.app_name + ".io",
            payload={"trigger": "schedule"},
        )
        audit_service.record(
            db,
            actor_email="scheduler@" + settings.app_name + ".io",
            actor_role="admin",
            action="run.create",
            entity="cost_run",
            entity_id=run.id,
            detail={"trigger": "schedule", "run_no": run.run_no, "total_cost_yuan": run.total_cost_yuan},
            layer="worker",
        )
    logger.info("daily cost recompute finished: %s", run.run_no)
    return {"run_no": run.run_no, "total_cost_yuan": run.total_cost_yuan}
