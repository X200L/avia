'use strict';

const state = {
  bootstrap: null, selectedRoute: null, selectedDate: null, price: 0,
  simulation: null, authMode: 'login',
  csrf: null, simReq: 0,
};
const el = (id) => document.getElementById(id);
const rub = (n) => `${new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 }).format(n)} ₽`;
const num = (n) => new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 }).format(n);
const shortRub = (n) => `${new Intl.NumberFormat('ru-RU', { maximumFractionDigits: Math.abs(n) >= 1e6 ? 2 : 1 }).format(n / (Math.abs(n) >= 1e6 ? 1e6 : 1e3))} ${Math.abs(n) >= 1e6 ? 'млн' : 'тыс.'} ₽`;
const dateDisplay = (dateString) => new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'long' }).format(new Date(`${dateString}T12:00:00`));
let updateTimer;
let toastTimer;

function toast(message, isError = false) {
  const node = el('toast');
  node.textContent = message;
  node.classList.toggle('error', isError);
  node.classList.add('visible');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => node.classList.remove('visible'), 3700);
}

async function api(url, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (state.csrf && options.method && options.method !== 'GET') headers['X-CSRF-Token'] = state.csrf;
  const response = await fetch(url, { ...options, headers, credentials: 'same-origin' });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || `Ошибка сервера (${response.status})`);
  return data;
}

function availableRoutes() {
  return state.bootstrap?.routes || [];
}
function routeData() {
  return availableRoutes().find((r) => r.route === state.selectedRoute);
}
function initRouteSelects() {
  const routes = availableRoutes();
  const origins = [...new Set(routes.map((r) => r.origin))];
  const from = el('originSelect');
  from.replaceChildren(...origins.map((x) => new Option(x, x)));
  const selected = routeData() || routes[0];
  if (!selected) return;
  state.selectedRoute = selected.route;
  from.value = selected.origin;
  refreshDestinationSelect();
}
function refreshDestinationSelect() {
  const origin = el('originSelect').value;
  const filtered = availableRoutes().filter((r) => r.origin === origin);
  const dest = el('destinationSelect');
  dest.replaceChildren(...filtered.map((r) => new Option(r.destination, r.route)));
  if (!filtered.some((r) => r.route === state.selectedRoute)) state.selectedRoute = filtered[0]?.route || null;
  dest.value = state.selectedRoute;
}
function updatePriceControl(reset = true) {
  const route = routeData();
  if (!route) return;
  if (reset) state.price = route.basePrice;
  state.price = Math.max(route.priceMin, Math.min(route.priceMax, state.price));
  const slider = el('priceSlider');
  const input = el('priceInput');
  slider.min = route.priceMin;
  slider.max = route.priceMax;
  slider.step = 100;
  slider.value = state.price;
  input.min = route.priceMin;
  input.max = route.priceMax;
  input.value = state.price;
  el('minPrice').textContent = rub(route.priceMin);
  el('maxPrice').textContent = rub(route.priceMax);
  renderDelta();
}
function renderDelta() {
  const r = routeData();
  if (!r) return;
  const delta = state.price - r.basePrice;
  const node = el('priceDelta');
  node.classList.toggle('negative', delta < 0);
  node.textContent = delta === 0 ? 'Базовая цена' : `${delta > 0 ? '+' : '−'}${rub(Math.abs(delta))} от базы`;
  const fraction = (state.price - r.priceMin) / (r.priceMax - r.priceMin || 1);
  el('priceSlider').style.background = `linear-gradient(to right, #3fb9a4 0%, #3fb9a4 ${fraction * 100}%, #e1ece4 ${fraction * 100}%, #e1ece4 100%)`;
}

function setPrice(price, applyImmediately = false) {
  const route = routeData();
  if (!route || !Number.isFinite(price)) return;
  state.price = Math.max(route.priceMin, Math.min(route.priceMax, price));
  el('priceSlider').value = state.price;
  el('priceInput').value = state.price;
  renderDelta();
  clearTimeout(updateTimer);
  if (applyImmediately) refreshForecast();
  else updateTimer = setTimeout(refreshForecast, 220);
}

async function loadBootstrap(keepSelection = false) {
  const previousRoute = keepSelection ? state.selectedRoute : null;
  const previousDate = keepSelection ? state.selectedDate : null;
  const bootstrap = await api('/api/bootstrap');
  state.bootstrap = bootstrap;
  state.csrf = bootstrap.csrf;
  state.selectedRoute = bootstrap.routes.some((r) => r.route === previousRoute) ? previousRoute : bootstrap.routes[0]?.route;
  state.selectedDate = bootstrap.dates.includes(previousDate) ? previousDate : bootstrap.dates[0];
  if (el('originSelect')) {
    initRouteSelects();
    el('flightDate').min = bootstrap.dates[0] || '';
    el('flightDate').max = bootstrap.dates[bootstrap.dates.length - 1] || '';
    el('flightDate').value = state.selectedDate || '';
    updatePriceControl(true);
  } else state.price = routeData()?.basePrice || 0;
  if (state.selectedRoute) await refreshForecast();
  renderMode();
  if (el('scenarioLargeChart') && state.simulation) renderScenariosPage(state.simulation);
}
function renderMode() {
  const { user } = state.bootstrap;
  el('userLabel').textContent = user ? user.name : 'Гостевой режим';
  el('authButton').textContent = user ? 'Выйти' : 'Войти';
}
async function refreshForecast() {
  const route = routeData();
  if (!route || !state.selectedDate) return;
  const simReq = ++state.simReq;
  const params = new URLSearchParams({ route: route.route, date: state.selectedDate, price: String(state.price) });
  const trendParams = new URLSearchParams({ route: route.route, price: String(state.price) });
  try {
    const [forecast, trend] = await Promise.all([
      api(`/api/simulate?${params}`), api(`/api/trends?${trendParams}`),
    ]);
    if (simReq !== state.simReq) return;
    state.simulation = forecast;
    if (el('medianWilling')) renderSimulation(forecast);
    if (el('trendChart')) renderTrend(trend);
    if (el('scenarioLargeChart')) renderScenariosPage(forecast);
  } catch (error) {
    if (simReq === state.simReq) toast(error.message, true);
  }
}
function renderSimulation(data) {
  const med = data.median;
  el('medianWilling').textContent = num(med.willing);
  el('confidenceText').textContent = `${num(data.interval[0])}-${num(data.interval[1])}`;
  el('soldValue').textContent = num(med.sold);
  el('availableValue').textContent = num(med.available);
  el('seatsTotal').textContent = `${num(data.seats)}`;
  el('soldShare').textContent = data.seats > 0 ? `${Math.round(med.sold / data.seats * 100)}%` : '0%';
  el('revenueValue').textContent = shortRub(med.revenue);
  el('profitValue').textContent = shortRub(med.profit);
  el('recommendedPrice').textContent = rub(data.recommended.price);
  el('capacityInsight').textContent = med.willing > data.seats
    ? `Спрос превышает вместимость на ${num(med.willing - data.seats)} человек. Не все желающие смогут купить билет.`
    : `Мест достаточно: ожидаемые продажи ${num(med.sold)} из ${num(data.seats)}. Свободно ${num(med.available)}.`;
  renderDistributionChart('distributionChart', data, 670, 221);
  renderScenarioTable(data);
}
function quantileCell(quantile) {
  return `<td>${quantile}${quantile === '0.5' ? ' · медиана' : ''}</td>`;
}
function renderScenarioTable(data) {
  el('scenarioTableBody').innerHTML = data.scenarios.map((r) => `
    <tr class="${r.q === '0.5' ? 'median-row' : ''}">${quantileCell(r.q)}
      <td>${num(r.willing)}</td><td>${num(r.sold)}</td><td>${num(r.available)}</td>
      <td>${rub(r.recommendedPrice)}</td><td>${shortRub(r.profit)}</td></tr>`).join('');
}
function renderScenariosPage(data) {
  el('lowPreview').textContent = num(data.scenarios[0].willing);
  el('midPreview').textContent = num(data.median.willing);
  el('highPreview').textContent = num(data.scenarios[8].willing);
  renderDistributionChart('scenarioLargeChart', data, 920, 282);
  el('scenarioCompareBody').innerHTML = data.scenarios.map((r) => `
    <tr class="${r.q === '0.5' ? 'median-row' : ''}">${quantileCell(r.q)}
      <td>${num(r.baseDemand)}</td><td>${num(r.willing)}</td>
      <td>${rub(r.recommendedPrice)}</td><td>${shortRub(r.profit)}</td></tr>`).join('');
}
const coord = (value) => Number(value).toFixed(2);
function renderDistributionChart(elementId, data, width, height) {
  const pts = data.scenarios;
  const l = 51, r = 20, t = 16, b = 35;
  const chartW = width - l - r, chartH = height - t - b;
  const maxY = Math.max(1, data.seats, ...pts.map((p) => p.willing)) * 1.13;
  const x = (i) => l + (chartW * i / (pts.length - 1));
  const y = (v) => t + chartH * (1 - v / maxY);
  const line = pts.map((p, i) => `${i ? 'L' : 'M'}${coord(x(i))},${coord(y(p.willing))}`).join(' ');
  const area = `${line} L${coord(x(8))},${coord(y(0))} L${coord(x(0))},${coord(y(0))} Z`;
  const grid = [0, .25, .5, .75, 1].map((k) => {
    const v = maxY * k, yy = y(v);
    return `<line x1="${l}" x2="${width-r}" y1="${coord(yy)}" y2="${coord(yy)}" stroke="#edf2ed" stroke-width="1"/>
      <text x="${l-12}" y="${coord(yy+3)}" font-size="10" text-anchor="end" fill="#a3b1a7">${num(v)}</text>`;
  }).join('');
  const labels = pts.map((p, i) => `<text x="${coord(x(i))}" y="${height-10}" font-size="10" text-anchor="middle" fill="${i === 4 ? '#208e78' : '#a0ada5'}" font-weight="${i === 4 ? 800 : 500}">${p.q}</text>`).join('');
  const circles = pts.map((p, i) => `<circle cx="${coord(x(i))}" cy="${coord(y(p.willing))}" r="${i===4 ? 5.5 : 3.2}" fill="${i===4 ? '#219a7b' : '#50c7ae'}" stroke="#fff" stroke-width="${i===4 ? 2.5 : 1.5}"><title>Квантиль ${p.q}: спрос ${num(p.willing)}; продадим ${num(p.sold)}</title></circle>`).join('');
  const seatLine = y(data.seats);
  const markup = `<svg viewBox="0 0 ${width} ${height}" role="presentation" xmlns="http://www.w3.org/2000/svg"><defs><linearGradient id="fill-${elementId}" x1="0" y1="0" x2="0" y2="1"><stop stop-color="#4ec9b2" stop-opacity=".27"/><stop offset="1" stop-color="#4ec9b2" stop-opacity=".015"/></linearGradient></defs>${grid}
    <line x1="${l}" x2="${width-r}" y1="${coord(seatLine)}" y2="${coord(seatLine)}" stroke="#93afa3" stroke-dasharray="5 5" stroke-width="1.5"/>
    <path d="${area}" fill="url(#fill-${elementId})"/><path d="${line}" fill="none" stroke="#35b89e" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>
    <line x1="${coord(x(4))}" x2="${coord(x(4))}" y1="${coord(y(pts[4].willing))}" y2="${coord(y(0))}" stroke="#56bca3" stroke-dasharray="3 4" opacity=".5"/>
    ${circles}${labels}</svg>`;
  el(elementId).innerHTML = markup;
}
function renderTrend(data) {
  const pts = data.points;
  if (!pts.length) return;
  const width = 1120, height = 177, l = 48, r = 15, t = 13, b = 28;
  const plotW = width - l - r, plotH = height - t - b;
  const maxY = Math.max(1, ...pts.map((p) => p.seats), ...pts.map((p) => p.sold)) * 1.08;
  const x = (i) => l + i * plotW / Math.max(1, pts.length - 1);
  const y = (v) => t + (1 - v / maxY) * plotH;
  const pointsLine = (key) => pts.map((p, i) => `${i ? 'L' : 'M'}${coord(x(i))},${coord(y(p[key]))}`).join(' ');
  const salesLine = pointsLine('sold');
  const area = `${salesLine} L${coord(x(pts.length-1))},${coord(y(0))} L${coord(x(0))},${coord(y(0))}Z`;
  const idx = pts.findIndex((p) => p.date === state.selectedDate);
  const selected = idx >= 0 ? `<line x1="${coord(x(idx))}" x2="${coord(x(idx))}" y1="${t}" y2="${coord(y(0))}" stroke="#7fbfac" stroke-dasharray="4 5"/><circle cx="${coord(x(idx))}" cy="${coord(y(pts[idx].sold))}" r="5" fill="#168c75" stroke="#fff" stroke-width="2"/>` : '';
  const grid = [0,.5,1].map((k) => `<line x1="${l}" x2="${width-r}" y1="${coord(y(maxY*k))}" y2="${coord(y(maxY*k))}" stroke="#eff3ef"/><text x="${l-12}" y="${coord(y(maxY*k)+3)}" text-anchor="end" font-size="10" fill="#a5b2aa">${num(maxY*k)}</text>`).join('');
  const indexes = [...new Set([0, Math.floor((pts.length - 1)/3), Math.floor((pts.length - 1)*2/3), pts.length-1])];
  const ticks = indexes.map((i) => `<text x="${coord(x(i))}" y="${height-8}" text-anchor="${i===0 ? 'start':i===pts.length-1?'end':'middle'}" font-size="10" fill="#a3b1a7">${dateDisplay(pts[i].date)}</text>`).join('');
  el('trendChart').innerHTML = `<svg viewBox="0 0 ${width} ${height}" xmlns="http://www.w3.org/2000/svg" role="presentation"><defs><linearGradient id="trend-fill" x1="0" y1="0" x2="0" y2="1"><stop stop-color="#44c3ab" stop-opacity=".23"/><stop offset="1" stop-color="#44c3ab" stop-opacity="0"/></linearGradient></defs>${grid}
    <path d="${area}" fill="url(#trend-fill)"/><path d="${pointsLine('seats')}" fill="none" stroke="#b9cbbd" stroke-width="2" stroke-dasharray="5 4"/>
    <path d="${salesLine}" fill="none" stroke="#37bba2" stroke-width="3" stroke-linejoin="round" stroke-linecap="round"/>${selected}${ticks}</svg>`;
}

function openAuth(mode = 'login') {
  setAuthMode(mode);
  el('authDialog').showModal();
}
function setAuthMode(mode) {
  state.authMode = mode;
  document.querySelectorAll('[data-auth-mode]').forEach((b) => b.classList.toggle('active', b.dataset.authMode === mode));
  el('nameField').hidden = mode !== 'register';
  el('authName').required = mode === 'register';
  el('authPassword').autocomplete = mode === 'register' ? 'new-password' : 'current-password';
  el('authSubmit').textContent = mode === 'register' ? 'Создать аккаунт ↗' : 'Войти ↗';
}

async function submitAuth(event) {
  event.preventDefault();
  const button = el('authSubmit');
  button.disabled = true;
  const data = { email: el('authEmail').value, password: el('authPassword').value };
  if (state.authMode === 'register') data.name = el('authName').value;
  try {
    const res = await api(`/api/auth/${state.authMode}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data),
    });
    state.csrf = res.csrf;
    el('authDialog').close();
    el('authPassword').value = '';
    await loadBootstrap(true);
    toast(state.authMode === 'register' ? 'Аккаунт создан' : 'Вы вошли в аккаунт');
  } catch (error) { toast(error.message, true); }
  finally { button.disabled = false; }
}
async function toggleAuth() {
  if (!state.bootstrap?.user) return openAuth();
  try {
    const response = await api('/api/auth/logout', { method: 'POST' });
    state.csrf = response.csrf;
    await loadBootstrap(false);
    toast('Вы вышли из аккаунта');
  } catch (error) { toast(error.message, true); }
}

function attachEvents() {
  el('authButton').addEventListener('click', toggleAuth);
  el('closeAuth').addEventListener('click', () => el('authDialog').close());
  el('authForm').addEventListener('submit', submitAuth);
  document.querySelectorAll('[data-auth-mode]').forEach((node) => node.addEventListener('click', () => setAuthMode(node.dataset.authMode)));
  if (el('originSelect')) {
    el('originSelect').addEventListener('change', () => { refreshDestinationSelect(); updatePriceControl(); refreshForecast(); });
    el('destinationSelect').addEventListener('change', () => { state.selectedRoute = el('destinationSelect').value; updatePriceControl(); refreshForecast(); });
    el('flightDate').addEventListener('change', () => {
      const date = el('flightDate').value;
      if (!state.bootstrap.dates.includes(date)) { el('flightDate').value = state.selectedDate; return toast('На эту дату прогноз не загружен', true); }
      state.selectedDate = date;
      refreshForecast();
    });
    el('priceSlider').addEventListener('input', () => setPrice(Number(el('priceSlider').value)));
    el('priceInput').addEventListener('change', () => setPrice(Number(el('priceInput').value), true));
    el('recalculateButton').addEventListener('click', refreshForecast);
    el('resetPriceButton').addEventListener('click', () => setPrice(routeData()?.basePrice || 0, true));
    el('applyRecommended').addEventListener('click', () => {
      if (state.simulation) setPrice(state.simulation.recommended.price, true);
    });
  }
}

window.addEventListener('DOMContentLoaded', async () => {
  attachEvents();
  try { await loadBootstrap(); }
  catch (error) {
    toast(error.message, true);
    if (el('distributionChart')) el('distributionChart').textContent = 'Данные недоступны';
  }
});
