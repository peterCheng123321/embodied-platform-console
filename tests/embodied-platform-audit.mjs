import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';

const root = process.cwd();
const appDir = path.join(root, 'apps', 'embodied-platform');
const labelerDir = path.join(root, 'apps', 'embodied-labeler');
const htmlPath = path.join(appDir, 'index.html');
const cssPath = path.join(appDir, 'assets', 'embodied-platform.css');
const platformGlassPath = path.join(appDir, 'assets', 'platform-glass.css');
const glassRefractPath = path.join(root, 'apps', '_vendor', 'glass', 'refract.js');
const jsPath = path.join(appDir, 'assets', 'embodied-platform.js');
const manifestPath = path.join(appDir, 'assets', 'manifest.webmanifest');
const iconPath = path.join(appDir, 'assets', 'icon.svg');
const fixturePath = path.join(appDir, 'fixtures', 'demo-state.json');
const uiRandomWalkPath = path.join(root, 'tests', 'embodied-platform-ui-random-walk.mjs');
const backendMainPath = path.join(root, 'backend', 'api', 'main.py');
const backendPyprojectPath = path.join(root, 'backend', 'pyproject.toml');
const eventRoutesPath = path.join(root, 'backend', 'api', 'embodied_platform', 'event_routes.py');

assert.equal(fs.existsSync(appDir), true, 'apps/embodied-platform folder should exist');
assert.equal(fs.existsSync(htmlPath), true, 'embodied platform index.html should exist');
assert.equal(fs.existsSync(cssPath), true, 'embodied platform CSS should exist');
assert.equal(fs.existsSync(platformGlassPath), true, 'embodied platform glass skin should exist');
assert.equal(fs.existsSync(glassRefractPath), true, 'shared glass refraction runtime should exist');
assert.equal(fs.existsSync(jsPath), true, 'embodied platform JS should exist');
assert.equal(fs.existsSync(manifestPath), true, 'embodied platform PWA manifest should exist');
assert.equal(fs.existsSync(iconPath), true, 'embodied platform should ship a PWA icon');
assert.equal(fs.existsSync(fixturePath), true, 'embodied platform should ship demo fallback fixtures');
assert.equal(fs.existsSync(uiRandomWalkPath), true, 'collection UI should ship a seeded browser random-walk runner');
assert.equal(fs.existsSync(labelerDir), true, 'unified platform should mount the temporal labeler under apps/embodied-labeler');
assert.equal(fs.existsSync(eventRoutesPath), true, 'unified host should own the retired event-ingest compatibility router');

const html = fs.readFileSync(htmlPath, 'utf8');
const css = fs.readFileSync(cssPath, 'utf8');
const platformGlass = fs.readFileSync(platformGlassPath, 'utf8');
const glassRefract = fs.readFileSync(glassRefractPath, 'utf8');
const js = fs.readFileSync(jsPath, 'utf8');
const manifest = fs.readFileSync(manifestPath, 'utf8');
const icon = fs.readFileSync(iconPath, 'utf8');
const fixture = fs.readFileSync(fixturePath, 'utf8');
const uiRandomWalk = fs.existsSync(uiRandomWalkPath) ? fs.readFileSync(uiRandomWalkPath, 'utf8') : '';
const backendMain = fs.readFileSync(backendMainPath, 'utf8');
const backendPyproject = fs.readFileSync(backendPyprojectPath, 'utf8');
const eventRoutes = fs.readFileSync(eventRoutesPath, 'utf8');
const labelerHtmlPath = path.join(labelerDir, 'index.html');
const labelerJsPath = path.join(labelerDir, 'assets', 'embodied', 'embodied.js');
const labelerConsoleJsPath = path.join(labelerDir, 'assets', 'console', 'embodied-console.js');
const embodiedRoutesPath = path.join(root, 'backend', 'api', 'embodied', 'routes.py');
const embodiedQcPath = path.join(root, 'backend', 'api', 'embodied', 'qc.py');
assert.equal(fs.existsSync(labelerHtmlPath), true, 'hosted labeler should have an index.html entrypoint');
assert.equal(fs.existsSync(labelerJsPath), true, 'hosted labeler should carry the temporal annotation JS');
assert.equal(fs.existsSync(labelerConsoleJsPath), true, 'hosted labeler should carry console episode-tree wiring');
assert.equal(fs.existsSync(embodiedQcPath), true, 'platform should own a small trajectory QC scorer instead of requiring the fork viewer');
assert.equal(fs.existsSync(path.join(labelerDir, 'assets', 'console', 'ops.js')), false, 'hosted labeler should not retain obsolete split-app ops.js');
const labelerHtml = fs.readFileSync(labelerHtmlPath, 'utf8');
const labelerJs = fs.readFileSync(labelerJsPath, 'utf8');
const labelerConsoleJs = fs.readFileSync(labelerConsoleJsPath, 'utf8');
const embodiedRoutes = fs.readFileSync(embodiedRoutesPath, 'utf8');
const embodiedQc = fs.readFileSync(embodiedQcPath, 'utf8');
const all = `${html}\n${css}\n${js}\n${manifest}\n${icon}\n${fixture}`;
const visibleCopy = `${html}\n${js}\n${manifest}\n${fixture}`;

const modules = [
  ['data-management', 'multimodal data management'],
  ['collection', 'first-person collection workflow'],
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
assert.match(css, /\.platform-header\s*{[\s\S]*width: calc\(100% - clamp\(1rem, 2\.2vw, 2\.2rem\)\)[\s\S]*margin: clamp\(0\.55rem, 1\.2vw, 0\.9rem\) auto clamp\(0\.55rem, 1\.2vw, 0\.9rem\)[\s\S]*top: 0/, 'header should be a contained sticky bar, not a full-bleed viewport strip');

// Unified platform seam: the full temporal labeler is no longer a separate
// localhost app. The console hosts it and its /api/embodied compatibility
// surface on the same origin.
assert.match(html, /href="\/labeler\/\?dataset=demo&amp;episode=0"/, 'annotation module should open the hosted temporal labeler');
assert.match(backendMain, /from \.embodied\.routes import router as embodied_router/, 'host backend must include the temporal labeler API router');
assert.match(backendMain, /from \.embodied_platform\.event_routes import router as event_ingest_router/, 'host backend must include the retired event ingest router');
assert.match(backendMain, /app\.include_router\(embodied_router\)/, 'host backend must mount /api/embodied routes');
assert.match(backendMain, /app\.include_router\(event_ingest_router\)/, 'host backend must mount /v1/events routes');
assert.match(backendMain, /app\.mount\(\s*"\/labeler"/, 'host backend must mount the temporal labeler under /labeler');
assert.match(backendMain, /app\.mount\(\s*"\/embodied-assets"/, 'host backend must serve built-in labeler demo assets');
assert.match(backendMain, /app\.mount\(\s*"\/embodied-cache"/, 'host backend must serve materialized episode bundles');
assert.match(backendPyproject, /"pyarrow>=16"/, 'host backend must declare pyarrow for recorded LeRobot dataset routes');
assert.doesNotMatch(`${html}\n${js}\n${labelerHtml}\n${labelerJs}\n${labelerConsoleJs}`, /127\.0\.0\.1:8000|127\.0\.0\.1:8001|localhost:8000|localhost:8001/, 'unified platform UI must not call or link to split localhost apps');
const labelerJsVersion = labelerHtml.match(/assets\/embodied\/embodied\.js\?v=(\d+)/)?.[1];
assert.ok(labelerJsVersion, 'hosted labeler should include a versioned temporal JS asset');
assert.match(labelerJs, /escapeHtml\(skill\.label\)/, 'palette must escape skill labels (XSS sink)');
const swSrc = fs.readFileSync(path.join(root, 'apps', 'embodied-platform', 'sw.js'), 'utf8');
assert.match(swSrc, /mode === 'navigate'[\s\S]{0,200}caches\.match\('\.\/index\.html'\)/, 'sw must serve the app shell for offline navigations (URL-key mismatch fix)');
const labelerCss = fs.readFileSync(path.join(labelerDir, 'assets', 'embodied', 'embodied.css'), 'utf8');
for (const tok of ['--r-1: 4px', '--r-2: 8px', '--motion-fast: 120ms', '--motion-base: 180ms', '--ease: cubic-bezier(0.2, 0, 0, 1)']) {
  assert.ok(css.includes(tok), `platform css must carry the shared design token ${tok}`);
  assert.ok(labelerCss.includes(tok), `labeler css must carry the shared design token ${tok}`);
}
assert.doesNotMatch(`${css}\n${labelerCss}\n${platformGlass}`, /transition:\s*all\b/, 'no transition:all anywhere (motion grammar)');
assert.match(labelerJs, /If-Match/, 'labeler saves must carry the optimistic-concurrency If-Match token');
assert.match(labelerJs, /409/, 'labeler must handle the stale-write conflict status');
assert.match(labelerHtml, /<video[^>]*\bmuted\b/, 'labeler video must be muted (no audio track; Chrome power policy pauses unmuted video-only media)');
assert.match(labelerJs, /armVideoStallFallback[\s\S]{0,2400}createObjectURL/, 'labeler must carry the media-stall blob fallback (Chrome instrumented-profile fix)');
assert.match(labelerJs, /state\.pendingStart !== null[\s\S]{0,200}片段未关闭/, 'manual save must guard on an open segment (f4c09c9 re-port)');
assert.match(labelerJs, /e\.metaKey \|\| e\.ctrlKey/, 'digit hotkeys must not hijack Cmd\/Ctrl tab-switching (f4c09c9 re-port)');
assert.match(labelerJs, /iouByIdForLanes/, 'renderLanes must hoist IoU matching out of the per-segment loop (f4c09c9 re-port)');
assert.match(labelerJs, /window\.location\.origin/, 'hosted labeler JS should default API calls to the current host origin');
assert.match(labelerConsoleJs, /window\.location\.origin/, 'hosted labeler episode tree should default API calls to the current host origin');
assert.match(embodiedRoutes, /\/datasets\/\{dataset_id\}\/episodes\/\{episode_index\}\/qc/, 'host backend must expose episode QC scoring on the unified API');
assert.match(embodiedQc, /temporal_iou/, 'platform QC scorer should include temporal IoU scoring');
assert.match(embodiedQc, /JEFFREYS_ALPHA0\s*=\s*0\.5/, 'platform QC scorer should use the LeRobot QC Jeffreys prior');
assert.doesNotMatch(embodiedQc, /gradio|sentence_transformers|lerobot\.quality\.viewer/i, 'platform QC scorer must not depend on the standalone fork viewer stack');
assert.match(eventRoutes, /prefix="\/v1\/events"/, 'event-ingest compatibility router should preserve the old /v1/events prefix');
assert.match(eventRoutes, /@router\.post\("\/label"/, 'event-ingest compatibility router should expose label batches');
assert.match(eventRoutes, /@router\.post\("\/telemetry"/, 'event-ingest compatibility router should expose telemetry batches');
assert.match(eventRoutes, /existing_ids/, 'event-ingest compatibility router should deduplicate by client event_id');
assert.match(backendMain, /POST \/v1\/events/, 'main entrypoint docs should advertise the unified event-ingest surface');

const primaryActions = [
  'create-dataset',
  'create-episode',
  'start-import',
  'create-collection-run',
  'register-collection-attempt',
  'review-collection-attempt',
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

// Model activation must persist a real, operator-supplied success metric — never
// a fabricated one. A hardcoded score would write an invented quality number to
// the backend for every activated model, so the activate-model payload must read
// the success field and validate it rather than embedding a literal.
assert.doesNotMatch(js, /success:\s*0\.82/, 'activate-model must not fabricate a hardcoded success metric');
assert.match(html, /id="model-success"/, 'model form should expose an operator-supplied success-rate input');
assert.match(js, /value\(['"]model-success['"]\)/, 'activate-model handler should read the operator-supplied success field');
assert.match(js, /FieldValidationError\(['"]model-success['"]/, 'activate-model handler should validate the success field range');

for (const endpoint of [
  '/api/embodied-platform/state',
  '/api/embodied-platform/datasets',
  '/api/embodied-platform/episodes',
  '/api/embodied-platform/imports',
  '/api/embodied-platform/annotation-tasks',
  '/api/embodied-platform/collection-profiles',
  '/api/embodied-platform/collection-runs',
  '/api/embodied-platform/collection-attempts',
  '/api/embodied-platform/training-jobs',
  '/api/embodied-platform/models',
  '/api/embodied-platform/simulation-jobs',
  '/api/embodied-platform/deployments',
  '/api/embodied-platform/learning-queue',
  '/api/embodied-platform/queue',
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
assert.match(js, /apiGet\(API\.state\)/, 'live reads should prefer the single backend state snapshot before per-endpoint fallback');
assert.match(js, /Promise\.allSettled/, 'live reads should not silently downgrade the whole app to demo mode on one endpoint failure');
assert.match(js, /assertOfflineReference/, 'offline-only reference checks should not block fresh live backend writes');
assert.match(js, /refreshState\(\)/, 'live writes should refresh canonical backend state after mutation');
assert.match(js, /function compactQueueDetail/, 'queue renderer should shorten long source/detail text before rendering');
assert.match(js, /queueRecords\s*=\s*Array\.isArray\(data\.queue\)/, 'frontend should render queues straight from the backend unified projection (data.queue), not re-derive them client-side');
assert.match(js, /function renderQueueList/, 'frontend should render queues through one universal card renderer');
assert.match(js, /renderQueueList\('imports-list'/, 'imports should route through the universal queue renderer');
assert.match(js, /renderQueueList\('training-list'/, 'training jobs should route through the universal queue renderer');
assert.match(js, /renderQueueList\('simulation-list'/, 'simulation jobs should route through the universal queue renderer');
assert.match(js, /renderQueueList\('deployment-list'/, 'deployments should route through the universal queue renderer');
assert.match(js, /renderQueueList\('learning-list'/, 'learning queue should route through the universal queue renderer');
assert.doesNotMatch(js, /table\('imports-list'/, 'imports-list should not use the generic dense table renderer');
assert.doesNotMatch(js, /table\('training-list'/, 'training-list should not use the generic dense table renderer');
assert.doesNotMatch(js, /table\('simulation-list'/, 'simulation-list should not use the generic dense table renderer');
assert.doesNotMatch(js, /table\('deployment-list'/, 'deployment-list should not use the generic dense table renderer');
assert.doesNotMatch(js, /table\('learning-list'/, 'learning-list should not use the generic dense table renderer');
assert.match(css, /\.queue-list/, 'queue lists should share a universal operational layout');
assert.match(css, /\.queue-card__detail/, 'queue details should have dedicated truncation styling');
assert.match(css, /\.queue-card__progress/, 'queue cards should show a stable status/progress track');
assert.match(html, /试采任务进度与复核/, 'collection panel should expose first-person trial progress and review');
assert.match(html, /id="collection-task-matrix"/, 'collection task progress matrix should exist');
assert.match(html, /id="collection-attempt-list"/, 'collection attempt queue should exist');
assert.match(js, /collectionProgressForRun/, 'collection progress should be computed deterministically in the frontend');
assert.match(js, /collection\.attempt\.create/, 'collection attempt registration should write an audit event');
assert.match(js, /collection\.review/, 'collection review should write an audit event');
assert.match(fixture, /collection_runs/, 'demo fixture should include collection runs');
assert.match(fixture, /collection_attempts/, 'demo fixture should include collection attempts');
assert.match(css, /\.collection-summary/, 'collection summary should have dedicated layout styling');
assert.match(uiRandomWalk, /runCollectionUiRandomWalk/, 'UI random walk runner should export runCollectionUiRandomWalk');
assert.match(uiRandomWalk, /seededRandom/, 'UI random walk runner should use a deterministic seed');
assert.match(uiRandomWalk, /collection-task-matrix/, 'UI random walk runner should inspect the task matrix');
assert.match(uiRandomWalk, /register-collection-attempt/, 'UI random walk runner should exercise attempt registration');
assert.match(uiRandomWalk, /review-collection-attempt/, 'UI random walk runner should exercise review submission');
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
assert.match(html, /platform-glass\.css\?v=\d+/, 'glass skin asset should be versioned to avoid stale browser cache');
assert.match(html, /platform-glass\.css\?v=6/, 'global glass material correction must ship behind a fresh cache-busted asset');
assert.match(html, /\/vendor\/glass\/refract\.js\?v=2/, 'refraction runtime should be cache-busted after performance changes');
assert.match(platformGlass, /GLOBAL MATERIAL CORRECTION/, 'platform glass must carry the final global material correction');
const globalGlassCorrection = platformGlass.slice(platformGlass.indexOf('GLOBAL MATERIAL CORRECTION'));
assert.match(globalGlassCorrection, /\.platform-workspace \.summary-grid article\.glass/, 'global glass correction must out-specify earlier KPI .glass selectors');
assert.match(globalGlassCorrection, /\.platform-workspace \.module-panel\.glass/, 'global glass correction must out-specify earlier panel .glass selectors');
assert.match(globalGlassCorrection, /\.platform-workspace \.summary-grid article\.glass::before/, 'KPI tile specular rim must out-specify the earlier disabled .glass rim');
assert.match(globalGlassCorrection, /\.platform-workspace \.summary-grid article\.glass::after/, 'KPI tile accent bar must have one winning global definition');
assert.match(platformGlass, /--ops-glass-material:/, 'platform glass must define a lighter translucent material token');
assert.match(platformGlass, /backdrop-filter:\s*blur\(38px\) saturate\(180%\) brightness\(1\.02\)/, 'major glass surfaces should use the corrected high-blur translucent material');
assert.match(globalGlassCorrection, /\.platform-workspace \.summary-grid article\.glass::after\s*{[\s\S]*height:\s*3px[\s\S]*linear-gradient\(90deg, var\(--accent\)/, 'KPI tiles should use a single radius-safe brand accent bar');
assert.match(globalGlassCorrection, /CONTENT PANE PERFORMANCE TIER/, 'platform glass must define a performance tier for large content panes');
assert.match(globalGlassCorrection, /\.platform-workspace \.module-panel\.glass,[\s\S]*\.platform-workspace \.data-table\s*{[\s\S]*backdrop-filter:\s*none/, 'large content panes must not use live backdrop blur');
assert.match(glassRefract, /maxArea/, 'glass refraction runtime must cap SVG refraction by rendered area');
assert.match(glassRefract, /w \* h > maxArea[\s\S]*backdropFilter = ""/, 'oversized glass surfaces must fall back instead of receiving SVG backdrop filters');
assert.match(platformGlass, /\.module-rail button\s*{[\s\S]*background-color 80ms var\(--ease\)[\s\S]*box-shadow 80ms var\(--ease\)/, 'module rail hover feedback should stay crisp');
assert.match(platformGlass, /\.module-rail button::before\s*{[\s\S]*transition-duration: 90ms/, 'module rail active marker should not feel slow');
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
// §4 redesign markers — XINGJU "Clinical Precision" teal + white instrument
// console. These assert the actual re-theme is present (would fail on a revert
// to the Azure blue theme or the old dark Ground Control theme / plain-table
// monitoring / unstyled tags), not tautologies.
// ---------------------------------------------------------------------------

// XINGJU teal design tokens defined in :root (spec §2).
for (const token of ['--bg:', '--surface:', '--surface-2:', '--hairline:', '--ink:', '--brand:', '--brand-lum:', '--accent:', '--st-info:', '--st-ok:', '--st-warn:', '--st-danger:']) {
  assert.match(css, new RegExp(token.replace(/[-]/g, '\\$&')), `design token ${token} should be defined in CSS :root`);
}
assert.match(css, /--bg:\s*#141619/, 'app background should be the dark instrument ground (spec §7 one-ground amendment)');
assert.match(css, /--surface:\s*#1a1d20/, 'panels should sit on the raised dark surface');
assert.match(css, /--ink:\s*#e8ecef/, 'primary text should be the dark-ground ink');
assert.match(css, /--brand:\s*#1f7a6b/, 'brand fills on dark should be the luminous teal (white ink)');
assert.match(css, /--brand-lum:\s*#5ec8c0/, 'focus rings/links should use the historical dark-scope brand teal');
assert.match(css, /--st-ok:\s*#7ec98f/, 'ok/active status should be the dark-ground green (semantic fix — ok is not blue)');
assert.match(css, /--accent:\s*#ff5a36/, 'signal coral accent should be defined (active rail + wordmark tick only)');
assert.doesNotMatch(css, /#1e40af|#2563eb|#0ea5e9|#d97706|#dc2626|rgba\(37,\s*99,\s*235/i, 'no Azure blue / old status literals should remain');
assert.doesNotMatch(css, /#059669|rgba\(5,\s*150,\s*105/i, 'no Tailwind emerald literals should remain (ok is the teal #1f7a6b)');
// The old dark Ground Control teal-green palette must be fully gone.
assert.doesNotMatch(css, /#34e0a1|#1f8f78|#2f6f63|rgba\(52,\s*224,\s*161/i, 'old teal-green brand/grain literals should be removed');
assert.doesNotMatch(css, /--bg:\s*#08110f/, 'old dark Ground Control background should be removed');

// Fonts/scripts are vendored (deploy readiness A1): zero external CDN bytes.
assert.match(html, /\/vendor\/fonts\/plex\.css/, 'platform must load the vendored Plex css (no external font CDN)');
assert.doesNotMatch(`${html}\n${labelerHtml}`, /fonts\.googleapis|fonts\.gstatic|cdn\.tailwindcss|cdn\.jsdelivr/, 'no external CDN references — must be deployable behind the GFW');
assert.match(labelerHtml, /assets\/console\/tailwind\.css\?v=\d+/, 'labeler must load compiled Tailwind CSS');
assert.doesNotMatch(labelerHtml, /tailwind-play\.js/, 'labeler should not ship the Tailwind runtime on the hot path');
assert.doesNotMatch(html, /Chakra\+Petch/, 'Chakra Petch should no longer be requested (Plex-only type system)');
for (const stack of ['IBM Plex Sans SC', 'IBM Plex Mono']) {
  assert.match(css, new RegExp(stack), `CSS font stack should use ${stack}`);
}
assert.doesNotMatch(css, /Chakra Petch/, 'Chakra Petch should be replaced by IBM Plex Mono in --font-accent');
assert.doesNotMatch(css, /font-family:[^;]*\bInter\b/i, 'Inter should be replaced by the IBM Plex type system');

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
// Required login fields must expose their requirement to assistive tech. The
// dialog is a div (not a <form>), so native `required` is inert — aria-required
// is the correct semantic. actor is client-validated non-empty; passcode is
// backend-required (SessionRequest.passcode min_length=1). role has a default
// option so it is never empty and is intentionally not marked.
assert.match(html, /id="login-actor"[^>]*aria-required="true"/, 'required login actor field should set aria-required');
assert.match(html, /id="login-passcode"[^>]*aria-required="true"/, 'required login passcode field should set aria-required');
assert.match(js, /\/api\/embodied-platform\/session/, 'login should call the session endpoint');
assert.match(js, /sessionStorage\.setItem\('embodied\.signature'/, 'login should store the signed principal signature');
assert.match(js, /sessionStorage\.removeItem\('embodied\.signature'/, 'logout should clear the stored signature');
assert.match(js, /submitLogin/, 'login submit handler should be wired');
assert.match(js, /renderPrincipal/, 'header should reflect the signed-in principal');

// Login deadlock fix: form-locking must NOT disable the login inputs (which live
// outside .module-panel), or sign-in is impossible in the live+unsigned state.
assert.match(js, /\.module-panel input, \.module-panel select/, 'write-form locking must be scoped to module panels so login stays usable');
assert.doesNotMatch(js, /querySelectorAll\('input, select'\)/, 'form-locking must not blanket-disable every input/select (would deadlock login)');

// PWA theming (spec §7 amendment) — one dark instrument ground.
assert.match(html, /<meta name="theme-color" content="#141619">/, 'theme-color meta should be the dark instrument ground');
assert.match(manifest, /"theme_color":\s*"#141619"/, 'manifest theme_color should be the dark instrument ground');
assert.match(manifest, /"background_color":\s*"#141619"/, 'manifest background_color should be the dark instrument ground');
// §7 amendment — shared app switcher (connective tissue between the surfaces).
assert.match(html, /class="app-switcher"/, 'platform header should carry the shared 运营台|标注台 app switcher');
assert.match(labelerHtml, /class="app-switcher"/, 'labeler topbar should carry the shared 运营台|标注台 app switcher');
assert.match(html, /href="\/labeler\//, 'platform switcher should deep-link to the hosted labeler');
assert.match(labelerHtml, /href="\/app\/"/, 'labeler switcher should link back to the operations console');

assert.match(icon, /#ffffff/, 'PWA icon should adopt the white light surface');
assert.match(icon, /#0d4f4a/, 'PWA icon should carry the XINGJU deep teal brand');
assert.doesNotMatch(icon, /#1e40af|#2563eb/, 'PWA icon should drop the Azure blue fills');
assert.doesNotMatch(icon, /#08110f|#34e0a1|#1f8f78/, 'PWA icon should drop the old dark teal-green fills');

console.log('Embodied platform audit passed');
