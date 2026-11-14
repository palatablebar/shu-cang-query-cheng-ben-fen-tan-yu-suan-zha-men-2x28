import { api } from '../api.js';
import { ENUMS, billStatusTone, can, diffTone, findingTone } from '../config.js';
import { badge, drawer, emptyState, errorBox, errorMessage, esc, field, fmtTime, statStrip, table, toast } from '../ui.js';

const TEMPLATE_HEADER = '查询ID,团队编码,用户邮箱,扫描量GB,单价(元/GB),金额(元)';
const TEMPLATE_SAMPLE = [
  'qh-0001,team-a,shen.yi@costcharge.io,120,0.028,3.36',
  'qh-0002,team-b,luo.qq@costcharge.io,80,0.028,2.24',
].join('\n');

const state = { selectedId: null, diffFilter: '', statusFilter: '' };

function importDrawer(view, ctx) {
  const { root, close } = drawer({
    title: '导入供应商账单',
    subtitle: '供应商按整月扫描量一口价结算 · CSV UTF-8（可含 BOM）',
    body: `
      <form id="bill-form" style="display:grid;gap:12px">
        ${field({ label: '账期', name: 'period', value: new Date().toISOString().slice(0, 7), placeholder: 'YYYY-MM' })}
        ${field({ label: '文件名（留痕用）', name: 'filename', value: 'supplier-bill.csv', placeholder: 'supplier-bill-2026-11.csv' })}
        <div class="field">
          <label for="csv_text">账单内容（粘贴 CSV，首行表头）</label>
          <textarea id="csv_text" name="csv_text" rows="10" spellcheck="false"
            placeholder="${esc(TEMPLATE_HEADER)}\n${esc(TEMPLATE_SAMPLE)}"
            style="width:100%;min-height:220px;font-family:var(--font-mono);font-size:var(--fs-sm)"></textarea>
        </div>
        <p class="mono muted" style="margin:0;font-size:var(--fs-xs)">
          支持列：查询ID/query_id、团队编码、用户邮箱、扫描量GB、单价(元/GB)、金额(元)、查询时间；
          金额留空按 扫描量 × 单价 推算。同一文件重复导入会被拒绝。
        </p>
        <button class="btn accent" type="submit">导入并保存</button>
      </form>`,
    footer: '<span class="mono muted">导入只落账，不触发任何分摊或告警变化</span>',
  });
  root.querySelector('#bill-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    const form = event.target;
    const csvText = form.csv_text.value.trim();
    if (!csvText) {
      toast('请粘贴账单 CSV 内容', 'err');
      return;
    }
    try {
      const bill = await api.post('/api/supplier-bills', {
        period: form.period.value.trim(),
        filename: form.filename.value.trim() || 'supplier-bill.csv',
        csv_text: csvText,
      });
      toast(`账单 ${bill.bill_no} 导入成功：${bill.line_count} 行`);
      close();
      state.selectedId = bill.id;
      await reconcilePage.render(view, ctx);
    } catch (err) {
      toast(errorMessage(err), 'err');
    }
  });
  return root;
}

function diffSummaryCells(run) {
  if (!run) {
    return [
      { label: '供应商应付', value: '—', hint: '未核对' },
      { label: '平台已计', value: '—', hint: '' },
      { label: '差异合计', value: '—', hint: '' },
    ];
  }
  return [
    { label: '供应商应付', value: `¥${Number(run.bill_total_yuan).toFixed(2)}`, hint: run.recon_no || '' },
    { label: '平台已计', value: `¥${Number(run.platform_total_yuan).toFixed(2)}`, hint: `账期 ${run.period}` },
    {
      label: '差异合计',
      value: `${Number(run.diff_total_yuan) >= 0 ? '+' : ''}¥${Number(run.diff_total_yuan).toFixed(2)}`,
      hint: '供应商 - 平台',
    },
  ];
}

function findingDrawer(view, ctx, finding, reload) {
  const canResolve = can(ctx.user.role, 'bill:resolve');
  const { root, close } = drawer({
    title: `${ENUMS.diffType[finding.diff_type] || finding.diff_type} · ${finding.query_id}`,
    subtitle: `${finding.team_code || '未知团队'} · 重复序号 ${finding.duplicate_seq} · 账期 ${finding.period}`,
    body: `
      <div style="margin-bottom:12px">
        ${badge(diffTone(finding.diff_type), ENUMS.diffType[finding.diff_type] || finding.diff_type)}
        ${badge(findingTone(finding.status), ENUMS.findingStatus[finding.status] || finding.status)}
      </div>
      <dl class="kv">
        <dt>供应商金额</dt><dd>¥${Number(finding.bill_amount_yuan).toFixed(4)}</dd>
        <dt>平台金额</dt><dd>¥${Number(finding.platform_amount_yuan).toFixed(4)}</dd>
        <dt>差异金额</dt><dd><b class="mono">${Number(finding.diff_amount_yuan) >= 0 ? '+' : ''}¥${Number(finding.diff_amount_yuan).toFixed(4)}</b></dd>
        <dt>供应商扫描</dt><dd class="mono">${Number(finding.bill_scanned_gb).toFixed(3)} GB</dd>
        <dt>平台扫描</dt><dd class="mono">${Number(finding.platform_scanned_gb).toFixed(3)} GB</dd>
        <dt>供应商单价</dt><dd class="mono">¥${Number(finding.bill_unit_price).toFixed(6)}/GB</dd>
        <dt>平台等效单价</dt><dd class="mono">¥${Number(finding.platform_unit_price).toFixed(6)}/GB</dd>
        <dt>平台状态</dt><dd>${esc(finding.detail?.platform_status || '—')}${finding.detail?.platform_cache_hit ? ' · 缓存命中' : ''}</dd>
        <dt>判定依据</dt><dd class="mono">${esc(finding.detail?.reason || '—')}</dd>
        <dt>处置人</dt><dd>${esc(finding.resolver || '—')}</dd>
        <dt>备注</dt><dd>${esc(finding.note || '—')}</dd>
      </dl>`,
    footer: canResolve
      ? `<form id="finding-form" style="display:grid;gap:10px">
          ${field({
            label: '处置结论',
            name: 'status',
            value: finding.status === 'dismissed' ? 'dismissed' : 'applied',
            options: [
              { value: 'applied', label: '入账（确认后随账期修正）' },
              { value: 'dismissed', label: '驳回（供应商冲红等）' },
            ],
          })}
          ${field({ label: '备注', name: 'note', value: finding.note || '', placeholder: '例如：供应商重复计费，已联系冲红' })}
          <button class="btn accent" type="submit">提交处置</button>
        </form>`
      : '<span class="mono muted">只读角色只能查看差异</span>',
  });
  root.querySelector('#finding-form')?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const form = event.target;
    try {
      await api.patch(`/api/supplier-bills/findings/${finding.id}/review`, {
        status: form.status.value,
        note: form.note.value.trim() || null,
      });
      toast('差异处置已保存');
      close();
      await reload();
    } catch (err) {
      toast(errorMessage(err), 'err');
    }
  });
  return root;
}

async function renderDetail(view, ctx, billId) {
  const [bill, findingsPage] = await Promise.all([
    api.get(`/api/supplier-bills/${billId}`),
    api.get(`/api/supplier-bills/${billId}/findings`, {
      diff_type: state.diffFilter || undefined,
      status: state.statusFilter || undefined,
      limit: 200,
    }),
  ]);
  const run = bill.latest_run;
  const counts = run?.diff_counts || {};
  const canReconcile = can(ctx.user.role, 'bill:reconcile');
  const canConfirm = can(ctx.user.role, 'bill:confirm');

  const countChips = ['missing', 'duplicate', 'price_mismatch', 'platform_extra']
    .map((type) => `${badge(diffTone(type), ENUMS.diffType[type])} <b class="mono">${counts[type] || 0}</b>`)
    .join('&nbsp;&nbsp;');
  const isConfirmed = bill.status === 'confirmed';
  const confirmDisabled = isConfirmed || !run || (bill.open_findings > 0 && bill.status === 'matched');
  const confirmHint = isConfirmed
    ? '账单已发布，修正已生效'
    : !run
      ? '先完成逐笔核对再确认'
      : confirmDisabled
        ? '差异清零前预算告警沿用旧值'
        : '确认后只重算差异涉及账期';

  const adjustmentRows = bill.adjustments || [];
  const detailNode = document.createElement('div');
  detailNode.innerHTML = `
    <section class="panel" style="margin-top:16px">
      <div class="panel-head">
        <h2>${esc(bill.bill_no)} <span class="meta">${esc(bill.period)} · ${esc(bill.source_filename)}</span></h2>
        ${badge(billStatusTone(bill.status), bill.status_label)}
      </div>
      <div class="panel-body">
        ${statStrip(diffSummaryCells(run))}
        <div class="hero-flags" style="margin:14px 0">
          <span class="badge">漏计/重复/单价不符/多计：</span>${countChips || '<span class="muted">尚未核对</span>'}
          <span class="badge ${bill.open_findings ? 'warn' : 'ok'}">待处置差异 ${bill.open_findings}</span>
          ${bill.published_run_id ? `<span class="badge ok">已发布到运行 #${bill.published_run_id}</span>` : ''}
        </div>
        ${bill.error_message ? `<div class="error-box" style="margin-bottom:12px"><span>核对失败：${esc(bill.error_message)}</span></div>` : ''}
        <div class="export-actions" style="flex-wrap:wrap;gap:10px">
          ${
            canReconcile
              ? `<button class="btn accent" id="btn-reconcile">${run ? '重新核对（幂等复用）' : '开始逐笔核对'}</button>`
              : ''
          }
          ${
            canConfirm
              ? `<button class="btn ${confirmDisabled ? 'ghost' : 'accent'}" id="btn-confirm" ${confirmDisabled ? 'disabled' : ''}>
                  ${isConfirmed ? '已确认发布' : '确认发布并修正账期'}
                </button>
                <span class="mono tiny muted">${confirmHint}</span>`
              : ''
          }
        </div>
        <p class="mono muted" style="font-size:var(--fs-xs);margin:10px 0 0">
          发布状态：${esc(bill.status_label)} · 导入于 ${fmtTime(bill.created_at)}
          ${bill.confirmed_at ? `· 确认于 ${fmtTime(bill.confirmed_at)} by ${esc(bill.confirmed_by || '')}` : ''}
        </p>
      </div>
    </section>

    <section class="panel" style="margin-top:16px">
      <div class="panel-head">
        <h2>差异明细（${findingsPage.total}）</h2>
        <div class="filter-bar" style="margin:0">
          <label class="field" style="min-width:150px">
            <span>差异类型</span>
            <select id="filter-diff">
              <option value="">全部</option>
              ${['missing', 'duplicate', 'price_mismatch', 'platform_extra']
                .map((t) => `<option value="${t}" ${state.diffFilter === t ? 'selected' : ''}>${ENUMS.diffType[t]}</option>`)
                .join('')}
            </select>
          </label>
          <label class="field" style="min-width:130px">
            <span>处置状态</span>
            <select id="filter-status">
              <option value="">全部</option>
              <option value="open" ${state.statusFilter === 'open' ? 'selected' : ''}>待处置</option>
              <option value="applied" ${state.statusFilter === 'applied' ? 'selected' : ''}>已入账</option>
              <option value="dismissed" ${state.statusFilter === 'dismissed' ? 'selected' : ''}>已驳回</option>
            </select>
          </label>
        </div>
      </div>
      ${table({
        rows: findingsPage.items,
        empty: { title: '没有差异记录', hint: run ? '本账单与平台逐笔一致，或筛选条件无匹配。' : '先发起逐笔核对。' },
        columns: [
          { key: 'query_id', label: '查询 ID', render: (row) => `<b class="mono">${esc(row.query_id)}</b><div class="mono muted tiny">${esc(row.team_code || '—')} · #${row.duplicate_seq}</div>` },
          { key: 'diff_type', label: '类型', render: (row) => badge(diffTone(row.diff_type), row.diff_type_label) },
          { key: 'bill_amount_yuan', label: '供应商金额', className: 'num', render: (row) => `¥${Number(row.bill_amount_yuan).toFixed(2)}` },
          { key: 'platform_amount_yuan', label: '平台金额', className: 'num', render: (row) => `¥${Number(row.platform_amount_yuan).toFixed(2)}` },
          { key: 'diff_amount_yuan', label: '差异', className: 'num', render: (row) => `<b class="mono">${Number(row.diff_amount_yuan) >= 0 ? '+' : ''}¥${Number(row.diff_amount_yuan).toFixed(2)}</b>` },
          { key: 'bill_unit_price', label: '供应商单价', className: 'num tiny', render: (row) => Number(row.bill_unit_price) ? `¥${Number(row.bill_unit_price).toFixed(4)}` : '—' },
          { key: 'platform_unit_price', label: '平台单价', className: 'num tiny', render: (row) => Number(row.platform_unit_price) ? `¥${Number(row.platform_unit_price).toFixed(4)}` : '—' },
          { key: 'status', label: '处置', render: (row) => badge(findingTone(row.status), row.status_label) },
        ],
      })}
    </section>

    <section class="panel" style="margin-top:16px">
      <div class="panel-head"><h2>账期修正台账</h2><span class="meta">确认发布后生成</span></div>
      ${
        adjustmentRows.length
          ? table({
              rows: adjustmentRows,
              columns: [
                { key: 'period', label: '账期', render: (row) => `<b class="mono">${esc(row.period)}</b>` },
                { key: 'team_code', label: '团队' },
                { key: 'diff_type', label: '差异类型', render: (row) => badge(diffTone(row.diff_type), ENUMS.diffType[row.diff_type] || row.diff_type) },
                { key: 'finding_count', label: '笔数', className: 'num' },
                { key: 'amount_yuan', label: '分摊修正', className: 'num', render: (row) => `${Number(row.amount_yuan) >= 0 ? '+' : ''}¥${Number(row.amount_yuan).toFixed(2)}` },
                { key: 'payable_delta_yuan', label: '应付修正', className: 'num', render: (row) => `${Number(row.payable_delta_yuan) >= 0 ? '+' : ''}¥${Number(row.payable_delta_yuan).toFixed(2)}` },
                { key: 'run_id', label: '重算运行', className: 'mono tiny', render: (row) => (row.run_id ? `#${row.run_id}` : '—') },
              ],
            })
          : `<div class="panel-body">${emptyState({ title: '尚未发布', hint: '差异全部处置并确认后，只重算差异涉及的账期。' })}</div>`
      }
    </section>`;

  const host = view.querySelector('#reconcile-detail');
  host.innerHTML = '';
  host.appendChild(detailNode);

  detailNode.querySelector('#filter-diff')?.addEventListener('change', (e) => {
    state.diffFilter = e.target.value;
    renderDetail(view, ctx, billId);
  });
  detailNode.querySelector('#filter-status')?.addEventListener('change', (e) => {
    state.statusFilter = e.target.value;
    renderDetail(view, ctx, billId);
  });
  detailNode.querySelector('#btn-reconcile')?.addEventListener('click', async () => {
    try {
      const result = await api.post(`/api/supplier-bills/${billId}/reconcile`);
      toast(result.reused ? '该账单已核对，复用既有核对结果' : `核对完成：差异 ¥${Number(result.run.diff_total_yuan).toFixed(2)}`);
      await renderDetail(view, ctx, billId);
    } catch (err) {
      toast(errorMessage(err), 'err');
      await renderDetail(view, ctx, billId);
    }
  });
  detailNode.querySelector('#btn-confirm')?.addEventListener('click', async () => {
    try {
      await api.post(`/api/supplier-bills/${billId}/confirm`);
      toast('账单已确认发布，差异账期分摊与告警已更新');
      await reconcilePage.render(view, ctx);
    } catch (err) {
      toast(errorMessage(err), 'err');
    }
  });
  detailNode.querySelectorAll('table.data tbody tr').forEach((node) => {
    node.addEventListener('click', () => {
      const finding = findingsPage.items.find((item) => String(item.id) === node.dataset.id);
      if (finding) findingDrawer(view, ctx, finding, () => renderDetail(view, ctx, billId));
    });
  });
}

export const reconcilePage = {
  async render(view, ctx) {
    let data;
    try {
      data = await api.get('/api/supplier-bills', { limit: 50 });
    } catch (err) {
      view.innerHTML = errorBox(errorMessage(err));
      view.querySelector('#retry-btn')?.addEventListener('click', () => reconcilePage.render(view, ctx));
      return;
    }
    const canImport = can(ctx.user.role, 'bill:import');
    view.innerHTML = `
      <section class="panel">
        <div class="panel-head">
          <h2>供应商对账</h2>
          <div class="head-meta">
            <span class="meta">供应商整月扫描量一口价 vs 平台逐条缓存/计费口径</span>
            ${canImport ? '<button class="btn accent sm" id="btn-import" data-testid="bill-import">导入供应商账单</button>' : ''}
          </div>
        </div>
        <div class="panel-body">
          <p class="mono muted" style="font-size:var(--fs-xs);margin:0 0 12px">
            逐笔对齐两侧查询，区分漏计 / 重复 / 单价不符 / 平台多计；重跑同一账单不新增核对结果，核对失败保留全部记录。
            差异清零前预算告警沿用旧值，确认发布后只重算差异涉及的账期。
          </p>
        </div>
        ${table({
          rows: data.items,
          empty: { title: '还没有供应商账单', hint: canImport ? '点击右上角导入第一份账单 CSV。' : '等待管理员或数据专员导入。', actionText: canImport ? '导入账单' : '', actionId: 'btn-import-empty' },
          columns: [
            { key: 'bill_no', label: '账单号', render: (row) => `<b class="mono">${esc(row.bill_no)}</b><div class="mono muted tiny">${esc(row.source_filename)}</div>` },
            { key: 'period', label: '账期', render: (row) => `<span class="mono">${esc(row.period)}</span>` },
            { key: 'line_count', label: '行数', className: 'num' },
            { key: 'total_scanned_gb', label: '扫描量(GB)', className: 'num', render: (row) => Number(row.total_scanned_gb).toFixed(2) },
            { key: 'total_amount_yuan', label: '供应商总额', className: 'num', render: (row) => `¥${Number(row.total_amount_yuan).toFixed(2)}` },
            { key: 'status', label: '发布状态', render: (row) => badge(billStatusTone(row.status), row.status_label) },
            { key: 'created_at', label: '导入时间', render: (row) => fmtTime(row.created_at) },
          ],
        })}
      </section>
      <div id="reconcile-detail"></div>`;

    const openImport = () => importDrawer(view, ctx);
    view.querySelector('#btn-import')?.addEventListener('click', openImport);
    view.querySelector('#btn-import-empty')?.addEventListener('click', openImport);

    view.querySelectorAll('table.data tbody tr').forEach((node) => {
      node.addEventListener('click', () => {
        state.selectedId = Number(node.dataset.id);
        view.querySelectorAll('table.data tbody tr').forEach((tr) => tr.classList.remove('selected'));
        node.classList.add('selected');
        renderDetail(view, ctx, state.selectedId).catch((err) => {
          toast(errorMessage(err), 'err');
        });
      });
    });

    if (state.selectedId && data.items.some((item) => item.id === state.selectedId)) {
      renderDetail(view, ctx, state.selectedId).catch((err) => toast(errorMessage(err), 'err'));
    }
  },
};

export default reconcilePage;
