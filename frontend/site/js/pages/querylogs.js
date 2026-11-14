import { api } from '../api.js';
import { ENUMS, can } from '../config.js';
import { drawer, errorBox, errorMessage, esc, field, fmtTime, kv, table } from '../ui.js';

const state = { teamId: '', anomaly: '', status: '', q: '' };

function renderRow(row) {
  return {
    ...row,
    scan: `<span class="mono">${Number(row.scanned_gb).toFixed(2)} GB</span>`,
    seconds: `${(row.duration_ms / 1000).toFixed(1)}s`,
    cost: `¥${Number(row.cost_yuan).toFixed(2)}`,
    cache: row.cache_hit ? '<span class="badge info">命中</span>' : '<span class="mono muted">—</span>',
    anomaly: row.is_anomaly
      ? `<span class="badge high" data-anomaly="1">异常 · ${Number(row.anomaly_score).toFixed(2)}×</span>`
      : '<span class="mono muted">—</span>',
  };
}

function openDetail(row) {
  const { root } = drawer({
    title: row.query_id,
    subtitle: `${row.team_name || row.team_id} · ${row.user_email}`,
    body: `${kv([
      ['查询 ID', `<span class="mono">${esc(row.query_id)}</span>`],
      ['团队', esc(row.team_name || '—')],
      ['执行人', `<span class="mono">${esc(row.user_email)}</span>`],
      ['SQL 指纹', `<span class="mono">${esc(row.sql_digest)}</span>`],
      ['扫描量', `${Number(row.scanned_gb).toFixed(3)} GB`],
      ['耗时', `${(row.duration_ms / 1000).toFixed(1)} 秒`],
      ['缓存命中', row.cache_hit ? '是（0.3 折）' : '否'],
      ['执行结果', esc(ENUMS.queryStatus[row.status] || row.status)],
      ['本次成本', `¥${Number(row.cost_yuan).toFixed(2)}`],
      ['异常', row.is_anomaly ? '是' : '否'],
      ['异常说明', esc(row.anomaly_reason || '—')],
      ['发生时间', fmtTime(row.queried_at)],
    ])}
    <h3 style="margin:14px 0 8px;font-size:0.95rem">成本口径</h3>
    <pre class="code">${esc(
      `扫描成本 = ${Number(row.scanned_gb).toFixed(3)} GB × 0.028 = ${(row.scanned_gb * 0.028).toFixed(4)} 元\n` +
        `计算成本 = ${Number(row.scanned_gb).toFixed(3)} GB × ${(row.duration_ms / 1000).toFixed(1)} s × 0.0004 = ${(
          row.scanned_gb *
          (row.duration_ms / 1000) *
          0.0004
        ).toFixed(4)} 元\n` +
        `缓存折扣 = ${row.cache_hit ? '× 0.3' : '× 1.0'}；失败/超时不计费\n` +
        `应付 = ${Number(row.cost_yuan).toFixed(2)} 元`,
    )}</pre>`,
    footer: '<span class="mono muted">日志只读，成本由后端成本运行写入</span>',
  });
  return root;
}

export const queryLogsPage = {
  async render(view, ctx) {
    let teams;
    try {
      teams = await api.get('/api/teams', { limit: 50 });
    } catch (err) {
      view.innerHTML = errorBox(errorMessage(err));
      return;
    }
    let data;
    try {
      data = await api.get('/api/query-logs', {
        team_id: state.teamId,
        anomaly: state.anomaly,
        status: state.status,
        q: state.q,
        limit: 50,
      });
    } catch (err) {
      view.innerHTML = errorBox(errorMessage(err));
      view.querySelector('#retry-btn')?.addEventListener('click', () => queryLogsPage.render(view, ctx));
      return;
    }
    const anomalyCount = data.items.filter((row) => row.is_anomaly).length;
    view.innerHTML = `
      <section class="panel">
        <div class="panel-head">
          <h2>查询日志</h2>
          <div class="head-meta">
            <span class="meta">${data.total} 条 · 本页异常 ${anomalyCount}</span>
            <span class="badge">P95+MAD 判定</span>
          </div>
        </div>
        <div class="panel-body">
          <div class="filter-bar" id="log-filters">
            ${field({
              label: '团队',
              name: 'team_id',
              value: state.teamId,
              options: [{ value: '', label: '全部团队' }, ...teams.items.map((team) => ({ value: team.id, label: team.name }))],
            })}
            ${field({
              label: '异常',
              name: 'anomaly',
              value: state.anomaly,
              options: [
                { value: '', label: '全部' },
                { value: 'true', label: '只看异常' },
                { value: 'false', label: '只看正常' },
              ],
            })}
            ${field({
              label: '状态',
              name: 'status',
              value: state.status,
              options: [
                { value: '', label: '全部' },
                { value: 'success', label: '成功' },
                { value: 'failed', label: '失败' },
                { value: 'timeout', label: '超时' },
              ],
            })}
            ${field({ label: '搜索', name: 'q', value: state.q, placeholder: '查询 ID / 用户 / 指纹' })}
            <div class="spacer"></div>
          </div>
        </div>
        ${table({
          rows: data.items.map(renderRow),
          empty: { title: '这个筛选下没有查询', hint: '换成「全部团队 / 全部异常」再看看。' },
          columns: [
            { key: 'query_id', label: '查询 ID', className: 'mono', render: (row) => `<b>${esc(row.query_id)}</b>` },
            { key: 'team_name', label: '团队' },
            { key: 'user_email', label: '执行人', className: 'mono' },
            { key: 'scan', label: '扫描量', className: 'num', render: (row) => `<span class="mono">${Number(row.scanned_gb).toFixed(2)} GB</span>` },
            { key: 'seconds', label: '耗时', className: 'num', render: (row) => `${(row.duration_ms / 1000).toFixed(1)}s` },
            { key: 'cache', label: '缓存', render: (row) => (row.cache_hit ? '<span class="badge info">命中</span>' : '<span class="mono muted">—</span>') },
            { key: 'cost', label: '成本', className: 'num', render: (row) => `¥${Number(row.cost_yuan).toFixed(2)}` },
            { key: 'anomaly', label: '异常', render: (row) => (row.is_anomaly ? `<span class="badge high" data-anomaly="1">异常 · ${Number(row.anomaly_score).toFixed(2)}×</span>` : '<span class="mono muted">—</span>') },
            { key: 'queried_at', label: '时间', render: (row) => fmtTime(row.queried_at) },
          ],
        })}
      </section>`;

    const filters = view.querySelector('#log-filters');
    filters?.addEventListener('change', () => {
      state.teamId = filters.querySelector('[name=team_id]').value;
      state.anomaly = filters.querySelector('[name=anomaly]').value;
      state.status = filters.querySelector('[name=status]').value;
      state.q = filters.querySelector('[name=q]').value.trim();
      queryLogsPage.render(view, ctx);
    });
    filters?.querySelector('[name=q]')?.addEventListener('keydown', (event) => {
      if (event.key === 'Enter') {
        state.q = event.target.value.trim();
        queryLogsPage.render(view, ctx);
      }
    });
    view.querySelectorAll('table.data tbody tr').forEach((node) => {
      node.addEventListener('click', () => {
        const row = data.items.find((item) => String(item.id) === node.dataset.id);
        if (row) openDetail(row);
      });
    });
  },
};

export default queryLogsPage;
