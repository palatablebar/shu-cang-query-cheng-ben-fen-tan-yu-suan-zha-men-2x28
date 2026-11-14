"""路由聚合：统一 /api 前缀（Nginx 反代时剥掉 /api）。"""
from fastapi import APIRouter

from src.routes.alerts import router as alerts_router
from src.routes.audit import router as audit_router
from src.routes.auth import router as auth_router
from src.routes.charges import router as charges_router
from src.routes.cost_runs import router as cost_runs_router
from src.routes.exports import router as exports_router
from src.routes.health import router as health_router
from src.routes.overview import router as overview_router
from src.routes.query_logs import router as query_logs_router
from src.routes.teams import router as teams_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(auth_router)
api_router.include_router(overview_router)
api_router.include_router(teams_router)
api_router.include_router(query_logs_router)
api_router.include_router(cost_runs_router)
api_router.include_router(charges_router)
api_router.include_router(alerts_router)
api_router.include_router(exports_router)
api_router.include_router(audit_router)
