const API_PATH = '/api/metrics';
const ACCESS_KEY_NAME = 'ankita-admin-access';
const REFRESH_INTERVAL_MS = 60_000;
const ANALYTICS_WINDOW_DAYS = 30;
const NUMBER_FORMAT = new Intl.NumberFormat('en');
const UTC_DATE_FORMAT = new Intl.DateTimeFormat('en', { month: 'short', day: 'numeric', timeZone: 'UTC' });
const UTC_DATETIME_FORMAT = new Intl.DateTimeFormat('en', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', timeZone: 'UTC' });
const SVG_NAMESPACE = 'http://www.w3.org/2000/svg';

const METRIC_CARDS = [
  { key: 'totalUsers', label: 'Total opted-in', detail: 'All-time installs', primary: true },
  { key: 'activeToday', label: 'Active today', detail: 'Daily active · UTC' },
  { key: 'active7Days', label: 'Active this week', detail: 'Rolling 7 days' },
  { key: 'active30Days', label: 'Active this month', detail: `Rolling ${ANALYTICS_WINDOW_DAYS} days` },
  { key: 'newUsers30Days', label: 'New this month', detail: `First seen in ${ANALYTICS_WINDOW_DAYS} days` },
  { key: 'returningUsers30Days', label: 'Returning', detail: `Seen before this ${ANALYTICS_WINDOW_DAYS}-day window` },
];

const COPY = Object.freeze({
  accessRequired: 'Enter your dashboard key to continue.',
  accessDenied: 'That key did not work. Check it and try again.',
  loadFailed: 'Could not reach the usage data. Try again in a moment.',
  setupMissing: 'The dashboard is not connected yet. Check its private server settings.',
  unknownError: 'The dashboard could not load. Try refreshing.',
  empty: 'No opted-in installs yet. When people choose to share, they’ll appear here.',
  peopleCount: 'recent anonymous installs · active in the past 30 days',
  updated: 'Updated',
});

const elements = {
  accessPanel: document.querySelector('#access-panel'),
  accessForm: document.querySelector('#access-form'),
  accessKey: document.querySelector('#access-key'),
  accessError: document.querySelector('#access-error'),
  dashboard: document.querySelector('#dashboard'),
  connection: document.querySelector('#connection-label'),
  updated: document.querySelector('#updated-label'),
  metrics: document.querySelector('#metric-grid'),
  chart: document.querySelector('#chart'),
  platforms: document.querySelector('#platform-list'),
  versions: document.querySelector('#version-list'),
  people: document.querySelector('#people-table'),
  empty: document.querySelector('#empty-state'),
  communityCount: document.querySelector('#community-count'),
  refresh: document.querySelector('#refresh-button'),
  lock: document.querySelector('#lock-button'),
  errorBanner: document.querySelector('#error-banner'),
};

let activeToken = sessionStorage.getItem(ACCESS_KEY_NAME) || '';
let refreshing = false;

function formattedNumber(value) {
  return NUMBER_FORMAT.format(Number.isFinite(Number(value)) ? Number(value) : 0);
}

function utcDate(value) {
  if (!value) return '—';
  const date = new Date(`${value}T00:00:00Z`);
  return Number.isNaN(date.valueOf()) ? '—' : UTC_DATE_FORMAT.format(date);
}

function utcDateTime(value) {
  if (!value) return '—';
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? '—' : `${UTC_DATETIME_FORMAT.format(date)} UTC`;
}

function setAuthenticated(isAuthenticated) {
  elements.accessPanel.hidden = isAuthenticated;
  elements.dashboard.hidden = !isAuthenticated;
  elements.connection.textContent = isAuthenticated ? 'Supabase · connected' : 'Private workspace';
}

function renderMetrics(summary = {}) {
  elements.metrics.replaceChildren();
  for (const metric of METRIC_CARDS) {
    const card = document.createElement('article');
    card.className = `metric-card${metric.primary ? ' primary' : ''}`;
    const label = document.createElement('div');
    label.className = 'metric-label';
    label.textContent = metric.label;
    const value = document.createElement('div');
    value.className = 'metric-value';
    value.textContent = formattedNumber(summary[metric.key]);
    const detail = document.createElement('div');
    detail.className = 'metric-detail';
    detail.textContent = metric.detail;
    card.append(label, value, detail);
    elements.metrics.append(card);
  }
}

function svgElement(tag, attributes) {
  const node = document.createElementNS(SVG_NAMESPACE, tag);
  for (const [name, value] of Object.entries(attributes)) node.setAttribute(name, String(value));
  return node;
}

function renderChart(daily = []) {
  const points = Array.isArray(daily) ? daily : [];
  const width = 800;
  const height = 224;
  const inset = { top: 12, right: 4, bottom: 10, left: 4 };
  const values = points.map(point => Number(point.users) || 0);
  const peak = Math.max(1, ...values);
  const innerWidth = width - inset.left - inset.right;
  const innerHeight = height - inset.top - inset.bottom;
  const svg = svgElement('svg', { viewBox: `0 0 ${width} ${height}`, preserveAspectRatio: 'none', role: 'presentation' });

  for (let row = 0; row <= 3; row += 1) {
    const y = inset.top + (innerHeight * row) / 3;
    svg.append(svgElement('line', { x1: inset.left, x2: width - inset.right, y1: y, y2: y, stroke: '#e7e5dc', 'stroke-width': 1 }));
  }

  if (!points.length) {
    elements.chart.replaceChildren(svg);
    return;
  }

  const coords = points.map((point, index) => {
    const x = inset.left + (points.length === 1 ? innerWidth / 2 : (innerWidth * index) / (points.length - 1));
    const y = inset.top + innerHeight - ((Number(point.users) || 0) / peak) * innerHeight;
    return [x, y];
  });
  const pathData = coords.map(([x, y], index) => `${index ? 'L' : 'M'} ${x.toFixed(2)} ${y.toFixed(2)}`).join(' ');
  const areaData = `${pathData} L ${coords.at(-1)[0].toFixed(2)} ${height - inset.bottom} L ${coords[0][0].toFixed(2)} ${height - inset.bottom} Z`;
  svg.append(svgElement('path', { d: areaData, fill: '#dfe8dc', opacity: '.72' }));
  svg.append(svgElement('path', { d: pathData, fill: 'none', stroke: '#335f4a', 'stroke-width': 2.4, 'stroke-linecap': 'round', 'stroke-linejoin': 'round', vectorEffect: 'non-scaling-stroke' }));
  const [lastX, lastY] = coords.at(-1);
  svg.append(svgElement('circle', { cx: lastX, cy: lastY, r: 4, fill: '#df805d', stroke: '#fbfaf6', 'stroke-width': 2, vectorEffect: 'non-scaling-stroke' }));
  elements.chart.replaceChildren(svg);
}

function renderMix(target, rows = []) {
  target.replaceChildren();
  const data = Array.isArray(rows) ? rows : [];
  const maximum = Math.max(1, ...data.map(row => Number(row.users) || 0));
  if (!data.length) {
    const empty = document.createElement('p');
    empty.className = 'metric-detail';
    empty.textContent = 'No data in this period';
    target.append(empty);
    return;
  }
  for (const row of data) {
    const item = document.createElement('div');
    item.className = 'mix-row';
    const name = document.createElement('span');
    name.className = 'mix-name';
    name.textContent = String(row.name || 'Other');
    const track = document.createElement('span');
    track.className = 'mix-track';
    const fill = document.createElement('span');
    fill.className = 'mix-fill';
    fill.style.display = 'block';
    fill.style.width = `${Math.min(100, ((Number(row.users) || 0) / maximum) * 100)}%`;
    track.append(fill);
    const count = document.createElement('span');
    count.className = 'mix-count';
    count.textContent = formattedNumber(row.users);
    item.append(name, track, count);
    target.append(item);
  }
}

function renderPeople(rows = [], activeUsers = 0) {
  elements.people.replaceChildren();
  const users = Array.isArray(rows) ? rows : [];
  elements.communityCount.textContent = `Showing ${formattedNumber(users.length)} of ${formattedNumber(activeUsers)} ${COPY.peopleCount}`;
  elements.empty.hidden = users.length > 0;
  document.querySelector('.table-wrap').hidden = users.length === 0;
  for (const user of users) {
    const row = document.createElement('tr');
    const idCell = document.createElement('td');
    const tag = document.createElement('span');
    tag.className = 'install-tag';
    const orb = document.createElement('span');
    orb.className = 'install-orb';
    const id = document.createElement('span');
    id.textContent = `#${String(user.id || '').slice(0, 10)}`;
    tag.append(orb, id);
    idCell.append(tag);
    const values = [user.platform, user.version, utcDate(user.firstSeen), utcDate(user.lastSeen)];
    row.append(idCell);
    for (const item of values) {
      const cell = document.createElement('td');
      cell.textContent = item || '—';
      row.append(cell);
    }
    elements.people.append(row);
  }
}

function errorMessage(status, payload) {
  if (status === 401) return COPY.accessDenied;
  if (payload?.error === 'dashboard_not_configured') return COPY.setupMissing;
  return COPY.loadFailed;
}

async function loadMetrics(token) {
  if (refreshing) return;
  refreshing = true;
  elements.refresh.disabled = true;
  elements.errorBanner.hidden = true;
  elements.accessError.textContent = '';
  try {
    const response = await fetch(API_PATH, { headers: { Authorization: `Bearer ${token}` }, cache: 'no-store' });
    const payload = await response.json().catch(() => ({}));
    if (response.status === 401) {
      sessionStorage.removeItem(ACCESS_KEY_NAME);
      activeToken = '';
      setAuthenticated(false);
      elements.accessError.textContent = errorMessage(response.status, payload);
      return;
    }
    setAuthenticated(true);
    if (!response.ok) {
      elements.errorBanner.textContent = errorMessage(response.status, payload);
      elements.errorBanner.hidden = false;
      return;
    }
    renderMetrics(payload.summary);
    renderChart(payload.daily);
    renderMix(elements.platforms, payload.platforms);
    renderMix(elements.versions, payload.versions);
    renderPeople(payload.recentUsers, payload.summary?.active30Days);
    elements.updated.textContent = `${COPY.updated} ${utcDateTime(payload.updatedAt)}`;
  } catch {
    elements.errorBanner.textContent = COPY.unknownError;
    elements.errorBanner.hidden = false;
  } finally {
    refreshing = false;
    elements.refresh.disabled = false;
  }
}

elements.accessForm.addEventListener('submit', event => {
  event.preventDefault();
  const token = elements.accessKey.value.trim();
  if (!token) {
    elements.accessError.textContent = COPY.accessRequired;
    return;
  }
  activeToken = token;
  sessionStorage.setItem(ACCESS_KEY_NAME, token);
  elements.accessKey.value = '';
  setAuthenticated(true);
  void loadMetrics(activeToken);
});

elements.refresh.addEventListener('click', () => void loadMetrics(activeToken));
elements.lock.addEventListener('click', () => {
  sessionStorage.removeItem(ACCESS_KEY_NAME);
  activeToken = '';
  setAuthenticated(false);
  elements.errorBanner.hidden = true;
});

if (activeToken) {
  setAuthenticated(true);
  void loadMetrics(activeToken);
}

// Refresh in the active tab so the owner sees fresh counts without reloading.
window.setInterval(() => {
  if (activeToken && !document.hidden) void loadMetrics(activeToken);
}, REFRESH_INTERVAL_MS);
