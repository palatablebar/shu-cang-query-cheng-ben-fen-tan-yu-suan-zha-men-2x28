import { api } from '../api.js';
import { session } from '../store.js';
import { BRAND } from '../config.js';
import { errorMessage, esc, toast } from '../ui.js';

const TEAM_LEDGER = [
  ['team-a', '计算平台组', '21%'],
  ['team-b', '增长分析组', '38%'],
  ['team-c', '供应链数据组', '17%'],
  ['team-d', '财务数据组', '14%'],
  ['team-e', '风控建模组', '10%'],
];

export const loginPage = {
  async render(root, ctx) {
    root.className = 'login-host';
    root.innerHTML = `
      <div class="login">
        <section class="login-brief terminal-cover">
          <div class="cover-top">
            <div class="eyebrow">${esc(BRAND.edition)} · ${esc(BRAND.gl)}</div>
            <div class="led-row">
              <span class="led on"></span><span class="mono">CH-COST · ONLINE</span>
              <span class="led warn"></span><span class="mono">3 ALERTS</span>
              <span class="led off"></span><span class="mono">GATE · STANDBY</span>
            </div>
          </div>
          <div class="cover-figure">
            <span class="k">MONTH TO DATE / 42,180.00 CNY</span>
            <b>¥42,180</b>
            <em>5 teams · 1,200 queries · threshold 338.97 GB</em>
          </div>
          <h1>${esc(BRAND.title)}<br /><span class="slash">/ costcharge</span></h1>
          <p class="tagline">${esc(BRAND.loginLead)}</p>
          <div class="brief-points">
            ${BRAND.loginPoints
              .map(([no, text]) => `<div class="brief-point"><i>${esc(no)}</i><span>${esc(text)}</span></div>`)
              .join('')}
          </div>
          <div class="cover-ledger">
            ${TEAM_LEDGER.map(
              ([code, name, share]) => `<div class="cover-line"><span class="mono">${esc(code)}</span><span>${esc(name)}</span><b class="mono">${esc(share)}</b></div>`,
            ).join('')}
          </div>
          <div class="eyebrow cover-foot">${esc(BRAND.org)} · 机房计费屏 v2026.11</div>
        </section>
        <section class="login-form-wrap">
          <form class="login-card" id="login-form" novalidate>
            <div>
              <div class="eyebrow">OPERATOR SIGN-IN</div>
              <div class="brand">进入计费工作台</div>
              <div class="sub">三个演示账号权限不同：管理员可配预算/导出，专员可核算/处置告警，只读账号仅看自己团队。</div>
            </div>
            <div class="field">
              <label for="email">邮箱</label>
              <input id="email" name="email" type="email" autocomplete="username" value="admin@${esc(BRAND.short)}.io" required />
            </div>
            <div class="field">
              <label for="password">密码</label>
              <input id="password" name="password" type="password" autocomplete="current-password" value="Demo@2026" required />
            </div>
            <div class="form-error" id="login-error" role="alert"></div>
            <button class="btn accent" id="login-submit" type="submit">接入计费屏</button>
            <div class="login-hint">
              演示账号（密码 <code>Demo@2026</code>）：<br />
              <code>admin@${esc(BRAND.short)}.io</code> 管理员 · <code>analyst@${esc(BRAND.short)}.io</code> 数据专员 ·
              <code>viewer@${esc(BRAND.short)}.io</code> 团队只读
            </div>
          </form>
        </section>
      </div>`;

    const form = root.querySelector('#login-form');
    const errorNode = root.querySelector('#login-error');
    const submit = root.querySelector('#login-submit');
    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      errorNode.textContent = '';
      submit.disabled = true;
      submit.textContent = '校验凭证…';
      try {
        const result = await api.post('/api/auth/login', {
          email: form.email.value.trim(),
          password: form.password.value,
        });
        session.set(result.access_token, result.user);
        toast(`欢迎回来，${result.user.display_name}`);
        location.hash = '#/overview';
        await ctx.reload();
      } catch (err) {
        errorNode.textContent = err.code === 'AUTH_INVALID' ? '账号或密码不正确' : errorMessage(err);
      } finally {
        submit.disabled = false;
        submit.textContent = '接入计费屏';
      }
    });
  },
};

export default loginPage;
