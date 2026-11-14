import { api } from '../api.js';
import { ENUMS, can, levelTone, pct, reviewTone } from '../config.js';
import { drawer, errorBox, errorMessage, esc, field, fmtTime, kv, meter, table, toast } from '../ui.js';

function openReview(view, ctx, alert) {
  const canReview = can(ctx.user.role, 'alert:review');
  const { root, close } = drawer({
    title: `${alert.team_name} · 预算告警`,
    subtitle: `${alert.team_code} · ${alert.cost_center} · ${alert.owner}`,
    body: `${kv([
      ['分档', `<span class="badge ${levelTone(alert.level)}">${esc(ENUMS.alertLevel[alert.level] || alert.level)}</span>`],
      ['预测金额', `¥${Number(alert.forecast_yuan).toFixed(2)}`],
      ['团队预算', `¥${Number(alert.budget_yuan).toFixed(2)}`],
      ['预测/预算', pct(alert.ratio)],
      ['闸门建议', `<span class="badge info">${esc(ENUMS.gateAction[alert.gate_action] || alert.gate_action)}</span>`],
      ['处置状态', `<span class="badge ${reviewTone(alert.status)}">${esc(ENUMS.alertStatus[alert.status] || alert.status)}</span>`],
      ['复核人', esc(alert.reviewer || '—')],
      ['复核备注', esc(alert.note || '—')],
      ['复核时间', fmtTime(alert.reviewed_at)],
      ['生成时间', fmtTime(alert.created_at)],
    ])}
    <div style="margin-top:12px">${meter(alert.ratio, { segments: 30, tone: alert.level === 'high' ? 'danger' : 'warn' })}</div>
    <p class="muted mono" style="margin:8px 0 0">预测 = 已用 + 近 7 天日均 × 剩余天数；&gt;110% 建议限额</p>`,
    footer: canReview
      ? `<form id="review-form" style="display:grid;gap:10px">
          ${field({ label: '处置结论', name: 'status', value: alert.status, options: Object.entries(ENUMS.alertStatus).map(([value, label]) => ({ value, label })) })}
          ${field({ label: '备注', name: 'note', value: alert.note || '', placeholder: '例如：已通知团队降采样' })}
          <button class="btn accent" type="submit">提交处置</button>
        </form>`
      : '<span class="mono muted">只读角色可以查看，但不能处置告警</span>',
  });
  root.querySelector('#review-form')?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const form = event.target;
    try {
      await api.patch(`/api/alerts/${alert.id}/review`, {
        status: form.status.value,
        note: form.note.value.trim() || null,
      });
      toast('告警处置已保存');
      close();
      await alertsPage.render(view, ctx);
    } catch (err) {
      toast(errorMessage(err), 'err');
    }
  });
}

export const alertsPage = {
  async render(view, ctx) {
    let data;
    try {
      data = await api.get('/api/alerts', { limit: 50 });
    } catch (err) {
      view.innerHTML = errorBox(errorMessage(err));
      view.querySelector('#retry-btn')?.addEventListener('click', () => alertsPage.render(view, ctx));
      return;
    }
    const pending = data.items.filter((item) => item.status === 'pending').length;
    view.innerHTML = `
      <section class="panel">
        <div class="panel-head">
          <h2>预算告警</h2>
          <div class="head-meta">
            <span class="meta">${data.total} 条 · 待处置 ${pending}</span>
            <span class="badge ${pending ? 'warn' : 'ok'}">${data.items.some((item) => item.level === 'high') ? '存在超预算' : '无超预算'}</span>
          </div>
        </div>
        ${table({
          rows: data.items,
          empty: { title: '本期没有预算告警', hint: '预测全部落在预算内。' },
          columns: [
            { key: 'team_name', label: '团队', render: (row) => `<b>${esc(row.team_name)}</b><div class="mono muted">${esc(row.team_code)}</div>` },
            { key: 'level', label: '分档', render: (row) => `<span class="badge ${levelTone(row.level)}">${esc(ENUMS.alertLevel[row.level] || row.level)}</span>` },
            { key: 'forecast_yuan', label: '预测', className: 'num', render: (row) => `¥${Number(row.forecast_yuan).toFixed(2)}` },
            { key: 'ratio', label: '预测/预算', render: (row) => `<span class="mono">${pct(row.ratio)}</span><div class="mini-meter">${meter(row.ratio, { segments: 18, tone: row.level === 'high' ? 'danger' : 'warn' })}</div>` },
            { key: 'gate_action', label: '闸门建议', render: (row) => esc(ENUMS.gateAction[row.gate_action] || row.gate_action) },
            { key: 'status', label: '处置', render: (row) => `<span class="badge ${reviewTone(row.status)}">${esc(ENUMS.alertStatus[row.status] || row.status)}</span>` },
            { key: 'reviewer', label: '复核人', className: 'mono', render: (row) => esc(row.reviewer || '—') },
            { key: 'created_at', label: '生成时间', render: (row) => fmtTime(row.created_at) },
          ],
        })}
      </section>`;

    view.querySelectorAll('table.data tbody tr').forEach((node) => {
      node.addEventListener('click', () => {
        const alert = data.items.find((item) => String(item.id) === node.dataset.id);
        if (alert) openReview(view, ctx, alert);
      });
    });
  },
};

export default alertsPage;
