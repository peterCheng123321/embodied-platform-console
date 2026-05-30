import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';

const root = process.cwd();
const appDir = path.join(root, 'apps', 'embodied-platform');
const htmlPath = path.join(appDir, 'index.html');
const cssPath = path.join(appDir, 'assets', 'embodied-platform.css');
const jsPath = path.join(appDir, 'assets', 'embodied-platform.js');
const manifestPath = path.join(appDir, 'assets', 'manifest.webmanifest');
const iconPath = path.join(appDir, 'assets', 'icon.svg');
const fixturePath = path.join(appDir, 'fixtures', 'demo-state.json');

assert.equal(fs.existsSync(appDir), true, 'apps/embodied-platform folder should exist');
assert.equal(fs.existsSync(htmlPath), true, 'embodied platform index.html should exist');
assert.equal(fs.existsSync(cssPath), true, 'embodied platform CSS should exist');
assert.equal(fs.existsSync(jsPath), true, 'embodied platform JS should exist');
assert.equal(fs.existsSync(manifestPath), true, 'embodied platform PWA manifest should exist');
assert.equal(fs.existsSync(iconPath), true, 'embodied platform should ship a PWA icon');
assert.equal(fs.existsSync(fixturePath), true, 'embodied platform should ship demo fallback fixtures');

const html = fs.readFileSync(htmlPath, 'utf8');
const css = fs.readFileSync(cssPath, 'utf8');
const js = fs.readFileSync(jsPath, 'utf8');
const manifest = fs.readFileSync(manifestPath, 'utf8');
const icon = fs.readFileSync(iconPath, 'utf8');
const fixture = fs.readFileSync(fixturePath, 'utf8');
const all = `${html}\n${css}\n${js}\n${manifest}\n${icon}\n${fixture}`;
const visibleCopy = `${html}\n${js}\n${manifest}\n${fixture}`;

const modules = [
  ['data-management', 'multimodal data management'],
  ['annotation', 'intelligent annotation'],
  ['training', 'training optimization'],
  ['models', 'model version management'],
  ['simulation', 'simulation sim2real'],
  ['deployment', 'edge deployment'],
  ['learning', 'online fine-tuning learning'],
  ['monitoring', 'monitoring dashboard'],
  ['audit', 'logs audit'],
  ['system', 'system management'],
];

for (const [id, label] of modules) {
  assert.match(html, new RegExp(`data-module="${id}"`), `${label} module should be represented`);
  assert.match(html, new RegExp(`id="${id}-panel"`), `${label} panel should exist`);
  assert.match(js, new RegExp(`${id}`), `${label} module should be handled in JS`);
}

assert.doesNotMatch(all, /medical|clinical|lesion|dicom|ct scan|radiology/i, 'medical copy should not drive the embodied-only app');
assert.match(html, /<html lang="zh-CN">/, 'embodied app should declare Simplified Chinese language');
assert.match(html, /具身平台运营台/, 'main product title should be Simplified Chinese');
assert.match(html, /数据集接入与片段登记/, 'data management panel should be localized');
assert.match(html, /保存标注/, 'annotation primary action should be localized');
assert.match(html, /激活模型/, 'model primary action should be localized');
assert.match(js, /排队中/, 'job status labels should be localized');
assert.match(js, /暂无记录/, 'empty table state should be localized');
assert.match(js, /需要签名写入权限/, 'live read-only message should be localized');
assert.match(manifest, /具身平台运营台/, 'PWA manifest should be localized');
assert.match(manifest, /icon\.svg/, 'PWA manifest should include an install icon');
assert.match(manifest, /maskable/, 'PWA manifest icon should support maskable installation surfaces');
assert.match(fixture, /机器人单元/, 'demo fixture readable descriptions should be localized');
assert.doesNotMatch(
  visibleCopy,
  /Embodied Platform Operations|Embodied production console|Create dataset|Save annotation|Activate model|No records yet|api live read-only|action failed|Dataset name is required|Pick and place episodes/i,
  'major user-visible embodied platform copy should be Chinese',
);
assert.match(html, /<main class="platform-workspace"/, 'first screen should be the dense operational workspace');
assert.doesNotMatch(html, /hero|landing|marketing/i, 'new app should not be a marketing landing page');

const primaryActions = [
  'create-dataset',
  'create-episode',
  'start-import',
  'save-annotation',
  'start-training',
  'activate-model',
  'start-simulation',
  'create-deployment',
  'enqueue-learning',
  'refresh-monitoring',
  'write-audit',
  'save-settings',
];

for (const action of primaryActions) {
  assert.match(html, new RegExp(`data-action="${action}"`), `${action} should exist in HTML`);
  assert.match(js, new RegExp(`case '${action}'|case "${action}"|${action}`), `${action} should be wired in JS`);
}

for (const endpoint of [
  '/api/embodied-platform/datasets',
  '/api/embodied-platform/episodes',
  '/api/embodied-platform/imports',
  '/api/embodied-platform/annotation-tasks',
  '/api/embodied-platform/training-jobs',
  '/api/embodied-platform/models',
  '/api/embodied-platform/simulation-jobs',
  '/api/embodied-platform/deployments',
  '/api/embodied-platform/learning-queue',
  '/api/embodied-platform/monitoring/overview',
  '/api/embodied-platform/audit-events',
  '/api/embodied-platform/system/settings',
]) {
  assert.match(js, new RegExp(endpoint), `${endpoint} should be present in the API client`);
}

assert.match(html, /<link rel="manifest"/, 'PWA manifest affordance should be declared');
assert.match(html, /<meta name="theme-color"/, 'PWA theme color should be declared');
assert.match(js, /serviceWorker/, 'service worker/offline affordance should be wired');
assert.match(js, /demo-state\.json/, 'JSON demo fallback should be used when API is unavailable');
assert.match(js, /embodied\.signature/, 'live writes should require a signed principal from the host shell');
assert.doesNotMatch(js, /X-Embodied-Role': 'admin'|X-Embodied-Role": "admin"/, 'frontend should not hard-code admin writes');
assert.match(js, /window\.location\.hash/, 'module navigation should support hash deep links');
assert.match(js, /hashchange/, 'module navigation should restore deep links on hash changes and reloads');
assert.match(js, /localStorage/, 'offline demo writes should persist locally across reloads');
assert.match(js, /button\.disabled = !state\.ready \|\| Boolean\(writeBlockReason\(action\)\)/, 'live read-only mode should disable primary write controls');
assert.match(js, /textInput\(/, 'offline form writes should validate required text before mutating state');
assert.match(js, /state\.ready/, 'actions should be gated until initial state is loaded');
assert.match(js, /Promise\.allSettled/, 'live reads should not silently downgrade the whole app to demo mode on one endpoint failure');
assert.match(js, /assertOfflineReference/, 'offline-only reference checks should not block fresh live backend writes');
assert.match(js, /refreshState\(\)/, 'live writes should refresh canonical backend state after mutation');
assert.match(js, /setFieldError/, 'field-level validation should render inline accessible errors');
assert.match(js, /requireNewLearningIdentity/, 'offline learning queue should reject duplicate logical entries');
assert.match(js, /Number\.isInteger/, 'numeric validation should require bounded integers');
assert.match(js, /AbortController/, 'API reads and writes should have request timeouts');
assert.match(js, /API_READ_TIMEOUT_MS/, 'API read timeout should be explicit');
assert.match(js, /ACTION_ROLES/, 'frontend should gate live write buttons by backend role');
assert.match(js, /roleAllowedForAction/, 'role-specific live write gating should be implemented');
assert.match(js, /preserveLiveOnFailure/, 'live write refresh failures should not silently fall back to demo mode');
assert.match(js, /ArrowRight/, 'tablist navigation should support keyboard arrow movement');
assert.match(
  js,
  /case 'create-episode':[\s\S]*frame_count: numberInput\('episode-frames'[\s\S]*requireNewEpisodeIdentity/,
  'episode frame validation should run before duplicate identity checks',
);
assert.match(js, /aria-current/, 'active module navigation should expose accessible current state');
assert.match(js, /data-label/, 'mobile table rows should expose labels for collapsed cells');
assert.doesNotMatch(js, /using local fallback/, 'live-read mode should not create volatile local rows for rejected writes');
assert.match(html, /name="viewport"/, 'responsive viewport should be declared');
assert.match(css, /@media \(max-width: 900px\)/, 'responsive tablet/mobile layout should be defined');
assert.match(css, /@media \(max-width: 640px\)/, 'compact mobile layout should be defined');
assert.doesNotMatch(css, /radial-gradient|gradient orb|bokeh/i, 'UI should avoid decorative gradient/orb backgrounds');
assert.match(css, /button:disabled/, 'disabled controls should have explicit visual treatment');
assert.match(css, /\.cell-label/, 'mobile table/card labels should be styled');
assert.match(css, /\.module-panel\s*{[^}]*grid-column:\s*2/s, 'desktop module panels should be pinned to the main workspace column');
assert.match(html, /embodied-platform\.css\?v=\d+/, 'CSS asset should be versioned to avoid stale service worker/browser cache');
assert.match(html, /embodied-platform\.js\?v=\d+/, 'JS asset should be versioned to avoid stale service worker/browser cache');
const cssVersion = html.match(/embodied-platform\.css\?v=(\d+)/)?.[1];
const jsVersion = html.match(/embodied-platform\.js\?v=(\d+)/)?.[1];

const sw = fs.readFileSync(path.join(appDir, 'sw.js'), 'utf8');
assert.match(sw, /skipWaiting/, 'service worker should activate new versions promptly');
assert.match(sw, /clients\.claim/, 'service worker should claim clients after activation');
assert.match(sw, /caches\.delete/, 'service worker should clean old embodied platform caches');
assert.match(sw, /manifest\.webmanifest/, 'service worker should precache the manifest');
assert.match(sw, /icon\.svg/, 'service worker should precache the PWA icon');
assert.match(sw, new RegExp(`embodied-platform\\.css\\?v=${cssVersion}`), 'service worker CSS cache version should match index.html');
assert.match(sw, new RegExp(`embodied-platform\\.js\\?v=${jsVersion}`), 'service worker JS cache version should match index.html');

// ---------------------------------------------------------------------------
// §4 redesign markers — "Azure" light blue + white instrument console.
// These assert the actual re-theme is present (would fail on a revert to the
// old dark Ground Control teal-green theme / plain-table monitoring / unstyled
// tags), not tautologies.
// ---------------------------------------------------------------------------

// Azure light design tokens defined in :root (spec §2).
for (const token of ['--bg:', '--surface:', '--surface-2:', '--hairline:', '--ink:', '--brand:', '--brand-lum:', '--st-info:', '--st-ok:', '--st-warn:', '--st-danger:']) {
  assert.match(css, new RegExp(token.replace(/[-]/g, '\\$&')), `design token ${token} should be defined in CSS :root`);
}
assert.match(css, /--bg:\s*#f4f7fb/, 'app background should be the cool white-blue Azure surface');
assert.match(css, /--surface:\s*#ffffff/, 'panels should be white cards in the Azure light theme');
assert.match(css, /--ink:\s*#0f2747/, 'primary text should be the deep navy ink');
assert.match(css, /--brand-lum:\s*#2563eb/, 'vivid azure accent should be defined');
assert.match(css, /--st-ok:\s*#2563eb/, 'ok/active status should be on-brand blue — no green in the palette');
assert.doesNotMatch(css, /#059669|rgba\(5,\s*150,\s*105/i, 'no emerald/green literals should remain (blue + white only)');
// The old dark Ground Control teal-green palette must be fully gone.
assert.doesNotMatch(css, /#34e0a1|#1f8f78|#2f6f63|rgba\(52,\s*224,\s*161/i, 'old teal-green brand/grain literals should be removed');
assert.doesNotMatch(css, /--bg:\s*#08110f/, 'old dark Ground Control background should be removed');

// Three Google Font families (spec §1): IBM Plex Sans SC, IBM Plex Mono, Chakra Petch.
for (const family of ['IBM\\+Plex\\+Sans\\+SC', 'IBM\\+Plex\\+Mono', 'Chakra\\+Petch']) {
  assert.match(html, new RegExp(family), `Google Fonts link should request ${family.replace(/\\\+/g, ' ')}`);
}
for (const stack of ['IBM Plex Sans SC', 'IBM Plex Mono', 'Chakra Petch']) {
  assert.match(css, new RegExp(stack), `CSS font stack should use ${stack}`);
}
assert.doesNotMatch(css, /font-family:[^;]*\bInter\b/i, 'Inter should be replaced by the IBM Plex / Chakra Petch type system');

// Semantic status tag classes (spec §2 status->token map).
for (const cls of ['.tag--neutral', '.tag--info', '.tag--ok', '.tag--warn', '.tag--danger', '.tag--faint']) {
  assert.match(css, new RegExp(cls.replace(/[.-]/g, '\\$&')), `semantic tag class ${cls} should be styled`);
}
// tag() must emit a semantic class derived from the status, still escaped.
assert.match(js, /tag--\$\{token\}/, 'tag() should attach a semantic status class to each tag');
assert.match(js, /STATUS_TOKENS/, 'tag() should derive its color from the status->token map');
assert.match(js, /escapeHtml\(LABELS\[text\]/, 'tag() must keep escaping its dynamic label');
for (const [status, token] of [['running', 'info'], ['succeeded', 'ok'], ['review', 'warn'], ['failed', 'danger'], ['low', 'faint'], ['queued', 'neutral']]) {
  assert.match(js, new RegExp(`${status}:\\s*'${token}'`), `status '${status}' should map to the '${token}' token`);
}

// Button hierarchy (spec §3) — classes both styled and applied.
for (const cls of ['.btn-primary', '.btn-secondary', '.btn-danger']) {
  assert.match(css, new RegExp(cls.replace(/[.-]/g, '\\$&')), `button class ${cls} should be styled`);
}
assert.match(html, /data-action="reset-demo"[^>]*class="btn-danger"|class="btn-danger"[^>]*data-action="reset-demo"/, 'destructive reset should use the danger button');
assert.match(html, /class="btn-primary"/, 'panel primary actions should use the primary button');
assert.match(html, /class="btn-secondary"/, 'secondary/refresh actions should use the secondary button');

// Monitoring visual board (spec §3 headline) — styled + rendered, with table fallback kept.
for (const cls of ['.mon-board', '.mon-tile', '.mon-tile__value', '.mon-tile__bar', '.mon-gauge', '.mon-gauge__fill']) {
  assert.match(css, new RegExp(cls.replace(/[.-]/g, '\\$&')), `monitoring board class ${cls} should be styled`);
}
assert.match(html, /id="monitoring-board"/, 'monitoring board mount should exist');
assert.match(html, /id="monitoring-list"/, 'monitoring table fallback should be retained');
assert.match(js, /renderMonitoring/, 'monitoring should render a visual board, not only a table');
assert.match(js, /mon-tile mon-tile--/, 'monitoring metrics should render as semantic instrument tiles');
assert.match(js, /mon-gauge__fill/, 'sim success rate should render as a gauge');
assert.match(js, /sim_success_rate/, 'monitoring gauge should read sim_success_rate');
assert.match(js, /MONITORING_TILE_KEYS[\s\S]*unknownEntries/, 'unknown monitoring metrics should fall back to the table');

// Login control (spec §5) — ids present + wired to /session with sessionStorage principal.
for (const id of ['login-toggle', 'login-form', 'login-actor', 'login-role', 'login-passcode', 'login-submit', 'principal-label', 'logout-btn']) {
  assert.match(html, new RegExp(`id="${id}"`), `login control #${id} should exist`);
}
assert.match(html, /role="dialog"/, 'login form should be an accessible dialog');
assert.match(js, /\/api\/embodied-platform\/session/, 'login should call the session endpoint');
assert.match(js, /sessionStorage\.setItem\('embodied\.signature'/, 'login should store the signed principal signature');
assert.match(js, /sessionStorage\.removeItem\('embodied\.signature'/, 'logout should clear the stored signature');
assert.match(js, /submitLogin/, 'login submit handler should be wired');
assert.match(js, /renderPrincipal/, 'header should reflect the signed-in principal');

// Login deadlock fix: form-locking must NOT disable the login inputs (which live
// outside .module-panel), or sign-in is impossible in the live+unsigned state.
assert.match(js, /\.module-panel input, \.module-panel select/, 'write-form locking must be scoped to module panels so login stays usable');
assert.doesNotMatch(js, /querySelectorAll\('input, select'\)/, 'form-locking must not blanket-disable every input/select (would deadlock login)');

// PWA light theming (spec §4) — Azure blue + white.
assert.match(html, /<meta name="theme-color" content="#ffffff">/, 'theme-color meta should be the light white surface');
assert.match(manifest, /"theme_color":\s*"#ffffff"/, 'manifest theme_color should be light');
assert.match(manifest, /"background_color":\s*"#f4f7fb"/, 'manifest background_color should be the cool white-blue surface');
assert.match(icon, /#ffffff/, 'PWA icon should adopt the white Azure surface');
assert.match(icon, /#2563eb/, 'PWA icon should carry the vivid azure brand accent');
assert.doesNotMatch(icon, /#08110f|#34e0a1|#1f8f78/, 'PWA icon should drop the old dark teal-green fills');

console.log('Embodied platform audit passed');
