import { api } from '../api.js';
import { ENUMS, can, levelTone, pct } from '../config.js';
import { costFigure, costTrend, emptyState, errorBox, errorMessage, esc, fmtTime, meter, toast } from '../ui.js';

function allocationRow(item) {
  const used = item.used_ratio || 0;
  return `<div class="alloc-row">
    <div class="alloc-head">
      <span class="mono">${esc(item.code)}</span>
      <b>${esc(item.name)}</b>
      <span class="badge ${levelTone(item.level)}">${esc(ENUMS.alertLevel[item.level] || item.level)}</span>
      <span class="mono num">¥${Number(item.amount_yuan).toFixed(2)}</span>
    </div>
    ${meter(used, { segments: 32, tone: used > 1 ? 'danger' : 'on' })}
    <div class="alloc-meta mono">
      <span>占比 ${pct(item.ratio)}</span>
      <span>预算 ¥${Number(item.budget_yuan).toFixed(2)}</span>
      <span>用量 ${pct(used)}</span>
      <span>预测 ${item.forecast_ratio === null ? '—' : pct(item.forecast_ratio)}</span>
    </div>
  </div>`;
}

export const overviewPage = {
  async render(view, ctx) {
    view.innerHTML = '<div class="empty"><div class="mark">读取计费数据…</div></div>';
    try {
      const data = await api.get('/api/overview');
      const latest = data.latest_run;
      const metrics = data.metrics || {};
      const canRun = can(ctx.user.role, 'run:create');
      const scoped = data.scope_team_id
        ? `<span class="badge warn">team scope · #${esc(data.scope_team_id)}</span>`
        : '<span class="badge">all teams</span>';
      view.innerHTML = `
        <section class="ops-hero">
          <div class="hero-main">
            <div class="eyebrow">CURRENT BILLING WINDOW ${latest ? `· ${esc(latest.run_no)}` : ''}</div>
            <div class="hero-cost">
              <span class="cur">¥</span><b data-testid="total-cost">${Number(data.total_cost_yuan || 0).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</b>
            </div>
            <div class="hero-sub mono">预算 ¥${Number(data.budget_total_yuan || 0).toFixed(2)} · 占用 ${data.budget_used_ratio === null ? '—' : pct(data.budget_used_ratio)} · ${data.query_total} 次查询 · ${data.failed_count} 次未计费</div>
            ${meter(data.budget_used_ratio || 0, { segments: 40 })}
            <div class="hero-flags">
              ${scoped}
              <span class="badge ${data.anomaly_count ? 'high' : 'ok'}">异常查询 ${data.anomaly_count}</span>
              <span class="badge ${data.pending_alerts ? 'warn' : 'ok'}">待处置告警 ${data.pending_alerts}</span>
              <span class="badge">阈值 ${Number(metrics.threshold_gb || 0).toFixed(2)} GB</span>
              <span class="badge">P95 ${Number(metrics.p95_gb || 0).toFixed(2)} GB</span>
              <span class="badge">MAD ${Number(metrics.mad_gb || 0).toFixed(2)} GB</span>
            </div>
          </div>
          <div class="hero-side">
            <div class="side-block">
              <span class="eyebrow">RUN STATUS</span>
              <b class="mono">${latest ? esc(ENUMS.runStatus[latest.status] || latest.status) : '—'}</b>
              <span class="mono tiny">${latest ? `${esc(latest.period)} · ${esc(latest.operator_email)}` : '还没有成本运行'}</span>
              <span class="mono tiny">${latest ? `扫描 ${latest.input_count} 条 · ${pct(metrics.cache_hit_ratio || 0)} 缓存命中` : ''}</span>
            </div>
            <div class="side-block">
              <span class="eyebrow">FORECAST / REMAINING</span>
              <b class="mono">${metrics.remaining_days ?? 0} 天</b>
              <span class="mono tiny">单查询均价 ¥${Number(metrics.avg_cost_yuan || 0).toFixed(2)}</span>
            </div>
            ${canRun ? `<button class="btn accent" id="run-cost" data-testid="run-cost">发起成本核算</button>` : '<span class="mono tiny muted">只读角色不能发起核算</span>'}
          </div>
        </section>

        <div class="grid-2">
          <section class="panel">
            <div class="panel-head"><h2>团队分摊</h2><span class="meta">charge / ${data.allocation.length} teams</span></div>
            <div class="panel-body alloc-list">
              ${data.allocation.length ? data.allocation.map(allocationRow).join('') : emptyState({ title: '还没有分摊结果', hint: '先跑一次成本核算。' })}
            </div>
          </section>
          <section class="panel">
            <div class="panel-head"><h2>近 7 天成本</h2><span class="meta">CNY / day</span></div>
            <div class="panel-body">
              ${costTrend(data.trend)}
              <div class="hero-flags" style="margin-top:14px">
                <span class="badge">worker ${data.worker_alive ? '在岗' : '心跳超时'}</span>
                <span class="badge">团队 ${data.team_count}</span>
                <span class="badge">告警 ${data.alert_count}</span>
              </div>
            </div>
          </section>
        </div>

        <div class="grid-2">
          <section class="panel">
            <div class="panel-head"><h2>预算告警</h2><span class="meta">latest run</span></div>
            <div class="panel-body">
              ${
                data.alerts.length
                  ? `<div class="alert-list">${data.alerts
                      .map(
                        (alert) => `<button class="alert-line" data-alert="${esc(alert.id)}">
                          <span class="badge ${levelTone(alert.level)}">${esc(ENUMS.alertLevel[alert.level] || alert.level)}</span>
                          <b>${esc(alert.team_name)}</b>
                          <span class="mono">预测 ¥${Number(alert.forecast_yuan).toFixed(2)} · ${pct(alert.ratio)}</span>
                          <span class="mono tiny">${esc(ENUMS.alertStatus[alert.status] || alert.status)}</span>
                        </button>`,
                      )
                      .join('')}</div>`
                  : emptyState({ title: '本期没有超预算告警', hint: '预测均在预算内。' })
              }
            </div>
          </section>
          <section class="panel">
            <div class="panel-head"><h2>最近一次核算</h2><span class="meta">cost run</span></div>
            <div class="panel-body">
              ${
                latest
                  ? `<dl class="kv">
                      <dt>运行号</dt><dd class="mono">${esc(latest.run_no)}</dd>
                      <dt>账期</dt><dd class="mono">${esc(latest.period)}</dd>
                      <dt>总成本</dt><dd>¥${Number(latest.total_cost_yuan).toFixed(2)}</dd>
                      <dt>开始</dt><dd>${fmtTime(latest.started_at)}</dd>
                      <dt>扫描</dt><dd>${data.query_total} 条查询（本视图）</dd>
                      <dt>输出</dt><dd>${data.allocation.length} 条分摊 / ${data.alert_count} 条告警</dd>
                    </dl>
                    <p class="muted mono" style="margin:10px 0 0">${esc(data.anomaly_count)} anomalies · threshold ${Number(latest.metrics?.threshold_gb || 0).toFixed(2)} GB</p>`
                  : emptyState({ title: '还没有运行记录', hint: '管理员或专员可以在上方发起核算。' })
              }
            </div>
          </section>
        </div>`;

      view.querySelector('#run-cost')?.addEventListener('click', async (event) => {
        const button = event.currentTarget;
        button.disabled = true;
        button.textContent = '核算中…';
        try {
          const run = await api.post('/api/cost-runs', { trigger: 'manual' });
          toast(`核算 ${run.run_no} 完成：¥${Number(run.total_cost_yuan).toFixed(2)}`);
          await overviewPage.render(view, ctx);
        } catch (err) {
          toast(errorMessage(err), 'err');
          button.disabled = false;
          button.textContent = '发起成本核算';
        }
      });
      view.querySelectorAll('[data-alert]').forEach((node) => {
        node.addEventListener('click', () => {
          location.hash = '#/alerts';
        });
      });
    } catch (err) {
      view.innerHTML = errorBox(errorMessage(err));
      view.querySelector('#retry-btn')?.addEventListener('click', () => overviewPage.render(view, ctx));
    }
  },
};

export default overviewPage;
