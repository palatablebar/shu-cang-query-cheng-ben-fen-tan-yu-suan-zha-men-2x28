import { api } from '../api.js';
import { pct } from '../config.js';
import { drawer, errorBox, errorMessage, esc, fmtTime, kv, meter, table } from '../ui.js';

function openUserSplit(row) {
  const users = row.user_split || [];
  const max = Math.max(1, ...users.map((item) => item.amount_yuan));
  const { root } = drawer({
    title: `${row.team_name} · 按用户分摊`,
    subtitle: `${row.team_code} / ${row.cost_center} · 负责人 ${row.owner}`,
    body: `${kv([
      ['团队金额', `¥${Number(row.amount_yuan).toFixed(2)}`],
      ['占总额', pct(row.ratio)],
      ['计费查询', `${row.query_count} 条`],
      ['缓存节省', `¥${Number(row.cached_saved_yuan).toFixed(2)}`],
      ['上月环比', row.mom_ratio === null ? '—' : `${(row.mom_ratio * 100).toFixed(1)}%`],
      ['团队预算', `¥${Number(row.budget_yuan).toFixed(2)}`],
      ['生成时间', fmtTime(row.created_at)],
    ])}
    <h3 style="margin:16px 0 8px;font-size:0.95rem">团队内用户分摊（前 5）</h3>
    <div class="user-split">
      ${users
        .map(
          (item) => `<div class="user-line">
            <span class="mono">${esc(item.user_email)}</span>
            <div class="bar-track"><div class="bar-fill" style="width:${Math.round((item.amount_yuan / max) * 100)}%"></div></div>
            <b class="mono">¥${Number(item.amount_yuan).toFixed(2)}</b>
            <span class="mono tiny">${item.query_count} 次</span>
          </div>`,
        )
        .join('')}
    </div>
    <h3 style="margin:16px 0 8px;font-size:0.95rem">最贵单条查询</h3>
    <pre class="code">${esc(JSON.stringify(row.top_query || {}, null, 2))}</pre>`,
    footer: '<span class="mono muted">金额由成本运行按扫描量/耗时/缓存折扣计算</span>',
  });
  return root;
}

export const chargesPage = {
  async render(view, ctx) {
    let data;
    let run;
    try {
      data = await api.get('/api/charges', { limit: 50 });
      run = data.run_id ? await api.get(`/api/cost-runs/${data.run_id}`) : null;
    } catch (err) {
      view.innerHTML = errorBox(errorMessage(err));
      view.querySelector('#retry-btn')?.addEventListener('click', () => chargesPage.render(view, ctx));
      return;
    }
    const totalBudget = data.items.reduce((sum, item) => sum + item.budget_yuan, 0);
    const totalAmount = data.total_amount_yuan || 0;
    view.innerHTML = `
      <section class="panel">
        <div class="panel-head">
          <h2>团队分摊</h2>
          <div class="head-meta">
            <span class="meta">${run ? esc(run.run_no) : '—'} · ${data.items.length} 个团队</span>
            <span class="badge">合计 ¥${Number(totalAmount).toFixed(2)}</span>
          </div>
        </div>
        <div class="panel-body">
          <div class="alloc-summary">
            <div class="summary-cell"><span class="eyebrow">TOTAL</span><b class="mono">¥${Number(totalAmount).toFixed(2)}</b></div>
            <div class="summary-cell"><span class="eyebrow">BUDGET</span><b class="mono">¥${Number(totalBudget).toFixed(2)}</b></div>
            <div class="summary-cell"><span class="eyebrow">USED</span><b class="mono">${totalBudget ? pct(totalAmount / totalBudget) : '—'}</b></div>
            <div class="summary-cell"><span class="eyebrow">ALERTS</span><b class="mono">${run ? run.alerts.length : 0}</b></div>
          </div>
        </div>
        ${table({
          rows: data.items,
          empty: { title: '还没有分摊结果', hint: '先发起一次成本核算。' },
          columns: [
            { key: 'team_name', label: '团队', render: (row) => `<b>${esc(row.team_name)}</b><div class="mono muted">${esc(row.team_code)} · ${esc(row.cost_center)}</div>` },
            { key: 'owner', label: '负责人' },
            { key: 'amount_yuan', label: '金额', className: 'num', render: (row) => `¥${Number(row.amount_yuan).toFixed(2)}` },
            { key: 'ratio', label: '占比', render: (row) => `${pct(row.ratio)}<div class="mini-meter">${meter(row.ratio, { segments: 18, tone: 'on' })}</div>` },
            { key: 'query_count', label: '查询数', className: 'num' },
            { key: 'cached_saved_yuan', label: '缓存节省', className: 'num', render: (row) => `¥${Number(row.cached_saved_yuan).toFixed(2)}` },
            { key: 'mom_ratio', label: '环比', className: 'num', render: (row) => (row.mom_ratio === null ? '—' : `${row.mom_ratio > 0 ? '+' : ''}${(row.mom_ratio * 100).toFixed(1)}%`) },
            { key: 'used_ratio', label: '预算占用', className: 'num', render: (row) => (row.budget_yuan ? pct(row.amount_yuan / row.budget_yuan) : '—') },
          ],
        })}
      </section>`;

    view.querySelectorAll('table.data tbody tr').forEach((node) => {
      node.addEventListener('click', () => {
        const row = data.items.find((item) => String(item.id) === node.dataset.id);
        if (row) openUserSplit(row);
      });
    });
  },
};

export default chargesPage;
