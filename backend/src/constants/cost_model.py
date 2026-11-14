"""成本口径常量：单价、折扣、异常阈值系数、预算分档。

单价（2026 年 ClickHouse 集群合同价）：
- 扫描：0.028 元 / GB
- 计算：0.0004 元 / GB·秒（按扫描量 × 耗时秒计）
- 缓存命中：按应付金额 0.3 折
- 失败 / 超时查询：不计费
"""
from __future__ import annotations

SCAN_PRICE_PER_GB = 0.028
COMPUTE_PRICE_PER_GB_SECOND = 0.0004
CACHE_DISCOUNT = 0.3
BILL_FAILED_QUERIES = False

# 异常查询：扫描量 > P95 + 3 × MAD
ANOMALY_PERCENTILE = 0.95
ANOMALY_MAD_FACTOR = 3.0

# 预算预测分档（预测金额 / 预算）
WATCH_RATIO = 1.0
HIGH_RATIO = 1.10

# 2026-11-13 基准单价，供 seed 与 README 引用
DEFAULT_UNIT_PRICES: dict[str, float] = {
    "scan_price": SCAN_PRICE_PER_GB,
    "compute_price": COMPUTE_PRICE_PER_GB_SECOND,
    "cache_discount": CACHE_DISCOUNT,
}

# ---- 供应商对账容差（账单按整月扫描量一口价，平台按查询逐条拆缓存/计费状态）----
# 金额容差：逐笔四舍五入与汇总分位差，单笔差异绝对值 <= 0.02 元视为一致
RECONCILE_AMOUNT_TOLERANCE_YUAN = 0.02
# 单价容差：等效扫描单价 = 金额 / 扫描量，相对偏差 > 1% 判为单价不符
RECONCILE_PRICE_REL_TOLERANCE = 0.01
# 供应商账单允许的最小扫描量（GB），避免除零
RECONCILE_MIN_SCANNED_GB = 0.000001
