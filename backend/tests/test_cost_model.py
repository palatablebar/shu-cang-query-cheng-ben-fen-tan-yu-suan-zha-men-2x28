"""算法单测：成本口径、分位数/MAD、异常阈值、分摊、预测与分档。"""
from __future__ import annotations

import pytest

from src.services import cost_model

from datetime import date


def test_query_cost_scan_and_compute():
    # 100 GB × 0.028 + 100 GB × 60 s × 0.0004 = 2.8 + 2.4
    assert cost_model.query_cost(100, 60_000) == pytest.approx(5.2, abs=1e-6)


def test_query_cost_cache_discount():
    full = cost_model.query_cost(80, 30_000)
    cached = cost_model.query_cost(80, 30_000, cache_hit=True)
    assert cached == pytest.approx(full * 0.3, abs=1e-6)


def test_query_cost_failed_not_billed():
    assert cost_model.query_cost(500, 600_000, True, "failed") == 0.0
    assert cost_model.query_cost(500, 600_000, False, "timeout") == 0.0


def test_percentile_linear_interpolation():
    assert cost_model.percentile([1, 2, 3, 4, 5], 0.5) == 3.0
    assert cost_model.percentile([1, 2, 3, 4], 0.95) == pytest.approx(3.85)
    assert cost_model.percentile([7.5], 0.95) == 7.5


def test_percentile_rejects_empty_and_bad_q():
    with pytest.raises(ValueError):
        cost_model.percentile([], 0.95)
    with pytest.raises(ValueError):
        cost_model.percentile([1, 2], 1.5)


def test_median_and_mad():
    values = [1, 1, 2, 2, 4, 6, 9]
    assert cost_model.median(values) == 2.0
    # |x-2| = [1,1,0,0,2,4,7] -> median 1
    assert cost_model.median_absolute_deviation(values) == 1.0


def test_anomaly_threshold_known_values():
    values = [float(i) for i in range(1, 101)]
    meta = cost_model.anomaly_threshold(values)
    assert meta["p95_gb"] == pytest.approx(95.05, abs=0.01)
    assert meta["median_gb"] == pytest.approx(50.5, abs=0.01)
    assert meta["mad_gb"] == pytest.approx(25.0, abs=0.01)
    assert meta["threshold_gb"] == pytest.approx(170.05, abs=0.02)


def test_anomaly_boundary_is_strict():
    assert cost_model.is_anomaly(170.5, 170.05) is True
    assert cost_model.is_anomaly(170.05, 170.05) is False
    assert cost_model.anomaly_score(170.05, 170.05) == 0.0


def test_allocate_amounts_and_zero_total():
    ratios = cost_model.allocate_amounts({1: 16028.4, 2: 42180 - 16028.4})
    assert ratios[1] == pytest.approx(0.38, abs=1e-4)
    assert cost_model.allocate_amounts({1: 0.0, 2: 0.0}) == {1: 0.0, 2: 0.0}


def test_mom_ratio():
    assert cost_model.mom_ratio(120.0, 100.0) == pytest.approx(0.2)
    assert cost_model.mom_ratio(120.0, 0.0) is None
    assert cost_model.mom_ratio(120.0, None) is None


def test_forecast_budget():
    result = cost_model.forecast_budget(1000.0, 700.0, 9)
    assert result["daily_avg_yuan"] == pytest.approx(100.0)
    assert result["forecast_yuan"] == pytest.approx(1900.0)
    assert cost_model.forecast_budget(1000.0, 0.0, 0)["forecast_yuan"] == 1000.0


def test_alert_level_bands():
    assert cost_model.alert_level(0.99) == "normal"
    assert cost_model.alert_level(1.0) == "normal"
    assert cost_model.alert_level(1.05) == "watch"
    assert cost_model.alert_level(1.10) == "watch"
    assert cost_model.alert_level(1.1001) == "high"
    assert cost_model.alert_level(1.12) == "high"


def test_gate_action():
    assert cost_model.gate_action("high", True) == "cap_quota"
    assert cost_model.gate_action("watch", True) == "sample_down"
    assert cost_model.gate_action("watch", False) == "materialized_view"
    assert cost_model.gate_action("normal", False) == "watch"


def test_remaining_days_of_month():
    assert cost_model.remaining_days_of_month(date(2026, 11, 13)) == 17
    assert cost_model.remaining_days_of_month(date(2026, 11, 30)) == 0
    assert cost_model.remaining_days_of_month(date(2026, 2, 1)) == 27


def test_deterministic_output():
    values = [3.5, 12.0, 8.25, 40.0, 15.5]
    first = cost_model.anomaly_threshold(values)
    second = cost_model.anomaly_threshold(values)
    assert first == second
