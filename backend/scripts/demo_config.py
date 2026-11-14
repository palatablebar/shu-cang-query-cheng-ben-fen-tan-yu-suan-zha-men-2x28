"""costcharge 演示数据：5 团队 / 3 账号 / 1,200 条查询日志。

日志生成是确定性的（固定随机种子），并经过配平：
- 五个团队金额精确落在 42,180 元的 21% / 38% / 17% / 14% / 10%；
- 恰好 7 条查询越过 P95+3×MAD 异常阈值，最大 620 GB；
- 团队预算由预测金额反推，使 B 团队预测/预算 ≈ 112%（high）、D 104%、E 101%。

注意：seed 只在团队首次创建时写入预算，重复执行不会覆盖管理员后来改过的预算。
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta

from src.constants.cost_model import CACHE_DISCOUNT, COMPUTE_PRICE_PER_GB_SECOND, SCAN_PRICE_PER_GB

DEMO_PASSWORD = "Demo@2026"
ORG = "云格 SaaS · 数据平台组"

DEMO_USERS = [
    ("admin@costcharge.io", "林可", "admin", None),
    ("analyst@costcharge.io", "周棠", "analyst", "team-b"),
    ("viewer@costcharge.io", "陈默", "viewer", "team-c"),
]

# code, name, cost_center, owner, prev_month_yuan, share, query_count, outlier_count, members
TEAM_SPECS = [
    (
        "team-a",
        "计算平台组",
        "CC-1001",
        "沈奕",
        8200.0,
        0.21,
        242,
        1,
        ["shen.yi@costcharge.io", "lu.heng@costcharge.io"],
    ),
    (
        "team-b",
        "增长分析组",
        "CC-1002",
        "罗清清",
        14900.0,
        0.38,
        298,
        2,
        ["luo.qq@costcharge.io", "zhou.tang@costcharge.io", "mai.xin@costcharge.io"],
    ),
    (
        "team-c",
        "供应链数据组",
        "CC-1003",
        "何至",
        7800.0,
        0.17,
        240,
        1,
        ["he.zhi@costcharge.io", "chen.mo@costcharge.io"],
    ),
    (
        "team-d",
        "财务数据组",
        "CC-1004",
        "唐雯",
        6100.0,
        0.14,
        220,
        1,
        ["tang.wen@costcharge.io", "qiu.shu@costcharge.io"],
    ),
    (
        "team-e",
        "风控建模组",
        "CC-1005",
        "邓一鸣",
        3900.0,
        0.10,
        200,
        2,
        ["deng.ym@costcharge.io", "yu.ke@costcharge.io"],
    ),
]

# 预算标定目标：预测 / 预算
TARGET_FORECAST_RATIOS = {
    "team-a": 0.88,
    "team-b": 1.12,
    "team-c": 0.96,
    "team-d": 1.04,
    "team-e": 1.01,
}
BUDGET_STEPS = {"team-b": 10.0}

TOTAL_COST_TARGET = 42180.0
TOTAL_LOGS = 1200

SQL_DIGESTS = [
    "SELECT dt, region, sum(gmv) FROM dwd_order GROUP BY dt, region",
    "SELECT user_id, count() FROM dwd_login WHERE dt BETWEEN ? AND ? GROUP BY user_id",
    "WITH base AS (SELECT * FROM dwd_event WHERE dt = ?) SELECT event, count() FROM base GROUP BY event",
    "SELECT campaign, sum(cost) FROM dwd_ad_spend GROUP BY campaign ORDER BY 2 DESC",
    "SELECT sku, sum(qty) FROM dwd_inventory GROUP BY sku HAVING sum(qty) < ?",
    "SELECT * FROM dws_user_profile WHERE tag = ? LIMIT 5000",
    "SELECT toStartOfHour(ts) h, avg(v) FROM dwd_metric WHERE ts >= ? GROUP BY h",
    "SELECT team, countIf(flag) FROM dwd_ticket GROUP BY team",
]


def _scan_pick(rng: random.Random) -> float:
    roll = rng.random()
    if roll < 0.80:
        return rng.uniform(40, 150)
    if roll < 0.98:
        return rng.uniform(150, 255)
    return rng.uniform(255, 299)


def build_query_rows(anchor: datetime) -> list[dict]:
    """生成 1,200 条查询（确定性的；anchor 为 UTC naive 的当前时刻）。"""
    rng = random.Random(20261113)
    outlier_pool = [620.0, 600.0, 575.0, 550.0, 520.0, 480.0, 458.0]
    rows: list[dict] = []

    for code, _name, _cc, _owner, _prev, share, count, outliers, members in TEAM_SPECS:
        target = TOTAL_COST_TARGET * share
        scans = outlier_pool[:outliers]
        outlier_pool = outlier_pool[outliers:]
        outlier_costs = 0.0
        for outlier_index, scan in enumerate(scans):
            duration_s = rng.uniform(240, 1800)
            cost = scan * SCAN_PRICE_PER_GB + scan * duration_s * COMPUTE_PRICE_PER_GB_SECOND
            outlier_costs += cost
            rows.append(
                {
                    "team_code": code,
                    "scan": round(scan, 3),
                    "duration_ms": int(duration_s * 1000),
                    "cache_hit": False,
                    "status": "success",
                    "user_email": members[outlier_index % len(members)],
                    "sql_digest": SQL_DIGESTS[(len(rows) * 5) % len(SQL_DIGESTS)],
                }
            )

        base_budget = target - outlier_costs
        candidates = []
        for _index in range(count - outliers):
            status = "failed" if rng.random() < 0.04 else "success"
            cache_hit = rng.random() < 0.18
            candidates.append(
                {
                    "status": status,
                    "cache_hit": cache_hit,
                    "weight": 0.4 + rng.random() * 1.6,
                    "scan_seed": _scan_pick(rng),
                }
            )
        billed = [item for item in candidates if item["status"] == "success"]
        weight_sum = sum(item["weight"] for item in billed)
        for item in billed:
            amount = base_budget * item["weight"] / weight_sum
            multiplier = CACHE_DISCOUNT if item["cache_hit"] else 1.0
            scan = item["scan_seed"]
            low = max(5.0, amount / (multiplier * (SCAN_PRICE_PER_GB + 7200 * COMPUTE_PRICE_PER_GB_SECOND)))
            high = min(300.0, amount / (multiplier * (SCAN_PRICE_PER_GB + 30 * COMPUTE_PRICE_PER_GB_SECOND)))
            if low > high:
                low = high
            scan = max(low, min(high, scan))
            duration_s = (amount / multiplier - scan * SCAN_PRICE_PER_GB) / (scan * COMPUTE_PRICE_PER_GB_SECOND)
            item["scan"] = round(scan, 3)
            item["duration_s"] = max(15.0, duration_s)
        for item in candidates:
            if item["status"] == "success":
                continue
            item["scan"] = round(item["scan_seed"], 3)
            item["duration_s"] = rng.uniform(30, 2400)

        # 收尾：用一条非缓存成功查询的耗时把团队金额精确配平到分
        team_total = outlier_costs + sum(
            (
                item["scan"] * SCAN_PRICE_PER_GB
                + item["scan"] * item["duration_s"] * COMPUTE_PRICE_PER_GB_SECOND
            )
            * (CACHE_DISCOUNT if item["cache_hit"] else 1.0)
            for item in billed
        )
        gap = target - team_total
        last = billed[-1]
        multiplier = CACHE_DISCOUNT if last["cache_hit"] else 1.0
        last["duration_s"] += gap / (multiplier * last["scan"] * COMPUTE_PRICE_PER_GB_SECOND)

        for index, item in enumerate(candidates):
            rows.append(
                {
                    "team_code": code,
                    "scan": item["scan"],
                    "duration_ms": int(round(item["duration_s"] * 1000)),
                    "cache_hit": item["cache_hit"],
                    "status": item["status"],
                    "user_email": members[index % len(members)],
                    "sql_digest": SQL_DIGESTS[(index * 7 + len(rows)) % len(SQL_DIGESTS)],
                }
            )

    for index, row in enumerate(rows):
        row["query_id"] = f"qh-{index + 1:05d}"
        day = index % 30
        hour = (index * 7) % 24
        minute = (index * 13) % 60
        row["queried_at"] = anchor - timedelta(days=day, hours=hour, minutes=minute)
    return rows


def calibrate_budget(team_code: str, forecast_yuan: float) -> float:
    """按目标预测比反推预算（取 100/50 元整），让演示数据落在预期分档。"""
    ratio = TARGET_FORECAST_RATIOS.get(team_code, 1.0)
    step = BUDGET_STEPS.get(team_code, 50.0)
    raw = forecast_yuan / ratio
    return max(step, round(raw / step) * step)
