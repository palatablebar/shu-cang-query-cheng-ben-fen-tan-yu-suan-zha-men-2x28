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
