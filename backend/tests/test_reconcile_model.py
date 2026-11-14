"""供应商对账纯函数单测：CSV 解析、四类差异分类、修正台账聚合、确定性。"""
from __future__ import annotations

import pytest

from src.constants.cost_model import RECONCILE_AMOUNT_TOLERANCE_YUAN
from src.constants.enums import DiffType
from src.services import reconcile_model

PERIOD = "2026-11"


def _bill_row(query_id, amount, scan=100.0, unit=0.028, team="team-a", user="u@x.io"):
    return {
        "query_id": query_id,
        "team_code": team,
        "user_email": user,
        "scanned_gb": scan,
        "unit_price": unit,
        "amount_yuan": amount,
    }


def _platform_row(query_id, cost, scan=100.0, status="success", cache_hit=False, team="team-a", user="u@x.io"):
    return {
        "query_id": query_id,
        "team_code": team,
        "user_email": user,
        "scanned_gb": scan,
        "cost_yuan": cost,
        "status": status,
        "cache_hit": cache_hit,
    }


def test_parse_bill_csv_chinese_headers_and_amount_inference():
    csv_text = (
        "查询ID,团队编码,扫描量GB,单价(元/GB),金额(元)\n"
        "qh-001,team-a,100,0.028,\n"
        "qh-002,team-b,200,0.03,6.00\n"
    )
    rows = reconcile_model.parse_bill_csv(csv_text)
    assert len(rows) == 2
    assert rows[0]["query_id"] == "qh-001"
    assert rows[0]["amount_yuan"] == pytest.approx(2.8)
    assert rows[1]["amount_yuan"] == pytest.approx(6.0)


def test_parse_bill_csv_rejects_empty_and_bad_header():
    with pytest.raises(reconcile_model.BillParseError):
        reconcile_model.parse_bill_csv("")
    with pytest.raises(reconcile_model.BillParseError):
        reconcile_model.parse_bill_csv("foo,bar\n1,2\n")
    with pytest.raises(reconcile_model.BillParseError):
        reconcile_model.parse_bill_csv("查询ID,扫描量GB\n,100\n")


def test_file_hash_stable():
    raw = "查询ID,扫描量GB\nqh-1,10\n"
    assert reconcile_model.bill_file_hash(raw) == reconcile_model.bill_file_hash(raw.encode("utf-8"))
    assert reconcile_model.bill_file_hash(raw) != reconcile_model.bill_file_hash(raw + " ")


def test_matched_within_tolerance():
    bill = [_bill_row("q1", 2.8)]
    platform = [_platform_row("q1", 2.8 + RECONCILE_AMOUNT_TOLERANCE_YUAN / 2)]
    result = reconcile_model.reconcile(bill, platform, period=PERIOD)
    assert result["counts"]["matched"] == 1
    assert result["findings"] == []


def test_missing_when_platform_absent():
    bill = [_bill_row("q1", 2.8)]
    result = reconcile_model.reconcile(bill, [], period=PERIOD)
    assert result["counts"]["missing"] == 1
    finding = result["findings"][0]
    assert finding["diff_type"] == DiffType.MISSING.value
    assert finding["diff_amount_yuan"] == pytest.approx(2.8)
    assert finding["detail"]["reason"] == "platform_query_absent"


def test_missing_when_platform_failed_not_billed():
    bill = [_bill_row("q1", 2.8)]
    platform = [_platform_row("q1", 0.0, status="failed")]
    result = reconcile_model.reconcile(bill, platform, period=PERIOD)
    assert result["counts"]["missing"] == 1
    assert result["findings"][0]["detail"]["reason"] == "platform_query_not_billed"


def test_duplicate_rows_in_bill():
    bill = [_bill_row("q1", 2.8), _bill_row("q1", 2.8)]
    platform = [_platform_row("q1", 2.8)]
    result = reconcile_model.reconcile(bill, platform, period=PERIOD)
    assert result["counts"]["duplicate"] == 1
    dup = next(item for item in result["findings"] if item["diff_type"] == DiffType.DUPLICATE.value)
    assert dup["duplicate_seq"] == 2
    assert dup["diff_amount_yuan"] == pytest.approx(2.8)


def test_price_mismatch_dominates_amount_gap():
    # 平台缓存命中 0.3 折 -> 等效单价远低于供应商一口价；判单价不符
    bill = [_bill_row("q1", 2.8, unit=0.028)]
    platform = [_platform_row("q1", 0.84, cache_hit=True)]
    result = reconcile_model.reconcile(bill, platform, period=PERIOD)
    assert result["counts"]["price_mismatch"] == 1
    finding = result["findings"][0]
    assert finding["bill_unit_price"] == pytest.approx(0.028)
    assert finding["platform_unit_price"] == pytest.approx(0.0084)


def test_missing_under_billed_vs_platform_extra():
    # 两侧等效单价完全一致（0.025），金额差来自扫描量；按 供应商-平台 的符号分类
    # 供应商收 2.8 > 平台计 2.5 -> 平台少计（漏计）
    under = reconcile_model.reconcile(
        [_bill_row("q1", 2.8, scan=112.0, unit=0.025)],
        [_platform_row("q1", 2.5, scan=100.0)],
        period=PERIOD,
    )
    assert under["counts"]["missing"] == 1
    assert under["findings"][0]["detail"]["reason"] == "amount_under_billed"

    # 供应商收 2.5 < 平台计 2.8 -> 平台多计
    over = reconcile_model.reconcile(
        [_bill_row("q1", 2.5, scan=100.0, unit=0.025)],
        [_platform_row("q1", 2.8, scan=112.0)],
        period=PERIOD,
    )
    assert over["counts"]["platform_extra"] == 1
    assert over["findings"][0]["diff_amount_yuan"] == pytest.approx(-0.3)


def test_platform_extra_when_bill_absent():
    platform = [_platform_row("q9", 5.0)]
    result = reconcile_model.reconcile([], platform, period=PERIOD)
    assert result["counts"]["platform_extra"] == 1
    assert result["findings"][0]["detail"]["reason"] == "bill_query_absent"


def test_totals_and_determinism():
    bill = [_bill_row("q1", 2.8), _bill_row("q2", 4.0), _bill_row("q3", 1.0, team="team-b")]
    platform = [_platform_row("q1", 2.8), _platform_row("q2", 3.2), _platform_row("q4", 1.5, team="team-c")]
    first = reconcile_model.reconcile(bill, platform, period=PERIOD)
    second = reconcile_model.reconcile(bill, platform, period=PERIOD)
    assert first == second
    assert first["bill_total_yuan"] == pytest.approx(7.8)
    assert first["platform_total_yuan"] == pytest.approx(7.5)
    # q2 漏计 0.8；q3 平台无 -> 漏计 1.0；q4 账单无 -> 平台多计 -1.5
    assert first["diff_total_yuan"] == pytest.approx(0.3)


def test_aggregate_adjustments_excludes_duplicate_from_team_amount():
    findings = [
        {
            "period": PERIOD, "team_code": "team-a", "diff_type": DiffType.MISSING.value,
            "diff_amount_yuan": 10.0, "status": "open",
        },
        {
            "period": PERIOD, "team_code": "team-a", "diff_type": DiffType.DUPLICATE.value,
            "diff_amount_yuan": 6.0, "status": "open",
        },
        {
            "period": PERIOD, "team_code": "team-a", "diff_type": DiffType.MISSING.value,
            "diff_amount_yuan": 4.0, "status": "open",
        },
    ]
    adjustments = reconcile_model.aggregate_adjustments(findings)
    by_type = {row["diff_type"]: row for row in adjustments}
    assert by_type["missing"]["amount_yuan"] == pytest.approx(14.0)
    assert by_type["missing"]["finding_count"] == 2
    assert by_type["duplicate"]["amount_yuan"] == 0.0
    assert by_type["duplicate"]["payable_delta_yuan"] == pytest.approx(6.0)


def test_open_diff_total():
    findings = [
        {"diff_amount_yuan": 10.0, "status": "open"},
        {"diff_amount_yuan": 4.0, "status": "applied"},
        {"diff_amount_yuan": -2.0, "status": "open"},
    ]
    assert reconcile_model.open_diff_total(findings) == pytest.approx(8.0)
