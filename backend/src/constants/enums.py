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
    RECONCILE = "reconcile"


TRIGGER_LABELS: dict[str, str] = {
    TriggerKind.MANUAL.value: "手动",
    TriggerKind.SCHEDULE.value: "定时",
    TriggerKind.SEED.value: "初始化",
    TriggerKind.RECONCILE.value: "对账修正",
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


class BillStatus(StrEnum):
    """供应商账单发布状态：导入 → 核对中 → 待确认/失败 → 已发布。"""

    IMPORTED = "imported"
    CHECKING = "checking"
    MATCHED = "matched"
    FAILED = "failed"
    CONFIRMED = "confirmed"


BILL_STATUS_LABELS: dict[str, str] = {
    BillStatus.IMPORTED.value: "待核对",
    BillStatus.CHECKING.value: "核对中",
    BillStatus.MATCHED.value: "待确认",
    BillStatus.FAILED.value: "核对失败",
    BillStatus.CONFIRMED.value: "已发布",
}


class ReconcileStatus(StrEnum):
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


RECONCILE_STATUS_LABELS: dict[str, str] = {
    ReconcileStatus.RUNNING.value: "核对中",
    ReconcileStatus.SUCCESS.value: "核对成功",
    ReconcileStatus.FAILED.value: "核对失败",
}


class DiffType(StrEnum):
    """逐笔核对差异分类。

    - missing 漏计：供应商已计费、平台未计或计得更少（含失败/超时查询平台不计费）；
    - duplicate 重复：同一 query_id 在供应商账单出现多行；
    - price_mismatch 单价不符：两侧都计费，但供应商整月扫描单价与平台等效单价超容差；
    - platform_extra 平台多计：平台有计费、供应商账单没有该笔；
    - matched 一致：金额与单价均在容差内。
    """

    MISSING = "missing"
    DUPLICATE = "duplicate"
    PRICE_MISMATCH = "price_mismatch"
    PLATFORM_EXTRA = "platform_extra"
    MATCHED = "matched"


DIFF_TYPE_LABELS: dict[str, str] = {
    DiffType.MISSING.value: "漏计",
    DiffType.DUPLICATE.value: "重复",
    DiffType.PRICE_MISMATCH.value: "单价不符",
    DiffType.PLATFORM_EXTRA.value: "平台多计",
    DiffType.MATCHED.value: "一致",
}

DIFF_TYPE_ORDER: list[str] = [
    DiffType.MISSING.value,
    DiffType.DUPLICATE.value,
    DiffType.PRICE_MISMATCH.value,
    DiffType.PLATFORM_EXTRA.value,
    DiffType.MATCHED.value,
]


class FindingStatus(StrEnum):
    """差异处置状态：open 待处置 / applied 随账期修正入账 / dismissed 人工驳回。"""

    OPEN = "open"
    APPLIED = "applied"
    DISMISSED = "dismissed"


FINDING_STATUS_LABELS: dict[str, str] = {
    FindingStatus.OPEN.value: "待处置",
    FindingStatus.APPLIED.value: "已入账",
    FindingStatus.DISMISSED.value: "已驳回",
}
