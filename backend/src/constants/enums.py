"""共享枚举（后端唯一定义处）。前端副本见 frontend/site/js/config.js。

README「共享枚举出现位置」一节列出全部出现点，改动需两侧同步。
"""
from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    ADMIN = "admin"
    ANALYST = "analyst"
    VIEWER = "viewer"


class QueryStatus(StrEnum):
    """单条查询的执行结果；失败查询不计费，但扫描量仍计入异常分布。"""

    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"


QUERY_STATUS_LABELS: dict[str, str] = {
    QueryStatus.SUCCESS.value: "成功",
    QueryStatus.FAILED.value: "失败",
    QueryStatus.TIMEOUT.value: "超时",
}


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"


RUN_STATUS_LABELS: dict[str, str] = {
    RunStatus.QUEUED.value: "排队中",
    RunStatus.RUNNING.value: "执行中",
    RunStatus.SUCCESS.value: "成功",
    RunStatus.PARTIAL.value: "部分成功",
    RunStatus.FAILED.value: "失败",
}


class TriggerKind(StrEnum):
    MANUAL = "manual"
    SCHEDULE = "schedule"
    SEED = "seed"


TRIGGER_LABELS: dict[str, str] = {
    TriggerKind.MANUAL.value: "手动",
    TriggerKind.SCHEDULE.value: "定时",
    TriggerKind.SEED.value: "初始化",
}


class AlertLevel(StrEnum):
    """预算预测分档：<=100% 正常 / 100-110% 关注 / >110% 超预算。"""

    NORMAL = "normal"
    WATCH = "watch"
    HIGH = "high"


ALERT_LEVEL_LABELS: dict[str, str] = {
    AlertLevel.NORMAL.value: "正常",
    AlertLevel.WATCH.value: "关注",
    AlertLevel.HIGH.value: "超预算",
}

ALERT_LEVEL_ORDER: list[str] = [AlertLevel.HIGH.value, AlertLevel.WATCH.value, AlertLevel.NORMAL.value]


class AlertStatus(StrEnum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    DISMISSED = "dismissed"


ALERT_STATUS_LABELS: dict[str, str] = {
    AlertStatus.PENDING.value: "待处置",
    AlertStatus.CONFIRMED.value: "已确认",
    AlertStatus.DISMISSED.value: "已驳回",
}

ALERT_STATUS_ORDER: list[str] = [
    AlertStatus.PENDING.value,
    AlertStatus.CONFIRMED.value,
    AlertStatus.DISMISSED.value,
]


class GateAction(StrEnum):
    """预算闸门建议。"""

    CAP_QUOTA = "cap_quota"
    SAMPLE_DOWN = "sample_down"
    MATERIALIZED_VIEW = "materialized_view"
    WATCH = "watch"


GATE_ACTION_LABELS: dict[str, str] = {
    GateAction.CAP_QUOTA.value: "限额",
    GateAction.SAMPLE_DOWN.value: "降采样",
    GateAction.MATERIALIZED_VIEW.value: "物化视图",
    GateAction.WATCH.value: "观察",
}
