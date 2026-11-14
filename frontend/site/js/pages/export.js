import { api } from '../api.js';
import { pct } from '../config.js';
import { emptyState, errorBox, errorMessage, esc, fmtTime, table, toast } from '../ui.js';

const state = { runId: '' };

async function download(path, filename) {
  const token = localStorage.getItem('costcharge.token');
  const response = await fetch(path, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    throw Object.assign(new Error(payload?.message || '导出失败'), { code: payload?.code || 'EXPORT_FAILED' });
  }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

export const exportPage = {
  async render(view, ctx) {
    let runs;
    let charges;
    try {
      runs = await api.get('/api/cost-runs', { limit: 20 });
      charges = await api.get('/api/charges', { limit: 50, run_id: state.runId || undefined });
    } catch (err) {
      view.innerHTML = errorBox(errorMessage(err));
      view.querySelector('#retry-btn')?.addEventListener('click', () => exportPage.render(view, ctx));
      return;
    }
    const current = runs.items.find((item) => String(item.id) === String(charges.run_id)) || runs.items[0];
    view.innerHTML = `
      <section class="panel">
        <div class="panel-head">
          <h2>账单导出</h2>
          <span class="meta">${current ? esc(current.run_no) : '—'} · ${charges.items.length} 行</span>
        </div>
        <div class="panel-body">
          <div class="export-grid">
            <label class="field">
              <span>成本运行</span>
              <select id="run-select">
                ${runs.items
                  .map((run) => `<option value="${run.id}" ${String(run.id) === String(charges.run_id) ? 'selected' : ''}>${esc(run.run_no)} · ¥${Number(run.total_cost_yuan).toFixed(2)}</option>`)
                  .join('')}
              </select>
            </label>
            <div class="export-actions">
              <button class="btn accent" id="export-charges" data-testid="export-charges">下载分摊 CSV（5 行）</button>
              <button class="btn ghost" id="export-runs">下载运行记录 CSV</button>
            </div>
          </div>
          <div class="export-note mono">
            导出受角色限制：仅平台管理员可下载；CSV 为 UTF-8 BOM，Excel 直接打开不乱码。
          </div>
        </div>
        ${
          charges.items.length
            ? table({
                rows: charges.items,
                columns: [
                  { key: 'team_name', label: '团队', render: (row) => `<b>${esc(row.team_name)}</b><div class="mono muted">${esc(row.cost_center)}</div>` },
                  { key: 'owner', label: '负责人' },
                  { key: 'amount_yuan', label: '金额(元)', className: 'num', render: (row) => Number(row.amount_yuan).toFixed(2) },
                  { key: 'ratio', label: '占比', className: 'num', render: (row) => pct(row.ratio) },
                  { key: 'query_count', label: '查询数', className: 'num' },
                  { key: 'cached_saved_yuan', label: '缓存节省(元)', className: 'num', render: (row) => Number(row.cached_saved_yuan).toFixed(2) },
                  { key: 'mom_ratio', label: '环比', className: 'num', render: (row) => (row.mom_ratio === null ? '—' : `${(row.mom_ratio * 100).toFixed(1)}%`) },
                ],
              })
            : emptyState({ title: '还没有可导出的账单', hint: '先完成一次成本核算。' })
        }
      </section>`;

    view.querySelector('#run-select')?.addEventListener('change', (event) => {
      state.runId = event.target.value;
      exportPage.render(view, ctx);
    });
    view.querySelector('#export-charges')?.addEventListener('click', async () => {
      try {
        await download(`/api/exports/charges.csv${charges.run_id ? `?run_id=${charges.run_id}` : ''}`, 'charges.csv');
        toast('分摊账单已开始下载');
      } catch (err) {
        toast(errorMessage(err), 'err');
      }
    });
    view.querySelector('#export-runs')?.addEventListener('click', async () => {
      try {
        await download('/api/exports/cost-runs.csv', 'cost-runs.csv');
        toast('运行记录已开始下载');
      } catch (err) {
        toast(errorMessage(err), 'err');
      }
    });
  },
};

export default exportPage;
