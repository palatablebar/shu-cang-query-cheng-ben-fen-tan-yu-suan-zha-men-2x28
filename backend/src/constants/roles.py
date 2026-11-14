"""角色 -> 权限点映射。README 与前端 site/js/config.js 同步。

角色键固定为 admin / analyst / viewer，各项目的展示名与职责不同。
- admin：配置团队预算、维护单价、导出账单、查看审计
- analyst：发起成本运行、查看查询日志、标记/复核异常
- viewer：只看自己团队（team 隔离，越权 403）
"""
from __future__ import annotations

from src.constants.enums import Role

ROLE_LABELS: dict[str, str] = {
    Role.ADMIN.value: "平台管理员",
    Role.ANALYST.value: "数据专员",
    Role.VIEWER.value: "团队只读",
}

ROLE_DUTIES: dict[str, str] = {
    Role.ADMIN.value: "配置团队预算与单价、发起成本运行、导出账单、查看审计",
    Role.ANALYST.value: "发起成本运行、查看查询日志、复核预算告警",
    Role.VIEWER.value: "只读本人所在团队的成本、查询与告警",
}

PERMISSIONS: dict[str, set[str]] = {
    Role.ADMIN.value: {
        "team:read", "team:write",
        "querylog:read",
        "run:read", "run:create",
        "charge:read", "alert:read", "alert:review",
        "export:read", "audit:read", "overview:read",
    },
    Role.ANALYST.value: {
        "team:read", "querylog:read",
        "run:read", "run:create",
        "charge:read", "alert:read", "alert:review",
        "overview:read",
    },
    Role.VIEWER.value: {
        "team:read", "querylog:read", "run:read", "charge:read", "alert:read", "overview:read",
    },
}

TEAM_WRITE_ROLES = (Role.ADMIN.value,)
RUN_CREATE_ROLES = (Role.ADMIN.value, Role.ANALYST.value)
ALERT_REVIEW_ROLES = (Role.ADMIN.value, Role.ANALYST.value)
EXPORT_ROLES = (Role.ADMIN.value,)
AUDIT_ROLES = (Role.ADMIN.value,)
READ_ROLES = (Role.ADMIN.value, Role.ANALYST.value, Role.VIEWER.value)


def has_permission(role: str, permission: str) -> bool:
    return permission in PERMISSIONS.get(role, set())
