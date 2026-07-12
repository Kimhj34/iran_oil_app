/* ══════════════════════════════════════════
   STATE — localStorage 기반 상태 유지
══════════════════════════════════════════ */
const _STATE_KEY = 'iranOilState';

function saveState(update) {
  try {
    const s = loadState();
    localStorage.setItem(_STATE_KEY, JSON.stringify({ ...s, ...update }));
  } catch (_) {}
}

function loadState() {
  try { return JSON.parse(localStorage.getItem(_STATE_KEY)) || {}; }
  catch { return {}; }
}

/* ══════════════════════════════════════════
   AUTH — 로그인 / 회원가입
══════════════════════════════════════════ */
let _authUser = null;

const getToken  = () => localStorage.getItem('auth_token');
const setToken  = t  => localStorage.setItem('auth_token', t);
const clearToken = () => localStorage.removeItem('auth_token');

/* ── 인증 상태에 따른 UI 업데이트 ── */
function updateAuthUI() {
  const loggedIn = !!_authUser;

  /* 랜딩 nav */
  const navGuest = document.getElementById('nav-guest');
  const navUser  = document.getElementById('nav-user');
  if (navGuest) navGuest.classList.toggle('hidden', loggedIn);
  if (navUser)  navUser.classList.toggle('hidden', !loggedIn);
  const navUsername = document.getElementById('nav-username');
  if (navUsername && _authUser) navUsername.textContent = _authUser.name;

  /* 탑바 */
  const tbUser  = document.getElementById('tb-user');
  const tbGuest = document.getElementById('tb-guest');
  if (tbUser)  tbUser.classList.toggle('hidden', !loggedIn);
  if (tbGuest) tbGuest.classList.toggle('hidden', loggedIn);
  const tbUsername = document.getElementById('tb-username');
  if (tbUsername && _authUser) tbUsername.textContent = `${_authUser.name}님`;

  /* 마이페이지 탭 표시/숨김 */
  const tab6Nav = document.getElementById('tab6-nav');
  if (tab6Nav) tab6Nav.classList.toggle('hidden', !loggedIn);

  /* 로그아웃 시 tab6에 있으면 tab1으로 이동 */
  if (!loggedIn) {
    const activeBtn = document.querySelector('.tab-btn.active');
    if (activeBtn?.dataset.tab === 'tab6') {
      document.querySelector('[data-tab="tab1"]').click();
    }
    tab6Loaded = false;
  }
}

/* ── 토큰으로 자동 로그인 확인 ── */
async function checkAuth() {
  const token = getToken();
  if (!token) {
    _restorePageState();
    return;
  }
  try {
    const res = await fetch('/api/auth/me', {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (res.ok) {
      _authUser = await res.json();
    } else {
      clearToken();
    }
  } catch (_) { clearToken(); }
  updateAuthUI();
  _restorePageState();
}

/* ── 새로고침 후 이전 화면 복원 ── */
function _restorePageState() {
  const s = loadState();
  if (s.view !== 'app') return;

  showApp();

  const tabId = s.activeTab || 'tab1';
  /* tab6(마이페이지)은 로그인 필요 */
  const target = (tabId === 'tab6' && !_authUser) ? 'tab1' : tabId;

  if (target !== 'tab1') {
    setTimeout(() => {
      const btn = document.querySelector(`[data-tab="${target}"]`);
      if (btn) btn.click();
    }, 0);
  }
}

/* ── 모달 열기/닫기 ── */
function openModal(tab = 'form-login') {
  document.getElementById('auth-modal').classList.remove('hidden');
  document.body.style.overflow = 'hidden';
  switchAuthTab(tab);
}

function closeModal() {
  document.getElementById('auth-modal').classList.add('hidden');
  document.body.style.overflow = '';
  clearFormErrors();
}

function switchAuthTab(formId) {
  /* 탭 버튼: onclick 속성에서 함수 인자로 받은 formId와 일치하는 버튼 활성화 */
  document.querySelectorAll('.mtab').forEach(btn => {
    const isTarget = btn.getAttribute('onclick')?.includes(formId);
    btn.classList.toggle('active', !!isTarget);
  });
  document.querySelectorAll('.auth-form').forEach(f => {
    f.classList.toggle('hidden', f.id !== formId);
  });
}

function clearFormErrors() {
  ['login-error', 'reg-error'].forEach(id => {
    const el = document.getElementById(id);
    if (el) { el.textContent = ''; el.classList.add('hidden'); }
  });
  document.querySelectorAll('.form-group input').forEach(i => i.classList.remove('input-error'));
}

function showError(id, msg) {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = msg;
  el.classList.remove('hidden');
}

/* ── 로그인 처리 ── */
async function doLogin() {
  const email = document.getElementById('login-email').value.trim();
  const pw    = document.getElementById('login-pw').value;
  if (!email || !pw) { showError('login-error', '이메일과 비밀번호를 모두 입력하세요.'); return; }

  const btn = document.getElementById('login-submit');
  btn.disabled = true; btn.textContent = '로그인 중...';

  try {
    const res  = await fetch('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password: pw }),
    });
    const data = await res.json();
    if (!res.ok) { showError('login-error', data.detail || '로그인에 실패했습니다.'); return; }
    setToken(data.token);
    _authUser = { user_id: data.user_id, name: data.name, email: data.email };
    updateAuthUI();
    closeModal();
    showApp();
  } catch (_) {
    showError('login-error', '네트워크 오류가 발생했습니다.');
  } finally {
    btn.disabled = false; btn.textContent = '로그인';
  }
}

/* ── 회원가입 처리 ── */
async function doRegister() {
  const name  = document.getElementById('reg-name').value.trim();
  const email = document.getElementById('reg-email').value.trim();
  const pw    = document.getElementById('reg-pw').value;

  if (!name)  { showError('reg-error', '이름을 입력하세요.'); return; }
  if (!email) { showError('reg-error', '이메일을 입력하세요.'); return; }
  if (pw.length < 6) { showError('reg-error', '비밀번호는 6자 이상이어야 합니다.'); return; }

  const btn = document.getElementById('reg-submit');
  btn.disabled = true; btn.textContent = '가입 중...';

  try {
    const res  = await fetch('/api/auth/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, email, password: pw }),
    });
    const data = await res.json();
    if (!res.ok) { showError('reg-error', data.detail || '회원가입에 실패했습니다.'); return; }
    setToken(data.token);
    _authUser = { user_id: data.user_id, name: data.name, email: data.email };
    updateAuthUI();
    closeModal();
    showApp();
  } catch (_) {
    showError('reg-error', '네트워크 오류가 발생했습니다.');
  } finally {
    btn.disabled = false; btn.textContent = '가입하기';
  }
}

/* ── 로그아웃 처리 ── */
function doLogout() {
  closeDropdown();
  clearToken();
  _authUser = null;
  updateAuthUI();
  showLanding();
}

/* ── 드롭다운 토글 ── */
function closeDropdown() {
  document.getElementById('dropdown-menu')?.classList.add('hidden');
  document.getElementById('tb-user')?.classList.remove('open');
}

function toggleDropdown(e) {
  e.stopPropagation();
  const menu = document.getElementById('dropdown-menu');
  const isOpen = !menu.classList.contains('hidden');
  if (isOpen) {
    closeDropdown();
  } else {
    menu.classList.remove('hidden');
    document.getElementById('tb-user').classList.add('open');
  }
}

function goToMyPage() {
  closeDropdown();
  const tab6btn = document.querySelector('[data-tab="tab6"]');
  if (tab6btn) tab6btn.click();
}

/* 드롭다운 바깥 클릭 시 닫기 */
document.addEventListener('click', () => closeDropdown());

/* 모달은 X 버튼 / 취소 버튼으로만 닫힘 (오버레이 클릭·Esc 비활성화) */

/* 자동 로그인 확인 */
checkAuth();

/* ── Chart.js 전역 기본값 (라이트 테마) ── */
Chart.defaults.color = '#6B7280';
Chart.defaults.borderColor = '#E5E7EB';
Chart.defaults.font.family = "'Segoe UI', 'Apple SD Gothic Neo', sans-serif";

const COLORS = {
  red:    '#EF4444',
  blue:   '#2563EB',
  green:  '#10B981',
  yellow: '#F59E0B',
  purple: '#8B5CF6',
  pink:   '#EC4899',
  teal:   '#14B8A6',
  orange: '#F97316',
};

const ITEM_COLORS = {
  '라면':    COLORS.red,
  '두부':    COLORS.blue,
  '우유':    COLORS.green,
  '달걀':    COLORS.yellow,
  '식용유':  COLORS.orange,
  '생수':    COLORS.teal,
  '전기료':  COLORS.purple,
  '도시가스': COLORS.pink,
};

/* ══════════════════════════════════════════ */
/* 랜딩 페이지 ↔ 메인 앱 전환                  */
/* ══════════════════════════════════════════ */
function showApp() {
  saveState({ view: 'app' });
  document.getElementById('landing').classList.add('hidden');
  document.getElementById('main-app').classList.remove('hidden');
  if (!tab1Loaded) loadTab1().catch(err => {
    console.error('loadTab1 실패:', err);
    const el = document.getElementById('tab1-kpi');
    if (el) el.innerHTML = `<div class="loading" style="color:#EF4444">오류: ${err.message}</div>`;
  });
}

function showLanding() {
  saveState({ view: 'landing' });
  document.getElementById('main-app').classList.add('hidden');
  document.getElementById('landing').classList.remove('hidden');
}

document.getElementById('start-btn')?.addEventListener('click', showApp);
document.getElementById('start-btn2')?.addEventListener('click', showApp);
document.getElementById('back-btn')?.addEventListener('click', showLanding);

/* 랜딩 페이지 실시간 가격 로드 */
(async function loadLandingPrice() {
  try {
    /* 실시간 시세 먼저 시도, 실패하면 /api/oil KPI 폴백 */
    let price = null, change = null, date = null;

    try {
      const rtRes = await fetch('/api/realtime');
      const rt    = await rtRes.json();
      if (rt && rt.price) { price = rt.price; change = rt.change ?? null; date = rt.date ?? null; }
    } catch (_) {}

    if (!price) {
      const oilRes = await fetch('/api/oil');
      const oil    = await oilRes.json();
      price = oil?.kpi?.current_brent ?? oil?.realtime?.price ?? null;
    }

    if (!price) return;

    const brentEl = document.getElementById('hero-brent');
    const chgEl   = document.getElementById('hero-brent-chg');
    if (brentEl) brentEl.textContent = `$${Number(price).toFixed(2)}`;
    if (chgEl && change !== null) {
      const sign = change >= 0 ? '▲' : '▼';
      chgEl.textContent = `${sign}${Math.abs(change)}% (전일 대비)`;
      chgEl.className   = 'hero-price-chg ' + (change >= 0 ? 'up' : 'dn');
    }

    const tickerEl = document.getElementById('t-brent');
    if (tickerEl) tickerEl.textContent = `$${Number(price).toFixed(2)}`;
  } catch (_) {}
})();

/* ══════════════════════════════════════════ */
/* 탭 전환                                    */
/* ══════════════════════════════════════════ */
document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById(btn.dataset.tab).classList.add('active');
    saveState({ activeTab: btn.dataset.tab });
    if (btn.dataset.tab === 'tab1' && !tab1Loaded) loadTab1().catch(e => console.error(e));
    if (btn.dataset.tab === 'tab2' && !tab2Loaded) loadTab2().catch(e => console.error(e));
    if (btn.dataset.tab === 'tab3' && !tab3Loaded) loadTab3().catch(e => console.error(e));
    if (btn.dataset.tab === 'tab4' && !tab4Loaded) loadTab4().catch(e => console.error(e));
    if (btn.dataset.tab === 'tab6') loadTab6();
  });
});

/* ══════════════════════════════════════════ */
/* 공통 차트 스케일 (라이트)                   */
/* ══════════════════════════════════════════ */
const GRID_COLOR  = '#F3F4F6';
const TICK_COLOR  = '#6B7280';
const AXIS_OPT = {
  x: (extra = {}) => ({
    ticks: { maxTicksLimit: 14, maxRotation: 0, color: TICK_COLOR, font: { size: 11 }, ...extra },
    grid:  { color: GRID_COLOR },
  }),
  y: (extra = {}) => ({
    ticks: { color: TICK_COLOR, ...extra },
    grid:  { color: GRID_COLOR },
  }),
};

/* ══════════════════════════════════════════ */
/* 탭 1: 유가 분석                            */
/* ══════════════════════════════════════════ */
let tab1Loaded    = false;
let chartBrent    = null;
let chartGasoline = null;

async function loadTab1() {
  tab1Loaded = true;

  /* ── 1단계: 데이터 수집 + KPI 렌더 ── */
  let data, rt;
  try {
    const [oilRes, rtRes] = await Promise.all([
      fetch('/api/oil'),
      fetch('/api/realtime'),
    ]);
    if (!oilRes.ok) throw new Error(`/api/oil ${oilRes.status}`);
    data = await oilRes.json();
    rt   = await rtRes.json().catch(() => null);
    try { sessionStorage.setItem('oilData', JSON.stringify(data)); } catch (_) {}
  } catch (err) {
    document.getElementById('tab1-kpi').innerHTML =
      `<div class="loading" style="color:#EF4444">데이터 로딩 실패: ${err.message}</div>`;
    return;
  }

  const kpi      = data.kpi ?? {};
  const rtPrice  = rt?.price  ?? kpi.current_brent ?? 0;
  const rtChange = rt?.change ?? null;
  const rtDate   = rt?.date   ?? '—';
  const chgHtml  = rtChange !== null
    ? `<span class="${rtChange >= 0 ? 'up' : 'dn'}">${rtChange >= 0 ? '▲' : '▼'}${Math.abs(rtChange)}%</span>`
    : '';

  const tickerEl = document.getElementById('t-brent');
  if (tickerEl) tickerEl.textContent = `$${rtPrice.toFixed(2)}`;

  document.getElementById('tab1-kpi').innerHTML = `
    <div class="kpi-card">
      <div class="kpi-label">실시간 브렌트유 ${chgHtml}</div>
      <div class="kpi-value up">$${rtPrice.toFixed(2)}</div>
      <div class="kpi-sub">Yahoo Finance · ${rtDate}</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">이란전쟁 이후 상승률</div>
      <div class="kpi-value up">+${kpi.iran_war_rise_pct ?? '—'}%</div>
      <div class="kpi-sub">2026.02 대비 (CSV 기준)</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">국내 휘발유 가격</div>
      <div class="kpi-value neu">${(kpi.gasoline_price ?? 0).toLocaleString()}원</div>
      <div class="kpi-sub">원/L (오피넷)</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-label">러-우 전쟁 최고가</div>
      <div class="kpi-value" style="color:#F59E0B">$${(kpi.russia_peak ?? 0).toFixed(2)}</div>
      <div class="kpi-sub">2022년 피크</div>
    </div>
  `;

  /* ── 2단계: 차트 렌더 (실패해도 KPI는 유지) ── */
  const months = data.months ?? [];
  const prices = data.prices ?? [];
  const wz     = data.war_zones ?? { russia: {}, iran: {} };

  try {
    if (chartBrent) chartBrent.destroy();
    chartBrent = new Chart(document.getElementById('chart-brent'), {
      type: 'line',
      data: {
        labels: months,
        datasets: [{
          label: '브렌트유 ($/bbl)',
          data: prices,
          borderColor: COLORS.blue,
          borderWidth: 2,
          fill: false,
          tension: 0.3,
          pointRadius: 0,
          pointHoverRadius: 4,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: { display: false },
          tooltip: { callbacks: { label: ctx => `$${ctx.raw.toFixed(2)}/bbl` } },
        },
        scales: {
          x: AXIS_OPT.x(),
          y: { ...AXIS_OPT.y(), ticks: { color: TICK_COLOR, callback: v => `$${v}` } },
        },
      },
      plugins: [warZonePlugin(months, wz)],
    });
  } catch (e) { console.error('chartBrent 오류:', e); }

  try {
    const gasolineData = estimateGasoline(months, prices);
    if (chartGasoline) chartGasoline.destroy();
    chartGasoline = new Chart(document.getElementById('chart-gasoline'), {
      type: 'line',
      data: {
        labels: months,
        datasets: [{
          label: '국내 휘발유 (원/L)',
          data: gasolineData,
          borderColor: COLORS.red,
          borderWidth: 2,
          fill: { target: 'origin', above: 'rgba(239,68,68,0.06)' },
          tension: 0.3,
          pointRadius: 0,
          pointHoverRadius: 4,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: { display: false },
          tooltip: { callbacks: { label: ctx => `${Math.round(ctx.raw).toLocaleString()}원/L` } },
        },
        scales: {
          x: AXIS_OPT.x(),
          y: { ...AXIS_OPT.y(), ticks: { color: TICK_COLOR, callback: v => `${v.toLocaleString()}원` }, min: 1200 },
        },
      },
      plugins: [warZonePlugin(months, wz, 'warZone2')],
    });
  } catch (e) { console.error('chartGasoline 오류:', e); }

  /* ── 3단계: 회귀분석 테이블 ── */
  try {
    const anRes   = await fetch('/api/analysis');
    const an      = await anRes.json();
    const tableEl = document.getElementById('analysis-table');
    if (tableEl && an.items) {
      const rows = an.items.map(it => {
        const badge = it.used_regression
          ? `<span class="reg-badge reg-used">회귀값</span>`
          : `<span class="reg-badge reg-est">추정치</span>`;
        const r2cls = it.r_squared !== null && it.r_squared >= 0.05 ? 'tag-green' : 'tag-red';
        const r2txt = it.r_squared !== null ? it.r_squared.toFixed(4) : 'N/A';
        const arrow = it.used_regression
          ? `<span class="tag-red">${it.original} → <b>${it.elasticity_used}</b></span>`
          : `<span class="tag-green">${it.elasticity_used}</span>`;
        return `
          <tr>
            <td>${it.name}</td>
            <td>${badge}</td>
            <td style="font-family:monospace">${arrow}</td>
            <td style="font-family:monospace" class="${r2cls}">${r2txt}</td>
            <td style="color:#9CA3AF">${it.n_samples ?? '—'}</td>
          </tr>`;
      }).join('');
      tableEl.innerHTML = `
        <table class="reg-table">
          <thead><tr><th>품목</th><th>적용</th><th>탄성계수</th><th>R²</th><th>샘플수</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>
        <p style="font-size:11px;color:#9CA3AF;margin-top:8px">
          * R² ≥ 0.05: 회귀값 적용 | R² &lt; 0.05: 추정치 유지
        </p>`;
    }
  } catch (_) {}
}

function estimateGasoline(months, brentPrices) {
  return brentPrices.map(p => p ? Math.max(1200, 1650 + (p - 75) * 8.5) : null);
}

/* 전쟁 구간 음영 Plugin */
function warZonePlugin(months, wz, id = 'warZone') {
  return {
    id,
    beforeDraw(chart) {
      const { ctx, chartArea, scales } = chart;
      if (!chartArea) return;
      const x = scales.x;
      function shade(start, end, color) {
        const si = months.findIndex(m => m >= start);
        const ei = end ? months.findIndex(m => m > end) - 1 : months.length - 1;
        if (si < 0) return;
        const x1 = x.getPixelForValue(si);
        const x2 = x.getPixelForValue(Math.max(si, ei));
        ctx.save();
        ctx.fillStyle = color;
        ctx.fillRect(x1, chartArea.top, x2 - x1, chartArea.height);
        ctx.restore();
      }
      shade(wz.russia.start, wz.russia.end, 'rgba(37,99,235,0.08)');
      shade(wz.iran.start,   wz.iran.end,   'rgba(239,68,68,0.08)');
    },
  };
}

/* ══════════════════════════════════════════ */
/* 탭 2: 물가 변화                            */
/* ══════════════════════════════════════════ */
let tab2Loaded  = false;
let chartPrices = null;
let chartAnnual = null;

async function loadTab2() {
  tab2Loaded = true;
  let data;
  try {
    const res = await fetch('/api/prices');
    if (!res.ok) throw new Error(`/api/prices ${res.status}`);
    data = await res.json();
  } catch (err) {
    document.getElementById('tab2-kpi').innerHTML =
      `<div class="loading" style="color:#EF4444">데이터 로딩 실패: ${err.message}</div>`;
    return;
  }

  /* KPI 카드 */
  const kpi = data.kpi ?? {};
  const kpiItems = ['라면', '달걀', '우유', '식용유', '두부'];
  document.getElementById('tab2-kpi').innerHTML = kpiItems.map(item => `
    <div class="kpi-card">
      <div class="kpi-label">${item}</div>
      <div class="kpi-value ${(kpi[item] ?? 0) > 0 ? 'up' : 'dn'}">
        ${(kpi[item] ?? 0) > 0 ? '+' : ''}${kpi[item] ?? 0}%
      </div>
      <div class="kpi-sub">2022.01 대비</div>
    </div>
  `).join('');

  /* 품목별 멀티라인 차트 */
  const months     = data.months;
  const items      = data.items;
  const showItems  = ['라면', '우유', '달걀', '식용유', '생수'];
  const datasets   = showItems.map(name => ({
    label: name,
    data:  items[name],
    borderColor: ITEM_COLORS[name] || COLORS.blue,
    borderWidth: 2,
    fill: false,
    tension: 0.3,
    pointRadius: 0,
    pointHoverRadius: 4,
  }));

  if (chartPrices) chartPrices.destroy();
  chartPrices = new Chart(document.getElementById('chart-prices'), {
    type: 'line',
    data: { labels: months, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: {
          display: true,
          position: 'top',
          labels: { color: TICK_COLOR, font: { size: 11 }, boxWidth: 12, padding: 12 },
        },
        tooltip: { callbacks: { label: ctx => `${ctx.dataset.label}: ${ctx.raw?.toFixed(1) ?? '-'}` } },
      },
      scales: {
        x: AXIS_OPT.x({ maxTicksLimit: 12 }),
        y: AXIS_OPT.y(),
      },
    },
    plugins: [{
      id: 'baseLine100',
      beforeDraw(chart) {
        const { ctx, chartArea, scales } = chart;
        if (!chartArea) return;
        const y100 = scales.y.getPixelForValue(100);
        ctx.save();
        ctx.strokeStyle = 'rgba(107,114,128,0.4)';
        ctx.setLineDash([4, 4]);
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(chartArea.left, y100);
        ctx.lineTo(chartArea.right, y100);
        ctx.stroke();
        ctx.restore();
      },
    }],
  });

  /* 연도별 바 차트 */
  const years      = ['2021', '2022', '2023', '2024', '2025'];
  const barColors  = [COLORS.blue, COLORS.teal, COLORS.yellow, COLORS.orange, COLORS.red];
  const annualItems = ['라면', '달걀', '우유', '식용유'];

  const barDatasets = years.map((yr, i) => ({
    label: `${yr}년`,
    data:  annualItems.map(item => data.annual[item]?.[yr] ?? null),
    backgroundColor: barColors[i] + 'BB',
    borderColor: barColors[i],
    borderWidth: 1,
    borderRadius: 4,
  }));

  if (chartAnnual) chartAnnual.destroy();
  chartAnnual = new Chart(document.getElementById('chart-annual'), {
    type: 'bar',
    data: { labels: annualItems, datasets: barDatasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          display: true,
          position: 'top',
          labels: { color: TICK_COLOR, font: { size: 11 }, boxWidth: 12, padding: 10 },
        },
        tooltip: { callbacks: { label: ctx => `${ctx.dataset.label}: ${ctx.raw?.toFixed(1) ?? '-'}` } },
      },
      scales: {
        x: AXIS_OPT.x(),
        y: { ...AXIS_OPT.y(), min: 90 },
      },
    },
  });
}

/* ══════════════════════════════════════════ */
/* 탭 3: 시나리오 예측                         */
/* ══════════════════════════════════════════ */
let tab3Loaded    = false;
let chartScenario = null;
let currentSc     = 'local';

async function loadTab3() {
  tab3Loaded = true;
  try {
    await renderScenario('local');
    await loadScenarioCompareChart();
  } catch (err) {
    document.getElementById('tab3-items').innerHTML =
      `<div class="loading" style="color:#EF4444">데이터 로딩 실패: ${err.message}</div>`;
    return;
  }

  document.querySelectorAll('.scenario-btn').forEach(btn => {
    btn.addEventListener('click', async () => {
      document.querySelectorAll('.scenario-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      currentSc = btn.dataset.sc;
      await renderScenario(currentSc);
    });
  });
}

async function renderScenario(sc) {
  const res  = await fetch(`/api/scenario/${sc}`);
  const data = await res.json();

  document.getElementById('tab3-items').innerHTML = data.items.map(it => `
    <div class="item-card">
      <div class="ic-name">${it.name} <span class="ic-unit">${it.unit}</span></div>
      <div class="ic-now">${it.price_now.toLocaleString()}원</div>
      <div class="ic-arrow">→</div>
      <div class="ic-pred">${it.price_pred.toLocaleString()}원</div>
      <div class="ic-badge">+${it.diff.toLocaleString()}원 (+${it.diff_pct}%)</div>
    </div>
  `).join('');

  const sum = data.summary;
  document.getElementById('tab3-summary').innerHTML = `
    <div class="summary-card">
      <div class="sum-item">
        <div class="sum-label">현재 월 생활비 (추정)</div>
        <div class="sum-val">${sum.total_now.toLocaleString()}원</div>
      </div>
      <div class="sum-item">
        <div class="sum-label">예측 월 생활비</div>
        <div class="sum-val">${sum.total_pred.toLocaleString()}원</div>
      </div>
      <div class="sum-item">
        <div class="sum-label">월 추가 부담</div>
        <div class="sum-val big">+${sum.monthly_extra.toLocaleString()}원</div>
      </div>
      <div class="sum-item">
        <div class="sum-label">연간 추가 부담</div>
        <div class="sum-val" style="color:#F59E0B">+${sum.yearly_extra.toLocaleString()}원</div>
      </div>
    </div>
  `;
}

async function loadScenarioCompareChart() {
  const [r1, r2, r3] = await Promise.all([
    fetch('/api/scenario/local').then(r => r.json()),
    fetch('/api/scenario/hormuz').then(r => r.json()),
    fetch('/api/scenario/fullwar').then(r => r.json()),
  ]);

  const extras = [
    r1.summary.monthly_extra,
    r2.summary.monthly_extra,
    r3.summary.monthly_extra,
  ];

  if (chartScenario) chartScenario.destroy();
  chartScenario = new Chart(document.getElementById('chart-scenario'), {
    type: 'bar',
    data: {
      labels: ['⚡ 국지전', '🚢 호르무즈 봉쇄', '💥 전면전'],
      datasets: [{
        label: '월 추가 생활비 (원)',
        data: extras,
        backgroundColor: [COLORS.yellow + 'CC', COLORS.orange + 'CC', COLORS.red + 'CC'],
        borderColor: [COLORS.yellow, COLORS.orange, COLORS.red],
        borderWidth: 2,
        borderRadius: 6,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      indexAxis: 'y',
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: ctx => `+${ctx.raw.toLocaleString()}원/월` } },
      },
      scales: {
        x: AXIS_OPT.x({ callback: v => `+${v.toLocaleString()}원`, maxTicksLimit: 6 }),
        y: AXIS_OPT.y({ font: { size: 13 } }),
      },
    },
  });
}

/* ══════════════════════════════════════════ */
/* 탭 4: 생활비 계산기                         */
/* ══════════════════════════════════════════ */
let tab4Loaded = false;

/* 유가 상승 시나리오 */
const SIMPLE_SCENARIOS = [
  { key: 'local',   rise: 0.25 },
  { key: 'hormuz',  rise: 0.60 },
  { key: 'fullwar', rise: 1.10 },
];
/* BASE_PRICES 단가 가중 평균 탄성계수 */
const AVG_ELASTICITY = 0.12;

const UNIT_PRICES = {
  '라면':     { id: 'qty-라면',     price: 950,   unit: '봉' },
  '달걀':     { id: 'qty-달걀',     price: 6500,  unit: '판' },
  '우유':     { id: 'qty-우유',     price: 2200,  unit: '개' },
  '식용유':   { id: 'qty-식용유',   price: 4500,  unit: '병' },
  '생수':     { id: 'qty-생수',     price: 1200,  unit: '병' },
  '샴푸':     { id: 'qty-샴푸',     price: 8000,  unit: '개' },
  '택배비':   { id: 'qty-택배비',   price: 2500,  unit: '건' },
  '휘발유':   { id: 'qty-휘발유',   price: 2011,  unit: 'L'  },
  '전기요금': { id: 'qty-전기요금', price: 45000, unit: '월' },
  '가스요금': { id: 'qty-가스요금', price: 55000, unit: '월' },
};
let chartCalc = null;

async function loadTab4() {
  tab4Loaded = true;

  /* 새로고침 후 이전 값 복원 */
  const s = loadState();
  if (s.totalBudget) {
    const inp = document.getElementById('total-budget');
    if (inp) inp.value = s.totalBudget;
  }
  if (s.calcScenario) {
    const sc = document.getElementById('calc-sc');
    if (sc) sc.value = s.calcScenario;
  }
  if (s.quantities) {
    for (const [name, info] of Object.entries(UNIT_PRICES)) {
      const el = document.getElementById(info.id);
      if (el && s.quantities[name] != null) el.value = s.quantities[name];
    }
  }

  calcAll();
  runCalculate();

  /* 총액 입력 */
  document.getElementById('total-budget')?.addEventListener('input', () => {
    const v = parseFloat(document.getElementById('total-budget').value) || 0;
    saveState({ totalBudget: v });
    calcAll();
  });

  /* 수량 / 시나리오 변경 */
  document.querySelectorAll('.input-qty, #calc-sc').forEach(el => {
    el.addEventListener('change', onCalcInput);
    el.addEventListener('input',  onCalcInput);
  });

  document.getElementById('btn-save-calc')?.addEventListener('click', saveCalcResult);
}

function calcAll() {
  const total = parseFloat(document.getElementById('total-budget')?.value ?? 0) || 0;
  for (const sc of SIMPLE_SCENARIOS) {
    const extra  = Math.round(total * sc.rise * AVG_ELASTICITY);
    const pred   = total + extra;
    const yearly = extra * 12;
    document.getElementById(`pred-${sc.key}`).textContent    = `${pred.toLocaleString()}원`;
    document.getElementById(`monthly-${sc.key}`).textContent = `+${extra.toLocaleString()}원`;
    document.getElementById(`yearly-${sc.key}`).textContent  = `+${yearly.toLocaleString()}원`;
  }
}

function onCalcInput() {
  const quantities = {};
  for (const [name, info] of Object.entries(UNIT_PRICES)) {
    const el = document.getElementById(info.id);
    quantities[name] = parseFloat(el?.value ?? 0) || 0;
  }
  saveState({ quantities, calcScenario: document.getElementById('calc-sc')?.value });
  runCalculate();
}

async function saveCalcResult() {
  if (!_authUser) { openModal('form-login'); return; }

  const scenario = document.getElementById('calc-sc').value;
  const budgets  = {};
  for (const [name, info] of Object.entries(UNIT_PRICES)) {
    const el = document.getElementById(info.id);
    budgets[name] = (parseFloat(el?.value ?? 0) || 0) * info.price;
  }

  const btn = document.getElementById('btn-save-calc');
  const msg = document.getElementById('calc-save-msg');
  btn.disabled = true;
  btn.textContent = '저장 중...';
  if (msg) { msg.textContent = ''; msg.classList.add('hidden'); }

  try {
    const token = getToken();
    await fetch('/api/history', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify({ budgets, scenario }),
    });
    btn.disabled = false;
    btn.textContent = '계산 결과 저장하기';
    document.querySelector('[data-tab="tab6"]')?.click();
  } catch (_) {
    if (msg) { msg.textContent = '저장 실패. 다시 시도해주세요.'; msg.classList.remove('hidden'); }
    btn.disabled = false;
    btn.textContent = '계산 결과 저장하기';
  }
}

async function runCalculate() {
  const scenario   = document.getElementById('calc-sc').value;
  const budgets    = {};
  const quantities = {};
  for (const [name, info] of Object.entries(UNIT_PRICES)) {
    const qty = parseFloat(document.getElementById(info.id)?.value ?? 0) || 0;
    quantities[name] = qty;
    budgets[name]    = qty * info.price;
  }

  const res  = await fetch('/api/calculate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ budgets, scenario }),
  });
  const data = await res.json();

  const resultsEl = document.getElementById('calc-results');
  const itemRows  = data.items.map(it => {
    const info      = UNIT_PRICES[it.name];
    const qty       = quantities[it.name] ?? 0;
    const predPrice = info ? Math.round(info.price * (1 + it.rise_pct / 100)) : 0;
    return `
    <div class="result-item-row">
      <span class="ri-name">${it.name}</span>
      <span class="ri-qty">${qty}${info?.unit ?? ''}</span>
      <span class="ri-unit-price">${(info?.price ?? 0).toLocaleString()}원</span>
      <span class="ri-arrow">→</span>
      <span class="ri-pred-unit">${predPrice.toLocaleString()}원</span>
      <span class="ri-extra">+${it.extra.toLocaleString()}원</span>
      <span class="ri-pct">+${it.rise_pct}%</span>
    </div>`;
  }).join('');

  resultsEl.innerHTML = `
    <h3>품목별 예산 변화</h3>
    <div class="result-item-header">
      <span>품목</span><span>수량</span><span>현재단가</span>
      <span></span><span>예측단가</span><span>추가부담</span><span>상승률</span>
    </div>
    ${itemRows}
    <div class="result-divider"></div>
    <div class="result-row">
      <span class="rr-label">현재 월 생활비</span>
      <span class="rr-val">${data.total_now.toLocaleString()}원</span>
    </div>
    <div class="result-row">
      <span class="rr-label">예측 월 지출</span>
      <span class="rr-val">${data.total_pred.toLocaleString()}원</span>
    </div>
    <div class="result-row highlight">
      <span class="rr-label">월 추가 부담</span>
      <span class="rr-val">+${data.monthly_extra.toLocaleString()}원</span>
    </div>
    <div class="result-row yearly">
      <span class="rr-label">연간 추가 부담</span>
      <span class="rr-val">+${data.yearly_extra.toLocaleString()}원</span>
    </div>
  `;

  const items = data.items.filter(it => it.extra > 0);
  if (chartCalc) chartCalc.destroy();
  chartCalc = new Chart(document.getElementById('chart-calc'), {
    type: 'bar',
    data: {
      labels: items.map(it => it.name),
      datasets: [
        {
          label: '현재 예산',
          data:  items.map(it => it.budget_now),
          backgroundColor: COLORS.blue + '44',
          borderColor: COLORS.blue,
          borderWidth: 1,
          borderRadius: 4,
        },
        {
          label: '추가 부담',
          data:  items.map(it => it.extra),
          backgroundColor: COLORS.red + 'BB',
          borderColor: COLORS.red,
          borderWidth: 1,
          borderRadius: 4,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      indexAxis: 'y',
      plugins: {
        legend: {
          display: true,
          position: 'top',
          labels: { color: TICK_COLOR, font: { size: 11 }, boxWidth: 12, padding: 10 },
        },
        tooltip: {
          callbacks: {
            label: ctx => ctx.dataset.label === '추가 부담'
              ? `+${ctx.raw.toLocaleString()}원`
              : `${ctx.raw.toLocaleString()}원`,
          },
        },
      },
      scales: {
        x: { ...AXIS_OPT.x({ callback: v => `${v.toLocaleString()}원`, maxTicksLimit: 6 }), stacked: true },
        y: { ...AXIS_OPT.y({ font: { size: 12 } }), stacked: true },
      },
    },
  });
}

/* ══════════════════════════════════════════
   탭 6: 마이페이지
══════════════════════════════════════════ */
let tab6Loaded = false;

const SC_NAMES = {
  local:   '⚡ 국지전',
  hormuz:  '🚢 호르무즈 봉쇄',
  fullwar: '💥 전면전',
};

async function loadTab6() {
  if (!_authUser) return;
  tab6Loaded = true;

  const token   = getToken();
  const headers = { Authorization: `Bearer ${token}` };

  /* 내 정보 */
  const meRes  = await fetch('/api/auth/me', { headers });
  const me     = await meRes.json();
  const initial = (me.name || '?')[0].toUpperCase();
  const since   = me.created_at?.slice(0, 10) ?? '—';

  document.getElementById('profile-card').innerHTML = `
    <div class="profile-avatar">${initial}</div>
    <div class="profile-info">
      <div class="profile-name">${me.name}</div>
      <div class="profile-email">${me.email}</div>
      <div class="profile-since">가입일 ${since}</div>
    </div>
  `;

  /* 계산 기록 */
  await refreshHistory(headers);
}

async function refreshHistory(headers) {
  if (!headers) {
    const token = getToken();
    headers = { Authorization: `Bearer ${token}` };
  }

  const res   = await fetch('/api/history', { headers });
  const data  = await res.json();
  const items = data.items ?? [];

  const badge = document.getElementById('history-count');
  if (badge) badge.textContent = `${items.length}건`;

  const el = document.getElementById('history-list');
  if (!el) return;

  if (!items.length) {
    el.innerHTML = `
      <div class="history-empty">
        <div style="font-size:32px">📋</div>
        <p>아직 저장된 기록이 없습니다.<br>생활비 계산기에서 "계산 결과 저장하기" 버튼을 눌러 저장하세요.</p>
      </div>`;
    return;
  }

  el.innerHTML = items.map(item => {
    const scClass = item.scenario === 'hormuz' ? 'hormuz'
                  : item.scenario === 'fullwar' ? 'fullwar' : '';
    const date    = (item.recorded_at ?? '').slice(0, 16);
    return `
      <div class="history-item">
        <span class="hi-date">${date}</span>
        <span class="hi-scenario ${scClass}">${SC_NAMES[item.scenario] ?? item.scenario}</span>
        <div class="hi-col">
          <div class="hi-label">현재 생활비</div>
          <div class="hi-val">${(item.total_now ?? 0).toLocaleString()}원</div>
        </div>
        <div class="hi-col">
          <div class="hi-label">예측 생활비</div>
          <div class="hi-val">${(item.total_pred ?? 0).toLocaleString()}원</div>
        </div>
        <div class="hi-col">
          <div class="hi-label">추가 부담</div>
          <div class="hi-val hi-extra">+${(item.monthly_extra ?? 0).toLocaleString()}원</div>
        </div>
        <button class="btn-delete" onclick="deleteHistory(${item.id})">삭제</button>
      </div>`;
  }).join('');
}

async function deleteHistory(id) {
  const token = getToken();
  await fetch(`/api/history/${id}`, {
    method: 'DELETE',
    headers: { Authorization: `Bearer ${token}` },
  });
  await refreshHistory();
}


/* ══════════════════════════════════════════ */
/* 초기화: 토큰으로 자동 로그인 후 화면은       */
/* showApp() 호출 시점에 탭1을 lazy 로드       */
/* ══════════════════════════════════════════ */
