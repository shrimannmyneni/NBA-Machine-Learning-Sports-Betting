// ── DOM refs ─────────────────────────────────────────────────────────────────
const terminal      = document.getElementById('terminal');
const placeholder   = document.getElementById('terminal-placeholder');
const statusDot     = document.getElementById('status-dot');
const statusText    = document.getElementById('status-text');

// ── State ────────────────────────────────────────────────────────────────────
let activeSource = null;  // current EventSource
let inTable      = false; // are we buffering a ranked-bets table?
let tableHeaders = [];
let tableRows    = [];

// ── Status indicator ─────────────────────────────────────────────────────────
function setRunning(running) {
    document.querySelectorAll('.action-btn:not(.action-btn-ghost)').forEach(b => {
        b.disabled = running;
    });
    if (running) {
        statusDot.style.background  = '#f2c94c';
        statusText.textContent = 'Running…';
    } else {
        statusDot.style.background  = '#2dd36f';
        statusText.textContent = 'Ready';
    }
}

// ── Pull Props inline form ───────────────────────────────────────────────────
const btnPullProps    = document.getElementById('btn-pull-props');
const propsForm       = document.getElementById('props-form');
const btnRun          = document.getElementById('btn-pull-props-run');
const btnCancel       = document.getElementById('btn-pull-props-cancel');

btnPullProps.addEventListener('click', () => {
    propsForm.classList.toggle('open');
});

btnCancel.addEventListener('click', () => {
    propsForm.classList.remove('open');
});

btnRun.addEventListener('click', () => {
    const date = document.getElementById('props-date').value.trim();
    const home = document.getElementById('props-home').value.trim();
    const away = document.getElementById('props-away').value.trim();
    const params = new URLSearchParams();
    if (date) params.set('date', date);
    if (home) params.set('home', home);
    if (away) params.set('away', away);
    propsForm.classList.remove('open');
    startStream('pull-props', params.toString());
});

// ── Run Model — sends optional date param ────────────────────────────────────
const btnRunModel = document.getElementById('btn-run-model');
if (btnRunModel) {
    btnRunModel.addEventListener('click', () => {
        const dateInput = document.getElementById('run-model-date');
        const params = new URLSearchParams();
        if (dateInput?.value) params.set('date', dateInput.value);
        startStream('run-model', params.toString());
    });
}

// ── Direct-action buttons (no extra params) ──────────────────────────────────
document.querySelectorAll('[data-action]').forEach(btn => {
    btn.addEventListener('click', () => startStream(btn.dataset.action));
});

// ── Clear button ─────────────────────────────────────────────────────────────
document.getElementById('btn-clear').addEventListener('click', () => {
    clearTerminal();
});

// ── SSE stream ───────────────────────────────────────────────────────────────
function startStream(action, queryString = '') {
    if (activeSource) {
        activeSource.close();
        activeSource = null;
    }

    clearTerminal();
    setRunning(true);
    resetTableState();

    const url = `/stream/${action}${queryString ? '?' + queryString : ''}`;
    activeSource = new EventSource(url);

    activeSource.onmessage = (e) => {
        const line = e.data;

        // Process sentinel — stream finished
        if (/^\[EXIT:-?\d+\]/.test(line)) {
            const code = line.match(/\[EXIT:(-?\d+)\]/)?.[1];
            flushTableIfPending();
            appendLine(
                `── done (exit ${code}) ─────────────────────────────`,
                code === '0' ? 'term-done' : 'term-error'
            );
            activeSource.close();
            activeSource = null;
            setRunning(false);
            return;
        }

        processLine(line);
        scrollToBottom();
    };

    activeSource.onerror = () => {
        flushTableIfPending();
        appendLine('[error] Stream closed unexpectedly.', 'term-error');
        activeSource?.close();
        activeSource = null;
        setRunning(false);
    };
}

// ── Terminal helpers ──────────────────────────────────────────────────────────
function clearTerminal() {
    terminal.innerHTML = '';
    placeholder.textContent = '';
    placeholder.style.display = 'none';
    resetTableState();
}

function scrollToBottom() {
    terminal.scrollTop = terminal.scrollHeight;
}

function lineClass(line) {
    if (line.includes('[error]') || line.includes('[ERR]'))  return 'term-error';
    if (line.includes('[warn]'))                              return 'term-warn';
    if (line.includes('[skip]') || line.includes('[SKIP]'))  return 'term-muted';
    if (/^\[\d{2}:\d{2}:\d{2}\]/.test(line))                return 'term-ts';
    if (line.startsWith('  →'))                              return 'term-accent';
    return '';
}

function appendLine(text, cls) {
    const div = document.createElement('div');
    div.className = 'terminal-line ' + (cls ?? lineClass(text));
    div.textContent = text;
    terminal.appendChild(div);
}

function appendNode(node) {
    terminal.appendChild(node);
}

// ── Ranked-bets table detection ───────────────────────────────────────────────
// Output_Formatter produces:
//   [timestamp] -----------Top Ranked Bets...
//   -------...-------   ← opening separator
//   Player/Team | Event | Odds | Weighted Bet Value
//   -------...-------
//   Row | ... | ... | ...
//   ...
//   -------...-------   ← closing separator

function resetTableState() {
    inTable      = false;
    tableHeaders = [];
    tableRows    = [];
}

function processLine(line) {
    // Detect table column-header row
    if (!inTable && /\bPlayer\/Team\b/.test(line) && line.includes('|')) {
        inTable      = true;
        tableHeaders = line.split('|').map(h => h.trim());
        tableRows    = [];
        return; // don't display raw header
    }

    if (inTable) {
        // Pure separator line (all dashes / spaces)
        if (/^[-\s]{10,}$/.test(line)) {
            if (tableRows.length > 0) {
                // Closing separator — flush and exit table mode
                flushTableIfPending();
            }
            // Opening separator before rows — skip
            return;
        }
        // Data row (contains pipe)
        if (line.includes('|')) {
            tableRows.push(line.split('|').map(c => c.trim()));
            return;
        }
        // Something unexpected — flush and fall through
        flushTableIfPending();
    }

    appendLine(line);
}

function flushTableIfPending() {
    if (!inTable || tableRows.length === 0) {
        inTable = false;
        return;
    }
    inTable = false;

    // Build Bootstrap table
    const wrapper = document.createElement('div');
    wrapper.className = 'ranked-table-wrap';

    const caption = document.createElement('div');
    caption.className = 'term-table-caption';
    caption.textContent = '── Top Ranked Bets ─────────────────────────────────';
    wrapper.appendChild(caption);

    const table = document.createElement('table');
    table.className = 'table table-dark table-sm ranked-table';

    const thead = document.createElement('thead');
    const hrow  = document.createElement('tr');
    tableHeaders.forEach(h => {
        const th = document.createElement('th');
        th.textContent = h;
        hrow.appendChild(th);
    });
    thead.appendChild(hrow);
    table.appendChild(thead);

    const tbody = document.createElement('tbody');
    tableRows.forEach(cells => {
        const tr = document.createElement('tr');
        cells.forEach((cell, i) => {
            const td = document.createElement('td');
            // Highlight positive Weighted Bet Value
            if (i === tableHeaders.length - 1) {
                const val = parseFloat(cell);
                if (!isNaN(val) && val > 0) td.className = 'term-positive';
            }
            td.textContent = cell;
            tr.appendChild(td);
        });
        tbody.appendChild(tr);
    });
    table.appendChild(tbody);
    wrapper.appendChild(table);

    appendNode(wrapper);
    tableRows    = [];
    tableHeaders = [];
}
