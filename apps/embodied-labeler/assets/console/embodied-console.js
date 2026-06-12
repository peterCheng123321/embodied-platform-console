/**
 * Labeler-page console wiring: episode tree + ⌘K commands.
 * Reuses the page's existing controls — embodied.js stays untouched.
 */
import { initCmdk, renderTree } from './console.js';

const API_BASE = document.querySelector('meta[name="api-base"]')?.content?.trim()
    || window.location.origin;
const params = new URLSearchParams(window.location.search);
const CURRENT_DS = (params.get('dataset') || 'demo').replace(/[^A-Za-z0-9_-]/g, '') || 'demo';
const CURRENT_EP = CURRENT_DS === 'demo' ? 0 : Math.max(0, parseInt(params.get('episode') || '0', 10) || 0);

function gotoEpisode(ds, ix) {
    const dest = new URL(window.location.href);
    dest.searchParams.set('dataset', ds);
    dest.searchParams.set('episode', String(ix));
    window.location.href = dest.toString();   // full navigation; beforeunload guards dirty work
}

// 10s-capped fetch: one hung dataset request must not stall the tree (and the
// palette's episode index) forever. Timeouts surface as rejections in the
// callers' existing catch paths.
async function fetchWithTimeout(url, opts = {}, ms = 10000) {
    const abort = new AbortController();
    const timer = setTimeout(() => abort.abort(), ms);
    try {
        return await fetch(url, { ...opts, signal: abort.signal });
    } finally {
        clearTimeout(timer);
    }
}

// Same toast idiom as embodied.js showToast (not exported there); the labeler
// page always carries #toast-container.
function toast(msg) {
    const container = document.getElementById('toast-container');
    if (!container) return;
    const t = document.createElement('div');
    t.className = 'bg-zinc-700 text-white text-sm px-4 py-2 rounded shadow-lg';
    t.textContent = msg;
    container.appendChild(t);
    setTimeout(() => t.remove(), 3000);
}

let episodeEntries = [];   // flat [{ds, ix, task, annotated}] for palette jumps

async function loadTree() {
    const container = document.getElementById('episode-tree');
    if (!container) return;
    try {
        const r = await fetchWithTimeout(`${API_BASE}/api/embodied/datasets`);
        if (!r.ok) return;
        const datasets = await r.json();
        const groups = [];
        for (const ds of datasets) {
            let eps = [];
            let failed = false;
            try {
                // Per-dataset isolation: one unreadable or HANGING dataset
                // (10s cap above) must not hide — or stall — the rest. A
                // failure renders the node with a 加载失败 marker instead.
                const er = await fetchWithTimeout(`${API_BASE}/api/embodied/datasets/${encodeURIComponent(ds.id)}/episodes`);
                if (er.ok) eps = await er.json();
                else failed = true;
            } catch (e) { failed = true; }
            episodeEntries.push(...eps.map((ep) => ({ ds: ds.id, ix: ep.episode_index, task: ep.task || '', annotated: !!ep.has_annotations })));
            groups.push({
                id: ds.id,
                label: ds.label || ds.id,
                meta: failed ? '加载失败' : String(ds.episode_count ?? eps.length),
                children: eps.map((ep) => ({
                    id: `${ds.id}:${ep.episode_index}`,
                    label: `ep ${ep.episode_index}`,
                    meta: (ep.task || '').slice(0, 14),
                    annotated: !!ep.has_annotations,
                    current: ds.id === CURRENT_DS && ep.episode_index === CURRENT_EP,
                    onSelect: () => gotoEpisode(ds.id, ep.episode_index),
                })),
            });
        }
        const filterBox = document.getElementById('episode-tree-filter');
        const draw = () => renderTree(container, groups, (filterBox?.value || '').trim().toLowerCase());
        filterBox?.addEventListener('input', draw);
        draw();
    } catch (e) {
        // Backend down: tree stays empty; the labeler's own demo fallback still works.
    }
}

function clickIfPresent(id) { document.getElementById(id)?.click(); }

const EP_RE = /^(?:ep\s*)?(\d+)$/i;
initCmdk([
    {
        id: 'jump',
        match: (q) => !q || EP_RE.test(q) || episodeEntries.some((e) => `${e.ds} ${e.task}`.toLowerCase().includes(q) && q.length > 1),
        label: (q) => {
            const m = q.match(EP_RE);
            if (m) return `跳转回合 ep ${m[1]}`;
            const hit = episodeEntries.find((e) => `${e.ds} ${e.task}`.toLowerCase().includes(q));
            return hit ? `跳转 ${hit.ds} · ep ${hit.ix} — ${hit.task}` : '跳转回合';
        },
        hint: 'EP n ⏎',
        run: (q) => {
            const m = q.match(EP_RE);
            if (m) {
                // Authorized simplification: if we're on demo but recorded episodes exist, jump into
                // the first non-demo dataset; otherwise stay on the current dataset.
                const targetDs = CURRENT_DS !== 'demo' ? CURRENT_DS
                    : (episodeEntries.find((e) => e.ds !== 'demo')?.ds || CURRENT_DS);
                // demo has exactly one episode; don't emit a misleading ?episode=N URL
                const ix = targetDs === 'demo' ? 0 : parseInt(m[1], 10);
                // Validate against the loaded tree before navigating — a full
                // page navigation to a nonexistent episode dead-ends on the
                // labeler's error overlay. When the dataset's episode list
                // never loaded (backend down / 加载失败) we can't know better,
                // so keep the old navigate-and-surface-it-there behavior.
                const dsLoaded = episodeEntries.some((e) => e.ds === targetDs);
                if (dsLoaded && !episodeEntries.some((e) => e.ds === targetDs && e.ix === ix)) {
                    toast(`回合不存在：${targetDs} 没有 ep ${ix}`);
                    return;
                }
                return gotoEpisode(targetDs, ix);
            }
            const hit = episodeEntries.find((e) => `${e.ds} ${e.task}`.toLowerCase().includes(q));
            if (hit) gotoEpisode(hit.ds, hit.ix);
        },
    },
    { id: 'save',   match: (q) => !q || '保存 save'.includes(q),         label: () => '保存全部 Save all',      hint: '⌘S', run: () => clickIfPresent('save-btn') },
    { id: 'loop',   match: (q) => !q || '循环 loop'.includes(q),         label: () => '循环播放选中片段 Loop',   hint: '\\', run: () => clickIfPresent('btn-loop') },
    { id: 'schema', match: (q) => !q || '标签集 schema'.includes(q),     label: () => '切换标签集 Label schema', hint: '',   run: () => document.getElementById('label-schema-select')?.focus() },
    { id: 'help',   match: (q) => !q || '快捷键 帮助 help'.includes(q), label: () => '键盘快捷键 Shortcuts',    hint: '?',  run: () => clickIfPresent('help-btn') },
]);

loadTree();
