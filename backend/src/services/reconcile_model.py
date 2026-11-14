"""供应商对账模型（纯函数，可单测，不依赖数据库/网络）。

口径背景：供应商按整月扫描量一口价结算（账单行 = query_id + 扫描量 + 单价 + 金额），
平台按每条查询的缓存折扣与计费状态逐条计费（失败/超时不计费、缓存命中 0.3 折）。
本模块把两侧逐笔对齐，输出四类差异：

- missing 漏计：供应商收了、平台少计/未计（含失败超时查询平台不计费但供应商计费）；
- duplicate 重复：同一 query_id 在供应商账单出现多行，多出的行即重复计费；
- price_mismatch 单价不符：两侧都计费，但等效扫描单价相对偏差超过容差；
- platform_extra 平台多计：平台计了费、供应商账单没有该笔（或同笔平台金额更高）。

所有函数保持确定性：相同输入两次调用结果逐位一致。
"""
from __future__ import annotations

import csv
import hashlib
import io
from datetime import datetime

from src.constants.cost_model import (
    RECONCILE_AMOUNT_TOLERANCE_YUAN,
    RECONCILE_MIN_SCANNED_GB,
    RECONCILE_PRICE_REL_TOLERANCE,
)
from src.constants.enums import DiffType

# 账单表头别名：中文模板列名 -> 标准字段
HEADER_ALIASES: dict[str, str] = {
    "查询id": "query_id",
    "query_id": "query_id",
    "queryid": "query_id",
    "团队编码": "team_code",
    "团队": "team_code",
    "team_code": "team_code",
    "team": "team_code",
    "用户邮箱": "user_email",
    "用户": "user_email",
    "user_email": "user_email",
    "扫描量gb": "scanned_gb",
    "扫描量": "scanned_gb",
    "scanned_gb": "scanned_gb",
    "scan_gb": "scanned_gb",
    "单价(元/gb)": "unit_price",
    "单价": "unit_price",
    "unit_price": "unit_price",
    "金额(元)": "amount_yuan",
    "金额": "amount_yuan",
    "amount_yuan": "amount_yuan",
    "amount": "amount_yuan",
    "查询时间": "queried_at",
    "queried_at": "queried_at",
}

REQUIRED_FIELDS = ("query_id", "scanned_gb")


class BillParseError(ValueError):
    """账单 CSV 结构或字段非法。"""


def bill_file_hash(raw: str | bytes) -> str:
    """账单原文 SHA-256；重跑同一文件靠它去重。"""
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _to_float(value: object, default: float = 0.0) -> float:
    if value is None or value == "":
        return default
    return float(str(value).strip().replace(",", "").replace("¥", ""))


def _parse_dt(value: object) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    try:
        return datetime.fromisoformat(text.replace("/", "-"))
    except ValueError:
        try:
            from dateutil import parser as date_parser

            return date_parser.parse(text)
        except (ValueError, OverflowError):
            return None


def parse_bill_csv(raw_text: str) -> list[dict]:
    """解析供应商账单 CSV 为标准行字典列表。

    表头中英文皆可；金额缺失时按 扫描量 × 单价 推算；空文件/缺列/缺必填抛 BillParseError。
    """
    buffer = io.StringIO(raw_text.lstrip("﻿"))
    reader = csv.reader(buffer)
    try:
        header = next(reader)
    except StopIteration as exc:
        raise BillParseError("账单为空，没有表头行") from exc
    keys = [HEADER_ALIASES.get((cell or "").strip().lower()) for cell in header]
    if not any(keys):
        raise BillParseError("账单表头无法识别，请使用模板列名")
    missing_cols = [name for name in REQUIRED_FIELDS if name not in keys]
    if missing_cols:
        raise BillParseError(f"账单缺少必填列：{', '.join(missing_cols)}")

    rows: list[dict] = []
    for line_no, raw_row in enumerate(reader, start=2):
        if not any((cell or "").strip() for cell in raw_row):
            continue
        record = {key: raw_row[index].strip() for index, key in enumerate(keys) if key}
        query_id = record.get("query_id", "").strip()
        if not query_id:
            raise BillParseError(f"第 {line_no} 行缺少查询 ID")
        scanned = _to_float(record.get("scanned_gb"))
        if scanned < 0:
            raise BillParseError(f"第 {line_no} 行扫描量不能为负")
        unit_price = _to_float(record.get("unit_price"))
        amount = _to_float(record.get("amount_yuan"))
        if amount <= 0 and scanned > 0 and unit_price > 0:
            amount = round(scanned * unit_price, 6)
        rows.append(
            {
                "query_id": query_id,
                "team_code": record.get("team_code", "").strip(),
                "user_email": record.get("user_email", "").strip(),
                "scanned_gb": round(scanned, 6),
                "unit_price": round(unit_price, 6),
                "amount_yuan": round(amount, 6),
                "queried_at": _parse_dt(record.get("queried_at")),
                "raw_line": ",".join(raw_row)[:1000],
            }
        )
    if not rows:
        raise BillParseError("账单没有任何数据行")
    return rows


def effective_unit_price(amount_yuan: float, scanned_gb: float) -> float:
    """等效扫描单价 = 金额 / 扫描量；扫描量为 0 时返回 0。"""
    if float(scanned_gb) <= RECONCILE_MIN_SCANNED_GB:
        return 0.0
    return round(float(amount_yuan) / float(scanned_gb), 8)


def _is_price_mismatch(bill_unit: float, platform_unit: float, price_tol: float) -> bool:
    if bill_unit <= 0 or platform_unit <= 0:
        return False
    deviation = abs(bill_unit - platform_unit) / platform_unit
    return deviation > price_tol


def _finding(
    *,
    diff_type: str,
    query_id: str,
    team_code: str | None,
    user_email: str | None,
    period: str,
    bill_row: dict | None,
    platform_row: dict | None,
    duplicate_seq: int = 1,
    extra_detail: dict | None = None,
) -> dict:
    bill_amount = round(float(bill_row["amount_yuan"]), 6) if bill_row else 0.0
    bill_scanned = round(float(bill_row["scanned_gb"]), 6) if bill_row else 0.0
    bill_unit = effective_unit_price(bill_amount, bill_scanned) if bill_row else 0.0
    platform_amount = round(float(platform_row["cost_yuan"]), 6) if platform_row else 0.0
    platform_scanned = round(float(platform_row["scanned_gb"]), 6) if platform_row else 0.0
    platform_unit = effective_unit_price(platform_amount, platform_scanned) if platform_row else 0.0
    detail = {
        "bill_status": "billed" if bill_row else "absent",
        "platform_status": platform_row.get("status") if platform_row else "absent",
        "platform_cache_hit": bool(platform_row.get("cache_hit")) if platform_row else False,
    }
    if extra_detail:
        detail.update(extra_detail)
    return {
        "query_id": query_id,
        "team_code": team_code,
        "user_email": user_email,
        "period": period,
        "diff_type": diff_type,
        "duplicate_seq": duplicate_seq,
        "bill_scanned_gb": bill_scanned,
        "platform_scanned_gb": platform_scanned,
        "bill_amount_yuan": bill_amount,
        "platform_amount_yuan": platform_amount,
        "diff_amount_yuan": round(bill_amount - platform_amount, 6),
        "bill_unit_price": bill_unit,
        "platform_unit_price": platform_unit,
        "detail": detail,
    }


def reconcile(
    bill_rows: list[dict],
    platform_rows: list[dict],
    *,
    period: str,
    amount_tolerance: float = RECONCILE_AMOUNT_TOLERANCE_YUAN,
    price_tolerance: float = RECONCILE_PRICE_REL_TOLERANCE,
) -> dict:
    """逐笔核对。入参均为标准字典行（见 parse_bill_csv 与服务层的 ORM 转换）。

    返回 {"findings": [...], "counts": {...}, "bill_total", "platform_total",
          "diff_total", "matched_count"}，确定性、无副作用。
    """
    bill_groups: dict[str, list[dict]] = {}
    for row in bill_rows:
        bill_groups.setdefault(row["query_id"], []).append(row)

    platform_groups: dict[str, list[dict]] = {}
    for row in platform_rows:
        platform_groups.setdefault(row["query_id"], []).append(row)

    findings: list[dict] = []
    counts = {
        DiffType.MISSING.value: 0,
        DiffType.DUPLICATE.value: 0,
        DiffType.PRICE_MISMATCH.value: 0,
        DiffType.PLATFORM_EXTRA.value: 0,
        DiffType.MATCHED.value: 0,
    }
    matched_pairs = 0

    for query_id, group in bill_groups.items():
        platform_group = platform_groups.get(query_id, [])
        platform_row = platform_group[0] if platform_group else None
        first = group[0]
        base_team = first.get("team_code") or (platform_row.get("team_code") if platform_row else None)
        base_user = first.get("user_email") or (platform_row.get("user_email") if platform_row else None)

        # 1) 供应商账单内重复行：第 2 行起全部判 duplicate
        for dup in group[1:]:
            findings.append(
                _finding(
                    diff_type=DiffType.DUPLICATE.value,
                    query_id=query_id,
                    team_code=dup.get("team_code") or base_team,
                    user_email=dup.get("user_email") or base_user,
                    period=period,
                    bill_row=dup,
                    platform_row=None,
                )
            )

        # 2) 首行与平台逐笔对齐
        if platform_row is None:
            findings.append(
                _finding(
                    diff_type=DiffType.MISSING.value,
                    query_id=query_id,
                    team_code=base_team,
                    user_email=base_user,
                    period=period,
                    bill_row=first,
                    platform_row=None,
                    extra_detail={"reason": "platform_query_absent"},
                )
            )
            continue

        if str(platform_row.get("status", "success")) != "success" or float(platform_row.get("cost_yuan", 0.0)) <= 0.0:
            # 平台失败/超时不计费，供应商仍计费 -> 漏计
            if float(first["amount_yuan"]) > amount_tolerance:
                findings.append(
                    _finding(
                        diff_type=DiffType.MISSING.value,
                        query_id=query_id,
                        team_code=base_team,
                        user_email=base_user,
                        period=period,
                        bill_row=first,
                        platform_row=platform_row,
                        extra_detail={"reason": "platform_query_not_billed"},
                    )
                )
            else:
                counts[DiffType.MATCHED.value] += 1
                matched_pairs += 1
            continue

        bill_amount = float(first["amount_yuan"])
        platform_amount = float(platform_row["cost_yuan"])
        diff = bill_amount - platform_amount
        if abs(diff) <= amount_tolerance:
            counts[DiffType.MATCHED.value] += 1
            matched_pairs += 1
            continue

        bill_unit = effective_unit_price(bill_amount, float(first["scanned_gb"]))
        platform_unit = effective_unit_price(platform_amount, float(platform_row["scanned_gb"]))
        if _is_price_mismatch(bill_unit, platform_unit, price_tolerance):
            findings.append(
                _finding(
                    diff_type=DiffType.PRICE_MISMATCH.value,
                    query_id=query_id,
                    team_code=base_team,
                    user_email=base_user,
                    period=period,
                    bill_row=first,
                    platform_row=platform_row,
                    extra_detail={
                        "reason": "unit_price_deviation",
                        "price_relative_diff": round(
                            abs(bill_unit - platform_unit) / platform_unit, 6
                        ) if platform_unit else None,
                    },
                )
            )
        elif diff > 0:
            findings.append(
                _finding(
                    diff_type=DiffType.MISSING.value,
                    query_id=query_id,
                    team_code=base_team,
                    user_email=base_user,
                    period=period,
                    bill_row=first,
                    platform_row=platform_row,
                    extra_detail={"reason": "amount_under_billed"},
                )
            )
        else:
            findings.append(
                _finding(
                    diff_type=DiffType.PLATFORM_EXTRA.value,
                    query_id=query_id,
                    team_code=base_team,
                    user_email=base_user,
                    period=period,
                    bill_row=first,
                    platform_row=platform_row,
                    extra_detail={"reason": "amount_over_billed"},
                )
            )

    # 3) 平台有、账单没有的计费查询 -> 平台多计
    for query_id, platform_group in platform_groups.items():
        if query_id in bill_groups:
            continue
        platform_row = platform_group[0]
        if float(platform_row.get("cost_yuan", 0.0)) <= 0.0:
            continue
        findings.append(
            _finding(
                diff_type=DiffType.PLATFORM_EXTRA.value,
                query_id=query_id,
                team_code=platform_row.get("team_code"),
                user_email=platform_row.get("user_email"),
                period=period,
                bill_row=None,
                platform_row=platform_row,
                extra_detail={"reason": "bill_query_absent"},
            )
        )

    # 4) 统一修正 duplicate_seq（同 query_id 第 n 行，n 从 2 开始）
    seq_cursor: dict[str, int] = {}
    for finding in findings:
        if finding["diff_type"] == DiffType.DUPLICATE.value:
            seq_cursor[finding["query_id"]] = seq_cursor.get(finding["query_id"], 1) + 1
            finding["duplicate_seq"] = seq_cursor[finding["query_id"]]

    for finding in findings:
        counts[finding["diff_type"]] += 1

    bill_total = round(sum(float(row["amount_yuan"]) for row in bill_rows), 2)
    platform_total = round(sum(float(row.get("cost_yuan", 0.0)) for row in platform_rows), 2)
    diff_total = round(sum(float(item["diff_amount_yuan"]) for item in findings), 2)
    return {
        "findings": findings,
        "counts": counts,
        "matched_count": matched_pairs,
        "bill_total_yuan": bill_total,
        "platform_total_yuan": platform_total,
        "diff_total_yuan": diff_total,
    }


def aggregate_adjustments(findings: list[dict]) -> list[dict]:
    """把差异按 (账期, 团队, 差异类型) 聚成修正台账行。

    amount_yuan 只汇总影响平台团队分摊的类型（duplicate 是供应商冲红，不改平台分摊）；
    payable_delta_yuan 含全部类型，是供应商应付口径的修正。
    """
    bucket: dict[tuple, dict] = {}
    for finding in findings:
        key = (finding["period"], finding.get("team_code") or "unknown", finding["diff_type"])
        entry = bucket.setdefault(
            key,
            {
                "period": key[0],
                "team_code": key[1],
                "diff_type": key[2],
                "amount_yuan": 0.0,
                "payable_delta_yuan": 0.0,
                "finding_count": 0,
            },
        )
        delta = float(finding["diff_amount_yuan"])
        entry["payable_delta_yuan"] = round(entry["payable_delta_yuan"] + delta, 6)
        if finding["diff_type"] != DiffType.DUPLICATE.value:
            entry["amount_yuan"] = round(entry["amount_yuan"] + delta, 6)
        entry["finding_count"] += 1
    return sorted(bucket.values(), key=lambda item: (item["period"], item["team_code"], item["diff_type"]))


def open_diff_total(findings: list[dict]) -> float:
    """未处置（open）差异的金额合计；用于"差异清零前"判断。"""
    return round(
        sum(float(item["diff_amount_yuan"]) for item in findings if item.get("status", "open") == "open"),
        2,
    )
