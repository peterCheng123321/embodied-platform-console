/**
 * Shared Mission Console components — vanilla ES module, no build step.
 * initCmdk: ⌘K palette. renderTree: data-hierarchy rail.
 * Pages import these and supply their own data/commands.
 */

function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
}

/**
 * commands: [{ id, label, hint, match(queryLower) -> bool|score, run() }]
 * Returns { open, close } for programmatic control.
 */
export function initCmdk(commands) {
    const overlay = el('div', 'console-cmdk hidden');
    overlay.id = 'console-cmdk';
    const panel = el('div', 'console-cmdk-panel');
    const input = el('input', 'console-cmdk-input');
    input.type = 'text';
    input.placeholder = '输入命令或回合编号… (EP 42 ⏎ 跳转)';
    input.setAttribute('aria-label', '命令输入');
    const list = el('div', 'console-cmdk-list');
    list.setAttribute('role', 'listbox');
    list.tabIndex = -1;   // programmatically focusable target for the Tab trap
    panel.append(input, list);
    overlay.appendChild(panel);
    document.body.appendChild(overlay);

    let items = [];
    let selected = 0;
    let lastFocused = null;   // element to restore focus to on close

    function close() {
        overlay.classList.add('hidden');
        input.value = '';
        if (lastFocused && document.contains(lastFocused) && typeof lastFocused.focus === 'function') {
            lastFocused.focus();
        }
        lastFocused = null;
    }
    function open() {
        lastFocused = document.activeElement;
        overlay.classList.remove('hidden'); input.value = ''; refresh(); input.focus();
    }

    function refresh() {
        const q = input.value.trim().toLowerCase();
        items = commands.filter((c) => c.match(q));
        selected = 0;
        list.textContent = '';
        for (const [i, c] of items.entries()) {
            const row = el('div', 'console-cmdk-item');
            row.setAttribute('role', 'option');
            row.setAttribute('aria-selected', String(i === selected));
            row.append(el('span', '', c.label(q)), el('span', 'console-cmdk-hint', c.hint || ''));
            row.addEventListener('click', () => { close(); c.run(q); });
            list.appendChild(row);
        }
    }

    input.addEventListener('input', refresh);
    overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });
    document.addEventListener('keydown', (e) => {
        if ((e.metaKey || e.ctrlKey) && (e.key === 'k' || e.key === 'K')) {
            e.preventDefault();
            overlay.classList.contains('hidden') ? open() : close();
            return;
        }
        if (overlay.classList.contains('hidden')) return;
        if (e.key === 'Escape') { e.preventDefault(); close(); }
        else if (e.key === 'Tab') {
            // Trap focus inside the palette while open: cycle input ↔ list
            // instead of tabbing into the page underneath the overlay.
            e.preventDefault();
            (document.activeElement === input ? list : input).focus();
        }
        else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
            e.preventDefault();
            selected = Math.max(0, Math.min(items.length - 1, selected + (e.key === 'ArrowDown' ? 1 : -1)));
            [...list.children].forEach((n, i) => n.setAttribute('aria-selected', String(i === selected)));
        } else if (e.key === 'Enter' && items[selected]) {
            e.preventDefault();
            const q = input.value.trim().toLowerCase();
            close();
            items[selected].run(q);
        }
    });

    return { open, close };
}

/**
 * groups: [{ id, label, meta, children: [{ id, label, meta, annotated, current, onSelect() }] }]
 * filter: current filter string (lowercase) — children not matching are hidden.
 */
export function renderTree(container, groups, filter = '') {
    container.textContent = '';
    for (const g of groups) {
        // Group heads are labels, not controls: groups are always expanded, so
        // a button (or aria-expanded) would promise a collapse that doesn't exist.
        const head = el('div', 'console-node console-node-head');
        head.append(el('span', '', `▾ ${g.label}`), el('span', 'console-node-meta', g.meta || ''));
        container.appendChild(head);
        const kids = el('div', 'console-node-group');
        for (const c of g.children) {
            if (filter && !`${c.id} ${c.label}`.toLowerCase().includes(filter)) continue;
            const btn = el('button', 'console-node');
            btn.type = 'button';
            if (c.current) btn.setAttribute('aria-current', 'true');
            const mark = c.annotated ? el('span', 'console-node-annotated', '●') : el('span', '', '○');
            btn.append(mark, el('span', '', c.label), el('span', 'console-node-meta', c.meta || ''));
            btn.addEventListener('click', c.onSelect);
            kids.appendChild(btn);
        }
        container.appendChild(kids);
    }
}
