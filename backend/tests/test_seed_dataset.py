"""seed 资产生成单测：总额、团队占比、异常条数与确定性。

只依赖纯函数与 demo_config，不连数据库，保证在 pytest 里可独立运行。
"""
from __future__ import annotations

from datetime import datetime, timedelta

from scripts import demo_config
from src.services import cost_model

ANCHOR = datetime(2026, 11, 13, 6, 0, 0)


def _dataset():
    rows = demo_config.build_query_rows(ANCHOR)
    costs = [
        cost_model.query_cost(row["scan"], row["duration_ms"], row["cache_hit"], row["status"]) for row in rows
    ]
    return rows, costs


def test_dataset_size_and_teams():
    rows, _ = _dataset()
    assert len(rows) == demo_config.TOTAL_LOGS == 1200
    assert {row["team_code"] for row in rows} == {"team-a", "team-b", "team-c", "team-d", "team-e"}


def test_total_cost_is_42180():
    _, costs = _dataset()
    assert round(sum(costs), 2) == demo_config.TOTAL_COST_TARGET


def test_team_b_share_is_38_percent():
    rows, costs = _dataset()
    total = sum(costs)
    team_b = sum(cost for row, cost in zip(rows, costs) if row["team_code"] == "team-b")
    assert round(team_b / total, 4) == 0.38
    assert round(team_b, 2) == 16028.40


def test_anomaly_count_and_max_scan():
    rows, _ = _dataset()
    meta = cost_model.anomaly_threshold([row["scan"] for row in rows])
    anomalies = [row for row in rows if row["scan"] > meta["threshold_gb"]]
    assert len(anomalies) == 7
    assert max(row["scan"] for row in anomalies) == 620.0


def test_cache_and_failed_mix():
    rows, _ = _dataset()
    assert sum(1 for row in rows if row["cache_hit"]) > 100
    assert sum(1 for row in rows if row["status"] != "success") > 20


def test_forecast_ratio_bands_for_seed_budgets():
    rows, costs = _dataset()
    cutoff = ANCHOR - timedelta(days=7)
    remaining = 17
    expected = {"team-a": "normal", "team-b": "high", "team-c": "normal", "team-d": "watch", "team-e": "watch"}
    for spec in demo_config.TEAM_SPECS:
        code = spec[0]
        amount = round(sum(cost for row, cost in zip(rows, costs) if row["team_code"] == code), 2)
        last7 = sum(
            cost
            for row, cost in zip(rows, costs)
            if row["team_code"] == code and cost > 0 and row["queried_at"] >= cutoff
        )
        forecast = cost_model.forecast_budget(amount, last7, remaining)
        budget = demo_config.calibrate_budget(code, forecast["forecast_yuan"])
        level = cost_model.alert_level(forecast["forecast_yuan"] / budget)
        assert level == expected[code], (code, level)
    team_b = next(spec for spec in demo_config.TEAM_SPECS if spec[0] == "team-b")
    amount = round(sum(cost for row, cost in zip(rows, costs) if row["team_code"] == "team-b"), 2)
    last7 = sum(
        cost
        for row, cost in zip(rows, costs)
        if row["team_code"] == "team-b" and cost > 0 and row["queried_at"] >= cutoff
    )
    forecast = cost_model.forecast_budget(amount, last7, remaining)
    budget = demo_config.calibrate_budget("team-b", forecast["forecast_yuan"])
    assert round(forecast["forecast_yuan"] / budget * 100) == 112
    assert team_b[5] == 0.38


def test_dataset_is_deterministic():
    first, _ = _dataset()
    second, _ = _dataset()
    assert [(row["query_id"], row["scan"], row["duration_ms"]) for row in first] == [
        (row["query_id"], row["scan"], row["duration_ms"]) for row in second
    ]
