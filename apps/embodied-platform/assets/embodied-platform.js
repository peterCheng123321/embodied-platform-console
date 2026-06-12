const API = {
  datasets: '/api/embodied-platform/datasets',
  episodes: '/api/embodied-platform/episodes',
  imports: '/api/embodied-platform/imports',
  annotation: '/api/embodied-platform/annotation-tasks',
  collectionProfiles: '/api/embodied-platform/collection-profiles',
  collectionRuns: '/api/embodied-platform/collection-runs',
  collectionAttempts: '/api/embodied-platform/collection-attempts',
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
  'collection',
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
  demoUnavailable: false,
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
  'collection_profiles',
  'collection_runs',
  'collection_attempts',
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
  { target: 'collection_profiles', label: '采集配置', url: API.collectionProfiles, fallback: [] },
  { target: 'collection_runs', label: '采集进度', url: API.collectionRuns, fallback: [] },
  { target: 'collection_attempts', label: '采集视频', url: API.collectionAttempts, fallback: [] },
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
  'create-collection-run': ['admin', 'data_manager', 'annotator', 'reviewer', 'operator'],
  'register-collection-attempt': ['admin', 'annotator', 'reviewer', 'operator'],
  'review-collection-attempt': ['admin', 'reviewer', 'operator'],
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
  uploaded: '已上传',
  draft: '草稿',
  recorded: '已录制',
  ready_for_review: '待复核',
  rejected: '已拒绝',
  deleted: '已删除',
  blocked: '已阻塞',
  collecting: '采集中',
  passed: '已通过',
  collect: '采集',
  ordinary: '常规',
  speak_while_doing: '边说边做',
  accept: '通过',
  reject: '拒绝',
  needs_rework: '返工',
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

const FIRST_PERSON_PROFILE_FALLBACK = {
  id: 'first_person_trial_v1',
  name: '第一人称试采流程',
  version: 1,
  source: 'Feishu workflow inspected 2026-06-08',
  task_count_required: 8,
  default_required_uploads: 6,
  default_max_attempts: 8,
  completion_policy: 'uploaded_count_per_task',
  tasks: [
    ['task_01', 'ordinary', '笔帽拔下后插到笔杆尾端'],
    ['task_02', 'ordinary', '杯盖盖紧后杯子倒放'],
    ['task_03', 'ordinary', '塑料袋撑开后放入空瓶并收拢袋口'],
    ['task_04', 'ordinary', '多个物体按颜色排序'],
    ['task_05', 'ordinary', '左右手按顺序抽纸巾擦桌子'],
    ['task_06', 'ordinary', '拧瓶盖'],
    ['task_07', 'speak_while_doing', '抽出碗底一次性筷子并拢摆齐'],
    ['task_08', 'speak_while_doing', '毛巾卷成一卷后放进抽屉右侧'],
  ].map(([task_id, mode, title]) => ({
    task_id,
    mode,
    title,
    required_uploads: 6,
    max_attempts: 8,
    environment: { clutter_min: task_id === 'task_04' ? 0 : 6, first_person_view: true },
    target_objects: [],
    speech: mode === 'ordinary' ? ['操作开始', '操作结束，任务成功'] : ['任务名称', '作业流程'],
    procedure_steps: [],
    duration_rules: [],
    qc_checks: [
      'speech.required_phrase',
      'scene.clutter',
      'scene.lighting',
      'view.first_person',
      'device.gripper_visibility',
      'device.marker_visibility',
      'audio.background_noise',
    ],
    task_notes: [],
  })),
  issue_codes: [
    ['missing_required_speech', '必需口述缺失或不清晰', 'critical'],
    ['speech_while_motion', '常规模式口述与动作重叠', 'warning'],
    ['task_description_mismatch', '任务描述与结果不一致', 'critical'],
    ['unclear_target_object', '目标物体指代不清', 'warning'],
    ['scene_clutter_insufficient', '杂乱物数量或分布不足', 'warning'],
    ['scene_clutter_invalid_plane', '杂乱物平面或堆叠不合规', 'warning'],
    ['lighting_too_dark', '环境过暗', 'warning'],
    ['other_people_or_devices_visible', '出现其他人员或采集设备', 'critical'],
    ['gripper_out_of_frame', '夹爪出画或触碰画面边缘', 'critical'],
    ['marker_or_block_missing', '定位块或固定码可见性不足', 'critical'],
    ['motion_too_fast', '动作过快', 'warning'],
    ['background_noise', '背景音干扰', 'warning'],
    ['device_disconnect', '设备断连或重启', 'critical'],
    ['abnormal_recovery_missing', '异常情况未按规则口述恢复', 'warning'],
    ['task_specific_setup_failure', '任务特定准备不合规', 'warning'],
    ['attempt_limit_exhausted', '录制次数已用尽', 'critical'],
    ['upload_quota_incomplete', '上传数量不足', 'critical'],
  ].map(([id, label, severity]) => ({ id, label, severity })),
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

// Buttons whose runAction is still in flight; keeps concurrent syncWriteControls
// calls (e.g. from a mid-write refresh) from re-enabling them and allowing a
// double submit.
const inFlightActionButtons = new Set();

function syncWriteControls() {
  document.querySelectorAll('[data-action]').forEach((button) => {
    const action = button.dataset.action;
    button.disabled = !state.ready || Boolean(writeBlockReason(action));
    if (NON_WRITE_ACTIONS.has(button.dataset.action)) {
      button.disabled = !state.ready && button.dataset.action !== 'refresh-monitoring';
    }
    if (inFlightActionButtons.has(button)) button.disabled = true;
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
  } else if (!state.live && state.demoUnavailable) {
    text = '演示数据不可用 — 以空状态启动';
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
  // Focus must leave the now-hidden form; the login toggle is also hidden once
  // signed in, so the logout button is the visible successor control.
  document.getElementById('logout-btn')?.focus();
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
  const runLogin = () => {
    if (submit.disabled) return;
    submit.disabled = true;
    submitLogin().finally(() => { submit.disabled = false; });
  };
  submit.addEventListener('click', runLogin);
  form.addEventListener('keydown', (event) => {
    if (event.key === 'Enter') {
      event.preventDefault();
      runLogin();
    }
    if (event.key === 'Escape') {
      event.preventDefault();
      form.hidden = true;
      toggle.focus();
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
  state.demoUnavailable = false;

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
      try {
        localStorage.removeItem(DEMO_STATE_KEY);
      } catch {
        // localStorage can be disabled by the host shell; fall through to the fixture.
      }
    }
  }

  let fixture = null;
  try {
    const response = await fetchWithTimeout('fixtures/demo-state.json');
    if (response.ok) fixture = await response.json();
  } catch {
    // Fixture unreachable (e.g. backend down and nothing cached); boot empty below.
  }

  if (fixture) {
    state.data = normaliseState(fixture);
    state.ready = true;
    setStatus(false);
    renderAll();
    return;
  }

  // Total failure: no saved state and no fixture. Boot an empty in-memory demo
  // state instead of leaving state.ready=false (which would lock the app forever).
  state.data = emptyClientState();
  state.ready = true;
  state.demoUnavailable = true;
  setStatus(false, '演示数据不可用');
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

let persistDemoStateWarned = false;

function persistDemoState() {
  if (!state.live && state.data) {
    const savedAt = new Date().toISOString();
    const envelope = {
      version: DEMO_STATE_VERSION,
      saved_at: savedAt,
      data: state.data,
    };
    try {
      localStorage.setItem(DEMO_STATE_KEY, JSON.stringify(envelope));
    } catch {
      // localStorage disabled or quota exceeded: keep the in-memory write, warn once.
      if (!persistDemoStateWarned) {
        persistDemoStateWarned = true;
        setStatus(false, '本地存储不可用，演示更改不会保留');
      }
      return;
    }
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
  try {
    localStorage.removeItem(DEMO_STATE_KEY);
  } catch {
    // localStorage disabled: nothing persisted, reset still reloads the fixture.
  }
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
  draft: 'neutral',
  recorded: 'neutral',
  collecting: 'info',
  uploaded: 'info',
  ready_for_review: 'warn',
  running: 'info',
  succeeded: 'ok',
  accepted: 'ok',
  active: 'ok',
  passed: 'ok',
  accept: 'ok',
  review: 'warn',
  rework: 'warn',
  needs_rework: 'warn',
  high: 'warn',
  failed: 'danger',
  rejected: 'danger',
  reject: 'danger',
  deleted: 'danger',
  blocked: 'danger',
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

function firstPersonProfile(profileId = '') {
  const profiles = state.data?.collection_profiles || [];
  const selectedId = profileId || document.getElementById('collection-profile')?.value || FIRST_PERSON_PROFILE_FALLBACK.id;
  return profiles.find((profile) => profile.id === selectedId)
    || profiles.find((profile) => profile.id === FIRST_PERSON_PROFILE_FALLBACK.id)
    || FIRST_PERSON_PROFILE_FALLBACK;
}

function syncCollectionTaskOptions(profile) {
  const select = document.getElementById('collection-task');
  if (!select) return;
  const current = select.value;
  const optionHtml = profile.tasks.map((task) => (
    `<option value="${escapeHtml(task.task_id)}">${escapeHtml(`${task.task_id} · ${task.title}`)}</option>`
  )).join('');
  if (select.dataset.profileId !== profile.id || select.options.length !== profile.tasks.length) {
    select.innerHTML = optionHtml;
    select.dataset.profileId = profile.id;
  }
  if (Array.from(select.options).some((option) => option.value === current)) {
    select.value = current;
  }
}

function collectionAttemptsForRun(runId) {
  return (state.data?.collection_attempts || []).filter((attempt) => attempt.run_id === runId);
}

function collectionUploadedStatus(status) {
  return ['uploaded', 'ready_for_review', 'accepted', 'rejected', 'rework'].includes(status);
}

function collectionProgressForRun(run) {
  const profile = firstPersonProfile(run.profile_id);
  const attempts = collectionAttemptsForRun(run.id);
  const tasks = profile.tasks.map((task) => {
    const taskAttempts = attempts.filter((attempt) => attempt.task_id === task.task_id);
    const attemptCount = taskAttempts.length;
    const uploadedCount = taskAttempts.filter((attempt) => collectionUploadedStatus(attempt.status)).length;
    const acceptedCount = taskAttempts.filter((attempt) => attempt.status === 'accepted').length;
    const remainingAttempts = Math.max(0, task.max_attempts - attemptCount);
    let status = 'collecting';
    if (acceptedCount >= task.required_uploads) {
      status = 'passed';
    } else if (uploadedCount >= task.required_uploads) {
      status = 'ready_for_review';
    } else if (remainingAttempts === 0) {
      status = 'blocked';
    }
    return {
      task_id: task.task_id,
      title: task.title,
      mode: task.mode,
      status,
      attempt_count: attemptCount,
      uploaded_count: uploadedCount,
      accepted_count: acceptedCount,
      remaining_attempts: remainingAttempts,
      required_uploads: task.required_uploads,
      max_attempts: task.max_attempts,
    };
  });
  const blockedTaskCount = tasks.filter((task) => task.status === 'blocked').length;
  const readyTaskCount = tasks.filter((task) => ['ready_for_review', 'passed'].includes(task.status)).length;
  const completedTaskCount = tasks.filter((task) => task.status === 'passed').length;
  let status = 'collecting';
  if (blockedTaskCount) {
    status = 'blocked';
  } else if (completedTaskCount === profile.task_count_required) {
    status = 'passed';
  } else if (readyTaskCount === profile.task_count_required) {
    status = 'ready_for_review';
  }
  return {
    run_id: run.id,
    profile_id: profile.id,
    status,
    completed_task_count: completedTaskCount,
    ready_task_count: readyTaskCount,
    blocked_task_count: blockedTaskCount,
    tasks,
  };
}

function selectedCollectionRun(data) {
  const runs = data.collection_runs || [];
  const runId = document.getElementById('collection-run-id')?.value.trim();
  if (runId) return runs.find((run) => run.id === runId) || null;
  return runs.at(-1) || null;
}

function renderCollection(data) {
  const summary = document.getElementById('collection-summary');
  const matrix = document.getElementById('collection-task-matrix');
  const attemptsNode = document.getElementById('collection-attempt-list');
  if (!summary || !matrix || !attemptsNode) return;

  const profile = firstPersonProfile(document.getElementById('collection-profile')?.value);
  syncCollectionTaskOptions(profile);
  const run = selectedCollectionRun(data);
  const runInput = document.getElementById('collection-run-id');
  if (run && runInput && !runInput.value.trim()) runInput.value = run.id;
  const progress = run ? collectionProgressForRun(run) : null;
  const attempts = run ? collectionAttemptsForRun(run.id) : [];
  const latestAttempt = attempts.at(-1);
  const reviewInput = document.getElementById('collection-review-attempt');
  if (latestAttempt && reviewInput && !reviewInput.value.trim()) reviewInput.value = latestAttempt.id;

  const summaryItems = [
    { label: '批次', content: run?.id || '未创建' },
    { label: '状态', content: progress ? tag(progress.status).value : tag('collecting').value, trusted: true },
    { label: '已达标任务', content: `${progress?.ready_task_count ?? 0}/${profile.task_count_required}` },
    { label: '已通过任务', content: `${progress?.completed_task_count ?? 0}/${profile.task_count_required}` },
    { label: '阻塞任务', content: String(progress?.blocked_task_count ?? 0) },
  ];
  summary.innerHTML = summaryItems.map((item) => (
    `<div><span>${escapeHtml(item.label)}</span><strong>${item.trusted ? item.content : escapeHtml(item.content)}</strong></div>`
  )).join('');

  const progressByTask = new Map((progress?.tasks || []).map((task) => [task.task_id, task]));
  table('collection-task-matrix', ['任务', '模式', '上传', '尝试', '剩余', '状态'], profile.tasks.map((task) => {
    const item = progressByTask.get(task.task_id) || {
      uploaded_count: 0,
      attempt_count: 0,
      remaining_attempts: task.max_attempts,
      required_uploads: task.required_uploads,
      max_attempts: task.max_attempts,
      status: 'collecting',
    };
    return [
      `${task.task_id} · ${task.title}`,
      LABELS[task.mode] || task.mode,
      `${item.uploaded_count}/${item.required_uploads}`,
      `${item.attempt_count}/${item.max_attempts}`,
      String(item.remaining_attempts),
      tag(item.status),
    ];
  }));

  table('collection-attempt-list', ['视频 ID', '任务', '次数', '视频', '状态', '复核'], attempts.slice().reverse().map((attempt) => {
    const review = attempt.review
      ? `${LABELS[attempt.review.decision] || attempt.review.decision} · ${attempt.review.reviewer}`
      : '未复核';
    return [
      attempt.id,
      attempt.task_id,
      String(attempt.attempt_index),
      attempt.video_uri,
      tag(attempt.status),
      review,
    ];
  }));
}

// index.html ships the offline fixtures' identifiers as reference-field defaults;
// against the live backend those records don't exist, so first writes 422 until the
// operator hand-edits the field. Tracks the last value applied per field so loaded
// state can replace an untouched default without ever clobbering a user edit.
const referenceFieldDefaults = {
  'training-dataset': 'warehouse-pick-v1',
  'simulation-model': 'demo-model',
  'deployment-model': 'demo-model',
  'learning-episode': 'episode-000042',
};

function syncReferenceField(fieldId, identifier) {
  if (!identifier) return;
  const input = document.getElementById(fieldId);
  if (!input || (input.value !== '' && input.value !== referenceFieldDefaults[fieldId])) return;
  input.value = identifier;
  referenceFieldDefaults[fieldId] = identifier;
}

function syncReferenceFieldDefaults(data) {
  // Backend reference checks accept datasets by id/name, models by id/name/version,
  // episodes by id/episode_id. Prefer the identifier the tables surface (dataset
  // name, episode_id); models use id, which stays unambiguous across versions.
  // No matching records (e.g. degraded live) -> keep the current default.
  const [dataset] = data.datasets;
  const [model] = data.models;
  const [episode] = data.episodes || [];
  if (dataset) syncReferenceField('training-dataset', dataset.name || dataset.id);
  if (model) {
    syncReferenceField('simulation-model', model.id);
    syncReferenceField('deployment-model', model.id);
  }
  if (episode) syncReferenceField('learning-episode', episode.episode_id || episode.id);
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
  renderCollection(data);
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
  syncReferenceFieldDefaults(data);
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

function requireCollectionRun(runId) {
  const run = state.data.collection_runs.find((item) => item.id === runId);
  if (!run) throw new FieldValidationError('collection-run-id', `未找到试采批次：${runId}`);
  return run;
}

function requireCollectionTask(profile, taskId) {
  const task = profile.tasks.find((item) => item.task_id === taskId);
  if (!task) throw new FieldValidationError('collection-task', `未找到试采任务：${taskId}`);
  return task;
}

function requireNewCollectionAttempt(runId, taskId, attemptIndex, maxAttempts) {
  if (attemptIndex > maxAttempts) {
    throw new FieldValidationError('collection-attempt-index', `录制次数不能超过 ${maxAttempts}`);
  }
  const duplicate = state.data.collection_attempts.find((attempt) => (
    attempt.run_id === runId
    && attempt.task_id === taskId
    && attempt.attempt_index === attemptIndex
  ));
  if (duplicate) throw new FieldValidationError('collection-attempt-index', `该任务第 ${attemptIndex} 次录制已存在`);
}

function requireCollectionAttempt(attemptId) {
  const attempt = state.data.collection_attempts.find((item) => item.id === attemptId);
  if (!attempt) throw new FieldValidationError('collection-review-attempt', `未找到采集视频：${attemptId}`);
  return attempt;
}

function parseCollectionIssueCodes() {
  return value('collection-review-issues')
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean);
}

function requireKnownIssueCodes(profile, issueCodes) {
  const allowed = new Set(profile.issue_codes.map((issue) => issue.id));
  const bad = issueCodes.filter((code) => !allowed.has(code));
  if (bad.length) throw new FieldValidationError('collection-review-issues', `未知问题代码：${bad.join(', ')}`);
}

function collectionStatusForReviewDecision(decision) {
  if (decision === 'accept') return 'accepted';
  if (decision === 'reject') return 'rejected';
  return 'rework';
}

function syncCollectionRunStatus(run) {
  const progress = collectionProgressForRun(run);
  run.status = progress.status;
  run.updated_at = new Date().toISOString();
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
      case 'create-collection-run': {
        const payload = {
          profile_id: value('collection-profile'),
          subject_id: textInput('collection-subject', '采集对象'),
          assignee: textInput('collection-assignee', '负责人'),
        };
        if (liveWrite) {
          const created = await apiWrite(API.collectionRuns, payload);
          document.getElementById('collection-run-id').value = created.id;
          await refreshState({ preserveLiveOnFailure: true });
        } else {
          const now = new Date().toISOString();
          const result = {
            id: `crun-${Date.now()}`,
            status: 'collecting',
            created_at: now,
            updated_at: now,
            ...payload,
          };
          document.getElementById('collection-run-id').value = result.id;
          useLocalWithAudit('collection_runs', result, 'collection.run.create', result.id, result.subject_id);
        }
        break;
      }
      case 'register-collection-attempt': {
        const runId = textInput('collection-run-id', '试采批次');
        const taskId = value('collection-task');
        const attemptIndex = numberInput('collection-attempt-index', '录制次数', 1, 50);
        const payload = {
          task_id: taskId,
          attempt_index: attemptIndex,
          video_uri: textInput('collection-video-uri', '视频 URI', 500),
          status: value('collection-attempt-status'),
        };
        const transcript = document.getElementById('collection-transcript')?.value.trim();
        if (transcript) payload.transcript = transcript;
        assertOfflineReference(liveWrite, () => {
          const run = requireCollectionRun(runId);
          const task = requireCollectionTask(firstPersonProfile(run.profile_id), taskId);
          requireNewCollectionAttempt(runId, taskId, attemptIndex, task.max_attempts);
        });
        if (liveWrite) {
          const created = await apiWrite(`${API.collectionRuns}/${runId}/attempts`, payload);
          document.getElementById('collection-review-attempt').value = created.id;
          await refreshState({ preserveLiveOnFailure: true });
        } else {
          const run = requireCollectionRun(runId);
          const now = new Date().toISOString();
          const result = {
            id: `cat-${Date.now()}`,
            run_id: runId,
            profile_id: run.profile_id,
            deleted: payload.status === 'deleted',
            recorded_at: now,
            duration_seconds: null,
            frame_count: null,
            review: null,
            segment_annotation_ref: null,
            ...payload,
          };
          state.data.collection_attempts.push(result);
          syncCollectionRunStatus(run);
          document.getElementById('collection-review-attempt').value = result.id;
          appendLocalAudit('collection.attempt.create', result.id, result.task_id);
          persistDemoState();
          renderAll();
        }
        break;
      }
      case 'review-collection-attempt': {
        const attemptId = textInput('collection-review-attempt', '复核视频 ID');
        const issueCodes = parseCollectionIssueCodes();
        const payload = {
          decision: value('collection-review-decision'),
          check_results: issueCodes.map((code) => ({ check_id: `issue.${code}`, result: 'fail', note: '' })),
          issue_codes: issueCodes,
          notes: document.getElementById('collection-review-notes')?.value.trim() || '',
        };
        assertOfflineReference(liveWrite, () => {
          const attempt = requireCollectionAttempt(attemptId);
          requireKnownIssueCodes(firstPersonProfile(attempt.profile_id), issueCodes);
        });
        if (liveWrite) {
          await commitLiveWrite(() => apiWrite(`${API.collectionAttempts}/${attemptId}/review`, payload, 'PATCH'));
        } else {
          const attempt = requireCollectionAttempt(attemptId);
          requireKnownIssueCodes(firstPersonProfile(attempt.profile_id), issueCodes);
          attempt.review = {
            reviewer: currentPrincipal().actor,
            reviewed_at: new Date().toISOString(),
            ...payload,
          };
          attempt.status = collectionStatusForReviewDecision(payload.decision);
          const run = requireCollectionRun(attempt.run_id);
          syncCollectionRunStatus(run);
          appendLocalAudit('collection.review', attempt.id, payload.decision);
          persistDemoState();
          renderAll();
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
  button.addEventListener('click', () => {
    if (inFlightActionButtons.has(button)) return;
    inFlightActionButtons.add(button);
    button.disabled = true;
    runAction(button.dataset.action).finally(() => {
      inFlightActionButtons.delete(button);
      button.disabled = false;
      syncWriteControls();
    });
  });
});

if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('sw.js').catch(() => {});
}

setupLogin();
syncWriteControls();
activateModule(moduleFromHash(), false);
refreshState();
