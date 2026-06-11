/**
 * Embodied-AI sub-task annotation labeler.
 *
 * Vanilla ES module — no build step.
 */

// Source video metadata. Default 15 fps for the bundled DROID clip; overwritten
// by loadEpisodeMeta() if episode_meta.json provides a different `fps` value.
// Using `let` (not `const`) so per-episode fps can be applied at runtime.
let VIDEO_FPS = 15;

// ----------------------------------------------------------------------------
// Episode source — ?dataset=<id>&episode=<n> selects what to label.
// The built-in demo keeps its zero-config static path (relative asset URLs,
// works with no backend); any other dataset id is resolved through the backend
// bundle route GET /api/embodied/datasets/{id}/episodes/{ix}.
// ----------------------------------------------------------------------------
const _queryParams = new URLSearchParams(window.location.search);
// Sanitize to the backend's dataset-id charset; anything else falls back to demo.
const DATASET_ID = (_queryParams.get('dataset') || 'demo').replace(/[^A-Za-z0-9_-]/g, '') || 'demo';
const IS_DEMO_SOURCE = DATASET_ID === 'demo';
// Demo has exactly one episode — clamp the index so a hand-edited
// ?dataset=demo&episode=5 can't stamp nonexistent indices into saved segments.
const EPISODE_INDEX = IS_DEMO_SOURCE ? 0
    : Math.max(0, parseInt(_queryParams.get('episode') || '0', 10) || 0);

// Backend base URL: <meta name="api-base"> wins (deploy-time override);
// hosted platform default is same-origin.
const API_BASE = document.querySelector('meta[name="api-base"]')?.content?.trim()
    || window.location.origin;

// Persistence key for save/load. The demo keeps its historical id so segments
// already saved (localStorage + backend JSONL) stay attached; other datasets
// derive an id matching the backend's ^[A-Za-z0-9_-]+$ episode_id pattern.
const EPISODE_ID = IS_DEMO_SOURCE ? 'demo_episode' : `${DATASET_ID}_ep${EPISODE_INDEX}`;

const video = document.getElementById('video');
const videoFrame = document.getElementById('video-frame');
const videoLoading = document.getElementById('video-loading');
const videoError = document.getElementById('video-error');
const videoErrorMessage = document.getElementById('video-error-message');
const videoRetry = document.getElementById('video-retry');
const videoSourceStatus = document.getElementById('video-source-status');
const scrubBar = document.getElementById('scrub-bar');
const scrubFill = document.getElementById('scrub-fill');
const scrubHead = document.getElementById('scrub-head');
const btnPlay = document.getElementById('btn-play');
const btnBack10 = document.getElementById('btn-back-10');
const btnBack1 = document.getElementById('btn-back-1');
const btnFwd1 = document.getElementById('btn-fwd-1');
const btnFwd10 = document.getElementById('btn-fwd-10');
const timeCurrent = document.getElementById('time-current');
const timeTotal = document.getElementById('time-total');
const frameCurrent = document.getElementById('frame-current');
const frameTotal = document.getElementById('frame-total');
// `let` — swapped to the bundle clip URL when a non-demo episode source loads;
// retryVideoLoad() re-reads it, so retry keeps working after the swap.
let videoSourcePath = video.dataset.videoSrc || video.querySelector('source')?.getAttribute('src') || 'assets/embodied/demo_episode.mp4';

function fmtTime(seconds) {
    const m = Math.floor(seconds / 60);
    const s = (seconds % 60).toFixed(3).padStart(6, '0');
    return `${String(m).padStart(2, '0')}:${s}`;
}

function frameOf(seconds) { return Math.round(seconds * VIDEO_FPS); }
function timeOfFrame(frame) { return frame / VIDEO_FPS; }

function syncPlayButton(forcePlaying = null) {
    const isPlaying = forcePlaying === null ? !video.paused : Boolean(forcePlaying);
    btnPlay.innerHTML = isPlaying
        ? '<i class="fa fa-pause text-base"></i>'
        : '<i class="fa fa-play text-base pl-0.5"></i>';
}

function videoSourceLabel() {
    return videoSourcePath.split('/').filter(Boolean).pop() || videoSourcePath;
}

// Single source of truth for "is the user typing into a form control".
// Used by every keydown handler so hotkeys never steal keys from an input,
// textarea, <select>, contenteditable region, or active IME composition.
function isEditableTarget(e) {
    const t = e.target;
    if (!t) return false;
    const tag = t.tagName;
    if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return true;
    if (t.isContentEditable) return true;
    if (e.isComposing) return true;
    return false;
}

function videoControlElements() {
    return [
        btnPlay,
        btnBack10,
        btnBack1,
        btnFwd1,
        btnFwd10,
        document.getElementById('playback-rate'),
        document.getElementById('btn-loop'),
        document.getElementById('btn-mark-start'),
        document.getElementById('btn-mark-end'),
    ].filter(Boolean);
}

function setVideoPlayerState(state, message = '') {
    if (!videoFrame) return;
    videoFrame.dataset.playerState = state;
    videoLoading?.classList.toggle('hidden', state !== 'loading');
    videoError?.classList.toggle('hidden', state !== 'error');
    video.classList.toggle('opacity-0', state === 'error');

    const disabled = state === 'error' || state === 'loading';
    for (const control of videoControlElements()) {
        control.disabled = disabled;
        control.setAttribute('aria-disabled', String(disabled));
    }

    if (videoSourceStatus) {
        if (state === 'ready') {
            const duration = Number.isFinite(video.duration) ? fmtTime(video.duration) : '--:--.---';
            const size = video.videoWidth && video.videoHeight ? `${video.videoWidth}×${video.videoHeight}` : 'metadata';
            videoSourceStatus.textContent = `${videoSourceLabel()} · ${size} · ${duration}`;
        } else if (state === 'error') {
            videoSourceStatus.textContent = `${videoSourceLabel()} · 加载失败`;
        } else {
            videoSourceStatus.textContent = `${videoSourceLabel()} · 载入中`;
        }
    }

    if (state === 'error' && videoErrorMessage) {
        videoErrorMessage.textContent = message || '无法读取当前视频源，请检查本地素材或重新加载。';
    }
}

function handleVideoLoadError() {
    const mediaError = video.error;
    const codeMap = {
        1: '视频加载被中断，请重新加载当前素材。',
        2: '浏览器无法读取视频文件，请确认本地服务器仍在运行。',
        3: '视频文件存在但无法解码，请更换为 H.264 MP4。',
        4: '当前浏览器不支持这个视频格式，请使用 H.264 MP4 素材。',
    };
    const message = codeMap[mediaError?.code] || '视频源没有返回可播放内容，请重新加载或更换素材。';
    jklStopReverse();
    setVideoPlayerState('error', message);
}

function retryVideoLoad() {
    setVideoPlayerState('loading');
    jklStopReverse();
    video.pause();
    if (!IS_DEMO_SOURCE && episodeSourceFailed) {
        // The bundle never loaded, so videoSourcePath still points at the demo
        // clip — retry the BUNDLE fetch, not the <source>. Reloading the demo
        // asset here would put the wrong video under a non-demo URL.
        episodeSourceReady = fetchEpisodeBundle().then((bundle) => {
            if (bundle) {
                loadEpisodeMeta();
                loadGold();
                loadGripper();
            }
            return bundle;
        });
        return;
    }
    video.removeAttribute('src');
    const source = video.querySelector('source');
    if (source) source.src = videoSourcePath;
    video.load();
}

// ----------------------------------------------------------------------------
// Non-demo episode bundles. The backend returns absolute-path URLs
// (/embodied-cache/... or /embodied-assets/...) — prefix API_BASE so they
// resolve against the API origin, not the static page server.
// ----------------------------------------------------------------------------
function apiUrl(u) {
    return u && u.startsWith('/') ? API_BASE + u : u;
}

function applyEpisodeBundle(bundle) {
    // Video: swap the <source> the same way retryVideoLoad() does.
    videoSourcePath = apiUrl(bundle.video_url);
    setVideoPlayerState('loading');
    video.pause();
    video.removeAttribute('src');
    const source = video.querySelector('source');
    if (source) {
        source.src = videoSourcePath;
        // <source>-child failures fire 'error' at the SOURCE element, never at
        // the media element — without this the player spins forever when the
        // cached clip has been evicted or the API restarted.
        source.onerror = () => setVideoPlayerState('error',
            `视频文件加载失败（${videoSourceLabel()}）— 缓存可能已失效，请重试。`);
    }
    video.load();
    // Sprite strip: thumb filmstrip + scrub hover preview share the image.
    // Tile count is measured from the image itself (see measureSpriteTiles).
    const spriteUrl = apiUrl(bundle.sprite_url);
    const thumb = document.getElementById('thumb-strip');
    if (thumb) thumb.style.backgroundImage = `url('${spriteUrl}')`;
    const preview = document.getElementById('scrub-preview');
    if (preview) preview.style.backgroundImage = `url('${spriteUrl}')`;
    measureSpriteTiles(spriteUrl);
}

// Sticky failure flag: a failed bundle fetch must keep the error overlay up.
// Without it, the cancelled <source>'s late media events (loadstart/canplay)
// race the fetch rejection and flip the player back to 'loading'. Cleared by
// fetchEpisodeBundle() on a successful retry.
let episodeSourceFailed = false;

// Fetch + apply the bundle for the current (non-demo) episode source.
// Called once at startup and again from retryVideoLoad() after a failure.
async function fetchEpisodeBundle() {
    try {
        const r = await fetch(`${API_BASE}/api/embodied/datasets/${encodeURIComponent(DATASET_ID)}/episodes/${EPISODE_INDEX}`);
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const bundle = await r.json();
        episodeSourceFailed = false;
        applyEpisodeBundle(bundle);
        return bundle;
    } catch (e) {
        console.error(`embodied.js: episode bundle ${DATASET_ID}/${EPISODE_INDEX} failed:`, e);
        episodeSourceFailed = true;
        setVideoPlayerState('error',
            `无法加载 ${DATASET_ID} · ep ${EPISODE_INDEX}（${e.message}）— 请确认后端已启动，或返回演示数据集。`);
        return null;
    }
}

// Resolved at startup (reassigned on retry). Demo → null (keeps the static
// asset path). Non-demo failure → null after surfacing the video error
// overlay; the asset loaders below treat null as "nothing to show".
let episodeSourceReady;
if (IS_DEMO_SOURCE) {
    episodeSourceReady = Promise.resolve(null);
} else {
    // Cancel the demo <source> the HTML kicked off before this module ran.
    // Without this, a failed bundle fetch leaves the demo clip loading — the
    // player flips to 'ready' under a non-demo URL and the user labels the
    // wrong video.
    video.pause();
    video.removeAttribute('src');
    video.querySelector('source')?.removeAttribute('src');
    video.load();
    setVideoPlayerState('loading');
    episodeSourceReady = fetchEpisodeBundle();
}

async function safePlayVideo() {
    try {
        await video.play();
        syncPlayButton(true);
    } catch (error) {
        if (video.error) {
            handleVideoLoadError();
            return;
        }
        syncPlayButton(false);
        showToast(`无法播放视频：${error.message || '请再次点击播放'}`, 'error');
    }
}

// Cached bar widths (px) for transform-based playhead updates.
// translateX(%) is relative to the element's OWN box, so we compute pixel
// offsets from the parent rect once per resize and reuse them per frame.
let scrubBarWidthPx = 0;
if (typeof ResizeObserver !== 'undefined') {
    const ro = new ResizeObserver((entries) => {
        for (const entry of entries) {
            if (entry.target === scrubBar) scrubBarWidthPx = entry.contentRect.width;
        }
    });
    ro.observe(scrubBar);
}

function updateTimeUI() {
    const cur = video.currentTime || 0;
    const dur = video.duration || 0;
    timeCurrent.textContent = fmtTime(cur);
    timeTotal.textContent = isFinite(dur) ? fmtTime(dur) : '--:--.---';
    frameCurrent.textContent = frameOf(cur);
    frameTotal.textContent = isFinite(dur) ? frameOf(dur) : '?';
    const pct = dur > 0 ? (cur / dur) : 0;
    // transform writes only — no layout per timeupdate (60Hz was thrashing)
    scrubFill.style.transform = `scaleX(${pct})`;
    if (!scrubBarWidthPx) scrubBarWidthPx = scrubBar.getBoundingClientRect().width;
    scrubHead.style.transform = `translateX(${pct * scrubBarWidthPx}px)`;
}

function stepFrame(delta) {
    // NLE convention (Premiere/DaVinci/Final Cut): frame-step pauses playback
    // first — at speed the playhead overruns the seek before the frame can be
    // read. Route through jklK() (not bare video.pause()) so the JKL shuttle
    // resets too: J-reverse keeps video.paused === true while its rAF loop
    // mutates currentTime, and would overwrite the step on the next tick.
    // Skipped when already paused — a bare step never touches the rate UI.
    if (!video.paused || (typeof jklState !== 'undefined' && jklState.mode === 'rev')) {
        if (typeof jklK === 'function') jklK();
        else { video.pause(); syncPlayButton(false); }
    }
    const f = frameOf(video.currentTime || 0) + delta;
    const target = Math.max(0, timeOfFrame(f));
    if (isFinite(video.duration)) {
        video.currentTime = Math.min(video.duration, target);
    } else {
        video.currentTime = target;
    }
}

// Route togglePlay through the JKL state machine so Space / play-button / video-click
// keep the J/K/L mode and the dropdown in sync.
function togglePlay() {
    if (video.paused || (typeof jklState !== 'undefined' && jklState.mode === 'rev')) {
        if (typeof jklL === 'function') jklL();
        else { void safePlayVideo(); }
    } else {
        if (typeof jklK === 'function') jklK();
        else { video.pause(); btnPlay.innerHTML = '<i class="fa fa-play text-base pl-0.5"></i>'; }
    }
}

// episodeSourceFailed guard: once the bundle fetch has failed, stray media
// events from the cancelled <source> must not lift the error overlay.
video.addEventListener('loadstart', () => {
    if (!episodeSourceFailed) setVideoPlayerState('loading');
});
video.addEventListener('loadedmetadata', () => {
    updateTimeUI();
    if (!episodeSourceFailed) setVideoPlayerState('ready');
});
video.addEventListener('canplay', () => {
    if (!episodeSourceFailed) setVideoPlayerState('ready');
});
video.addEventListener('timeupdate', updateTimeUI);
video.addEventListener('play', () => syncPlayButton(true));
video.addEventListener('pause', () => {
    if (jklState?.mode !== 'rev') syncPlayButton(false);
});
video.addEventListener('ended', () => syncPlayButton(false));
video.addEventListener('error', handleVideoLoadError);
videoRetry?.addEventListener('click', retryVideoLoad);
setVideoPlayerState(video.readyState >= 1 ? 'ready' : 'loading');

btnPlay.addEventListener('click', togglePlay);
video.addEventListener('click', togglePlay);  // standard UX: click video toggles play
btnBack10.addEventListener('click', () => stepFrame(-10));
btnBack1.addEventListener('click', () => stepFrame(-1));
btnFwd1.addEventListener('click', () => stepFrame(1));
btnFwd10.addEventListener('click', () => stepFrame(10));

// ----------------------------------------------------------------------------
// JKL continuous shuttle — the 30-year industry-standard video-editor rhythm.
// J = reverse-play, K = pause, L = forward-play. Multi-tap within JKL_MULTITAP_MS
// accelerates (1× → 2× → 4× → 8×). Reverse uses rAF since HTML5 <video>
// doesn't support native negative playbackRate in Chromium.
// ----------------------------------------------------------------------------
const JKL_MULTITAP_MS = 400;
const JKL_MAX_RATE = 8;
const jklState = { mode: 'paused', rate: 1, lastTapTime: 0 };
let reverseRafId = null;
let reverseLastT = 0;

function jklStopReverse() {
    if (reverseRafId !== null) {
        cancelAnimationFrame(reverseRafId);
        reverseRafId = null;
    }
}
function jklStartReverse(rate) {
    jklStopReverse();
    reverseLastT = performance.now();
    const tick = (now) => {
        if (jklState.mode !== 'rev') { jklStopReverse(); return; }
        const dt = (now - reverseLastT) / 1000;
        reverseLastT = now;
        const newTime = (video.currentTime || 0) - dt * rate;
        if (newTime <= 0) {
            video.currentTime = 0;
            jklK();   // stop at start
            return;
        }
        video.currentTime = newTime;
        reverseRafId = requestAnimationFrame(tick);
    };
    reverseRafId = requestAnimationFrame(tick);
}

function jklK() {
    jklState.mode = 'paused';
    jklState.rate = 1;
    jklStopReverse();
    video.playbackRate = 1;
    if (!video.paused) video.pause();
    // Sync the playback-rate dropdown to 1× when JKL pauses
    if (playbackRateEl) playbackRateEl.value = '1';
    syncPlayButton(false);
}
function jklL() {
    const now = performance.now();
    if (jklState.mode === 'fwd' && (now - jklState.lastTapTime) < JKL_MULTITAP_MS) {
        jklState.rate = Math.min(JKL_MAX_RATE, jklState.rate * 2);
    } else {
        jklState.rate = 1;
    }
    jklState.mode = 'fwd';
    jklState.lastTapTime = now;
    jklStopReverse();
    video.playbackRate = jklState.rate;
    if (video.paused) void safePlayVideo();
    if (playbackRateEl && jklState.rate <= 2) playbackRateEl.value = String(jklState.rate);
    syncPlayButton(true);
    if (jklState.rate > 1) showToast(`▶ ${jklState.rate}×`, 'info');
}
function jklJ() {
    const now = performance.now();
    if (jklState.mode === 'rev' && (now - jklState.lastTapTime) < JKL_MULTITAP_MS) {
        jklState.rate = Math.min(JKL_MAX_RATE, jklState.rate * 2);
    } else {
        jklState.rate = 1;
    }
    jklState.mode = 'rev';
    jklState.lastTapTime = now;
    video.pause();
    jklStartReverse(jklState.rate);
    syncPlayButton(true);
    showToast(`◀ ${jklState.rate}×`, 'info');
}

// ----------------------------------------------------------------------------
// Playback speed + loop-selected-segment — boundary-verification tools
// ----------------------------------------------------------------------------
const playbackRateEl = document.getElementById('playback-rate');
playbackRateEl.addEventListener('change', () => {
    // Manually changing the rate exits any J-reverse shuttle and resets to forward
    jklStopReverse();
    jklState.mode = 'paused';
    jklState.rate = 1;
    video.playbackRate = parseFloat(playbackRateEl.value);
});

const btnLoop = document.getElementById('btn-loop');
let loopEnabled = false;

function setLoop(on) {
    loopEnabled = on;
    btnLoop.classList.toggle('ring-accent', on);
    btnLoop.classList.toggle('text-light', on);
    btnLoop.classList.toggle('bg-accent/15', on);
    if (!on) return;
    // If a segment is selected, snap playhead to its start so the loop is
    // immediate; if not, the loop only activates when one becomes selected.
    const sel = state.segments.find(s => s.id === state.selectedId);
    if (sel) {
        video.currentTime = timeOfFrame(sel.start_frame);
        if (video.paused) void safePlayVideo();
    } else {
        showToast('Select a segment first to loop it', 'info');
    }
}

btnLoop.addEventListener('click', () => setLoop(!loopEnabled));

function enterSegmentQALoop(seg) {
    // Normalize shuttle state before setLoop starts forward playback. Without
    // this, committing from J-reverse can leave reverse rAF and native play
    // fighting over currentTime.
    if (typeof jklK === 'function') jklK();
    state.selectedId = seg.id;
    if (isFinite(video.duration)) video.currentTime = timeOfFrame(seg.start_frame);
    if (typeof setLoop === 'function') setLoop(true);
}

// On every frame tick, if looping and we've crossed the selected segment's
// end, snap back to its start. The check is cheap (one if + one math op).
video.addEventListener('timeupdate', () => {
    if (!loopEnabled) return;
    const sel = state.segments.find(s => s.id === state.selectedId);
    if (!sel) return;
    const endTime = timeOfFrame(sel.end_frame);
    const startTime = timeOfFrame(sel.start_frame);
    if (video.currentTime >= endTime || video.currentTime < startTime - 0.05) {
        video.currentTime = startTime;
    }
});

// Click + drag the scrub bar to seek. Drag listens at the window level so the
// user can drag past the bar's left/right edges without losing the gesture.
// Quantize to the nearest integer frame so the playhead snaps where the user
// expects (research E.12: continuous-time scrub previously left the playhead
// up to half a frame off the cursor's visual position).
let scrubDragging = false;
function seekFromScrub(clientX) {
    const rect = scrubBar.getBoundingClientRect();
    const pct = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
    if (isFinite(video.duration)) {
        const frame = Math.round(pct * (video.duration * VIDEO_FPS));
        video.currentTime = timeOfFrame(frame);
    }
}
scrubBar.addEventListener('mousedown', (e) => {
    scrubDragging = true;
    seekFromScrub(e.clientX);
    e.preventDefault();   // prevent text selection while dragging
});
window.addEventListener('mousemove', (e) => {
    if (scrubDragging) seekFromScrub(e.clientX);
});
window.addEventListener('mouseup', () => { scrubDragging = false; });

document.addEventListener('keydown', (e) => {
    if (isEditableTarget(e)) return;
    // Focused <button> keeps native Space activation for Tab-nav users —
    // don't preventDefault transport keys over it (same idiom as seg-list rows).
    if (e.target && typeof e.target.closest === 'function' && e.target.closest('button')) return;
    if (e.key === ' ') { e.preventDefault(); togglePlay(); }
    else if (e.key === ',') { e.preventDefault(); stepFrame(e.shiftKey ? -10 : -1); }
    else if (e.key === '.') { e.preventDefault(); stepFrame(e.shiftKey ? 10 : 1); }
});

// ----------------------------------------------------------------------------
// Label palette (schema-driven taxonomy)
// ----------------------------------------------------------------------------

const FALLBACK_LABEL_SCHEMAS = [
    {
        id: 'tabletop_manipulation',
        name: '桌面操作',
        description: '适合抓取、放置、移动物体的机器人桌面任务。',
        labels: [
            { id: 'reach', label: '接近 reach', color: '#7c3aed' },
            { id: 'grasp', label: '抓取 grasp', color: '#10b981' },
            { id: 'lift', label: '抬起 lift', color: '#0ea5e9' },
            { id: 'transport', label: '移动 transport', color: '#2563eb' },
            { id: 'place', label: '放置 place', color: '#f59e0b' },
            { id: 'adjust', label: '微调 adjust', color: '#ec4899' },
            { id: 'release', label: '松开 release', color: '#14b8a6' },
            { id: 'idle', label: '空闲 idle', color: '#71717a' },
        ],
    },
];

let labelSchemas = FALLBACK_LABEL_SCHEMAS;
let activeLabelSchema = labelSchemas[0];
let SKILLS = activeLabelSchema.labels.slice();
let episodePreferredSchemaId = '';
let labelSchemasLoaded = false;

const state = {
    activeSkillId: SKILLS[0].id,
};

const palette = document.getElementById('palette');
const labelSchemaSelect = document.getElementById('label-schema-select');
const labelSchemaDescription = document.getElementById('label-schema-description');
const workflowActiveSkill = document.getElementById('workflow-active-skill');
const workflowSegmentState = document.getElementById('workflow-segment-state');
const workflowSaveState = document.getElementById('workflow-save-state');
const storageModeBadge = document.getElementById('storage-mode-badge');

function getSkillById(skillId) {
    return SKILLS.find(s => s.id === skillId) || {
        id: skillId || 'unknown',
        label: skillId || '未知标签',
        color: '#64748b',
    };
}

function normalizeLabelSchemas(payload) {
    const rawSchemas = Array.isArray(payload?.schemas) ? payload.schemas : [];
    const cleaned = rawSchemas.map(schema => ({
        id: String(schema.id || '').trim(),
        name: String(schema.name || schema.id || '').trim(),
        description: String(schema.description || '').trim(),
        labels: Array.isArray(schema.labels) ? schema.labels
            .filter(label => label?.id && label?.label && label?.color)
            .map(label => ({
                id: String(label.id).trim(),
                label: String(label.label).trim(),
                color: String(label.color).trim(),
            }))
            : [],
    })).filter(schema => schema.id && schema.name && schema.labels.length > 0);
    return {
        defaultSchemaId: payload?.default_schema_id || cleaned[0]?.id,
        schemas: cleaned.length ? cleaned : FALLBACK_LABEL_SCHEMAS,
    };
}

// Escapers for values interpolated into innerHTML / style attributes.
// Schema ids, names and colors come from fetched JSON (label_schemas.json
// today, the backend tomorrow) — treat them as data, not markup.
function escapeHtml(value) {
    return String(value).replace(/[&<>"']/g, c => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    })[c]);
}

function safeCssColor(value) {
    const v = String(value || '').trim();
    return /^(#[0-9a-fA-F]{3,8}|[a-zA-Z]+|(rgb|rgba|hsl|hsla)\([0-9.,%\s/]*\))$/.test(v) ? v : 'inherit';
}

function renderLabelSchemaSelect() {
    if (!labelSchemaSelect) return;
    labelSchemaSelect.innerHTML = labelSchemas
        .map(schema => `<option value="${escapeHtml(schema.id)}">${escapeHtml(schema.name)}</option>`)
        .join('');
    labelSchemaSelect.value = activeLabelSchema.id;
    if (labelSchemaDescription) {
        labelSchemaDescription.textContent = activeLabelSchema.description || '按任务选择可用动作标签';
    }
}

function buildSkillOptionsHtml(currentSkillId = '') {
    const hasCurrent = SKILLS.some(skill => skill.id === currentSkillId);
    const options = SKILLS.map(skill => `<option value="${escapeHtml(skill.id)}">${escapeHtml(skill.label)}</option>`);
    if (currentSkillId && !hasCurrent) {
        options.push(`<option value="${escapeHtml(currentSkillId)}">${escapeHtml(currentSkillId)}（旧标签）</option>`);
    }
    return options.join('');
}

function syncSkillSelectOptions(selectEl, selectedSkillId) {
    if (!selectEl) return;
    if (selectEl.dataset.schemaId !== activeLabelSchema.id) {
        selectEl.innerHTML = buildSkillOptionsHtml(selectedSkillId);
        selectEl.dataset.schemaId = activeLabelSchema.id;
    }
    selectEl.value = selectedSkillId;
}

function updateWorkflowPanel() {
    if (workflowActiveSkill) {
        workflowActiveSkill.textContent = getSkillById(state.activeSkillId).label;
    }
    if (workflowSegmentState) {
        workflowSegmentState.textContent = state.pendingStart === null || state.pendingStart === undefined
            ? `${state.segments?.length || 0} 个片段`
            : `起点 frame ${state.pendingStart}`;
    }
    if (workflowSaveState) {
        workflowSaveState.textContent = state.dirty ? '待保存' : '已同步';
    }
}

function refreshSchemaDependentViews() {
    renderPalette();
    if (typeof renderLanes === 'function') renderLanes();
    try {
        if (typeof renderGoldLane === 'function' && Array.isArray(GOLD_SEGMENTS)) renderGoldLane(GOLD_SEGMENTS);
    } catch (e) {
        // GOLD_SEGMENTS is declared later in module initialization.
    }
    if (typeof renderSegmentList === 'function') renderSegmentList();
}

function setLabelSchema(schemaId, { persist = true, refresh = true } = {}) {
    const nextSchema = labelSchemas.find(schema => schema.id === schemaId) || labelSchemas[0];
    if (!nextSchema) return;
    activeLabelSchema = nextSchema;
    SKILLS = activeLabelSchema.labels.slice();
    if (!SKILLS.some(skill => skill.id === state.activeSkillId)) {
        state.activeSkillId = SKILLS[0]?.id || '';
    }
    renderLabelSchemaSelect();
    if (persist) {
        try { localStorage.setItem('embodied.label_schema_id', activeLabelSchema.id); } catch (e) { /* ignore storage failures */ }
    }
    if (refresh) refreshSchemaDependentViews();
    const selectedSkill = getSkillById(state.activeSkillId);
    const ms = document.getElementById('btn-mark-start');
    if (ms && selectedSkill) {
        ms.style.borderLeft = `4px solid ${selectedSkill.color}`;
        const dot = ms.querySelector('i.fa-circle');
        if (dot) dot.style.color = selectedSkill.color;
    }
}

async function loadLabelSchemas(preferredSchemaId = '') {
    try {
        const r = await fetch('assets/embodied/label_schemas.json');
        if (r.ok) {
            const payload = await r.json();
            const normalized = normalizeLabelSchemas(payload);
            labelSchemas = normalized.schemas;
            const storedSchemaId = (() => {
                try { return localStorage.getItem('embodied.label_schema_id') || ''; } catch (e) { return ''; }
            })();
            labelSchemasLoaded = true;
            setLabelSchema(preferredSchemaId || storedSchemaId || episodePreferredSchemaId || normalized.defaultSchemaId, { persist: false });
            return;
        }
    } catch (e) {
        // Fall through to the local fallback schema.
    }
    labelSchemasLoaded = true;
    setLabelSchema(preferredSchemaId || FALLBACK_LABEL_SCHEMAS[0].id, { persist: false });
}

if (labelSchemaSelect) {
    labelSchemaSelect.addEventListener('change', (e) => {
        setLabelSchema(e.target.value, { persist: true });
        showToast(`标签集已切换为 ${activeLabelSchema.name}`, 'success');
    });
}

function renderPalette() {
    palette.innerHTML = '';
    SKILLS.forEach((skill, idx) => {
        const pill = document.createElement('button');
        pill.className = 'skill-pill flex items-center gap-2 rounded-full px-3.5 py-2 text-sm bg-zinc-800 hover:bg-zinc-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-zinc-900 transition';
        pill.dataset.skillId = skill.id;
        // Container is role="group" (not radiogroup) — see embodied.html. Pills
        // are plain buttons; aria-pressed reflects active state without making
        // an implicit promise of arrow-key roving focus that isn't implemented.
        pill.setAttribute('aria-pressed', String(skill.id === state.activeSkillId));
        if (skill.id === state.activeSkillId) pill.classList.add('active');
        pill.innerHTML = `
            <span class="font-mono text-xs text-zinc-500">${idx + 1}</span>
            <span class="inline-block w-3 h-3 rounded-full" style="background:${safeCssColor(skill.color)}"></span>
            <span>${skill.label}</span>
        `;
        pill.addEventListener('click', () => setActiveSkill(skill.id));
        palette.appendChild(pill);
    });
}

function setActiveSkill(skillId) {
    state.activeSkillId = skillId;
    renderPalette();
    // Tint the Mark Start button with the active skill's color so the labeler
    // can see what color the next segment will get.
    const ms = document.getElementById('btn-mark-start');
    const skill = getSkillById(skillId);
    if (ms && skill) {
        ms.style.borderLeft = `4px solid ${skill.color}`;
        const dot = ms.querySelector('i.fa-circle');
        if (dot) dot.style.color = skill.color;
    }
    updateWorkflowPanel();
}

document.addEventListener('keydown', (e) => {
    if (isEditableTarget(e)) return;
    // Cmd/Ctrl+digit is browser tab-switching on every major OS — don't hijack.
    if (e.metaKey || e.ctrlKey) return;
    // Use e.code so Shift+1 doesn't get reported as "!" on US keyboards.
    // e.code for "1" is always "Digit1" regardless of shift state.
    const m = /^Digit([1-9])$/.exec(e.code);
    if (!m) return;
    const n = parseInt(m[1], 10);
    if (n < 1 || n > SKILLS.length) return;
    e.preventDefault();
    const targetSkill = SKILLS[n - 1].id;

    if (e.shiftKey) {
        // Shift+1-9: reassign the selected segment's skill (Update operation)
        const sel = state.segments.find(s => s.id === state.selectedId);
        if (!sel) {
            showToast('选中一个片段先 (select a segment first)', 'error');
            return;
        }
        if (sel.skill_id === targetSkill) return;
        if (typeof pushUndoSnapshot === 'function') pushUndoSnapshot();
        sel.skill_id = targetSkill;
        renderLanes();
        renderSegmentList();
        setDirty(true);
        showToast(`Changed selected segment to ${targetSkill}`, 'success');
        return;
    }

    // Plain 1-9: set the active skill (for the next segment created)
    setActiveSkill(targetSkill);
    // Brief flash on the activated pill so keyboard activation registers
    // visually, not just via the .active ring transition.
    const pill = palette.querySelectorAll('.skill-pill')[n - 1];
    if (pill) {
        pill.classList.add('flash');
        setTimeout(() => pill.classList.remove('flash'), 240);
    }
});

renderPalette();
renderLabelSchemaSelect();
loadLabelSchemas();

// ----------------------------------------------------------------------------
// Timeline strip — segment lanes (SVG), thumb strip (CSS sprite), gripper (SVG)
// ----------------------------------------------------------------------------

const lanesSvg = document.getElementById('timeline-lanes');
const playheadEl = document.getElementById('timeline-playhead');
const gripperSvg = document.getElementById('gripper-plot');
const gripperError = document.getElementById('gripper-error');

state.segments = [];   // populated in T10
state.selectedId = null;

function bindTimelineLegendControls() {
    const legendButtons = document.querySelectorAll('[data-timeline-focus]');
    const trackRows = document.querySelectorAll('[data-timeline-track]');
    legendButtons.forEach((button) => {
        button.addEventListener('click', () => {
            const target = button.dataset.timelineFocus;
            const row = document.querySelector(`[data-timeline-track="${target}"]`);
            if (!row) return;
            legendButtons.forEach(btn => btn.setAttribute('aria-pressed', String(btn === button)));
            trackRows.forEach(track => track.classList.toggle('timeline-track-focused', track === row));
            row.scrollIntoView({ behavior: 'smooth', block: 'center', inline: 'nearest' });
            if (target === 'user') focusUserAnnotationWorkflow();
        });
    });
}

bindTimelineLegendControls();

function focusUserAnnotationWorkflow() {
    const marker = state.pendingStart === null
        ? document.getElementById('btn-mark-start')
        : document.getElementById('btn-mark-end');
    if (!marker) return;
    const actionLabel = state.pendingStart === null ? '标记起点' : '标记终点';
    marker.focus({ preventScroll: true });
    marker.classList.remove('timeline-focus-pulse');
    // Restart the pulse when the user clicks the legend repeatedly.
    void marker.offsetWidth;
    marker.classList.add('timeline-focus-pulse');
    setTimeout(() => marker.classList.remove('timeline-focus-pulse'), 760);
    showToast(`你的标注轨道已聚焦，点击${actionLabel}或按 S 继续`, 'info');
}

function totalFrames() { return frameOf(video.duration || 0); }
function frameToPct(f) {
    const total = totalFrames();
    return total > 0 ? (f / total) * 100 : 0;
}

// ----------------------------------------------------------------------------
// renderLanes — incremental diff-and-patch.
// Was: O(N²) lane assignment (greedy `findIndex` × `every`) + full SVG wipe on
//     every mutation. At N=1000 with overlaps, ~1M comparisons + 1000 DOM
//     creations per keystroke.
// Now: O(N log N) lane assignment (sort + sweep) + per-segment mutation of
//     existing SVG groups via a segId→group Map. New segments create one group;
//     existing segments only have attributes updated. Removed segments drop
//     one group. Click listeners are attached ONCE at group creation and look
//     up the current seg via state.segments on each click, so they survive
//     re-renders without leaks.
//
// Each segment is a single <g> wrapping (rect + optional text label). The group
// holds the data-seg-id used by the edge-drag handler.
// ----------------------------------------------------------------------------

const SVG_NS = 'http://www.w3.org/2000/svg';
const LANE_HEIGHT = 24;
const segGroups = new Map();   // segId → <g> element

// Sweep-line lane assignment: sort by start_frame, then for each segment
// linearly scan existing lanes (each tracks its current "last_end" frame).
// First lane whose last_end <= seg.start gets the segment. Otherwise, new lane.
// O(N log N) for the sort + O(N × L) for the placement where L is concurrent
// lane count (typically tiny — ≤ max-overlap).
function assignLanesSweep(segments) {
    const sorted = segments.slice().sort((a, b) => a.start_frame - b.start_frame);
    const laneLastEnd = [];   // index = lane number, value = current last_end
    sorted.forEach(seg => {
        let laneIdx = laneLastEnd.findIndex(end => end <= seg.start_frame);
        if (laneIdx === -1) { laneLastEnd.push(seg.end_frame); laneIdx = laneLastEnd.length - 1; }
        else { laneLastEnd[laneIdx] = seg.end_frame; }
        seg._lane = laneIdx;
    });
    return laneLastEnd.length;
}

function renderLanes() {
    const totalF = totalFrames();
    if (!totalF) return;

    const laneCount = Math.max(1, assignLanesSweep(state.segments));
    lanesSvg.setAttribute('height', laneCount * LANE_HEIGHT + 8);

    // Track which segIds we touched this pass; orphans (in map but not in state)
    // are removed after.
    const touched = new Set();

    // Hoist IoU computation out of the per-segment loop: O(N·M) instead of
    // O(N²·M) per render. Edge-drag re-renders on every mousemove, so the
    // per-segment recompute was the hot path under load.
    const iouByIdForLanes = GOLD_SEGMENTS.length ? computeIouMatches() : null;

    state.segments.forEach(seg => {
        touched.add(seg.id);
        const skill = getSkillById(seg.skill_id);
        const x = frameToPct(seg.start_frame);
        const w = frameToPct(seg.end_frame - seg.start_frame);
        const y = seg._lane * LANE_HEIGHT + 4;
        const dur = ((seg.end_frame - seg.start_frame) / VIDEO_FPS).toFixed(2);

        let g = segGroups.get(seg.id);
        let rect, text, tooltip;
        if (!g) {
            // Create group + rect + (always-present) text label. Listener attached once.
            g = document.createElementNS(SVG_NS, 'g');
            g.dataset.segId = String(seg.id);
            rect = document.createElementNS(SVG_NS, 'rect');
            rect.setAttribute('y', y);
            rect.setAttribute('height', LANE_HEIGHT - 4);
            rect.setAttribute('rx', 4);
            rect.setAttribute('fill-opacity', '0.85');
            rect.classList.add('timeline-segment');
            rect.classList.add('just-created');
            rect.addEventListener('animationend', () => rect.classList.remove('just-created'), { once: true });
            rect.dataset.segId = String(seg.id);
            rect.setAttribute('role', 'button');
            rect.setAttribute('tabindex', '0');
            // Native SVG tooltip — shows full segment info on hover, no JS needed
            tooltip = document.createElementNS(SVG_NS, 'title');
            rect.appendChild(tooltip);
            g.appendChild(rect);
            text = document.createElementNS(SVG_NS, 'text');
            text.setAttribute('y', y + 14);
            text.setAttribute('fill', 'white');
            text.setAttribute('font-size', '10');
            text.setAttribute('font-family', 'IBM Plex Mono, monospace');
            g.appendChild(text);
            // Single click listener uses live state lookup, so mutations don't
            // leave stale captured references.
            rect.addEventListener('click', (e) => {
                e.stopPropagation();
                const sid = parseInt(g.dataset.segId, 10);
                const target = state.segments.find(s => s.id === sid);
                if (!target) return;
                state.selectedId = target.id;
                video.currentTime = timeOfFrame(target.start_frame);
                renderLanes();
                if (typeof renderSegmentList === 'function') renderSegmentList();
            });
            lanesSvg.appendChild(g);
            segGroups.set(seg.id, g);
        } else {
            rect = g.querySelector('rect');
            text = g.querySelector('text');
        }

        // Patch only what changed
        rect.setAttribute('x', x + '%');
        rect.setAttribute('y', y);
        rect.setAttribute('width', w + '%');
        rect.setAttribute('fill', skill.color);
        rect.setAttribute('aria-label',
            `${seg.skill_id} segment, frames ${seg.start_frame} to ${seg.end_frame}, ${dur} seconds. Click to select. Drag edges to resize.`);
        rect.classList.toggle('selected', seg.id === state.selectedId);
        // Hover tooltip: skill · range · duration · IoU (when gold is loaded)
        const titleEl = rect.querySelector('title');
        if (titleEl) {
            const iouStr = iouByIdForLanes
                ? (() => {
                    const m = iouByIdForLanes.get(seg.id);
                    return m && m.gold ? ` · IoU ${m.iou.toFixed(2)} vs gold` : '';
                  })()
                : '';
            titleEl.textContent = `${seg.skill_id} · frames ${seg.start_frame}–${seg.end_frame} · ${dur}s${iouStr}`;
        }

        // Text label visible only when rect is wide enough
        if (w > 6) {
            text.setAttribute('x', (x + 0.3) + '%');
            text.setAttribute('y', y + 14);
            text.textContent = skill.label?.split(' ')[0] || seg.skill_id;
            text.style.display = '';
        } else {
            text.style.display = 'none';
        }
    });

    // Remove orphan groups (segments deleted since last render)
    segGroups.forEach((g, id) => {
        if (!touched.has(id)) {
            g.remove();
            segGroups.delete(id);
        }
    });
}

// Click anywhere on the empty lane SVG seeks the video.
lanesSvg.addEventListener('click', (e) => {
    if (e.target.tagName === 'rect' || e.target.tagName === 'text') return;
    const rect = lanesSvg.getBoundingClientRect();
    const pct = (e.clientX - rect.left) / rect.width;
    if (isFinite(video.duration)) {
        video.currentTime = Math.max(0, Math.min(video.duration, pct * video.duration));
    }
});

// Load + display the episode's task description so the labeler knows what
// they're labeling. Falls back silently if the metadata file is missing.
async function loadEpisodeMeta() {
    try {
        let meta;
        if (IS_DEMO_SOURCE) {
            const r = await fetch('assets/embodied/episode_meta.json');
            if (!r.ok) return null;
            meta = await r.json();
        } else {
            const bundle = await episodeSourceReady;
            if (!bundle?.meta) return null;
            // Bundle meta carries episode_index/fps/total_frames/camera/task;
            // dataset id comes from the URL, not the materializer.
            meta = { dataset: DATASET_ID, ...bundle.meta };
        }
        // Apply per-episode fps if provided. Default 15 set in module-level
        // declaration; all frameOf/timeOfFrame conversions pick this up
        // automatically since they read VIDEO_FPS at call time.
        if (typeof meta.fps === 'number' && meta.fps > 0) {
            VIDEO_FPS = meta.fps;
            updateTimeUI();   // refresh the frame readouts in case duration
                              // was known before fps changed
        }
        const taskText = document.getElementById('task-text');
        const taskZh = document.getElementById('task-text-zh');
        const datasetLabel = document.getElementById('dataset-label');
        if (taskText && meta.task) taskText.textContent = meta.task;
        if (taskZh && meta.task_zh) taskZh.textContent = meta.task_zh;
        if (datasetLabel && meta.dataset) {
            datasetLabel.textContent = `${meta.dataset} · ep ${meta.episode_index} · ${meta.camera || 'cam'}`;
        }
        if (meta.label_schema_id) {
            episodePreferredSchemaId = meta.label_schema_id;
            const storedSchemaId = (() => {
                try { return localStorage.getItem('embodied.label_schema_id') || ''; } catch (e) { return ''; }
            })();
            if (labelSchemasLoaded && !storedSchemaId) {
                setLabelSchema(episodePreferredSchemaId, { persist: false });
            }
        }
        return meta;
    } catch (e) {
        // No-op — header just shows the placeholder
    }
    return null;
}
loadEpisodeMeta();

// Gold reference lane — semi-transparent, dashed-outline rects on a separate
// SVG above the user's lanes. Loaded once at startup; never editable.
// GOLD_SEGMENTS is also exposed as a module-level array for IoU scoring.
let GOLD_SEGMENTS = [];
async function loadGold() {
    const goldSvg = document.getElementById('gold-lane');
    if (!goldSvg) return;
    try {
        let golds;
        if (IS_DEMO_SOURCE) {
            const r = await fetch('assets/embodied/gold_segments.json');
            if (!r.ok) return;
            golds = await r.json();
        } else {
            // Recorded gold rows are SubtaskSegment dumps — same
            // start_frame/end_frame/skill_id fields the lane renderer reads.
            const bundle = await episodeSourceReady;
            golds = bundle?.gold;
            if (!Array.isArray(golds)) return;   // null → dataset has no gold
        }
        GOLD_SEGMENTS = golds;
        renderGoldLane(golds);
        // Re-render the segment list so IoU badges appear if segments are
        // loaded before gold (race).
        if (typeof renderSegmentList === 'function') renderSegmentList();
    } catch (e) {
        // Silently fail — gold reference is a demo aid, not a requirement
    }
}

// ----------------------------------------------------------------------------
// Temporal IoU — exactly the same definition the LeRobot fork uses in
// src/lerobot/quality/temporal_iou.py temporal_iou(): intersection /
// union of two frame ranges. 0 if disjoint, 1 if identical, in between
// otherwise. The whole point of the spec.
// ----------------------------------------------------------------------------
function temporalIou(a, b) {
    // Defensive: zero/negative-length inputs → no overlap. Without this,
    // two same-point degenerate segments give 0/0 = NaN downstream → "NaN%".
    if (a.start_frame >= a.end_frame || b.start_frame >= b.end_frame) return 0;
    const inter = Math.max(0, Math.min(a.end_frame, b.end_frame) - Math.max(a.start_frame, b.start_frame));
    if (inter === 0) return 0;
    const union = (a.end_frame - a.start_frame) + (b.end_frame - b.start_frame) - inter;
    return union > 0 ? inter / union : 0;
}

// Match each user segment to the best-IoU gold segment with the same skill_id.
// Returns Map<userSegId, { gold, iou }>. Spec §5.1 uses Hungarian for true
// optimality; for the typical case of ≤1 user segment per skill, greedy
// best-match is identical and cheaper.
function computeIouMatches() {
    const matches = new Map();
    state.segments.forEach(u => {
        const candidates = GOLD_SEGMENTS.filter(g => g.skill_id === u.skill_id);
        if (candidates.length === 0) {
            matches.set(u.id, { gold: null, iou: 0 });
            return;
        }
        let bestIou = 0, bestGold = candidates[0];
        candidates.forEach(g => {
            const iou = temporalIou(u, g);
            if (iou > bestIou) { bestIou = iou; bestGold = g; }
        });
        matches.set(u.id, { gold: bestGold, iou: bestIou });
    });
    return matches;
}

function iouBadgeClass(iou, hasGold) {
    if (!hasGold) return 'bg-zinc-700/40 text-zinc-500 ring-zinc-700';
    if (iou >= 0.7) return 'bg-emerald-500/15 text-emerald-300 ring-emerald-500/40';
    if (iou >= 0.5) return 'bg-amber-500/15 text-amber-300 ring-amber-500/40';
    return 'bg-red-500/15 text-red-300 ring-red-500/40';
}

// Header summary: how many user segments meet the IoU≥0.7 threshold + avg IoU.
// Hidden when there's no gold or no user segments yet.
function renderIouSummary() {
    const el = document.getElementById('iou-summary');
    if (!el) return;
    if (!state.segments.length || !GOLD_SEGMENTS.length) {
        el.classList.add('hidden');
        return;
    }
    const matches = computeIouMatches();
    const ious = Array.from(matches.values()).filter(m => m.gold).map(m => m.iou);
    const aboveThreshold = ious.filter(iou => iou >= 0.7).length;
    const total = state.segments.length;
    const avg = ious.length ? ious.reduce((s, v) => s + v, 0) / ious.length : 0;
    const avgCls = avg >= 0.7 ? 'text-emerald-300'
                  : avg >= 0.5 ? 'text-amber-300'
                  : 'text-red-300';
    el.classList.remove('hidden');
    el.innerHTML = `
        <span class="text-zinc-500">vs gold:</span>
        <span class="text-light font-medium">${aboveThreshold}/${total}</span>
        <span class="text-zinc-600 text-[10px]">above IoU ≥ 0.7</span>
        <span class="text-zinc-700">·</span>
        <span class="${avgCls} font-medium">avg ${avg.toFixed(2)}</span>
    `;
}

function renderGoldLane(golds) {
    const goldSvg = document.getElementById('gold-lane');
    if (!goldSvg || !golds || !golds.length) return;
    goldSvg.innerHTML = '';
    const total = totalFrames() || golds[golds.length - 1].end_frame;
    golds.forEach(g => {
        const skill = getSkillById(g.skill_id);
        const x = (g.start_frame / total) * 100;
        const w = ((g.end_frame - g.start_frame) / total) * 100;
        const rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
        rect.setAttribute('x', x + '%');
        rect.setAttribute('y', 5);
        rect.setAttribute('width', w + '%');
        rect.setAttribute('height', 22);
        rect.setAttribute('rx', 6);
        rect.setAttribute('fill', skill.color);
        rect.setAttribute('fill-opacity', '0.16');
        rect.setAttribute('stroke', skill.color);
        rect.setAttribute('stroke-opacity', '0.72');
        rect.setAttribute('stroke-width', '1.5');
        rect.setAttribute('stroke-dasharray', '4 3');
        rect.setAttribute('role', 'img');
        rect.setAttribute('aria-label', `参考片段：${skill.label || g.skill_id}，第 ${g.start_frame} 到 ${g.end_frame} 帧。${g.instruction_text || ''}`);
        // Tooltip on hover
        const title = document.createElementNS('http://www.w3.org/2000/svg', 'title');
        title.textContent = `${skill.label || g.skill_id} · ${g.start_frame}–${g.end_frame} · ${g.instruction_text || ''}`;
        rect.appendChild(title);
        goldSvg.appendChild(rect);
        // Label text
        if (w > 5) {
            const text = document.createElementNS('http://www.w3.org/2000/svg', 'text');
            text.setAttribute('x', (x + 0.5) + '%');
            text.setAttribute('y', 20);
            text.setAttribute('fill', skill.color);
            text.setAttribute('font-size', '10');
            text.setAttribute('font-family', 'IBM Plex Mono, monospace');
            text.setAttribute('font-weight', '700');
            text.setAttribute('opacity', '0.95');
            text.setAttribute('pointer-events', 'none');
            text.textContent = skill.label?.split(' ')[0] || g.skill_id;
            goldSvg.appendChild(text);
        }
    });
}

async function loadGripper() {
    try {
        let url = 'assets/embodied/demo_episode.gripper.json';
        if (!IS_DEMO_SOURCE) {
            const bundle = await episodeSourceReady;
            if (!bundle?.proprio_url) throw new Error('bundle unavailable');
            // proprio.json (single channel) is the same flat float array shape
            // as the demo gripper trace.
            url = apiUrl(bundle.proprio_url);
        }
        const r = await fetch(url);
        if (!r.ok) throw new Error('fetch failed');
        const arr = await r.json();
        renderGripper(arr);
    } catch (e) {
        gripperError.classList.remove('hidden');
    }
}

function renderGripper(arr) {
    if (!arr.length) { gripperError.classList.remove('hidden'); return; }
    // Reduce loop, not a spread into Math.min/max — a long recorded episode
    // (>~65k frames) as call arguments overflows the engine's argument limit.
    let min = Infinity, max = -Infinity;
    for (const v of arr) {
        if (v < min) min = v;
        if (v > max) max = v;
    }
    const range = (max - min) || 1;
    gripperSvg.innerHTML = '';
    const W = 1000, H = 32;
    gripperSvg.setAttribute('viewBox', `0 0 ${W} ${H}`);
    gripperSvg.setAttribute('preserveAspectRatio', 'none');
    let d = '';
    arr.forEach((v, i) => {
        const x = (i / (arr.length - 1 || 1)) * W;
        const y = H - ((v - min) / range) * (H - 2) - 1;
        d += (i === 0 ? 'M' : 'L') + x.toFixed(1) + ',' + y.toFixed(1) + ' ';
    });
    const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    path.setAttribute('d', d);
    path.setAttribute('fill', 'none');
    path.setAttribute('stroke', '#0ea5e9');
    path.setAttribute('stroke-width', '1.5');
    gripperSvg.appendChild(path);
}

// Cached parent width for the timeline playhead (see scrubBarWidthPx note above).
let timelineTrackWidthPx = 0;
if (typeof ResizeObserver !== 'undefined' && playheadEl?.parentElement) {
    const ro = new ResizeObserver((entries) => {
        for (const entry of entries) {
            timelineTrackWidthPx = entry.contentRect.width;
        }
    });
    ro.observe(playheadEl.parentElement);
}

function updatePlayhead() {
    const pct = frameToPct(frameOf(video.currentTime || 0)) / 100;
    // transform writes only — no layout per timeupdate (60Hz was thrashing)
    if (!timelineTrackWidthPx && playheadEl?.parentElement) {
        timelineTrackWidthPx = playheadEl.parentElement.getBoundingClientRect().width;
    }
    playheadEl.style.transform = `translateX(${pct * timelineTrackWidthPx}px)`;
    renderPendingGhost();
}

// Ghost rect on the lanes SVG showing the in-progress segment from
// state.pendingStart to the current playhead. Industry-standard affordance
// (ATLAS, VIA): the labeler sees exactly what span S/S would commit before
// they release. Removed when no segment is open.
function renderPendingGhost() {
    let g = document.getElementById('pending-ghost');
    if (state.pendingStart === null) {
        if (g) g.remove();
        return;
    }
    const curFrame = frameOf(video.currentTime || 0);
    const lo = Math.min(state.pendingStart, curFrame);
    const hi = Math.max(state.pendingStart, curFrame);
    if (!g) {
        g = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
        g.id = 'pending-ghost';
        g.setAttribute('y', 4);
        g.setAttribute('height', 20);
        g.setAttribute('rx', 4);
        g.setAttribute('stroke-width', 1.5);
        g.setAttribute('stroke-dasharray', '4 3');
        g.setAttribute('pointer-events', 'none');
        lanesSvg.appendChild(g);
    }
    const skill = getSkillById(state.activeSkillId);
    g.setAttribute('x', frameToPct(lo) + '%');
    g.setAttribute('width', Math.max(0.3, frameToPct(hi - lo)) + '%');
    g.setAttribute('fill', skill.color);
    g.setAttribute('fill-opacity', '0.25');
    g.setAttribute('stroke', skill.color);
}
video.addEventListener('timeupdate', updatePlayhead);

// Sprite dimensions. SPRITE_TILES is only the pre-measurement default —
// the authoritative tile count comes from the sprite image's own width
// (measureSpriteTiles), so JS can never disagree with the asset, whether
// it's the 30-tile demo strip or a materialized ceil(duration*2) bundle strip.
const SPRITE_TILES = 30;
const SPRITE_FPS = 2;
const SPRITE_TILE_W = 128;  // px per tile in sprite.png
let spriteTilesTotal = SPRITE_TILES;
let spriteTilesUsed = SPRITE_TILES;

// Crop the thumbnail filmstrip to only the tiles that have content.
// Math.floor — better to slightly clip the last tile (no black showing) than
// to round up and let the trailing black peek through. Called from both
// loadedmetadata (duration known) and measureSpriteTiles (total known) since
// either can resolve first.
function applySpriteCrop() {
    if (!isFinite(video.duration) || video.duration <= 0) return;
    spriteTilesUsed = Math.max(1, Math.min(spriteTilesTotal, Math.floor(video.duration * SPRITE_FPS)));
    const sprite = document.getElementById('thumb-strip');
    if (sprite) {
        sprite.style.backgroundSize = spriteTilesUsed < spriteTilesTotal
            ? `${(spriteTilesTotal / spriteTilesUsed) * 100}% 100%`
            : '100% 100%';
    }
}

function measureSpriteTiles(url) {
    const img = new Image();
    img.onload = () => {
        if (img.naturalWidth > 0) {
            spriteTilesTotal = Math.max(1, Math.round(img.naturalWidth / SPRITE_TILE_W));
            applySpriteCrop();
        }
    };
    img.src = url;
}
if (IS_DEMO_SOURCE) {
    measureSpriteTiles('assets/embodied/sprite.png');
}
// (non-demo: applyEpisodeBundle measures the bundle's sprite URL)

video.addEventListener('loadedmetadata', () => {
    renderLanes();
    updatePlayhead();
    loadGold();   // now that totalFrames is known, render the gold lane
    applySpriteCrop();
});

// Scrub-bar hover preview: floating frame thumbnail follows the cursor.
// Uses the same sprite-sheet (one tile per 0.5s) for zero extra network cost.
const scrubPreview = document.getElementById('scrub-preview');
const scrubPreviewTime = document.getElementById('scrub-preview-time');
scrubBar.addEventListener('mousemove', (e) => {
    if (!isFinite(video.duration)) return;
    const rect = scrubBar.getBoundingClientRect();
    const pct = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    // Clamp tileIdx both directions — fast mouse can produce clientX outside rect.
    const tileIdx = Math.max(0, Math.min(spriteTilesUsed - 1, Math.floor(pct * spriteTilesUsed)));
    // Pull the right tile out of the sprite into the 128px window.
    scrubPreview.style.backgroundPosition = `-${tileIdx * SPRITE_TILE_W}px 0`;
    scrubPreview.style.backgroundSize = 'auto 100%';
    // Position via clamped pct, not raw clientX — overshoot would float the preview off the bar.
    scrubPreview.style.left = (pct * rect.width) + 'px';
    scrubPreviewTime.textContent = (pct * video.duration).toFixed(2) + 's';
    scrubPreview.classList.remove('hidden');
});
scrubBar.addEventListener('mouseleave', () => scrubPreview.classList.add('hidden'));

loadGripper();

// ----------------------------------------------------------------------------
// Segment creation: keyboard S toggle, buttons, click-and-drag on timeline
// ----------------------------------------------------------------------------

const btnMarkStart = document.getElementById('btn-mark-start');
const btnMarkEnd = document.getElementById('btn-mark-end');
const segmentStatus = document.getElementById('segment-status');

state.pendingStart = null;   // null or frame number while a segment is open
state.nextId = 1;
state.dirty = false;         // true when local segments differ from last save
state.storageMode = 'checking';
// Monotonic counter bumped by every mutation (via setDirty(true)). saveAll
// snapshots this before the fetch; if the value moves while the POST is in
// flight, a fresh mutation happened and we must NOT clear the dirty flag on
// response success — otherwise the new mutation would be silently lost.
state.saveEpoch = 0;

const dirtyBadge = document.getElementById('dirty-badge');
const saveHint = document.getElementById('save-hint');
const AUTOSAVE_DEBOUNCE_MS = 1500;
let autoSaveTimer = null;
const DIRTY_BADGE_DEFAULT_HTML = dirtyBadge.innerHTML;

function setDirty(d) {
    state.dirty = d;
    if (d) {
        // race-guard: bump epoch so any in-flight save can detect it raced a mutation.
        state.saveEpoch++;
        // If a "Saved" flash is still running, cancel it so we don't get a
        // delayed green→hidden overwrite of our fresh amber "Unsaved" badge.
        if (saveFlashTimer) { clearTimeout(saveFlashTimer); saveFlashTimer = null; }
        dirtyBadge.classList.remove('hidden');
        dirtyBadge.classList.remove('dirty-badge-saved');
        dirtyBadge.innerHTML = DIRTY_BADGE_DEFAULT_HTML;
        saveHint.classList.remove('hidden');
        scheduleAutoSave();
    } else {
        dirtyBadge.classList.add('hidden');
        saveHint.classList.add('hidden');
        if (autoSaveTimer) { clearTimeout(autoSaveTimer); autoSaveTimer = null; }
    }
    updateWorkflowPanel();
}

function setStorageMode(mode, detail = '') {
    state.storageMode = mode;
    if (!storageModeBadge) return;
    storageModeBadge.dataset.storageMode = mode;
    if (mode === 'backend') {
        storageModeBadge.textContent = detail || '后端同步已连接';
    } else if (mode === 'local') {
        storageModeBadge.textContent = detail || '本地演示模式 · 片段保存在浏览器';
    } else if (mode === 'pending') {
        storageModeBadge.textContent = detail || '本地副本待同步';
    } else {
        storageModeBadge.textContent = detail || '检查后端同步';
    }
}

// === Save-success pulse ===
// On a successful save (manual or auto), morph the amber "Unsaved" badge into
// a green "Saved" check for ~1.2s then hide. Replaces the previous silent
// disappear so the labeler gets positive confirmation that their work landed.
// Sequence: setDirty(false) hides the badge silently; flashSaveSuccess() then
// re-shows it briefly in the success state. The .dirty-badge-saved CSS class
// overrides the Tailwind amber utilities baked into the element.
let saveFlashTimer = null;
function flashSaveSuccess() {
    // Cancel any in-flight flash (e.g. user spams save) so we restart cleanly.
    if (saveFlashTimer) { clearTimeout(saveFlashTimer); saveFlashTimer = null; }
    dirtyBadge.classList.remove('hidden');
    dirtyBadge.classList.add('dirty-badge-saved');
    dirtyBadge.innerHTML = `
        <span class="dirty-badge-saved-dot"></span>
        <i class="fa fa-check"></i>
        已保存 Saved
    `;
    const reduced = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const holdMs = reduced ? 700 : 1200;
    saveFlashTimer = setTimeout(() => {
        saveFlashTimer = null;
        dirtyBadge.classList.add('hidden');
        dirtyBadge.classList.remove('dirty-badge-saved');
        dirtyBadge.innerHTML = DIRTY_BADGE_DEFAULT_HTML;
    }, holdMs);
}

// Debounced auto-save: every mutation calls setDirty(true) which schedules
// a save after AUTOSAVE_DEBOUNCE_MS of no further edits. If a segment is
// in-progress (S pressed but not yet closed), retry once it's closed so we
// never persist half-states.
function scheduleAutoSave(delayMs = AUTOSAVE_DEBOUNCE_MS) {
    if (autoSaveTimer) clearTimeout(autoSaveTimer);
    autoSaveTimer = setTimeout(() => {
        autoSaveTimer = null;
        if (state.pendingStart !== null) {
            scheduleAutoSave();
            return;
        }
        if (state.dirty) saveAll({ auto: true });
    }, delayMs);
}

// Now that btn-mark-start exists, apply the initial active-skill tint.
setActiveSkill(state.activeSkillId);

function showToast(msg, kind = 'info') {
    const container = document.getElementById('toast-container');
    const t = document.createElement('div');
    const color = kind === 'error' ? 'bg-red-600'
                : kind === 'success' ? 'bg-emerald-600'
                : 'bg-zinc-700';
    t.className = `${color} text-white text-sm px-4 py-2 rounded shadow-lg`;
    t.textContent = msg;
    container.appendChild(t);
    setTimeout(() => t.remove(), 3000);
}

function getAnnotatorId() {
    let id = localStorage.getItem('embodied.annotator_id');
    if (!id) {
        id = crypto.randomUUID();
        localStorage.setItem('embodied.annotator_id', id);
    }
    return id;
}

// Raw commit — always invoked through the commitSegment() wrapper below,
// which pushes the undo snapshot first.
function commitSegmentRaw(start, end, skillId) {
    // defensive: enforce minimum width regardless of caller
    if (end - start < MIN_FRAMES) {
        end = start + MIN_FRAMES;
    }
    const seg = {
        id: state.nextId++,
        annotator_id: getAnnotatorId(),
        episode_index: EPISODE_INDEX,   // from ?episode= (0 for the demo)
        start_frame: start,
        end_frame: end,
        skill_id: skillId,
        success: null,
    };
    state.segments.push(seg);
    renderLanes();
    renderPendingGhost();   // clear the ghost overlay
    if (typeof renderSegmentList === 'function') renderSegmentList();
    if (typeof setDirty === 'function') setDirty(true);
    // Auto-loop the just-created segment so the labeler can QA the boundaries
    // immediately (research E.2 — Labelbox community pattern, "watch in a
    // loop in their normal practice"). Replaces the previous auto-advance:
    // QA-then-move-on beats commit-and-fly-past for boundary accuracy. To
    // mark back-to-back without loop, press \\ once to disable.
    enterSegmentQALoop(seg);
    showToast(`Added ${skillId} [${start}, ${end}) — segment selected for QA`, 'success');
}

function toggleSegment() {
    const curFrame = frameOf(video.currentTime || 0);
    if (state.pendingStart === null) {
        // Open new segment
        state.pendingStart = curFrame;
        btnMarkStart.classList.add('hidden');
        btnMarkEnd.classList.remove('hidden');
        const skill = getSkillById(state.activeSkillId);
        segmentStatus.classList.remove('hidden');
        segmentStatus.innerHTML = `
            <i class="fa fa-circle text-accent" style="animation: pulse 1.5s ease-in-out infinite;"></i>
            <span>Segment <span style="color:${safeCssColor(skill.color)}">${escapeHtml(skill.id)}</span> open at frame <span class="text-light">${curFrame}</span> — scrub to end and press <kbd class="px-1 bg-zinc-800 ring-1 ring-zinc-700 rounded text-zinc-300">S</kbd></span>
        `;
        renderPendingGhost();
        updateWorkflowPanel();
    } else {
        // Close
        const start = state.pendingStart;
        const end = curFrame;
        state.pendingStart = null;
        btnMarkStart.classList.remove('hidden');
        btnMarkEnd.classList.add('hidden');
        segmentStatus.classList.add('hidden');
        segmentStatus.textContent = '';
        if (end <= start) {
            showToast('终点必须晚于起点 (end must be > start)', 'error');
            renderPendingGhost();   // clear stale ghost on invalid close
            updateWorkflowPanel();
            return;
        }
        commitSegment(start, end, state.activeSkillId);
        updateWorkflowPanel();
    }
}

btnMarkStart.addEventListener('click', toggleSegment);
btnMarkEnd.addEventListener('click', toggleSegment);

document.addEventListener('keydown', (e) => {
    if (isEditableTarget(e)) return;
    if (e.key === 's' || e.key === 'S') {
        e.preventDefault();
        toggleSegment();
    }
});

// ----------------------------------------------------------------------------
// Edge-drag on committed segments: cursor within EDGE_ZONE of left/right edge
// starts resizing that boundary. Anywhere else within the rect = click-to-select
// (handled by the rect's own click listener in renderLanes).
// ----------------------------------------------------------------------------
let edgeDrag = null;
const EDGE_ZONE = 8;  // pixels
// Minimum segment width in frames — clamp each edge against the OTHER edge so
// successive nudges/drags can never collapse a segment to zero or negative width.
const MIN_FRAMES = 1;

lanesSvg.addEventListener('mousedown', (e) => {
    if (e.target.tagName !== 'rect') return;
    if (!e.target.classList.contains('timeline-segment')) return;
    const segId = parseInt(e.target.dataset.segId, 10);
    const seg = state.segments.find(s => s.id === segId);
    if (!seg) return;
    const r = e.target.getBoundingClientRect();
    const nearLeft = e.clientX < r.left + EDGE_ZONE;
    const nearRight = e.clientX > r.right - EDGE_ZONE;
    if (nearLeft || nearRight) {
        if (typeof pushUndoSnapshot === 'function') pushUndoSnapshot();
        edgeDrag = { seg, side: nearLeft ? 'start' : 'end' };
        document.body.style.cursor = 'ew-resize';
        e.preventDefault();
        e.stopPropagation();   // prevent click-to-select from firing
    }
});

// Cursor feedback when hovering near a segment edge
lanesSvg.addEventListener('mousemove', (e) => {
    if (edgeDrag) return;
    if (e.target.tagName !== 'rect' || !e.target.classList.contains('timeline-segment')) return;
    const r = e.target.getBoundingClientRect();
    const nearEdge = e.clientX < r.left + EDGE_ZONE || e.clientX > r.right - EDGE_ZONE;
    e.target.style.cursor = nearEdge ? 'ew-resize' : 'pointer';
});

// During edge drag: update segment boundary from cursor X
window.addEventListener('mousemove', (e) => {
    if (!edgeDrag) return;
    const lanesRect = lanesSvg.getBoundingClientRect();
    const pct = Math.max(0, Math.min(1, (e.clientX - lanesRect.left) / lanesRect.width));
    const frame = Math.round(pct * totalFrames());
    const { seg, side } = edgeDrag;
    if (side === 'start') {
        seg.start_frame = Math.max(0, Math.min(seg.end_frame - MIN_FRAMES, frame));
    } else {
        seg.end_frame = Math.max(seg.start_frame + MIN_FRAMES, Math.min(totalFrames(), frame));
    }
    // Visual feedback: scrub the video to follow the dragged edge.
    if (isFinite(video.duration)) video.currentTime = timeOfFrame(frame);
    renderLanes();
});

// End edge drag — final commit + cleanup
window.addEventListener('mouseup', () => {
    if (!edgeDrag) return;
    renderSegmentList();
    setDirty(true);
    document.body.style.cursor = '';
    edgeDrag = null;
});

// ----------------------------------------------------------------------------
// Click-and-drag on empty timeline space = third creation path.
// A drag of ≥2 frames commits a new segment with the active skill.
// ----------------------------------------------------------------------------
let drag = null;
lanesSvg.addEventListener('mousedown', (e) => {
    if (e.target.tagName === 'rect' || e.target.tagName === 'text') return;
    if (edgeDrag) return;   // edge-drag wins if it's already active
    const rect = lanesSvg.getBoundingClientRect();
    const pct = (e.clientX - rect.left) / rect.width;
    const startFrame = Math.round(pct * totalFrames());
    drag = { startFrame };
});
window.addEventListener('mouseup', (e) => {
    if (!drag) return;
    const rect = lanesSvg.getBoundingClientRect();
    const pct = (e.clientX - rect.left) / rect.width;
    const endFrame = Math.round(pct * totalFrames());
    if (Math.abs(endFrame - drag.startFrame) >= 2) {
        commitSegment(
            Math.min(drag.startFrame, endFrame),
            Math.max(drag.startFrame, endFrame),
            state.activeSkillId,
        );
    }
    drag = null;
});

// ----------------------------------------------------------------------------
// Segment list panel — inline edit, success toggle, delete, click-to-seek
// ----------------------------------------------------------------------------

const segmentListEl = document.getElementById('segment-list');
const segCount = document.getElementById('seg-count');

// ----------------------------------------------------------------------------
// renderSegmentList — incremental diff-and-patch.
// Was: full innerHTML wipe + create N rows × (6 nodes/row + ~6 listeners/row)
//     on every mutation. At N=500 with active typing, several hundred ms of
//     jank per keystroke.
// Now: rowById Map; existing rows have their inner values patched, new rows
//     are created once with listeners attached that look up the current seg
//     by data-seg-id on every event. Reordering on sort is free (appendChild
//     moves existing nodes). Orphans are removed after.
// ----------------------------------------------------------------------------

const rowByIdMap = new Map();   // segId → row DIV
const EMPTY_STATE_HTML = `
    <div class="embodied-empty-segments empty-state">
        <div class="embodied-empty-summary">
            <div class="embodied-empty-icon" aria-hidden="true">
                <i class="fa fa-pencil-square-o"></i>
            </div>
            <div>
                <p class="embodied-empty-eyebrow">当前清单为空</p>
                <h3>从第一个动作片段开始</h3>
                <p>选好技能后，在视频里标记动作开始和结束，片段会自动出现在这里供复核。</p>
            </div>
        </div>
        <div class="embodied-empty-steps" aria-label="标注步骤">
            <span><strong>1</strong> 选技能</span>
            <span><strong>2</strong> 标起点</span>
            <span><strong>3</strong> 标终点并复核</span>
        </div>
        <div class="embodied-empty-buttons">
            <button type="button" class="embodied-empty-action" data-action="empty-mark-start">
                <i class="fa fa-circle"></i>
                从当前帧开始标记
            </button>
            <button type="button" class="embodied-empty-secondary" data-action="empty-open-shortcuts">
                <i class="fa fa-keyboard-o"></i>
                查看快捷键
            </button>
        </div>
    </div>
`;
const ROW_TEMPLATE = `
    <span class="skill-dot inline-block w-3 h-3 rounded-full flex-shrink-0"></span>
    <select data-action="change-skill"
            class="skill-select bg-transparent text-sm w-24 px-1.5 py-0.5 rounded
                   hover:bg-zinc-800 focus:bg-zinc-800
                   focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent
                   cursor-pointer transition border-none appearance-none"
            title="Change skill — Shift+1–9 also works when this segment is selected"></select>
    <span class="font-mono text-xs text-zinc-400 tabular-nums">
        <input type="number" data-field="start_frame" class="w-14 bg-transparent border-b border-zinc-700 focus:border-accent outline-none text-right">
        →
        <input type="number" data-field="end_frame" class="w-14 bg-transparent border-b border-zinc-700 focus:border-accent outline-none text-right">
    </span>
    <span class="duration ml-2 font-mono text-xs text-zinc-500 tabular-nums"></span>
    <span class="iou-badge ml-2 px-2 py-0.5 rounded-full text-[10px] font-mono font-medium ring-1" style="display:none"></span>
    <button data-action="toggle-success" class="ml-2 w-7 h-7 flex items-center justify-center rounded text-sm hover:bg-zinc-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent transition" title="success / fail / unknown"></button>
    <button data-action="delete" class="ml-auto w-7 h-7 flex items-center justify-center rounded text-zinc-500 hover:bg-zinc-700 hover:text-red-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent transition" title="Delete">
        <i class="fa fa-times"></i>
    </button>
`;
const SUCCESS_COLOR_CLASSES = ['text-emerald-500', 'text-red-500', 'text-zinc-600'];

segmentListEl.addEventListener('click', (e) => {
    const actionButton = e.target.closest('[data-action]');
    if (!actionButton) return;
    if (actionButton.dataset.action === 'empty-mark-start') {
        e.preventDefault();
        e.stopPropagation();
        if (state.pendingStart !== null) {
            showToast('已经有起点了，拖到终点后再按 S 完成片段', 'info');
            return;
        }
        toggleSegment();
        video.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
    if (actionButton.dataset.action === 'empty-open-shortcuts') {
        e.preventDefault();
        e.stopPropagation();
        document.getElementById('help-overlay')?.classList.remove('hidden');
    }
});

// Live-lookup helper so listeners survive across diff-and-patch renders
function _segByRow(row) {
    const id = parseInt(row.dataset.segId, 10);
    return state.segments.find(s => s.id === id);
}

function _createSegmentRow(seg) {
    const row = document.createElement('div');
    row.dataset.segId = String(seg.id);
    row.className = 'flex items-center gap-3 px-3 py-2 rounded hover:bg-zinc-800 cursor-pointer';
    row.innerHTML = ROW_TEMPLATE;

    // Click row → seek + select (skip when click target is input/select/button)
    row.addEventListener('click', (e) => {
        if (isEditableTarget(e) || e.target.closest('button')) return;
        const s = _segByRow(row);
        if (!s) return;
        state.selectedId = s.id;
        video.currentTime = timeOfFrame(s.start_frame);
        renderLanes();
        renderSegmentList();
    });
    // Change skill via dropdown
    const sel = row.querySelector('[data-action="change-skill"]');
    syncSkillSelectOptions(sel, seg.skill_id);
    sel.addEventListener('change', (e) => {
        const s = _segByRow(row);
        if (!s || e.target.value === s.skill_id) return;
        pushUndoSnapshot?.();
        s.skill_id = e.target.value;
        renderLanes();
        renderSegmentList();
        setDirty(true);
        showToast(`Changed to ${e.target.value}`, 'success');
    });
    sel.addEventListener('click', (e) => e.stopPropagation());
    // Inline-edit start / end frames
    row.querySelectorAll('input[data-field]').forEach(inp => {
        inp.addEventListener('change', () => {
            const s = _segByRow(row);
            if (!s) return;
            const field = inp.dataset.field;
            const val = parseInt(inp.value, 10);
            if (isNaN(val) || val < 0) { inp.value = s[field]; return; }
            const prev = s[field];
            // Speculatively apply so we can validate against both fields, but
            // snapshot BEFORE the mutation so undo restores cleanly. If the
            // validation fails, pop the (now-invalid) snapshot we just pushed.
            pushUndoSnapshot?.();
            s[field] = val;
            if (s.start_frame >= s.end_frame) {
                showToast('起点必须早于终点', 'error');
                s[field] = prev;
                inp.value = prev;
                // Roll back the snapshot we pushed — there was no real edit
                state.undoStack?.pop();
                return;
            }
            renderLanes();
            renderSegmentList();
            setDirty(true);
        });
    });
    // Success toggle
    row.querySelector('[data-action="toggle-success"]').addEventListener('click', (e) => {
        e.stopPropagation();
        const s = _segByRow(row);
        if (!s) return;
        pushUndoSnapshot?.();
        s.success = s.success === null ? true : s.success === true ? false : null;
        renderSegmentList();
        setDirty(true);
    });
    // Delete
    row.querySelector('[data-action="delete"]').addEventListener('click', (e) => {
        e.stopPropagation();
        const s = _segByRow(row);
        if (!s) return;
        pushUndoSnapshot?.();
        state.segments = state.segments.filter(x => x.id !== s.id);
        if (state.selectedId === s.id) state.selectedId = null;
        renderLanes();
        renderSegmentList();
        setDirty(true);
        showToast(`Deleted ${s.skill_id} — 按 Z 撤销 (press Z to undo)`);
    });
    return row;
}

function _patchSegmentRow(row, seg, iouMatch) {
    // Selection ring (compose with base classes — no innerHTML thrash)
    const isSelected = seg.id === state.selectedId;
    row.classList.toggle('bg-zinc-800', isSelected);
    row.classList.toggle('ring-1', isSelected);
    row.classList.toggle('ring-accent', isSelected);

    const skill = getSkillById(seg.skill_id);
    row.querySelector('.skill-dot').style.background = skill.color;

    const sel = row.querySelector('[data-action="change-skill"]');
    syncSkillSelectOptions(sel, seg.skill_id);
    if (sel.value !== seg.skill_id) sel.value = seg.skill_id;

    const startInp = row.querySelector('input[data-field="start_frame"]');
    const endInp = row.querySelector('input[data-field="end_frame"]');
    // Don't stomp on the user actively typing into the input
    if (document.activeElement !== startInp) startInp.value = seg.start_frame;
    if (document.activeElement !== endInp) endInp.value = seg.end_frame;

    row.querySelector('.duration').innerHTML =
        `· ${((seg.end_frame - seg.start_frame) / VIDEO_FPS).toFixed(2)}s ` +
        `<span class="text-zinc-600">(${seg.end_frame - seg.start_frame}f)</span>`;

    // IoU badge
    const iouEl = row.querySelector('.iou-badge');
    if (iouMatch && GOLD_SEGMENTS.length) {
        const cls = iouBadgeClass(iouMatch.iou, !!iouMatch.gold);
        const label = iouMatch.gold ? `IoU ${iouMatch.iou.toFixed(2)}` : 'no gold';
        iouEl.className = `iou-badge ml-2 px-2 py-0.5 rounded-full text-[10px] font-mono font-medium ring-1 ${cls}`;
        iouEl.textContent = label;
        iouEl.title = iouMatch.gold
            ? `vs gold ${iouMatch.gold.skill_id} [${iouMatch.gold.start_frame}, ${iouMatch.gold.end_frame}): IoU = ${iouMatch.iou.toFixed(3)}`
            : `No gold reference for ${seg.skill_id}`;
        iouEl.style.display = '';
    } else {
        iouEl.style.display = 'none';
    }

    // Success state — 3-state icon + color class
    const successBtn = row.querySelector('[data-action="toggle-success"]');
    successBtn.textContent = seg.success === true ? '✓' : seg.success === false ? '✗' : '—';
    SUCCESS_COLOR_CLASSES.forEach(c => successBtn.classList.remove(c));
    successBtn.classList.add(
        seg.success === true ? 'text-emerald-500'
        : seg.success === false ? 'text-red-500'
        : 'text-zinc-600'
    );
}

function renderSegmentList() {
    segCount.textContent = `(${state.segments.length})`;
    updateWorkflowPanel();
    renderIouSummary();
    if (state.segments.length === 0) {
        // Drop all rows; show empty state
        rowByIdMap.forEach(row => row.remove());
        rowByIdMap.clear();
        if (!segmentListEl.querySelector('.empty-state')) {
            segmentListEl.innerHTML = EMPTY_STATE_HTML;
        }
        return;
    }
    // Drop the empty-state node if present
    const empty = segmentListEl.querySelector('.empty-state');
    if (empty) empty.remove();

    const iouMatches = computeIouMatches();
    const sorted = state.segments.slice().sort((a, b) => a.start_frame - b.start_frame);
    const touched = new Set();
    sorted.forEach(seg => {
        touched.add(seg.id);
        let row = rowByIdMap.get(seg.id);
        if (!row) {
            row = _createSegmentRow(seg);
            rowByIdMap.set(seg.id, row);
        }
        _patchSegmentRow(row, seg, iouMatches.get(seg.id));
        // Reorder: appendChild moves an existing node to the end, preserving listeners
        segmentListEl.appendChild(row);
    });
    // Remove orphans (segments deleted since last render)
    rowByIdMap.forEach((row, id) => {
        if (!touched.has(id)) {
            row.remove();
            rowByIdMap.delete(id);
        }
    });
}

renderSegmentList();

// ----------------------------------------------------------------------------
// Save / Load via the backend (API_BASE + EPISODE_ID are derived at the top
// of this module from the <meta name="api-base"> tag and ?dataset/?episode).
// ----------------------------------------------------------------------------

const saveBtn = document.getElementById('save-btn');

// In-flight guard so a manual click during a pending auto-save (or vice-versa)
// doesn't fire two concurrent POSTs and let the wrong one win.
let saveInFlight = false;

function segmentsForPersistence(rawSegments) {
    return rawSegments
        .filter(s => s.end_frame > s.start_frame)
        .map(s => ({
            annotator_id: s.annotator_id,
            episode_index: s.episode_index,
            start_frame: s.start_frame,
            end_frame: s.end_frame,
            skill_id: s.skill_id,
            success: s.success,
        }));
}

function localSegmentsKey(annotatorId) {
    return `embodied.segments.${EPISODE_ID}.${annotatorId}`;
}

function localPendingSyncKey(annotatorId) {
    return `embodied.pending_sync.${EPISODE_ID}.${annotatorId}`;
}

function saveSegmentsLocal(segments, annotatorId = getAnnotatorId()) {
    localStorage.setItem(localSegmentsKey(annotatorId), JSON.stringify(segments));
}

function loadSegmentsLocal(annotatorId = getAnnotatorId()) {
    try {
        const raw = localStorage.getItem(localSegmentsKey(annotatorId));
        if (!raw) return [];
        const parsed = JSON.parse(raw);
        return Array.isArray(parsed) ? parsed : [];
    } catch (e) {
        return [];
    }
}

function markLocalPendingSync(annotatorId = getAnnotatorId(), segmentCount = 0) {
    try {
        localStorage.setItem(localPendingSyncKey(annotatorId), JSON.stringify({
            episode_id: EPISODE_ID,
            annotator_id: annotatorId,
            segment_count: segmentCount,
            saved_at: new Date().toISOString(),
        }));
    } catch (e) {
        // If storage metadata fails but segments were saved, keep the save path
        // non-blocking and rely on the visible local-mode badge.
    }
}

function clearLocalPendingSync(annotatorId = getAnnotatorId()) {
    try {
        localStorage.removeItem(localPendingSyncKey(annotatorId));
    } catch (e) {
        // Ignore storage cleanup failures; backend save already succeeded.
    }
}

function clearLocalDemoState(annotatorId = getAnnotatorId()) {
    try {
        localStorage.removeItem(localSegmentsKey(annotatorId));
        localStorage.removeItem(localPendingSyncKey(annotatorId));
    } catch (e) {
        // Ignore cleanup failures; reset still rotates the local annotator id.
    }
}

function hasLocalPendingSync(annotatorId = getAnnotatorId()) {
    try {
        return localStorage.getItem(localPendingSyncKey(annotatorId)) !== null;
    } catch (e) {
        return false;
    }
}

async function saveAll({ auto = false } = {}) {
    if (saveInFlight) {
        // If auto fires while manual is in flight, silently skip — the manual
        // save will land what we have. If manual fires during auto, also skip
        // and let auto finish (manual will re-schedule via setDirty if state
        // hasn't been cleaned yet). For manual clicks, surface a hint so the
        // user knows their click was acknowledged (data is safe either way).
        if (!auto) showToast('保存中…请稍候 Save already running', 'info');
        return;
    }
    // Don't persist while a segment is mid-creation (S/I pressed, no O/S yet).
    // Auto-save already defers via scheduleAutoSave; manual must mirror that
    // or the in-progress mark is silently dropped from the saved payload.
    if (state.pendingStart !== null) {
        if (!auto) showToast('片段未关闭 — 按 O 或 S 标记结束后再保存', 'info');
        return;
    }
    saveInFlight = true;
    // race-guard: snapshot the mutation generation; if it moves before the
    // response lands, a fresh edit raced us and we must NOT clear dirty.
    const epoch = state.saveEpoch;
    const annotator_id = getAnnotatorId();
    const rawSegments = state.segments;
    // Defensive validator: drop any zero/negative-width seg before POST.
    // Should be unreachable after MIN_FRAMES clamps; belt-and-suspenders so a
    // future regression can't push an invalid seg server-side (422).
    const segments = segmentsForPersistence(rawSegments);
    if (segments.length !== rawSegments.length) {
        console.warn('saveAll: dropped', rawSegments.length - segments.length, 'zero-width segment(s) before POST');
    }
    // Loading state:
    //   - Manual save: prominent button-spinner so the click registers
    //   - Auto-save:   quiet badge swap so the labeler isn't interrupted
    const origBtnHTML = saveBtn.innerHTML;
    if (!auto) {
        saveBtn.disabled = true;
        saveBtn.classList.add('opacity-70', 'cursor-not-allowed');
        saveBtn.innerHTML = '<i class="fa fa-spinner fa-spin mr-2"></i>保存中…';
    } else {
        dirtyBadge.innerHTML = `
            <i class="fa fa-spinner fa-spin text-amber-300"></i>
            自动保存中… Auto-saving
        `;
    }
    try {
        if (state.storageMode === 'local') {
            saveSegmentsLocal(segments, annotator_id);
            markLocalPendingSync(annotator_id, segments.length);
            if (!auto) showToast(`已保存 ${segments.length} 个片段到本地演示`, 'success');
            if (state.saveEpoch === epoch) {
                setDirty(false);
                flashSaveSuccess();
            } else {
                scheduleAutoSave();
            }
            return;
        }
        const r = await fetch(`${API_BASE}/api/embodied/segments`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                // Defense-in-depth: server requires header == body annotator_id.
                'X-Annotator-Id': annotator_id,
            },
            body: JSON.stringify({ episode_id: EPISODE_ID, annotator_id, segments }),
        });
        if (!r.ok) {
            const txt = await r.text();
            throw new Error(`${r.status} ${txt.slice(0, 80)}`);
        }
        const data = await r.json();
        setStorageMode('backend', '后端同步已连接');
        if (!auto) {
            showToast(`已保存 ${data.written} 个片段`, 'success');
        }
        if (state.saveEpoch === epoch) {
            clearLocalPendingSync(annotator_id);
            // No mutation raced us — safe to clear dirty + flash success.
            setDirty(false);
            flashSaveSuccess();
        } else {
            // Mutation happened during the in-flight POST; that mutation's
            // setDirty(true) already armed a fresh timer, but re-arm
            // defensively so we never end up dirty-but-untimed.
            scheduleAutoSave();
        }
    } catch (e) {
        saveSegmentsLocal(segments, annotator_id);
        markLocalPendingSync(annotator_id, segments.length);
        setStorageMode('local', '本地演示模式 · 后端不可用，片段保存在浏览器');
        if (auto) {
            dirtyBadge.innerHTML = DIRTY_BADGE_DEFAULT_HTML;
        } else {
            showToast(`后端不可用，已保存 ${segments.length} 个片段到本地演示`, 'success');
        }
        if (state.saveEpoch === epoch) {
            setDirty(false);
            flashSaveSuccess();
        } else {
            scheduleAutoSave();
        }
    } finally {
        saveInFlight = false;
        if (!auto) {
            saveBtn.disabled = false;
            saveBtn.classList.remove('opacity-70', 'cursor-not-allowed');
            saveBtn.innerHTML = origBtnHTML;
        }
    }
}

async function loadExisting() {
    const annotator_id = getAnnotatorId();
    const localPendingSync = hasLocalPendingSync(annotator_id);
    setStorageMode('checking', '检查后端同步');
    try {
        const r = await fetch(`${API_BASE}/api/embodied/segments?episode_id=${EPISODE_ID}&annotator_id=${annotator_id}`, {
            // Defense-in-depth: server requires header == query annotator_id.
            headers: { 'X-Annotator-Id': annotator_id },
        });
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const segs = await r.json();
        if (localPendingSync) {
            const localSegments = loadSegmentsLocal(annotator_id);
            state.segments = localSegments.map(s => ({ ...s, id: state.nextId++ }));
            renderLanes();
            renderSegmentList();
            setDirty(true);
            setStorageMode('pending', '本地副本待同步 · 后端已恢复');
            scheduleAutoSave(0);
            showToast(`已恢复 ${localSegments.length} 个待同步本地片段，正在同步后端`, 'info');
            return;
        }
        // Tag each loaded segment with a fresh client id (server doesn't track ids)
        state.segments = segs.map(s => ({ ...s, id: state.nextId++ }));
        renderLanes();
        renderSegmentList();
        setDirty(false);   // freshly loaded = pristine
        setStorageMode('backend', '后端同步已连接');
        if (segs.length) showToast(`已加载 ${segs.length} 个保存的片段`);
    } catch (e) {
        const segs = loadSegmentsLocal(annotator_id);
        state.segments = segs.map(s => ({ ...s, id: state.nextId++ }));
        renderLanes();
        renderSegmentList();
        setDirty(false);
        setStorageMode('local', '本地演示模式 · 片段保存在浏览器');
        if (segs.length) showToast(`已加载 ${segs.length} 个本地演示片段`);
    }
}

// ⌘S / Ctrl+S — natural save shortcut. preventDefault stops the browser
// Save-Page dialog from intercepting. Deliberately NOT gated on
// isEditableTarget: save must work from any focus context (input, button,
// dropdown) — otherwise ⌘S from a frame-edit input opens the browser dialog.
document.addEventListener('keydown', (e) => {
    if ((e.metaKey || e.ctrlKey) && (e.key === 's' || e.key === 'S')) {
        e.preventDefault();
        saveAll();
    }
});

// Protect unsaved work on navigation. Browsers show their own dialog; we just
// trigger it by setting returnValue when state.dirty OR a save is in flight
// (closing mid-POST cancels the fetch — the user may have hit Save and assumed
// it landed; surface the prompt so they can wait one more second).
window.addEventListener('beforeunload', (e) => {
    if (state.dirty || saveInFlight) {
        e.preventDefault();
        e.returnValue = '';   // required by some browsers to trigger the prompt
    }
});

saveBtn.addEventListener('click', saveAll);

loadExisting();

// ----------------------------------------------------------------------------
// Hotkey overlay + remaining shortcuts: Q/E nav, [/] nudge, Backspace delete, Z undo
// ----------------------------------------------------------------------------

const helpBtn = document.getElementById('help-btn');
const helpOverlay = document.getElementById('help-overlay');
const helpClose = document.getElementById('help-close');

helpBtn.addEventListener('click', () => helpOverlay.classList.remove('hidden'));
helpClose.addEventListener('click', () => helpOverlay.classList.add('hidden'));
helpOverlay.addEventListener('click', (e) => {
    if (e.target === helpOverlay) helpOverlay.classList.add('hidden');
});

// Reset Demo: clear current local demo data, rotate annotator id, reload.
// Lives in the help overlay because that's where presenters naturally look.
const resetDemoBtn = document.getElementById('reset-demo');
if (resetDemoBtn) {
    resetDemoBtn.addEventListener('click', () => {
        const currentAnnotatorId = getAnnotatorId();
        clearLocalDemoState(currentAnnotatorId);
        localStorage.removeItem('embodied.annotator_id');
        location.reload();
    });
}

// Undo / redo stacks. Each entry is a deep clone of state.segments.
// pushUndoSnapshot is called before every mutation; it also clears the redo
// stack (new branch). undo() pops to redoStack; redo() pops back.
state.undoStack = [];
state.redoStack = [];

function pushUndoSnapshot() {
    state.undoStack.push(JSON.parse(JSON.stringify(state.segments)));
    if (state.undoStack.length > 50) state.undoStack.shift();
    state.redoStack.length = 0;   // new mutation invalidates redo history
}

function redo() {
    if (!state.redoStack.length) {
        showToast('Nothing to redo');
        return;
    }
    // Push current state to undo, restore from redo
    state.undoStack.push(JSON.parse(JSON.stringify(state.segments)));
    if (state.undoStack.length > 50) state.undoStack.shift();
    state.segments = state.redoStack.pop();
    state.selectedId = null;
    renderLanes();
    renderSegmentList();
    setDirty(true);
}

// commitSegment = undo snapshot + raw commit. A named wrapper (not a
// reassignment of the original declaration) — reassignment only worked
// because function declarations are var-like, and a refactor to const
// would have silently broken the undo hook.
function commitSegment(start, end, skillId) {
    pushUndoSnapshot();
    commitSegmentRaw(start, end, skillId);
}

function selectedSegment() {
    return state.segments.find(s => s.id === state.selectedId);
}

function nudgeEdge(side, delta) {
    const seg = selectedSegment();
    if (!seg) return;
    pushUndoSnapshot();
    if (side === 'left') {
        // Clamp against the opposite edge so nudging never collapses width to 0.
        seg.start_frame = Math.max(0, Math.min(seg.end_frame - MIN_FRAMES, seg.start_frame + delta));
    } else {
        seg.end_frame = Math.max(seg.start_frame + MIN_FRAMES, Math.min(totalFrames(), seg.end_frame + delta));
    }
    renderLanes();
    renderSegmentList();
    setDirty(true);
}

function jumpSegment(dir) {
    const sorted = state.segments.slice().sort((a, b) => a.start_frame - b.start_frame);
    if (!sorted.length) return;
    const cur = frameOf(video.currentTime || 0);
    let target;
    if (dir > 0) {
        target = sorted.find(s => s.start_frame > cur) || sorted[0];
    } else {
        target = sorted.slice().reverse().find(s => s.start_frame < cur) || sorted[sorted.length - 1];
    }
    state.selectedId = target.id;
    video.currentTime = timeOfFrame(target.start_frame);
    renderLanes();
    renderSegmentList();
}

function deleteSelected() {
    const seg = selectedSegment();
    if (!seg) return;
    pushUndoSnapshot();
    state.segments = state.segments.filter(s => s.id !== seg.id);
    state.selectedId = null;
    renderLanes();
    renderSegmentList();
    setDirty(true);
    showToast(`Deleted ${seg.skill_id} — 按 Z 撤销 (press Z to undo)`);
}

function undo() {
    if (!state.undoStack.length) {
        showToast('Nothing to undo');
        return;
    }
    // Capture the state we're leaving so redo can return to it
    state.redoStack.push(JSON.parse(JSON.stringify(state.segments)));
    if (state.redoStack.length > 50) state.redoStack.shift();
    state.segments = state.undoStack.pop();
    state.selectedId = null;
    renderLanes();
    renderSegmentList();
    setDirty(true);
}

document.addEventListener('keydown', (e) => {
    if (isEditableTarget(e)) return;
    // Focused <button> keeps native Space/Enter activation for Tab-nav users —
    // JKL and the edit hotkeys must not steal keys over it (seg-list row idiom).
    if (e.target && typeof e.target.closest === 'function' && e.target.closest('button')) return;
    // ? toggles overlay. Note: Shift+/ produces "?" on US keyboards.
    if (e.key === '?' || (e.shiftKey && e.key === '/')) {
        e.preventDefault();
        helpOverlay.classList.toggle('hidden');
    } else if (e.key === 'Escape') {
        helpOverlay.classList.add('hidden');
    } else if (e.key === 'q' || e.key === 'Q') {
        e.preventDefault(); jumpSegment(-1);
    } else if (e.key === 'e' || e.key === 'E') {
        e.preventDefault(); jumpSegment(1);
    } else if (e.key === '[') {
        e.preventDefault(); nudgeEdge('left', e.shiftKey ? -10 : -1);
    } else if (e.key === ']') {
        e.preventDefault(); nudgeEdge('right', e.shiftKey ? 10 : 1);
    } else if (e.key === 'Backspace' || e.key === 'Delete') {
        e.preventDefault(); deleteSelected();
    } else if (e.key === 'z' && !e.metaKey && !e.ctrlKey && !e.shiftKey) {
        e.preventDefault(); undo();
    } else if ((e.key === 'Z' && e.shiftKey) || ((e.metaKey || e.ctrlKey) && (e.key === 'y' || e.key === 'Y'))) {
        // Redo: Shift+Z or Cmd/Ctrl+Y (research E.11 — verified missing)
        e.preventDefault(); redo();
    } else if (e.key === '\\') {
        // Loop selected segment (moved off L since JKL now claims L for play)
        e.preventDefault(); setLoop(!loopEnabled);
    } else if (e.key === 'j' || e.key === 'J') {
        e.preventDefault(); jklJ();
    } else if (e.key === 'k' || e.key === 'K') {
        e.preventDefault(); jklK();
    } else if (e.key === 'l' || e.key === 'L') {
        e.preventDefault(); jklL();
    } else if (e.key === 'i' || e.key === 'I') {
        // Mark in: drop start at current frame (additive to S; Premiere/DaVinci convention)
        e.preventDefault();
        if (state.pendingStart === null) {
            state.pendingStart = frameOf(video.currentTime || 0);
            btnMarkStart.classList.add('hidden');
            btnMarkEnd.classList.remove('hidden');
            const skill = getSkillById(state.activeSkillId);
            segmentStatus.classList.remove('hidden');
            segmentStatus.innerHTML = `
                <i class="fa fa-circle text-accent" style="animation: pulse 1.5s ease-in-out infinite;"></i>
                <span>Segment <span style="color:${safeCssColor(skill.color)}">${escapeHtml(skill.id)}</span> open at frame <span class="text-light">${state.pendingStart}</span> — press <kbd class="px-1 bg-zinc-800 ring-1 ring-zinc-700 rounded text-zinc-300">O</kbd> or <kbd class="px-1 bg-zinc-800 ring-1 ring-zinc-700 rounded text-zinc-300">S</kbd> at end</span>
            `;
            renderPendingGhost();
        } else {
            showToast('Segment already open — press O or S to close', 'info');
        }
    } else if (e.key === 'o' || e.key === 'O') {
        // Mark out: close at current frame (additive to S)
        e.preventDefault();
        if (state.pendingStart !== null) toggleSegment();
        else showToast('No segment open — press I or S first', 'info');
    }
});
