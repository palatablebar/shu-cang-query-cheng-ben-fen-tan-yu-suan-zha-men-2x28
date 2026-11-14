"""成本模型（纯函数，可单测，不依赖数据库/网络）。

算法 A｜成本计算与分摊
    cost = (scan_gb * 扫描单价 + scan_gb * 耗时秒 * 计算单价) * 缓存折扣
    - 缓存命中按 0.3 折；失败/超时查询不计费；
    - 团队金额 = 该团队计费查询之和；占比 = 团队金额 / 总金额；
    - 环比 = 本期金额 / 上月金额 - 1（上月金额来自团队台账）。

算法 B｜异常与预算预测
    - 异常：单查询扫描量 > P95 + 3 × MAD（中位数绝对偏差）；
    - 预测 = 已用 + 近 7 天日均 × 剩余天数；
    - 分档：<=100% 正常 / 100-110% 关注 / >110% 超预算；
    - 闸门建议：超预算 -> 限额；有关注且有异常 -> 降采样；其余 -> 物化视图。

所有函数保持确定性：相同输入两次调用结果逐位一致。
"""
from __future__ import annotations

import calendar
import math
from datetime import date

from src.constants.cost_model import (
    ANOMALY_MAD_FACTOR,
    ANOMALY_PERCENTILE,
    CACHE_DISCOUNT,
    COMPUTE_PRICE_PER_GB_SECOND,
    HIGH_RATIO,
    SCAN_PRICE_PER_GB,
    WATCH_RATIO,
)
from src.constants.enums import AlertLevel, GateAction, QueryStatus


def query_cost(
    scanned_gb: float,
    duration_ms: int,
    cache_hit: bool = False,
    status: str = QueryStatus.SUCCESS.value,
    *,
    scan_price: float = SCAN_PRICE_PER_GB,
    compute_price: float = COMPUTE_PRICE_PER_GB_SECOND,
    cache_discount: float = CACHE_DISCOUNT,
) -> float:
    """单条查询应付金额（元）。失败/超时查询不计费。"""
    if status != QueryStatus.SUCCESS.value:
        return 0.0
    gb = max(0.0, float(scanned_gb or 0.0))
    seconds = max(0, int(duration_ms or 0)) / 1000.0
    amount = gb * scan_price + gb * seconds * compute_price
    if cache_hit:
        amount *= cache_discount
    return round(amount, 6)


def percentile(values: list[float], q: float = ANOMALY_PERCENTILE) -> float:
    """线性插值分位数（确定性）。空集或越界 q 抛 ValueError。"""
    if not values:
        raise ValueError("percentile of empty sequence")
    if not 0.0 <= q <= 1.0:
        raise ValueError("q must be within [0, 1]")
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * q
    lower = int(math.floor(position))
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def median(values: list[float]) -> float:
    return percentile(values, 0.5)


def median_absolute_deviation(values: list[float]) -> float:
    """MAD：|x - median| 的中位数。"""
    center = median(values)
    return median([abs(float(value) - center) for value in values])


def anomaly_threshold(
    scanned_values: list[float],
    *,
    q: float = ANOMALY_PERCENTILE,
    mad_factor: float = ANOMALY_MAD_FACTOR,
) -> dict:
    """P95 + 3 × MAD；返回分档所需的全部分量。"""
    p95 = percentile(scanned_values, q)
    med = median(scanned_values)
    mad = median_absolute_deviation(scanned_values)
    threshold = p95 + mad_factor * mad
    return {
        "p95_gb": round(p95, 3),
        "median_gb": round(med, 3),
        "mad_gb": round(mad, 3),
        "threshold_gb": round(threshold, 3),
        "mad_factor": mad_factor,
        "percentile": q,
    }


def is_anomaly(scanned_gb: float, threshold_gb: float) -> bool:
    return float(scanned_gb) > float(threshold_gb)


def anomaly_score(scanned_gb: float, threshold_gb: float) -> float:
    """超出阈值的倍数，便于排序；未超阈值返回 0。"""
    if threshold_gb <= 0 or scanned_gb <= threshold_gb:
        return 0.0
    return round((scanned_gb - threshold_gb) / threshold_gb, 4)


def anomaly_reason(scanned_gb: float, meta: dict) -> str:
    return (
        f"扫描 {scanned_gb:.1f} GB > 阈值 {meta['threshold_gb']:.1f} GB "
        f"(P95 {meta['p95_gb']:.1f} + {meta['mad_factor']:g}×MAD {meta['mad_gb']:.1f})"
    )


def allocate_amounts(team_amounts: dict[int | str, float]) -> dict[int | str, float]:
    """按金额算占比（保留 4 位小数）；总额为 0 时全部返回 0。"""
    total = sum(float(value) for value in team_amounts.values())
    if total <= 0:
        return {key: 0.0 for key in team_amounts}
    return {key: round(float(value) / total, 4) for key, value in team_amounts.items()}


def mom_ratio(current_yuan: float, prev_month_yuan: float | None) -> float | None:
    """环比：本期 / 上月 - 1；上月缺失或为 0 时返回 None。"""
    if not prev_month_yuan:
        return None
    return round(float(current_yuan) / float(prev_month_yuan) - 1.0, 4)


def remaining_days_of_month(today: date) -> int:
    """本月剩余天数（不含当天）。"""
    last_day = calendar.monthrange(today.year, today.month)[1]
    return max(0, last_day - today.day)


def forecast_budget(used_yuan: float, last7_yuan: float, remaining_days: int) -> dict:
    """预测 = 已用 + 近 7 天日均 × 剩余天数。"""
    daily_avg = float(last7_yuan) / 7.0
    remaining = max(0, int(remaining_days))
    forecast = float(used_yuan) + daily_avg * remaining
    return {
        "used_yuan": round(float(used_yuan), 2),
        "daily_avg_yuan": round(daily_avg, 2),
        "remaining_days": remaining,
        "forecast_yuan": round(forecast, 2),
    }


def alert_level(ratio: float) -> str:
    """预测金额 / 预算 的分档。"""
    if ratio > HIGH_RATIO:
        return AlertLevel.HIGH.value
    if ratio > WATCH_RATIO:
        return AlertLevel.WATCH.value
    return AlertLevel.NORMAL.value


def gate_action(level: str, has_anomaly: bool = False) -> str:
    """闸门建议：限额 / 降采样 / 物化视图 / 观察。"""
    if level == AlertLevel.HIGH.value:
        return GateAction.CAP_QUOTA.value
    if level == AlertLevel.WATCH.value:
        return GateAction.SAMPLE_DOWN.value if has_anomaly else GateAction.MATERIALIZED_VIEW.value
    return GateAction.WATCH.value


def summary_metrics(
    *,
    total_cost_yuan: float,
    billed_count: int,
    failed_count: int,
    cache_hits: int,
    scanned_gb: float,
    anomaly_meta: dict,
    anomaly_count: int,
    remaining_days: int,
) -> dict:
    """运行快照指标（写入 CostRun.metrics）。"""
    return {
        "total_cost_yuan": round(total_cost_yuan, 2),
        "billed_queries": billed_count,
        "failed_queries": failed_count,
        "cache_hits": cache_hits,
        "cache_hit_ratio": round(cache_hits / (billed_count + failed_count), 4)
        if (billed_count + failed_count)
        else 0.0,
        "scanned_gb": round(scanned_gb, 2),
        "avg_cost_yuan": round(total_cost_yuan / billed_count, 2) if billed_count else 0.0,
        "anomaly_count": anomaly_count,
        "remaining_days": remaining_days,
        **anomaly_meta,
    }
