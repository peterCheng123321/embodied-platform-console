const API = {
  datasets: '/api/embodied-platform/datasets',
  episodes: '/api/embodied-platform/episodes',
  imports: '/api/embodied-platform/imports',
  annotation: '/api/embodied-platform/annotation-tasks',
  training: '/api/embodied-platform/training-jobs',
  models: '/api/embodied-platform/models',
  simulation: '/api/embodied-platform/simulation-jobs',
  deployment: '/api/embodied-platform/deployments',
  learning: '/api/embodied-platform/learning-queue',
  monitoring: '/api/embodied-platform/monitoring/overview',
  audit: '/api/embodied-platform/audit-events',
  system: '/api/embodied-platform/system/settings',
  session: '/api/embodied-platform/session',
};

const MODULE_IDS = [
  'data-management',
  'annotation',
  'training',
  'models',
  'simulation',
  'deployment',
  'learning',
  'monitoring',
  'audit',
  'system',
];

const state = {
  data: null,
  live: false,
  ready: false,
  degraded: false,
  liveFailures: [],
  demoSavedAt: null,
};

const API_READ_TIMEOUT_MS = 8000;
const API_WRITE_TIMEOUT_MS = 15000;
const DEMO_STATE_VERSION = 3;
const DEMO_STATE_KEY = `embodied-platform.demo-state.v${DEMO_STATE_VERSION}`;
const DEMO_STATE_PREFIX = 'embodied-platform.demo-state.';
const DEMO_STATE_TTL_MS = 7 * 24 * 60 * 60 * 1000;
const COLLECTIONS = [
  'datasets',
  'episodes',
  'imports',
  'annotation_tasks',
  'training_jobs',
  'models',
  'simulation_jobs',
  'deployments',
  'learning_queue',
  'audit_events',
];

const LIVE_ENDPOINTS = [
  { target: 'datasets', label: '数据集', url: API.datasets, fallback: [] },
  { target: 'episodes', label: '片段', url: API.episodes, fallback: [] },
  { target: 'imports', label: '导入任务', url: API.imports, fallback: [] },
  { target: 'annotation_tasks', label: '标注任务', url: API.annotation, fallback: [] },
  { target: 'training_jobs', label: '训练任务', url: API.training, fallback: [] },
  { target: 'models', label: '模型', url: API.models, fallback: [] },
  { target: 'simulation_jobs', label: '仿真任务', url: API.simulation, fallback: [] },
  { target: 'deployments', label: '部署任务', url: API.deployment, fallback: [] },
  { target: 'learning_queue', label: '学习队列', url: API.learning, fallback: [] },
  { target: 'monitoring', label: '监控', url: API.monitoring, fallback: {} },
  { target: 'audit_events', label: '审计', url: API.audit, fallback: [] },
  { target: 'system_settings', label: '系统设置', url: API.system, fallback: null },
];

const NON_WRITE_ACTIONS = new Set(['refresh-monitoring', 'reset-demo']);
const WRITE_ROLES = ['admin', 'data_manager', 'annotator', 'reviewer', 'ml_engineer', 'deployment_operator', 'operator'];
const ACTION_ROLES = {
  'create-dataset': ['admin', 'data_manager', 'operator'],
  'create-episode': ['admin', 'data_manager', 'operator'],
  'start-import': ['admin', 'data_manager', 'operator'],
  'save-annotation': ['admin', 'annotator', 'reviewer', 'operator'],
  'start-training': ['admin', 'ml_engineer', 'operator'],
  'activate-model': ['admin', 'ml_engineer', 'operator'],
  'start-simulation': ['admin', 'ml_engineer', 'operator'],
  'create-deployment': ['admin', 'deployment_operator', 'operator'],
  'enqueue-learning': ['admin', 'annotator', 'reviewer', 'operator'],
  'write-audit': WRITE_ROLES,
  'save-settings': ['admin'],
};

const LABELS = {
  queued: '排队中',
  running: '运行中',
  succeeded: '已完成',
  failed: '失败',
  cancelled: '已取消',
  review: '待复核',
  open: '待处理',
  accepted: '已通过',
  rework: '返工',
  active: '已激活',
  current: '当前',
  set: '已设置',
  high: '高',
  normal: '普通',
  urgent: '紧急',
  low: '低',
  api: 'API',
  fixture: '演示数据',
  vision_language_action: '视觉-语言-动作',
  multimodal: '多模态',
  vision: '视觉',
  action: '动作',
  trajectory_segment: '轨迹分段',
  success_check: '成功检查',
  language_grounding: '语言对齐',
  safety_event: '安全事件',
  lora: 'LoRA',
  qlora: 'QLoRA',
  distillation: '蒸馏',
  full: '全量训练',
  dataset_count: '数据集数',
  episode_count: '片段数',
  queued_jobs: '排队任务',
  running_jobs: '运行任务',
  active_model_id: '当前模型',
  active_deployments: '活跃部署',
  open_learning_items: '待学习样本',
  recent_audit_events: '近期审计事件',
  sim_success_rate: '仿真成功率',
  retention_days: '保留天数',
  offline_mode: '离线模式',
  active_robot_fleet: '机器人集群',
  approval_required_for_edge: '边缘审批',
};

class FieldValidationError extends Error {
  constructor(fieldId, message) {
    super(message);
    this.name = 'FieldValidationError';
    this.fieldId = fieldId;
  }
}

function value(id) {
  return document.getElementById(id).value;
}

function textInput(id, label, max = 120) {
  const text = value(id).trim();
  if (!text) throw new FieldValidationError(id, `${label}不能为空`);
  if (text.length > max) throw new FieldValidationError(id, `${label}不能超过 ${max} 个字符`);
  return text;
}

function numberInput(id, label, min = 0, max = Number.MAX_SAFE_INTEGER) {
  const raw = value(id).trim();
  const numberValue = Number(raw);
  if (
    !raw
    || !Number.isFinite(numberValue)
    || !Number.isInteger(numberValue)
    || numberValue < min
    || numberValue > max
  ) {
    throw new FieldValidationError(id, `${label}必须是 ${min} 到 ${max} 之间的整数`);
  }
  return numberValue;
}

function escapeHtml(valueToEscape) {
  return String(valueToEscape ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

async function fetchWithTimeout(url, options = {}, timeoutMs = API_READ_TIMEOUT_MS) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...options, signal: controller.signal });
  } catch (error) {
    if (error.name === 'AbortError') throw new Error(`${url} 请求超时`);
    throw error;
  } finally {
    clearTimeout(timeout);
  }
}

async function apiGet(url) {
  const response = await fetchWithTimeout(url);
  if (!response.ok) throw new Error(`${url} ${response.status}`);
  return response.json();
}

async function apiWrite(url, body, method = 'POST') {
  const response = await fetchWithTimeout(
    url,
    {
      method,
      headers: writeHeaders(),
      body: JSON.stringify(body),
    },
    API_WRITE_TIMEOUT_MS,
  );
  if (!response.ok) {
    let detail = `${url} ${response.status}`;
    try {
      const payload = await response.json();
      if (payload.detail) detail = Array.isArray(payload.detail) ? JSON.stringify(payload.detail) : payload.detail;
    } catch {
      detail = `${url} ${response.status}`;
    }
    throw new Error(detail);
  }
  return response.json();
}

function currentPrincipal() {
  return {
    actor: sessionStorage.getItem('embodied.actor') || 'static-pwa',
    role: sessionStorage.getItem('embodied.role') || 'offline_demo',
    signature: sessionStorage.getItem('embodied.signature') || '',
  };
}

function writeHeaders() {
  const principal = currentPrincipal();
  return {
    'Content-Type': 'application/json',
    'X-Embodied-Role': principal.role,
    'X-Embodied-Actor': principal.actor,
    'X-Embodied-Signature': principal.signature,
  };
}

function roleAllowedForAction(action) {
  if (!action || NON_WRITE_ACTIONS.has(action)) return true;
  const allowedRoles = ACTION_ROLES[action];
  if (!allowedRoles) return false;
  return allowedRoles.includes(currentPrincipal().role);
}

function canUseLiveWrites(action = null) {
  const principal = currentPrincipal();
  return state.ready && state.live && !state.degraded && Boolean(principal.signature) && roleAllowedForAction(action);
}

function writeBlockReason(action = null) {
  if (!state.ready) return '平台数据仍在加载，写入已暂时锁定';
  if (!state.live) return '';
  if (state.degraded) return `API 部分可用：${state.liveFailures.join('、')} 不可用，写入已暂停`;
  if (!currentPrincipal().signature) return 'API 已连接（只读）：需要签名写入权限';
  if (!roleAllowedForAction(action)) return `当前角色 ${currentPrincipal().role} 无权执行该操作`;
  return '';
}

function syncWriteControls() {
  document.querySelectorAll('[data-action]').forEach((button) => {
    const action = button.dataset.action;
    button.disabled = !state.ready || Boolean(writeBlockReason(action));
    if (NON_WRITE_ACTIONS.has(button.dataset.action)) {
      button.disabled = !state.ready && button.dataset.action !== 'refresh-monitoring';
    }
    button.title = button.disabled ? (writeBlockReason(action) || '平台数据仍在加载') : '';
    button.setAttribute('aria-disabled', String(button.disabled));
  });

  const formLocked = !state.ready || (state.live && (!currentPrincipal().signature || state.degraded));
  // Scope to module-panel form controls only: the login form must stay usable
  // precisely when writes are locked (live + unsigned) so the operator can sign in.
  document.querySelectorAll('.module-panel input, .module-panel select').forEach((control) => {
    control.disabled = formLocked;
    control.title = formLocked ? (writeBlockReason() || '平台数据仍在加载') : '';
  });
}

function updateModeBanner() {
  const banner = document.getElementById('mode-banner');
  if (!banner) return;
  let text = '';
  let mode = '';
  if (!state.ready) {
    text = '正在加载平台数据，写入操作已锁定。';
    mode = 'loading';
  } else if (state.live && state.degraded) {
    text = `API 部分可用：${state.liveFailures.join('、')} 暂不可用；当前为只读模式，避免写入到不完整状态。`;
    mode = 'warning';
  } else if (state.live && !currentPrincipal().signature) {
    text = 'API 已连接（只读）：需要签名写入权限后才能保存变更。';
    mode = 'warning';
  } else if (!state.live) {
    const savedAge = state.demoSavedAt ? `，本地保存于 ${formatSavedAge(state.demoSavedAt)}` : '';
    text = `离线演示数据${savedAge}；写入只保存在当前浏览器。`;
    mode = 'offline';
  }

  banner.textContent = text;
  banner.hidden = !text;
  banner.className = `mode-banner ${mode}`.trim();
}

function setStatus(live, detail = '') {
  const node = document.getElementById('api-status');
  state.live = live;
  node.textContent = detail || (live ? 'API 已连接' : '离线演示');
  node.className = `status-pill ${live ? 'live' : 'offline'}`;
  syncWriteControls();
  updateModeBanner();
}

function isSignedIn() {
  return Boolean(sessionStorage.getItem('embodied.signature'));
}

function renderPrincipal() {
  const toggle = document.getElementById('login-toggle');
  const form = document.getElementById('login-form');
  const label = document.getElementById('principal-label');
  const logout = document.getElementById('logout-btn');
  if (!toggle || !form || !label || !logout) return;
  const signedIn = isSignedIn();
  if (signedIn) {
    const principal = currentPrincipal();
    label.textContent = `${principal.actor} · ${principal.role}`;
    label.hidden = false;
    logout.hidden = false;
    toggle.hidden = true;
    form.hidden = true;
  } else {
    label.textContent = '';
    label.hidden = true;
    logout.hidden = true;
    toggle.hidden = false;
  }
}

async function submitLogin() {
  const actor = document.getElementById('login-actor').value.trim();
  const role = document.getElementById('login-role').value;
  const passcode = document.getElementById('login-passcode').value;
  if (!actor) {
    setStatus(state.live, '登录失败：操作者不能为空');
    return;
  }
  if (actor.length > 120) {
    setStatus(state.live, '登录失败：操作者不能超过 120 个字符');
    return;
  }
  let payload;
  try {
    const response = await fetchWithTimeout(
      API.session,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ actor, role, passcode }),
      },
      API_WRITE_TIMEOUT_MS,
    );
    if (!response.ok) {
      let detail = `${response.status}`;
      try {
        const body = await response.json();
        if (body.detail) detail = Array.isArray(body.detail) ? JSON.stringify(body.detail) : body.detail;
      } catch {
        detail = `${response.status}`;
      }
      setStatus(state.live, `登录失败：${detail}`);
      return;
    }
    payload = await response.json();
  } catch (error) {
    setStatus(state.live, `登录失败：${error.message}`);
    return;
  }

  if (!payload || !payload.signature) {
    setStatus(state.live, '登录失败：响应缺少签名');
    return;
  }
  sessionStorage.setItem('embodied.actor', payload.actor || actor);
  sessionStorage.setItem('embodied.role', payload.role || role);
  sessionStorage.setItem('embodied.signature', payload.signature);
  document.getElementById('login-passcode').value = '';
  document.getElementById('login-form').hidden = true;
  renderPrincipal();
  syncWriteControls();
  updateModeBanner();
  await refreshState();
}

function logout() {
  sessionStorage.removeItem('embodied.actor');
  sessionStorage.removeItem('embodied.role');
  sessionStorage.removeItem('embodied.signature');
  renderPrincipal();
  syncWriteControls();
  updateModeBanner();
}

function setupLogin() {
  const toggle = document.getElementById('login-toggle');
  const form = document.getElementById('login-form');
  const submit = document.getElementById('login-submit');
  const logoutBtn = document.getElementById('logout-btn');
  if (!toggle || !form || !submit || !logoutBtn) return;
  toggle.addEventListener('click', () => {
    form.hidden = !form.hidden;
    if (!form.hidden) document.getElementById('login-actor').focus();
  });
  submit.addEventListener('click', () => { submitLogin(); });
  form.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') {
      event.preventDefault();
      submitLogin();
    }
  });
  logoutBtn.addEventListener('click', logout);
  renderPrincipal();
}

function emptyClientState() {
  return normaliseState({});
}

function normaliseState(data) {
  COLLECTIONS.forEach((collection) => {
    if (!Array.isArray(data[collection])) data[collection] = [];
  });
  data.system_settings ||= {
    retention_days: 30,
    offline_mode: true,
    active_robot_fleet: 'warehouse-fleet-a',
    approval_required_for_edge: true,
  };
  data.monitoring ||= {};
  return data;
}

function isValidStoredDemoState(payload) {
  if (!payload || payload.version !== DEMO_STATE_VERSION || !payload.data || !payload.saved_at) return false;
  const savedAt = Date.parse(payload.saved_at);
  if (!Number.isFinite(savedAt) || Date.now() - savedAt > DEMO_STATE_TTL_MS) return false;
  return COLLECTIONS.every((collection) => Array.isArray(payload.data[collection]));
}

function cleanupOldDemoStateKeys() {
  try {
    Object.keys(localStorage)
      .filter((key) => key.startsWith(DEMO_STATE_PREFIX) && key !== DEMO_STATE_KEY)
      .forEach((key) => localStorage.removeItem(key));
  } catch {
    // localStorage can be disabled by the host shell; demo mode still works without persistence.
  }
}

function formatSavedAge(savedAt) {
  const elapsedMs = Math.max(0, Date.now() - Date.parse(savedAt));
  const minutes = Math.floor(elapsedMs / 60000);
  if (minutes < 1) return '刚刚';
  if (minutes < 60) return `${minutes} 分钟前`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} 小时前`;
  return `${Math.floor(hours / 24)} 天前`;
}

async function loadDemoState(preferSaved = true) {
  cleanupOldDemoStateKeys();
  state.ready = false;
  state.degraded = false;
  state.liveFailures = [];
  state.demoSavedAt = null;

  if (preferSaved) {
    try {
      const saved = localStorage.getItem(DEMO_STATE_KEY);
      if (saved) {
        const payload = JSON.parse(saved);
        if (isValidStoredDemoState(payload)) {
          state.data = normaliseState(payload.data);
          state.demoSavedAt = payload.saved_at;
          state.ready = true;
          setStatus(false);
          renderAll();
          return;
        }
        localStorage.removeItem(DEMO_STATE_KEY);
      }
    } catch {
      localStorage.removeItem(DEMO_STATE_KEY);
    }
  }

  const response = await fetch('fixtures/demo-state.json');
  state.data = normaliseState(await response.json());
  state.ready = true;
  setStatus(false);
  renderAll();
}

async function loadLiveState() {
  state.ready = false;
  const results = await Promise.allSettled(LIVE_ENDPOINTS.map((endpoint) => apiGet(endpoint.url)));
  const successCount = results.filter((result) => result.status === 'fulfilled').length;
  if (successCount === 0) throw new Error('API 不可用，已切换到离线演示数据');

  const liveData = emptyClientState();
  const failures = [];
  results.forEach((result, index) => {
    const endpoint = LIVE_ENDPOINTS[index];
    if (result.status === 'fulfilled') {
      liveData[endpoint.target] = result.value;
    } else {
      failures.push(endpoint.label);
      liveData[endpoint.target] = endpoint.fallback ?? liveData[endpoint.target];
    }
  });

  state.data = normaliseState(liveData);
  state.ready = true;
  state.degraded = failures.length > 0;
  state.liveFailures = failures;
  state.demoSavedAt = null;
  setStatus(true, failures.length ? 'API 部分可用（只读）' : (currentPrincipal().signature ? 'API 已连接' : 'API 已连接（只读）'));
  renderAll();
}

function persistDemoState() {
  if (!state.live && state.data) {
    const savedAt = new Date().toISOString();
    const envelope = {
      version: DEMO_STATE_VERSION,
      saved_at: savedAt,
      data: state.data,
    };
    localStorage.setItem(DEMO_STATE_KEY, JSON.stringify(envelope));
    state.demoSavedAt = savedAt;
    updateModeBanner();
  }
}

async function refreshState(options = {}) {
  state.ready = false;
  syncWriteControls();
  updateModeBanner();
  try {
    await loadLiveState();
  } catch (error) {
    if (options.preserveLiveOnFailure && state.data) {
      state.ready = true;
      state.live = true;
      state.degraded = true;
      state.liveFailures = ['刷新'];
      state.demoSavedAt = null;
      setStatus(true, `写入已提交，刷新失败（只读）：${error.message}`);
      renderAll();
      return;
    }
    await loadDemoState();
  }
}

async function resetDemoState() {
  localStorage.removeItem(DEMO_STATE_KEY);
  cleanupOldDemoStateKeys();
  clearFieldErrors();
  if (state.live) {
    await refreshState();
  } else {
    await loadDemoState(false);
  }
}

function clearFieldError(id) {
  const input = document.getElementById(id);
  if (!input) return;
  input.removeAttribute('aria-invalid');
  input.removeAttribute('aria-describedby');
  const error = document.getElementById(`${id}-error`);
  if (error) error.remove();
}

function clearFieldErrors() {
  document.querySelectorAll('[aria-invalid="true"]').forEach((node) => clearFieldError(node.id));
}

function setFieldError(fieldId, message) {
  const input = document.getElementById(fieldId);
  if (!input) return;
  let error = document.getElementById(`${fieldId}-error`);
  if (!error) {
    error = document.createElement('span');
    error.id = `${fieldId}-error`;
    error.className = 'field-error';
    input.insertAdjacentElement('afterend', error);
  }
  error.textContent = message;
  input.setAttribute('aria-invalid', 'true');
  input.setAttribute('aria-describedby', error.id);
  input.focus();
}

function table(id, columns, rows) {
  const node = document.getElementById(id);
  node.setAttribute('role', 'table');
  node.setAttribute('aria-label', node.dataset.label || id);
  const columnTemplate = `grid-template-columns: repeat(${Math.max(columns.length, 1)}, minmax(0, 1fr));`;
  if (!rows.length) {
    node.innerHTML = `<div class="row empty" role="row" style="${columnTemplate}"><span role="cell" data-label="状态">暂无记录</span></div>`;
    return;
  }
  const head = `<div class="row header" role="row" style="${columnTemplate}">${columns.map((col) => `<span role="columnheader">${escapeHtml(col)}</span>`).join('')}</div>`;
  const body = rows.map((row) => {
    const cells = columns.map((col, index) => {
      const cell = row[index] ?? '';
      const content = cell?.trustedHtml ? cell.value : escapeHtml(cell);
      return `<span role="cell" data-label="${escapeHtml(col)}"><span class="cell-label">${escapeHtml(col)}</span><span class="cell-value">${content}</span></span>`;
    }).join('');
    return `<div class="row" role="row" style="${columnTemplate}">${cells}</div>`;
  }).join('');
  node.innerHTML = head + body;
}

const STATUS_TOKENS = {
  queued: 'neutral',
  open: 'neutral',
  set: 'neutral',
  current: 'neutral',
  normal: 'neutral',
  running: 'info',
  succeeded: 'ok',
  accepted: 'ok',
  active: 'ok',
  review: 'warn',
  rework: 'warn',
  high: 'warn',
  failed: 'danger',
  cancelled: 'danger',
  urgent: 'danger',
  low: 'faint',
};

function statusToken(rawStatus) {
  return STATUS_TOKENS[rawStatus] || 'neutral';
}

function tag(text) {
  const token = statusToken(text);
  return {
    trustedHtml: true,
    value: `<span class="tag tag--${token}">${escapeHtml(LABELS[text] || text || '排队中')}</span>`,
  };
}

function appendLocalAudit(action, resource, detail = '') {
  const principal = currentPrincipal();
  state.data.audit_events.push({
    id: `audit-${Date.now()}`,
    action,
    resource,
    detail,
    actor: principal.actor,
    role: principal.role,
    created_at: new Date().toISOString(),
  });
}

// Known MonitoringOverview metrics rendered as instrument tiles, in display order.
// `sim_success_rate` is rendered as a gauge (handled separately); everything else
// not listed here falls through to the #monitoring-list table fallback.
const MONITORING_TILES = [
  { key: 'dataset_count', token: 'neutral' },
  { key: 'episode_count', token: 'neutral' },
  { key: 'queued_jobs', token: 'neutral' },
  { key: 'running_jobs', token: 'info' },
  { key: 'active_model_id', token: 'ok', kind: 'id' },
  { key: 'active_deployments', token: 'ok' },
  { key: 'open_learning_items', token: 'warn' },
  { key: 'recent_audit_events', token: 'neutral' },
];
const MONITORING_TILE_KEYS = new Set(MONITORING_TILES.map((tile) => tile.key));

function renderMonitoring(monitoring) {
  const board = document.getElementById('monitoring-board');
  const fallback = document.getElementById('monitoring-list');
  if (!board) return;

  const source = state.live ? 'API' : '演示数据';
  const numericTiles = MONITORING_TILES
    .filter((tile) => tile.kind !== 'id')
    .map((tile) => Number(monitoring[tile.key]))
    .filter((num) => Number.isFinite(num) && num > 0);
  const maxNumeric = numericTiles.length ? Math.max(...numericTiles) : 0;

  const tilesHtml = MONITORING_TILES
    .filter((tile) => monitoring[tile.key] !== undefined && monitoring[tile.key] !== null)
    .map((tile) => {
      const rawValue = monitoring[tile.key];
      const label = LABELS[tile.key] || tile.key;
      if (tile.kind === 'id') {
        const display = String(rawValue) || '—';
        const present = Boolean(rawValue);
        const barWidth = present ? 100 : 0;
        return monTile(tile.token, label, escapeHtml(display), '', barWidth);
      }
      const numeric = Number(rawValue);
      const safeNumeric = Number.isFinite(numeric) ? numeric : 0;
      const barWidth = maxNumeric > 0 ? Math.round((safeNumeric / maxNumeric) * 100) : 0;
      return monTile(tile.token, label, escapeHtml(String(rawValue ?? 0)), '', barWidth);
    })
    .join('');

  let gaugeHtml = '';
  if (monitoring.sim_success_rate !== undefined && monitoring.sim_success_rate !== null) {
    const rate = Number(monitoring.sim_success_rate);
    const safeRate = Number.isFinite(rate) ? Math.min(Math.max(rate, 0), 1) : 0;
    const pct = Math.round(safeRate * 100);
    gaugeHtml = `<div class="mon-gauge">`
      + `<div class="mon-gauge__head">`
      + `<span class="mon-gauge__label">${escapeHtml(LABELS.sim_success_rate)}</span>`
      + `<span class="mon-gauge__value">${pct}%</span>`
      + `</div>`
      + `<div class="mon-gauge__track"><div class="mon-gauge__fill" style="width:${pct}%"></div></div>`
      + `<div class="mon-gauge__scale"><span>0</span><span>50</span><span>100</span></div>`
      + `</div>`;
  }

  if (!tilesHtml && !gaugeHtml) {
    board.innerHTML = '';
    board.hidden = true;
  } else {
    board.innerHTML = tilesHtml + gaugeHtml;
    board.hidden = false;
  }

  // Unknown metrics (not handled as a tile or the gauge) keep the accessible
  // table fallback so nothing from the backend is silently dropped.
  const unknownEntries = Object.entries(monitoring).filter(
    ([key]) => !MONITORING_TILE_KEYS.has(key) && key !== 'sim_success_rate',
  );
  if (unknownEntries.length) {
    fallback.hidden = false;
    table('monitoring-list', ['信号', '数值', '来源', '状态'], unknownEntries.map(([key, val]) => [
      LABELS[key] || key,
      String(val ?? ''),
      source,
      tag('current'),
    ]));
    return;
  }
  // No tiles, no gauge, no unknown metrics (e.g. degraded-live with monitoring
  // unavailable -> {}): preserve the original empty-state instead of a blank board.
  if (!tilesHtml && !gaugeHtml) {
    fallback.hidden = false;
    table('monitoring-list', ['信号', '数值', '来源', '状态'], []);
    return;
  }
  fallback.innerHTML = '';
  fallback.hidden = true;
}

function monTile(token, label, valueHtml, unitHtml, barWidth) {
  const width = Math.min(Math.max(Number(barWidth) || 0, 0), 100);
  const unit = unitHtml ? `<span class="mon-unit">${unitHtml}</span>` : '';
  return `<div class="mon-tile mon-tile--${token}">`
    + `<div class="mon-tile__label">${escapeHtml(label)}</div>`
    + `<div class="mon-tile__value">${valueHtml}${unit}</div>`
    + `<div class="mon-tile__bar"><span style="width:${width}%"></span></div>`
    + `</div>`;
}

function renderAll() {
  if (!state.data) return;
  const data = state.data;
  const episodes = data.episodes || [];
  const monitoring = data.monitoring || {};
  document.getElementById('metric-datasets').textContent = monitoring.dataset_count ?? data.datasets.length;
  document.getElementById('metric-queued').textContent = monitoring.queued_jobs ?? 0;
  document.getElementById('metric-running').textContent = monitoring.running_jobs ?? 0;
  document.getElementById('metric-learning').textContent = monitoring.open_learning_items ?? data.learning_queue.length;

  table('datasets-list', ['名称', '模态', '存储', '片段数'], data.datasets.map((item) => [
    item.name,
    LABELS[item.modality] || item.modality,
    item.storage_uri,
    String(item.episode_count ?? 0),
  ]));
  table('episodes-list', ['片段', '数据集', '单元', '帧数'], episodes.map((item) => [
    item.episode_id,
    item.dataset_id,
    item.robot_cell || '',
    String(item.frame_count ?? 0),
  ]));
  table('annotation-list', ['片段', '任务', '负责人', '状态'], data.annotation_tasks.map((item) => [
    item.episode_id,
    LABELS[item.task_type] || item.task_type,
    item.assignee,
    tag(item.status),
  ]));
  table('training-list', ['名称', '基础模型', '优化方式', '状态'], data.training_jobs.map((item) => [
    item.name,
    item.base_model,
    LABELS[item.optimizer] || item.optimizer,
    tag(item.status),
  ]));
  table('models-list', ['名称', '版本', '产物', '启用'], data.models.map((item) => [
    item.name,
    item.version,
    item.artifact_uri,
    item.active ? tag('active') : '',
  ]));
  table('simulation-list', ['场景', '仿真器', '指标', '状态'], data.simulation_jobs.map((item) => [
    item.scenario,
    item.simulator,
    item.sim2real_metric || '迁移',
    tag(item.status),
  ]));
  table('deployment-list', ['目标', '环境', '模型', '状态'], data.deployments.map((item) => [
    item.target,
    item.environment,
    item.model_id,
    tag(item.status),
  ]));
  table('learning-list', ['片段', '优先级', '原因', '状态'], data.learning_queue.map((item) => [
    item.episode_id,
    LABELS[item.priority] || item.priority,
    item.reason,
    tag(item.status),
  ]));
  renderMonitoring(monitoring);
  table('audit-list', ['动作', '资源', '操作者', '详情'], data.audit_events.slice(-8).reverse().map((item) => [
    item.action,
    item.resource,
    item.actor,
    item.detail || '',
  ]));
  table('system-list', ['设置项', '值', '模式', '状态'], Object.entries(data.system_settings || {}).map(([key, val]) => [
    LABELS[key] || key,
    typeof val === 'boolean' ? (val ? '是' : '否') : String(val),
    state.live ? 'API' : '演示数据',
    tag('set'),
  ]));
  syncWriteControls();
  updateModeBanner();
}

function useLocal(collection, item) {
  state.data[collection].push(item);
  renderAll();
}

function useLocalWithAudit(collection, item, action, resource, detail = '') {
  state.data[collection].push(item);
  appendLocalAudit(action, resource, detail);
  persistDemoState();
  renderAll();
}

function incrementLocalDatasetEpisodeCount(datasetId) {
  state.data.datasets.forEach((dataset) => {
    if (dataset.id === datasetId || dataset.name === datasetId) {
      dataset.episode_count = Number(dataset.episode_count || 0) + 1;
    }
  });
}

function findDataset(identifier) {
  return state.data.datasets.find((dataset) => dataset.id === identifier || dataset.name === identifier);
}

function findEpisode(identifier) {
  return (state.data.episodes || []).find((episode) => episode.id === identifier || episode.episode_id === identifier);
}

function findModel(identifier) {
  return state.data.models.find((model) => model.id === identifier || model.name === identifier || model.version === identifier);
}

function requireDataset(identifier, fieldId = 'dataset-name') {
  const dataset = findDataset(identifier);
  if (!dataset) throw new FieldValidationError(fieldId, `未找到数据集：${identifier}`);
  return dataset;
}

function requireEpisode(identifier, fieldId = 'episode-id') {
  const episode = findEpisode(identifier);
  if (!episode) throw new FieldValidationError(fieldId, `未找到片段：${identifier}`);
  return episode;
}

function requireModel(identifier, fieldId = 'model-name') {
  const model = findModel(identifier);
  if (!model) throw new FieldValidationError(fieldId, `未找到模型：${identifier}`);
  return model;
}

function requireEpisodeInDataset(datasetIdentifier, episodeIdentifier) {
  const dataset = requireDataset(datasetIdentifier, 'annotation-dataset');
  const episode = requireEpisode(episodeIdentifier, 'annotation-episode');
  if (![dataset.id, dataset.name, datasetIdentifier].includes(episode.dataset_id)) {
    throw new FieldValidationError('annotation-episode', `片段 ${episodeIdentifier} 不属于数据集 ${datasetIdentifier}`);
  }
}

function requireNewDatasetIdentity(name, storageUri) {
  const duplicate = state.data.datasets.find((dataset) => dataset.name === name || dataset.storage_uri === storageUri);
  if (duplicate) throw new FieldValidationError('dataset-name', `数据集已存在：${duplicate.name}`);
}

function requireNewEpisodeIdentity(episodeId) {
  if (findEpisode(episodeId)) throw new FieldValidationError('episode-id', `片段已存在：${episodeId}`);
}

function requireNewLearningIdentity(episodeId, reason, priority) {
  const duplicate = state.data.learning_queue.find((item) => (
    item.episode_id === episodeId
    && item.reason === reason
    && item.priority === priority
    && ['queued', 'running', 'open'].includes(item.status || 'queued')
  ));
  if (duplicate) throw new FieldValidationError('learning-episode', `学习队列已存在：${episodeId}`);
}

function assertOfflineReference(liveWrite, check) {
  if (!liveWrite) check();
}

async function commitLiveWrite(operation) {
  await operation();
  await refreshState({ preserveLiveOnFailure: true });
}

async function runAction(action) {
  clearFieldErrors();
  try {
    if (action === 'reset-demo') {
      await resetDemoState();
      return;
    }
    if (!state.ready && action !== 'refresh-monitoring') {
      setStatus(state.live, '平台数据仍在加载，稍后再试');
      return;
    }

    const liveWrite = canUseLiveWrites(action);
    if (state.live && !liveWrite && !NON_WRITE_ACTIONS.has(action)) {
      setStatus(true, writeBlockReason(action));
      return;
    }

    switch (action) {
      case 'create-dataset': {
        const datasetName = textInput('dataset-name', '数据集名称');
        const storageUri = textInput('dataset-uri', '存储 URI', 500);
        assertOfflineReference(liveWrite, () => requireNewDatasetIdentity(datasetName, storageUri));
        const payload = {
          name: datasetName,
          modality: value('dataset-modality'),
          robot_type: textInput('dataset-robot', '机器人类型', 80),
          storage_uri: storageUri,
          description: '由静态运营台创建。',
        };
        if (liveWrite) {
          await commitLiveWrite(() => apiWrite(API.datasets, payload));
        } else {
          const result = { id: `demo-${Date.now()}`, episode_count: 0, created_at: new Date().toISOString(), ...payload };
          useLocalWithAudit('datasets', result, 'dataset.create', result.id, result.name);
        }
        break;
      }
      case 'create-episode': {
        const datasetId = textInput('episode-dataset', '片段数据集');
        const episodeId = textInput('episode-id', '片段 ID');
        const payload = {
          dataset_id: datasetId,
          episode_id: episodeId,
          robot_cell: textInput('episode-cell', '机器人单元'),
          frame_count: numberInput('episode-frames', '帧数', 1, 1000000),
        };
        assertOfflineReference(liveWrite, () => {
          requireDataset(datasetId, 'episode-dataset');
          requireNewEpisodeIdentity(episodeId);
        });
        if (liveWrite) {
          await commitLiveWrite(() => apiWrite(API.episodes, payload));
        } else {
          const result = { id: `ep-${Date.now()}`, created_at: new Date().toISOString(), ...payload };
          incrementLocalDatasetEpisodeCount(payload.dataset_id);
          useLocalWithAudit('episodes', result, 'episode.create', result.id, result.episode_id);
        }
        break;
      }
      case 'start-import': {
        const payload = { source_uri: textInput('dataset-uri', '存储 URI', 500), dataset_name: textInput('dataset-name', '数据集名称'), format: 'lerobot' };
        if (liveWrite) {
          await commitLiveWrite(() => apiWrite(API.imports, payload));
        } else {
          const result = { id: `imp-${Date.now()}`, status: 'queued', created_at: new Date().toISOString(), updated_at: new Date().toISOString(), ...payload };
          useLocalWithAudit('imports', result, 'import.create', result.id, result.source_uri);
        }
        break;
      }
      case 'save-annotation': {
        const datasetId = textInput('annotation-dataset', '标注数据集');
        const episodeId = textInput('annotation-episode', '标注片段');
        const payload = {
          dataset_id: datasetId,
          episode_id: episodeId,
          task_type: 'trajectory_segment',
          assignee: textInput('annotation-assignee', '负责人'),
          status: value('annotation-status'),
          labels: [
            { start_frame: 0, end_frame: 64, skill_id: 'approach' },
            { start_frame: 65, end_frame: 140, skill_id: 'grasp' },
          ],
        };
        assertOfflineReference(liveWrite, () => requireEpisodeInDataset(datasetId, episodeId));
        if (liveWrite) {
          await commitLiveWrite(() => apiWrite(API.annotation, payload));
        } else {
          const result = { id: `ann-${Date.now()}`, label_count: payload.labels.length, updated_at: new Date().toISOString(), ...payload };
          useLocalWithAudit('annotation_tasks', result, 'annotation.save', result.id, result.episode_id);
        }
        break;
      }
      case 'start-training': {
        const datasetId = textInput('training-dataset', '训练数据集');
        const payload = { name: textInput('training-name', '训练任务'), dataset_id: datasetId, base_model: textInput('training-base', '基础模型'), optimizer: value('training-optimizer') };
        assertOfflineReference(liveWrite, () => requireDataset(datasetId, 'training-dataset'));
        if (liveWrite) {
          await commitLiveWrite(() => apiWrite(API.training, payload));
        } else {
          const result = { id: `train-${Date.now()}`, status: 'queued', created_at: new Date().toISOString(), updated_at: new Date().toISOString(), ...payload };
          useLocalWithAudit('training_jobs', result, 'training.create', result.id, result.name);
        }
        break;
      }
      case 'activate-model': {
        const payload = { name: textInput('model-name', '模型名称'), version: textInput('model-version', '模型版本', 80), artifact_uri: textInput('model-uri', '产物 URI', 500), metrics: { success: 0.82 } };
        if (liveWrite) {
          try {
            const created = await apiWrite(API.models, payload);
            await apiWrite(`${API.models}/${created.id}/activate`, {}, 'POST');
          } finally {
            await refreshState({ preserveLiveOnFailure: true });
          }
        } else {
          const result = { id: `model-${Date.now()}`, active: true, created_at: new Date().toISOString(), ...payload };
          state.data.models.forEach((model) => { model.active = false; });
          useLocalWithAudit('models', result, 'model.activate', result.id, result.version);
        }
        break;
      }
      case 'start-simulation': {
        const modelId = textInput('simulation-model', '仿真模型');
        const payload = { scenario: textInput('simulation-scenario', '场景'), model_id: modelId, simulator: value('simulation-simulator'), sim2real_metric: textInput('simulation-metric', '仿真指标') };
        assertOfflineReference(liveWrite, () => requireModel(modelId, 'simulation-model'));
        if (liveWrite) {
          await commitLiveWrite(() => apiWrite(API.simulation, payload));
        } else {
          const result = { id: `sim-${Date.now()}`, status: 'queued', created_at: new Date().toISOString(), updated_at: new Date().toISOString(), ...payload };
          useLocalWithAudit('simulation_jobs', result, 'simulation.create', result.id, result.scenario);
        }
        break;
      }
      case 'create-deployment': {
        const modelId = textInput('deployment-model', '部署模型');
        const payload = { model_id: modelId, target: textInput('deployment-target', '部署目标'), environment: textInput('deployment-env', '部署环境') };
        assertOfflineReference(liveWrite, () => requireModel(modelId, 'deployment-model'));
        if (liveWrite) {
          await commitLiveWrite(() => apiWrite(API.deployment, payload));
        } else {
          const result = { id: `dep-${Date.now()}`, status: 'queued', created_at: new Date().toISOString(), updated_at: new Date().toISOString(), ...payload };
          useLocalWithAudit('deployments', result, 'deployment.create', result.id, result.target);
        }
        break;
      }
      case 'enqueue-learning': {
        const episodeId = textInput('learning-episode', '学习片段');
        const reason = textInput('learning-reason', '学习原因', 240);
        const priority = value('learning-priority');
        assertOfflineReference(liveWrite, () => {
          requireEpisode(episodeId, 'learning-episode');
          requireNewLearningIdentity(episodeId, reason, priority);
        });
        const payload = { episode_id: episodeId, reason, priority };
        if (liveWrite) {
          await commitLiveWrite(() => apiWrite(API.learning, payload));
        } else {
          const result = { id: `learn-${Date.now()}`, status: 'queued', created_at: new Date().toISOString(), updated_at: new Date().toISOString(), ...payload };
          useLocalWithAudit('learning_queue', result, 'learning.enqueue', result.id, result.reason);
        }
        break;
      }
      case 'refresh-monitoring':
        await refreshState();
        break;
      case 'write-audit': {
        const payload = { action: textInput('audit-action', '审计动作'), resource: textInput('audit-resource', '审计资源'), detail: textInput('audit-detail', '审计详情', 500) };
        if (liveWrite) {
          await commitLiveWrite(() => apiWrite(API.audit, payload));
        } else {
          const principal = currentPrincipal();
          const result = { id: `audit-${Date.now()}`, actor: principal.actor, role: principal.role, created_at: new Date().toISOString(), ...payload };
          useLocal('audit_events', result);
          persistDemoState();
        }
        break;
      }
      case 'save-settings': {
        const payload = {
          retention_days: numberInput('settings-retention', '保留天数', 1, 3650),
          active_robot_fleet: textInput('settings-fleet', '机器人集群'),
          offline_mode: value('settings-offline') === 'true',
          approval_required_for_edge: value('settings-approval') === 'true',
        };
        if (liveWrite) {
          await commitLiveWrite(() => apiWrite(API.system, payload, 'PATCH'));
        } else {
          state.data.system_settings = payload;
          appendLocalAudit('system.settings', 'settings', '设置已更新');
          persistDemoState();
          renderAll();
        }
        break;
      }
    }
  } catch (error) {
    if (error instanceof FieldValidationError) {
      setFieldError(error.fieldId, error.message);
    }
    setStatus(state.live, `操作失败：${error.message}`);
  }
}

function moduleFromHash() {
  const candidate = window.location.hash.replace(/^#/, '');
  return MODULE_IDS.includes(candidate) ? candidate : 'data-management';
}

function activateModule(module, updateHash = true) {
  const activeModule = MODULE_IDS.includes(module) ? module : 'data-management';
  document.querySelector('.module-rail')?.setAttribute('role', 'tablist');
  document.querySelectorAll('.module-rail [data-module]').forEach((node) => {
    const active = node.dataset.module === activeModule;
    node.classList.toggle('active', active);
    node.setAttribute('role', 'tab');
    node.setAttribute('aria-selected', String(active));
    node.setAttribute('aria-controls', `${node.dataset.module}-panel`);
    if (active) {
      node.setAttribute('aria-current', 'page');
    } else {
      node.removeAttribute('aria-current');
    }
  });
  document.querySelectorAll('.module-panel').forEach((panel) => {
    const active = panel.id === `${activeModule}-panel`;
    panel.classList.toggle('active', active);
    panel.setAttribute('role', 'tabpanel');
    panel.setAttribute('aria-hidden', String(!active));
  });
  const targetHash = `#${activeModule}`;
  if (window.location.hash !== targetHash) {
    const historyMethod = updateHash ? 'pushState' : 'replaceState';
    window.history[historyMethod](null, '', targetHash);
  }
}

document.querySelectorAll('.module-rail [data-module]').forEach((button) => {
  button.addEventListener('click', () => activateModule(button.dataset.module));
  button.addEventListener('keydown', (event) => {
    const currentIndex = MODULE_IDS.indexOf(button.dataset.module);
    let nextIndex = currentIndex;
    if (event.key === 'ArrowRight' || event.key === 'ArrowDown') nextIndex = (currentIndex + 1) % MODULE_IDS.length;
    if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') nextIndex = (currentIndex - 1 + MODULE_IDS.length) % MODULE_IDS.length;
    if (event.key === 'Home') nextIndex = 0;
    if (event.key === 'End') nextIndex = MODULE_IDS.length - 1;
    if (nextIndex !== currentIndex) {
      event.preventDefault();
      const target = document.querySelector(`.module-rail [data-module="${MODULE_IDS[nextIndex]}"]`);
      target?.focus();
      activateModule(MODULE_IDS[nextIndex]);
    }
  });
});

window.addEventListener('hashchange', () => activateModule(moduleFromHash(), false));

document.querySelectorAll('[data-action]').forEach((button) => {
  button.addEventListener('click', () => runAction(button.dataset.action));
});

if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('sw.js').catch(() => {});
}

setupLogin();
syncWriteControls();
activateModule(moduleFromHash(), false);
refreshState();
