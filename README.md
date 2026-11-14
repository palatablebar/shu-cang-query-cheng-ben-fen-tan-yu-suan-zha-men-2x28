# costcharge · 数仓查询成本分摊与预算闸门

云格 SaaS 数据平台的内部计费工作台：把 ClickHouse `query_log` 变成可解释的团队账单，
在超预算之前给出闸门建议，并留下可审计的操作链。

- 场景：5 人数据平台组，ClickHouse 集群月账单 4.2 万元；月底导 query log → Excel 按人统计 → 邮件要预算。
- 本系统：查询日志 → 成本口径 → 团队分摊 → 预算预测 → 闸门建议 → 财务账单。
- 5 个服务：`frontend`（Nginx 静态站 + 原生 ES Modules）/ `backend`（FastAPI）/ `worker`（Celery）/ `db`（PostgreSQL 16）/ `redis`。

## 1. 快速开始

```bash
docker compose up -d --build
# 前端 http://localhost:18206  后端 http://localhost:19206/api/health
docker compose exec -T backend python -m scripts.seed_demo
docker compose exec -T backend python -m pytest tests -q
```

演示账号（密码 `Demo@2026`）：

| 账号 | 角色 | 能看到什么 |
| --- | --- | --- |
| `admin@costcharge.io` | 平台管理员 | 全部团队、改预算/单价、发起核算、导出 CSV、审计 |
| `analyst@costcharge.io` | 数据专员 | 全部团队、发起核算、处置预算告警；不能导出与看审计（403） |
| `viewer@costcharge.io` | 团队只读（供应链数据组） | 只看 team-c 的查询/分摊/告警；换团队 403 |

## 2. 领域实体（5）

| 实体 | 表 | 关键字段 | 说明 |
| --- | --- | --- | --- |
| `Team` | `teams` | code、name、budget_yuan、cost_center、owner、prev_month_yuan | 预算与成本中心台账，上月金额用于环比 |
| `QueryLog` | `query_logs` | query_id、user_email、team_id、sql_digest、scanned_gb、duration_ms、cache_hit、status、queried_at、cost_yuan、is_anomaly | 贴源查询日志，成本与异常的最小事实单元 |
| `CostRun` | `cost_runs` | run_no、period、扫描/计算单价、cache_discount、status、metrics | 一次账期核算，冻结单价与指标快照 |
| `Charge` | `charges` | run_id、team_id、amount_yuan、ratio、query_count、mom_ratio、user_split、top_query | 团队分摊 + 用户下钻 |
| `BudgetAlert` | `budget_alerts` | run_id、team_id、forecast_yuan、ratio、level、gate_action、status | 预测分档与处置 |

链路：`Team` → `QueryLog` → `CostRun` → `Charge` / `BudgetAlert`。每个实体都有表 → model → schema → service → controller/route → 前端 api/页面。

## 3. 算法口径（全部由后端 Python 计算）

实现位置：`backend/src/services/cost_model.py`（纯函数）+ `backend/src/services/cost_run_service.py`（取数与落库）。
算法详情、边界用例见 `backend/tests/test_cost_model.py`、`test_seed_dataset.py`（共 26 个单测）。

**算法 A｜成本计算与分摊**

- 扫描单价 `0.028 元/GB`；计算单价 `0.0004 元/GB·秒`（按扫描量 × 耗时秒）；
- 缓存命中按 `0.3` 折；失败/超时查询不计费；
- `cost = (scanned_gb × 0.028 + scanned_gb × duration_s × 0.0004) × (0.3 if cache_hit)`；
- 团队金额 = 计费查询之和；占比 = 团队金额 / 总额；环比 = 本期 / `prev_month_yuan` - 1。

**算法 B｜异常与预算预测**

- 异常阈值 `= P95 + 3 × MAD`（P95 为线性插值分位数，MAD 为 |x - 中位数| 的中位数）；
- `预测 = 已用 + 近 7 天日均 × 剩余天数`；
- 分档：`≤100%` 正常 / `100–110%` 关注 / `>110%` 超预算；
- 闸门建议：超预算 → `限额`；关注且有异常 → `降采样`；其余 → `物化视图` / `观察`。

**seed 验收数值**（由 `scripts/seed_demo.py` 生成，结果由后端算出）：

- 总成本 `42,180.00 元`，5 团队占比 `21% / 38% / 17% / 14% / 10%`；
- 团队 B `16,028.40 元`（38.0%），环比 +7.6%；
- 异常查询 `7 条`，最大扫描 `620 GB`，阈值 `338.97 GB`（P95 236.69 + 3×MAD 34.10）；
- 团队 B 预测/预算 `112.0% → high`，D `104%`、E `101%`（共 3 条告警）；
- `GET /api/exports/charges.csv` 输出表头 + 5 行团队分摊。

## 4. API

| 方法 | 路径 | 角色 | 说明 |
| --- | --- | --- | --- |
| POST | `/api/auth/login` | 公开 | 登录换 JWT |
| GET | `/api/overview` | 全部 | 本月成本、预算进度、异常、告警、7 天曲线（viewer 限本团队） |
| GET | `/api/teams`、`/api/teams/{id}` | 全部 | 团队预算与最近一次运行快照 |
| PATCH | `/api/teams/{id}` | admin | 调整预算/成本中心/负责人（审计） |
| GET | `/api/query-logs`、`/api/query-logs/{id}` | 全部 | 按团队/异常/状态/缓存筛选，viewer 强制本团队 |
| GET | `/api/cost-runs`、`/api/cost-runs/{id}` | 全部 | 运行列表/详情（详情含分摊与告警） |
| POST | `/api/cost-runs` | admin/analyst | 发起核算；只有 admin 可覆盖单价/账期 |
| GET | `/api/charges` | 全部 | 某次运行的分摊（默认最新） |
| GET | `/api/alerts` | 全部 | 预算告警列表 |
| PATCH | `/api/alerts/{id}/review` | admin/analyst | 处置告警（审计） |
| GET | `/api/exports/charges.csv` | admin | 分摊账单 CSV（5 行） |
| GET | `/api/exports/cost-runs.csv` | admin | 运行记录 CSV |
| GET | `/api/audit` | admin | 审计日志 |
| GET | `/api/health` | 公开 | 5 服务健康与 worker 心跳 |

越权返回真实 `403`、无 token `401`、非法参数 `422`、重复自然键 `409`。

## 5. 共享枚举出现位置

两组枚举（后端唯一定义 + 前端只读副本）：

1. **告警分档 / 处置状态**：`backend/src/constants/enums.py`（`AlertLevel`、`AlertStatus`、`GateAction`）→
   `frontend/site/js/config.js`（`ENUMS.alertLevel`、`ENUMS.alertStatus`、`ENUMS.gateAction`）→
   页面 `overview.js`、`alerts.js`、`export.js`；服务 `alert_service.py`、`overview_service.py`；导出 `export_service.py`。
2. **查询状态 / 运行状态 / 触发方式**：`backend/src/constants/enums.py`（`QueryStatus`、`RunStatus`、`TriggerKind`）→
   `frontend/site/js/config.js`（`ENUMS.queryStatus`、`ENUMS.runStatus`、`ENUMS.trigger`）→
   页面 `querylogs.js`、`overview.js`；服务 `query_log_service.py`、`cost_run_service.py`。

成本单价常量：`backend/src/constants/cost_model.py`；角色权限：`backend/src/constants/roles.py` 与
`frontend/site/js/config.js` 的 `PERMISSIONS`（README 本节即对照表）。

## 6. 视觉与页面

- 方向：机房计费屏，深墨底 `oklch(0.195 0.021 210)` + 荧光绿 `oklch(0.86 0.19 150)` + 分段进度条；
  字体 `Chakra Petch`（display）+ `Noto Sans SC`（body）+ `JetBrains Mono`（数字）。
- 页面：登录（运维终端封面）/ 成本总览（成本大屏 + 预算分段条）/ 查询日志（异常筛选 + 成本口径抽屉）/
  团队分摊（团队行 + 用户下钻 + 最贵查询）/ 预算告警（预测 meter + 处置）/ 账单导出 / 审计日志。
- 原生 HTML/CSS/JS（ES Modules），无框架、无打包器；Google Fonts 离线时回退 `PingFang SC` / 系统等宽。

## 7. 横切能力

- JWT + 三角色 RBAC（`src/middlewares/auth.py`、`rbac.py`，viewer 另有 team scope 校验）；
- 审计：HTTP 写请求中间件 + 领域动作（登录/改预算/核算/处置/导出）；
- 限流：Redis 固定窗口，读 300/min、写 60/min（`src/middlewares/rate_limit.py`）；
- CSV 导出：UTF-8 BOM，Excel 直开；
- worker 心跳：Celery beat 每 10 秒写 Redis，`/api/health` 与总览展示；每日 07:40 自动重算账期。

## 8. 目录

```
backend/src/{config,constants,controllers,middlewares,models,routes,schemas,services,utils}
backend/scripts/{seed_demo.py,demo_config.py,worker_healthcheck.sh}
backend/migrations/001_core_tables.sql
backend/tests/{test_cost_model.py,test_seed_dataset.py,test_security.py}
frontend/site/{index.html,css/{tokens,app}.css,js/{config,api,store,ui,app}.js,js/pages/*.js}
```
