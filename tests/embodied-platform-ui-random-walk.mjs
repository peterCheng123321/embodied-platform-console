// Seeded random walk for the collection UI.
//
// Usage from the Codex in-app browser Node session:
//   const mod = await import('/Users/peter/Downloads/project/embodied-platform-console/tests/embodied-platform-ui-random-walk.mjs');
//   const report = await mod.runCollectionUiRandomWalk({ tab, seed: 20260608, steps: 25 });
//   nodeRepl.write(JSON.stringify(report, null, 2));

export function seededRandom(seed) {
  let state = Number(seed) >>> 0;
  return function next() {
    state = (Math.imul(1664525, state) + 1013904223) >>> 0;
    return state / 0x100000000;
  };
}

function pick(rng, values) {
  return values[Math.floor(rng() * values.length)];
}

function taskId(index) {
  return `task_${String(index).padStart(2, '0')}`;
}

async function expectUnique(tab, selector, label) {
  const locator = tab.playwright.locator(selector);
  const count = await locator.count();
  if (count !== 1) throw new Error(`${label} selector ${selector} matched ${count} elements`);
  return locator;
}

async function click(tab, selector, label) {
  const locator = await expectUnique(tab, selector, label);
  if (!(await locator.isEnabled())) throw new Error(`${label} is disabled`);
  await locator.click({});
}

async function fill(tab, selector, value, label) {
  const locator = await expectUnique(tab, selector, label);
  if (!(await locator.isEnabled())) throw new Error(`${label} is disabled`);
  await locator.fill(String(value), {});
}

async function selectValue(tab, selector, value, label) {
  const locator = await expectUnique(tab, selector, label);
  if (!(await locator.isEnabled())) throw new Error(`${label} is disabled`);
  await locator.selectOption(String(value), {});
}

async function settle(tab) {
  await tab.playwright.waitForTimeout(250);
}

async function readCollectionState(tab) {
  return tab.playwright.evaluate(() => {
    const text = (selector) => document.querySelector(selector)?.textContent?.trim() || '';
    const value = (selector) => document.querySelector(selector)?.value || '';
    const hidden = (selector) => Boolean(document.querySelector(selector)?.hidden);
    const rows = Array.from(document.querySelectorAll('#collection-task-matrix .row:not(.header):not(.empty)'));
    const attemptRows = Array.from(document.querySelectorAll('#collection-attempt-list .row:not(.header):not(.empty)'));
    return {
      url: location.href,
      apiStatus: text('#api-status'),
      modeBanner: text('#mode-banner'),
      signedIn: !hidden('#principal-label') && Boolean(text('#principal-label')),
      activeCollection: document.querySelector('#collection-panel')?.getAttribute('aria-hidden') === 'false',
      runId: value('#collection-run-id'),
      reviewAttempt: value('#collection-review-attempt'),
      taskMatrixRowCount: rows.length,
      taskMatrixText: text('#collection-task-matrix'),
      attemptRowCount: attemptRows.length,
      attemptText: text('#collection-attempt-list'),
      fieldError: text('.field-error'),
      disabledActions: Array.from(document.querySelectorAll('#collection-panel [data-action]'))
        .filter((button) => button.disabled)
        .map((button) => button.dataset.action),
    };
  });
}

async function ensureCollectionPage(tab, targetUrl) {
  const currentUrl = await tab.url();
  if (!currentUrl || !currentUrl.startsWith(targetUrl.split('#')[0])) {
    await tab.goto(targetUrl);
  } else if (!currentUrl.endsWith('#collection')) {
    await tab.goto(targetUrl);
  } else {
    await tab.reload();
  }
  await tab.playwright.waitForLoadState({ state: 'domcontentloaded', timeoutMs: 10000 });
  await expectUnique(tab, '#collection-panel', 'collection panel');
  await settle(tab);
}

async function ensureSignedIn(tab, passcode) {
  let state = await readCollectionState(tab);
  if (state.signedIn) return;
  await click(tab, '#login-toggle', 'login toggle');
  await fill(tab, '#login-passcode', passcode, 'login passcode');
  await click(tab, '#login-submit', 'login submit');
  await tab.playwright.locator('#principal-label').waitFor({ state: 'visible', timeoutMs: 5000 });
  await settle(tab);
  state = await readCollectionState(tab);
  if (!state.signedIn) throw new Error('login did not produce a signed principal');
}

async function assertUiInvariants(tab, log, allowUserError = false) {
  const state = await readCollectionState(tab);
  if (!state.activeCollection) throw new Error(`collection panel inactive after ${log.action}`);
  if (state.taskMatrixRowCount !== 8) throw new Error(`expected 8 task matrix rows, saw ${state.taskMatrixRowCount}`);
  if (!state.signedIn) throw new Error(`principal lost after ${log.action}`);
  if (state.disabledActions.length) throw new Error(`collection actions disabled after ${log.action}: ${state.disabledActions.join(', ')}`);
  if (!allowUserError && (state.fieldError || state.apiStatus.includes('操作失败'))) {
    throw new Error(`unexpected UI error after ${log.action}: ${state.fieldError || state.apiStatus}`);
  }
  return state;
}

async function createRun(tab, context, step) {
  const suffix = `${context.seed}-${step}`;
  await fill(tab, '#collection-subject', `ui-subject-${suffix}`, 'collection subject');
  await fill(tab, '#collection-assignee', `ui-agent-${suffix}`, 'collection assignee');
  await click(tab, '[data-action="create-collection-run"]', 'create collection run');
  await settle(tab);
  const state = await readCollectionState(tab);
  if (!state.runId.startsWith('crun_') && !state.runId.startsWith('crun-')) {
    throw new Error(`create run did not set a run id: ${state.runId}`);
  }
  context.runId = state.runId;
  context.usedAttempts = new Set();
  return state;
}

async function registerAttempt(tab, context, step, { duplicate = false } = {}) {
  if (!context.runId) await createRun(tab, context, step);
  let selectedTask = taskId(1 + Math.floor(context.rng() * 8));
  let attemptIndex = 1 + Math.floor(context.rng() * 8);
  if (duplicate && context.usedAttempts.size) {
    const key = pick(context.rng, Array.from(context.usedAttempts));
    [selectedTask, attemptIndex] = key.split(':');
  } else {
    let guard = 0;
    while (context.usedAttempts.has(`${selectedTask}:${attemptIndex}`) && guard < 80) {
      selectedTask = taskId(1 + Math.floor(context.rng() * 8));
      attemptIndex = 1 + Math.floor(context.rng() * 8);
      guard += 1;
    }
  }
  await selectValue(tab, '#collection-task', selectedTask, 'collection task');
  await fill(tab, '#collection-attempt-index', attemptIndex, 'collection attempt index');
  await selectValue(tab, '#collection-attempt-status', pick(context.rng, ['uploaded', 'recorded', 'deleted']), 'collection attempt status');
  await fill(tab, '#collection-video-uri', `file:///ui-random/${context.seed}/${context.runId}/${selectedTask}-${attemptIndex}.mp4`, 'collection video URI');
  await fill(tab, '#collection-transcript', pick(context.rng, ['操作开始。操作结束，任务成功。', '任务名称：随机 UI 试采。正在执行动作。']), 'collection transcript');
  await click(tab, '[data-action="register-collection-attempt"]', 'register collection attempt');
  await settle(tab);
  const state = await readCollectionState(tab);
  if (!duplicate) {
    context.usedAttempts.add(`${selectedTask}:${attemptIndex}`);
    context.reviewAttempt = state.reviewAttempt;
    if (!state.reviewAttempt) throw new Error('register attempt did not populate review attempt id');
  }
  return state;
}

async function reviewAttempt(tab, context, step, { unknownIssue = false } = {}) {
  if (!context.reviewAttempt) await registerAttempt(tab, context, step);
  await fill(tab, '#collection-review-attempt', context.reviewAttempt, 'review attempt id');
  await selectValue(tab, '#collection-review-decision', pick(context.rng, ['accept', 'reject', 'needs_rework']), 'review decision');
  await fill(tab, '#collection-review-issues', unknownIssue ? 'not_a_real_issue' : pick(context.rng, ['', 'missing_required_speech', 'gripper_out_of_frame']), 'review issue codes');
  await fill(tab, '#collection-review-notes', `ui random review ${context.seed}/${step}`, 'review notes');
  await click(tab, '[data-action="review-collection-attempt"]', 'review collection attempt');
  await settle(tab);
  return readCollectionState(tab);
}

async function reloadCollection(tab, context, targetUrl) {
  await tab.reload();
  await tab.playwright.waitForLoadState({ state: 'domcontentloaded', timeoutMs: 10000 });
  await settle(tab);
  await ensureSignedIn(tab, context.passcode);
  if (context.runId) await fill(tab, '#collection-run-id', context.runId, 'collection run id');
  return readCollectionState(tab);
}

export async function runCollectionUiRandomWalk({
  tab,
  seed = 20260608,
  steps = 25,
  targetUrl = 'http://127.0.0.1:3000/app/#collection',
  passcode = 'ground-control-dev',
} = {}) {
  if (!tab) throw new Error('runCollectionUiRandomWalk requires a Codex browser tab');
  const rng = seededRandom(seed);
  const context = { seed, rng, passcode, runId: '', reviewAttempt: '', usedAttempts: new Set() };
  const entries = [];
  const failures = [];
  const startedAt = Date.now();

  try {
    await ensureCollectionPage(tab, targetUrl);
    await ensureSignedIn(tab, passcode);
    await createRun(tab, context, 0);
    await assertUiInvariants(tab, { action: 'bootstrap' });
  } catch (error) {
    return { seed, steps, entries, failures: [`bootstrap: ${error.message}`] };
  }

  const actions = [
    'register_attempt',
    'register_attempt',
    'review_attempt',
    'review_attempt',
    'register_duplicate',
    'review_unknown_issue',
    'reload',
    'create_run',
  ];

  for (let step = 1; step <= steps; step += 1) {
    const action = pick(rng, actions);
    const log = { step, action };
    try {
      let state;
      if (action === 'create_run') state = await createRun(tab, context, step);
      if (action === 'register_attempt') state = await registerAttempt(tab, context, step);
      if (action === 'review_attempt') state = await reviewAttempt(tab, context, step);
      if (action === 'register_duplicate') state = await registerAttempt(tab, context, step, { duplicate: true });
      if (action === 'review_unknown_issue') state = await reviewAttempt(tab, context, step, { unknownIssue: true });
      if (action === 'reload') state = await reloadCollection(tab, context, targetUrl);
      const allowUserError = action === 'register_duplicate' || action === 'review_unknown_issue';
      state = await assertUiInvariants(tab, log, allowUserError);
      entries.push({ ...log, ok: true, runId: state.runId, reviewAttempt: state.reviewAttempt, apiStatus: state.apiStatus });
    } catch (error) {
      failures.push(`${step}:${action}: ${error.message}`);
      break;
    }
  }

  const errorLogs = (await tab.dev.logs({ levels: ['error'], limit: 20 }))
    .filter((entry) => Date.parse(entry.timestamp) >= startedAt);
  if (errorLogs.length) {
    failures.push(`browser console errors: ${errorLogs.map((entry) => entry.message).join(' | ')}`);
  }
  const finalState = await readCollectionState(tab);
  return { seed, steps, entries, failures, finalState };
}
