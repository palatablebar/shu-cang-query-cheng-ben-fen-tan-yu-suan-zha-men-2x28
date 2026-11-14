/**
 * 项目品牌、导航、角色权限与枚举文案（前端唯一定义处）。
 * 后端对应：backend/src/constants/{roles,enums,cost_model}.py；README 列出全部出现位置。
 */
export const BRAND = {
  short: 'costcharge',
  title: '数仓查询成本分摊与预算闸门',
  org: '云格 SaaS · 数据平台组',
  edition: 'METERING ROOM · 2026',
  subtitle: 'query_log → 成本口径 → 团队分摊 → 预算预测 → 闸门建议，一条链路留痕',
  loginLead: 'ClickHouse 集群每月 4.2 万元，谁在烧、烧在哪、下个月会不会超，必须先算清楚再谈优化。',
  loginPoints: [
    ['A', '扫描 0.028 元/GB、计算 0.0004 元/GB·s，缓存命中 0.3 折，失败查询不计费。'],
    ['B', '按团队汇总、按用户下钻；占比与上月环比同屏，客服和财务不用再对 Excel。'],
    ['C', 'P95 + 3×MAD 抓异常大查询，预测 112% 自动给出限额/降采样/物化视图建议。'],
  ],
  gl: 'GL-2026',
};

export const NAV = [
  { to: '#/overview', no: '01', label: '成本总览', permission: 'overview:read' },
  { to: '#/query-logs', no: '02', label: '查询日志', permission: 'querylog:read' },
  { to: '#/charges', no: '03', label: '团队分摊', permission: 'charge:read' },
  { to: '#/alerts', no: '04', label: '预算告警', permission: 'alert:read' },
  { to: '#/export', no: '05', label: '账单导出', permission: 'export:read' },
  { to: '#/audit', no: '06', label: '审计日志', permission: 'audit:read' },
];

export const ROLE_LABELS = {
  admin: '平台管理员',
  analyst: '数据专员',
  viewer: '团队只读',
};

export const PERMISSIONS = {
  admin: [
    'overview:read',
    'team:read',
    'team:write',
    'querylog:read',
    'run:read',
    'run:create',
    'charge:read',
    'alert:read',
    'alert:review',
    'export:read',
    'audit:read',
  ],
  analyst: ['overview:read', 'team:read', 'querylog:read', 'run:read', 'run:create', 'charge:read', 'alert:read', 'alert:review'],
  viewer: ['overview:read', 'team:read', 'querylog:read', 'run:read', 'charge:read', 'alert:read'],
};

export const ENUMS = {
  queryStatus: {
    success: '成功',
    failed: '失败',
    timeout: '超时',
  },
  runStatus: {
    queued: '排队中',
    running: '执行中',
    success: '成功',
    partial: '部分成功',
    failed: '失败',
  },
  trigger: {
    manual: '手动',
    schedule: '定时',
    seed: '初始化',
  },
  alertLevel: {
    normal: '正常',
    watch: '关注',
    high: '超预算',
  },
  alertStatus: {
    pending: '待处置',
    confirmed: '已确认',
    dismissed: '已驳回',
  },
  gateAction: {
    cap_quota: '限额',
    sample_down: '降采样',
    materialized_view: '物化视图',
    watch: '观察',
  },
};

export function can(role, permission) {
  return (PERMISSIONS[role] || []).includes(permission);
}

export function levelTone(level) {
  return { high: 'high', watch: 'warn', normal: 'ok' }[level] || 'info';
}

export function reviewTone(status) {
  return { pending: 'pending warn', confirmed: 'ok', dismissed: 'danger' }[status] || 'info';
}

export function pct(value, digits = 1) {
  if (value === null || value === undefined) return '—';
  return `${(Number(value) * 100).toFixed(digits)}%`;
}

export function yuan(value) {
  if (value === null || value === undefined) return '—';
  return `¥${Number(value).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}
