/**
 * ePaper Harvester 2.0 - Frontend Application
 */

const state = {
    sources: [],
    archives: [],
    activeJobs: {},
    selectedLanguage: 'all',
    searchQuery: '',
    ws: null,
    currentNewsSource: null,
    currentNewsCategory: 'all',
    currentNewsChannel: 'epaper', // 'epaper' or 'online'
    currentSearchKeyword: '',
    newsCache: {},
    uploadedNewsData: null,
    currentUploadCategory: 'all',
    selectedEmailCategory: 'all',
    inboxClippings: [],
    realInboxMessages: [],
};

// Strict list of publications configured with active session cookies for broadsheet ePaper harvesting.
// ALL other publications support Online News (Google News) ONLY.
const ACTIVE_COOKIE_EPAPER_SOURCES = new Set([
    'the_hindu',
    'financial_express',
    'lokmat_samachar',
    'lokmat',
    'loksatta',
    'dt_next'
]);

function isEpaperCookieSource(sourceOrId) {
    if (!sourceOrId) return false;
    let sid = '';
    let sname = '';
    if (typeof sourceOrId === 'string') {
        sid = sourceOrId.toLowerCase().trim().replace(/-/g, '_');
    } else if (typeof sourceOrId === 'object') {
        sid = (sourceOrId.id || '').toLowerCase().trim().replace(/-/g, '_');
        sname = (sourceOrId.name || '').toLowerCase().trim();
    }
    if (!sname && state.sources && state.sources.length > 0) {
        const found = state.sources.find(s => s.id === sid);
        if (found) sname = (found.name || '').toLowerCase().trim();
    }

    // Direct match against the 6 authorized publications
    if (ACTIVE_COOKIE_EPAPER_SOURCES.has(sid)) return true;

    // The Hindu
    if (sid === 'the_hindu' || sid === 'hindu' || sid === 'the_hindhu' || sid === 'hindhu' || sname.includes('the hindu')) return true;

    // Financial Express
    if (sid.includes('financial') || sid.includes('financeexpress') || sid.includes('finance_express') || sid === 'fe' || sname.includes('financial express')) return true;

    // Lokmat Samachar
    if (sid === 'lokmat_samachar' || sid.startsWith('lokmat_samachar_') || sname.includes('lokmat samachar')) return true;

    // Lokmat (Marathi)
    if (sid === 'lokmat' || (sid.startsWith('lokmat_') && !sid.includes('samachar')) || (sname.includes('lokmat') && !sname.includes('samachar'))) return true;

    // Loksatta
    if (sid === 'loksatta' || sid.startsWith('loksatta_') || sname.includes('loksatta')) return true;

    // DT Next
    if (sid === 'dt_next' || sid === 'dtnext' || sname.includes('dt next')) return true;

    return false;
}

// Initialize App
document.addEventListener('DOMContentLoaded', () => {
    initClock();
    initTabs();
    initDatePicker();
    fetchSources();
    fetchArchives();
    fetchSessions();
    fetchStorageStats();
    initWebSocket();
    setupEventListeners();
});

// --------------------------------------------------------------------------
// Clock & Utilities
// --------------------------------------------------------------------------
function initClock() {
    function updateClock() {
        const now = new Date();
        const istTime = new Intl.DateTimeFormat('en-IN', {
            timeZone: 'Asia/Kolkata',
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit',
            hour12: false
        }).format(now);
        const el = document.getElementById('istClockDisplay');
        if (el) el.textContent = `${istTime} IST`;
    }
    updateClock();
    setInterval(updateClock, 1000);
}

function initDatePicker() {
    const today = new Date().toISOString().split('T')[0];
    const el = document.getElementById('globalHarvestDate');
    if (el) el.value = today;
}

// --------------------------------------------------------------------------
// Tabs Switching
// --------------------------------------------------------------------------
function initTabs() {
    const tabBtns = document.querySelectorAll('.tab-btn');
    tabBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            tabBtns.forEach(b => b.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));

            btn.classList.add('active');
            const targetId = 'view' + btn.dataset.tab.charAt(0).toUpperCase() + btn.dataset.tab.slice(1);
            const targetContent = document.getElementById(targetId);
            if (targetContent) targetContent.classList.add('active');

            if (btn.dataset.tab === 'archives') fetchArchives();
            if (btn.dataset.tab === 'sessions') fetchSessions();
        });
    });
}

// --------------------------------------------------------------------------
// Data Fetching: Sources & Filtering
// --------------------------------------------------------------------------
async function fetchSources() {
    try {
        const res = await fetch('/api/sources');
        state.sources = await res.json();
        const counter = document.getElementById('metricSourcesCount');
        if (counter) counter.textContent = state.sources.length;
        renderSources();
        populateCookieSources();
        populateKeywordSources();
    } catch (e) {
        logToTerminal(`[ERROR] Failed to fetch sources: ${e.message}`, 'error');
    }
}

function renderSources() {
    const container = document.getElementById('sourcesGridContainer');
    if (!container) return;

    let filtered = state.sources;

    // Filter by language
    if (state.selectedLanguage !== 'all') {
        filtered = filtered.filter(s => s.language.toLowerCase() === state.selectedLanguage.toLowerCase());
    }

    // Filter by search query
    if (state.searchQuery) {
        const q = state.searchQuery.toLowerCase();
        filtered = filtered.filter(s =>
            s.name.toLowerCase().includes(q) ||
            s.language.toLowerCase().includes(q) ||
            s.state_region.toLowerCase().includes(q) ||
            s.id.toLowerCase().includes(q)
        );
    }

    const countEl = document.getElementById('sourceFilterCount');
    if (countEl) countEl.textContent = filtered.length;

    if (filtered.length === 0) {
        const queryEscaped = (state.searchQuery || '').replace(/"/g, '&quot;').replace(/'/g, "\\'");
        container.innerHTML = `
            <div class="empty-state">
                <div style="font-size:2.2rem;margin-bottom:0.5rem;">🔍</div>
                <h3>No publications match "${queryEscaped}"</h3>
                <p class="text-secondary" style="margin-top:0.35rem;margin-bottom:1rem;">Searching for news stories or article headlines?</p>
                <button class="btn btn-primary" onclick="triggerKeywordSearch('${queryEscaped}')">
                    ⚡ Search News Headlines for "${queryEscaped}"
                </button>
            </div>
        `;
        return;
    }

    container.innerHTML = filtered.map(source => {
        const editionOptions = source.available_editions.map(ed =>
            `<option value="${ed.code}" ${ed.code === source.default_edition ? 'selected' : ''}>${ed.name}</option>`
        ).join('');

        const engineBadge = source.engine_type === 'playwright_flipbook'
            ? `<span class="badge badge-auth" title="Uses Headless Playwright Flipbook Viewer">🎭 Browser Flipbook</span>`
            : `<span class="badge badge-engine" title="Uses High-Speed Manifest API">⚡ Manifest API</span>`;

        const authBadge = source.auth_required
            ? `<span class="badge badge-auth" title="Session cookies required for complete edition">🔒 Subscribed</span>`
            : `<span class="badge" style="background:rgba(255,255,255,0.06);color:#9aa8be;">Free Access</span>`;

        const hasEpaperSupport = isEpaperCookieSource(source.id) || !!source.supports_epaper_digital;
        const channelBadge = hasEpaperSupport
            ? `<span class="badge" style="background:rgba(56,189,248,0.15);color:#38bdf8;border:1px solid rgba(56,189,248,0.35);font-weight:700;" title="Authenticated Broadsheet ePaper + Google Online News">📰 ePaper + 🌐 Online</span>`
            : `<span class="badge" style="background:rgba(168,85,247,0.12);color:#c084fc;border:1px solid rgba(168,85,247,0.3);" title="Live Google News Feed auto-translated">🌐 Online News Only</span>`;

        // Check if an archive is available for this source
        const matchingArchive = state.archives.find(a => a.source_id === source.id);
        const pdfReadyBtn = matchingArchive
            ? `<button class="btn btn-sm btn-pdf-ready" onclick="event.stopPropagation(); openPdfPreview('${matchingArchive.source_id}', '${matchingArchive.target_date}', '${matchingArchive.filename}', '${source.name} - ${matchingArchive.edition} (${matchingArchive.target_date})')" title="Read harvested PDF edition">👁️ View PDF</button>`
            : '';

        return `
            <div class="source-card" id="card_${source.id}" onclick="openNewspaperNewsModal('${source.id}')" title="Click to read categorized news">
                <div class="source-card-main">
                    <div class="source-header">
                        <div>
                            <div class="source-title">📰 ${source.name}</div>
                            <div class="source-region">${source.state_region} • ${source.category}</div>
                        </div>
                        <span class="badge badge-lang">${source.language}</span>
                    </div>

                    <div class="source-meta">
                        ${channelBadge}
                        ${engineBadge}
                        ${authBadge}
                        <span class="badge" style="background:rgba(255,255,255,0.04);color:#627086;">⏰ ${source.schedule_time} IST</span>
                    </div>

                    <!-- Category Chips directly on the card -->
                    <div class="card-categories-strip" onclick="event.stopPropagation()">
                        <button class="card-cat-tag cat-sports" onclick="openNewspaperNewsModal('${source.id}', 'sports')" title="View Sports News">🏆 Sports</button>
                        <button class="card-cat-tag cat-business" onclick="openNewspaperNewsModal('${source.id}', 'business')" title="View Business News">💼 Business</button>
                        <button class="card-cat-tag cat-economic" onclick="openNewspaperNewsModal('${source.id}', 'economic')" title="View Economic News">📈 Economic</button>
                        <button class="card-cat-tag cat-political" onclick="openNewspaperNewsModal('${source.id}', 'political')" title="View Political News">🏛️ Political</button>
                        <button class="card-cat-tag cat-crises" onclick="openNewspaperNewsModal('${source.id}', 'crises_disasters')" title="View Crises & Disasters">🚨 Crises</button>
                    </div>
                </div>

                <div class="source-card-footer" onclick="event.stopPropagation()">
                    <div class="source-controls">
                        <select class="edition-select" id="edition_${source.id}">
                            ${editionOptions}
                        </select>
                        <div class="source-button-row ${matchingArchive ? 'has-pdf' : ''}">
                            <button class="btn btn-sm btn-harvest-action" onclick="triggerSingleHarvest('${source.id}')" id="btn_harvest_${source.id}" title="Download offline PDF">
                                ⚡ Harvest
                            </button>
                            ${pdfReadyBtn}
                        </div>
                        <div class="source-button-row secondary-row">
                            <button class="btn btn-sm btn-news" onclick="openNewspaperNewsModal('${source.id}')" title="Read categorized news stories">
                                ${hasEpaperSupport ? '📰 ePaper + 🌐 Online' : '🌐 Read Online News'}
                            </button>
                            <button class="btn btn-sm btn-outline" onclick="openNewspaperSearch('${source.id}')" title="Search keywords specifically in ${source.name}">
                                🔍 Search
                            </button>
                            <a href="${source.base_url}" target="_blank" rel="noopener noreferrer" class="btn btn-sm btn-outline btn-live" title="Visit official online portal in new tab">
                                🌐 Portal ↗
                            </a>
                        </div>
                    </div>
                </div>
            </div>
        `;
    }).join('');
}

// --------------------------------------------------------------------------
// Harvest Actions
// --------------------------------------------------------------------------
async function triggerSingleHarvest(sourceId) {
    const editionSelect = document.getElementById(`edition_${sourceId}`);
    const edition = editionSelect ? editionSelect.value : null;
    const dateInput = document.getElementById('globalHarvestDate');
    const targetDate = dateInput ? dateInput.value : null;

    const btn = document.getElementById(`btn_harvest_${sourceId}`);
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = '⏳ Queuing...';
    }

    try {
        const res = await fetch('/api/harvest/run', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                source_id: sourceId,
                edition: edition,
                target_date: targetDate
            })
        });
        const job = await res.json();
        logToTerminal(`[HARVEST] Queued download for ${sourceId} (${job.edition}, ${job.target_date}) - Job: ${job.job_id}`, 'system');

        // Switch to Monitor tab
        document.getElementById('tabMonitor').click();
    } catch (e) {
        logToTerminal(`[ERROR] Failed to start harvest: ${e.message}`, 'error');
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = '⚡ Harvest';
        }
    }
}

async function triggerBatchHarvest() {
    const dateInput = document.getElementById('globalHarvestDate');
    const targetDate = dateInput ? dateInput.value : null;

    const confirm = window.confirm(`Trigger automated harvest for all 50+ configured newspapers for ${targetDate}?`);
    if (!confirm) return;

    try {
        const res = await fetch('/api/harvest/batch', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ target_date: targetDate })
        });
        const data = await res.json();
        logToTerminal(`[BATCH] Queued batch harvest with ${data.total_jobs} newspaper jobs!`, 'system');
        document.getElementById('tabMonitor').click();
    } catch (e) {
        logToTerminal(`[ERROR] Batch trigger error: ${e.message}`, 'error');
    }
}

// --------------------------------------------------------------------------
// WebSocket & Live Monitor
// --------------------------------------------------------------------------
let wsRetries = 0;
function initWebSocket() {
    if (wsRetries > 2) {
        const statusText = document.getElementById('wsStatusText');
        if (statusText) statusText.textContent = 'Active (HTTP)';
        return;
    }
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws/events`;

    const statusPill = document.getElementById('wsStatusIndicator');
    const statusText = document.getElementById('wsStatusText');

    try {
        state.ws = new WebSocket(wsUrl);

        state.ws.onopen = () => {
            wsRetries = 0;
            if (statusPill) statusPill.style.borderColor = 'rgba(16, 185, 129, 0.4)';
            if (statusText) statusText.textContent = 'Live Sync';
        };

        state.ws.onmessage = (event) => {
            try {
                const msg = JSON.parse(event.data);
                handleWsMessage(msg);
            } catch (e) {}
        };

        state.ws.onerror = () => {
            wsRetries++;
        };

        state.ws.onclose = () => {
            if (wsRetries > 2) {
                if (statusText) statusText.textContent = 'Active (HTTP)';
                return;
            }
            setTimeout(initWebSocket, 10000);
        };
    } catch (e) {
        wsRetries++;
    }
}

function handleWsMessage(msg) {
    const { type, data } = msg;

    if (type === 'init') {
        if (data && data.active_jobs) {
            data.active_jobs.forEach(j => { state.activeJobs[j.job_id] = j; });
            renderActiveJobs();
        }
        return;
    }

    if (['job_created', 'job_started', 'job_progress', 'job_retry'].includes(type)) {
        if (data && data.job_id) {
            state.activeJobs[data.job_id] = data;
            renderActiveJobs();
        }
        if (type === 'job_progress') {
            logToTerminal(`[PROGRESS] ${data.source_name} (${data.edition}): ${data.current_step}`);
        } else if (type === 'job_started') {
            logToTerminal(`[START] Harvest engine executing: ${data.source_name}`, 'system');
        } else if (type === 'job_retry') {
            logToTerminal(`[RETRY] ${data.source_name}: ${data.current_step}`, 'warning');
        }
    } else if (type === 'job_completed') {
        logToTerminal(`[SUCCESS] Completed PDF compiled for ${data.source_name}! (${data.total_pages} pages, ${(data.file_size_bytes/1048576).toFixed(2)} MB)`, 'success');
        delete state.activeJobs[data.job_id];
        renderActiveJobs();
        fetchArchives();
        fetchStorageStats();
    } else if (type === 'job_failed') {
        logToTerminal(`[FAILED] Harvest error on ${data.source_name}: ${data.error_message}`, 'error');
        delete state.activeJobs[data.job_id];
        renderActiveJobs();
    }
}

function renderActiveJobs() {
    const container = document.getElementById('activeJobsList');
    const badge = document.getElementById('activeJobsBadge');
    const counter = document.getElementById('activeJobsCounter');
    const jobs = Object.values(state.activeJobs);

    if (badge) badge.textContent = `${jobs.length} Active`;
    if (counter) {
        counter.textContent = jobs.length;
        counter.style.display = jobs.length > 0 ? 'inline-block' : 'none';
    }

    if (!container) return;

    if (jobs.length === 0) {
        container.innerHTML = '<div class="empty-state">No jobs currently executing. Trigger a harvest from the Catalog.</div>';
        return;
    }

    container.innerHTML = jobs.map(job => `
        <div class="job-card" id="job_${job.job_id}">
            <div class="job-header">
                <span class="job-name">📰 ${job.source_name} <small class="text-secondary">(${job.edition})</small></span>
                <span class="badge badge-engine">${job.status.toUpperCase()}</span>
            </div>
            <div class="progress-bar-wrap">
                <div class="progress-bar-fill" style="width: ${Math.max(job.progress_percentage, 5)}%"></div>
            </div>
            <div class="job-status-line">
                <span>${job.current_step || 'Processing...'}</span>
                <span>${job.progress_percentage}%</span>
            </div>
        </div>
    `).join('');
}

function logToTerminal(text, type = 'normal') {
    const term = document.getElementById('liveTerminalLogs');
    if (!term) return;

    const time = new Date().toLocaleTimeString('en-GB');
    const div = document.createElement('div');
    div.className = `log-entry ${type}`;
    div.textContent = `[${time}] ${text}`;
    term.appendChild(div);

    term.scrollTop = term.scrollHeight;
}

// --------------------------------------------------------------------------
// Archives View & PDF Reader Modal
// --------------------------------------------------------------------------
async function fetchArchives() {
    try {
        const res = await fetch('/api/harvest/history');
        state.archives = await res.json();
        const counter = document.getElementById('metricArchivesCount');
        if (counter) counter.textContent = state.archives.length;
        renderArchives();
        renderSources(); // re-render sources to update "PDF Ready" badges
    } catch (e) {
        console.error('Error loading archives:', e);
    }
}

function renderArchives(filterQuery = '') {
    const container = document.getElementById('archivesGridContainer');
    if (!container) return;

    let list = state.archives;
    if (filterQuery) {
        const q = filterQuery.toLowerCase();
        list = list.filter(a =>
            (a.source_name && a.source_name.toLowerCase().includes(q)) ||
            (a.edition && a.edition.toLowerCase().includes(q)) ||
            (a.target_date && a.target_date.includes(q)) ||
            (a.filename && a.filename.toLowerCase().includes(q))
        );
    }

    if (list.length === 0) {
        container.innerHTML = `
            <div class="empty-state" style="grid-column: 1 / -1;">
                <h3>${filterQuery ? 'No matching archived PDFs found' : 'No harvested ePaper PDFs yet'}</h3>
                <p class="text-secondary" style="margin-top:0.5rem;">${filterQuery ? 'Try another keyword or clear search.' : 'Pick any newspaper from the Catalog tab and click <strong>Harvest</strong> to start downloading.'}</p>
            </div>
        `;
        return;
    }

    container.innerHTML = list.map(a => {
        const thumbContent = a.thumbnail_url
            ? `<img src="${a.thumbnail_url}" class="archive-thumb" alt="${a.source_name} Front Page">`
            : `<div class="archive-thumb-placeholder">📰</div>`;

        return `
            <div class="archive-card">
                <div class="archive-thumb-wrap" onclick="openPdfPreview('${a.source_id}', '${a.target_date}', '${a.filename}', '${a.source_name} - ${a.edition} (${a.target_date})')">
                    ${thumbContent}
                </div>
                <div class="archive-content">
                    <div class="archive-title">${a.source_name}</div>
                    <div class="archive-meta">
                        <span>📅 ${a.target_date} • ${a.edition}</span>
                        <span>📑 ${a.page_count} Pages (${a.file_size_mb} MB)</span>
                    </div>
                    <div class="archive-actions">
                        <button class="btn btn-secondary btn-sm" style="flex:1;" onclick="openPdfPreview('${a.source_id}', '${a.target_date}', '${a.filename}', '${a.source_name} - ${a.edition} (${a.target_date})')">
                            👁️ Preview
                        </button>
                        <a class="btn btn-primary btn-sm" href="${a.download_url}" download target="_blank">
                            ⬇️ Download
                        </a>
                        <button class="btn btn-outline btn-xs" onclick="deleteArchive('${a.source_id}', '${a.target_date}', '${a.filename}')" title="Delete file">
                            🗑️
                        </button>
                    </div>
                </div>
            </div>
        `;
    }).join('');
}

function openPdfPreview(sourceId, targetDate, filename, title) {
    const modal = document.getElementById('pdfReaderModal');
    const iframe = document.getElementById('pdfPreviewIframe');
    const titleEl = document.getElementById('pdfReaderTitle');
    const dlBtn = document.getElementById('pdfDownloadBtn');
    const tabBtn = document.getElementById('pdfOpenTabBtn');

    if (!modal) return;

    const previewUrl = `/api/harvest/preview/${sourceId}/${targetDate}/${filename}`;
    const downloadUrl = `/api/harvest/download/${sourceId}/${targetDate}/${filename}`;

    if (titleEl) titleEl.textContent = title;
    if (iframe) iframe.src = previewUrl;
    if (dlBtn) dlBtn.href = downloadUrl;
    if (tabBtn) tabBtn.href = previewUrl;

    modal.classList.add('open');
}

async function deleteArchive(sourceId, targetDate, filename) {
    if (!window.confirm(`Delete ${filename}?`)) return;
    try {
        await fetch(`/api/harvest/archive/${sourceId}/${targetDate}/${filename}`, { method: 'DELETE' });
        fetchArchives();
        fetchStorageStats();
    } catch (e) {
        alert('Delete failed: ' + e.message);
    }
}

// --------------------------------------------------------------------------
// Sessions & Auth Manager
// --------------------------------------------------------------------------
async function fetchSessions() {
    try {
        const res = await fetch('/api/sessions');
        const sessions = await res.json();
        const tbody = document.getElementById('sessionsTableBody');
        if (!tbody) return;

        tbody.innerHTML = sessions.map(s => {
            const statusBadge = s.has_session
                ? (s.is_valid ? '<span class="badge badge-engine">Active & Valid</span>' : '<span class="badge badge-auth">Cookies Present</span>')
                : '<span class="badge" style="background:rgba(255,255,255,0.06);color:#9aa8be;">No Session</span>';

            const updatedStr = s.last_updated ? new Date(s.last_updated).toLocaleString() : 'Never';
            const expiresStr = s.expires_at ? new Date(s.expires_at).toLocaleDateString() : 'Session based';

            return `
                <tr>
                    <td><strong>${s.source_name}</strong></td>
                    <td>${statusBadge}</td>
                    <td>${s.cookie_count} cookies</td>
                    <td>${expiresStr}</td>
                    <td>${updatedStr}</td>
                    <td>
                        <button class="btn btn-secondary btn-xs" onclick="openCookieModalFor('${s.source_id}')">
                            ✏️ Import Cookies
                        </button>
                    </td>
                </tr>
            `;
        }).join('');
    } catch (e) {
        console.error(e);
    }
}

function populateCookieSources() {
    const select = document.getElementById('cookieSourceSelect');
    if (!select) return;
    select.innerHTML = state.sources.map(s =>
        `<option value="${s.id}">${s.name} (${s.language})</option>`
    ).join('');
}

function populateKeywordSources() {
    const select = document.getElementById('globalKeywordSourceSelect');
    if (!select) return;
    const currentVal = select.value;
    select.innerHTML = '<option value="">🌐 All Newspapers (50+ Sources)</option>' +
        state.sources.map(s => `<option value="${s.id}">📰 ${s.name} (${s.language})</option>`).join('');
    if (currentVal) select.value = currentVal;
}

function openNewspaperSearch(sourceId) {
    // Open news modal with search focused directly for this paper
    openNewspaperNewsModal(sourceId, 'all');
    setTimeout(() => {
        const input = document.getElementById('modalKeywordSearchInput');
        if (input) {
            input.focus();
            input.select();
        }
    }, 200);
}

function openCookieModalFor(sourceId) {
    const modal = document.getElementById('cookieImportModal');
    const select = document.getElementById('cookieSourceSelect');
    if (select) select.value = sourceId;
    if (modal) modal.classList.add('open');
}

// --------------------------------------------------------------------------
// Storage Stats & Purge
// --------------------------------------------------------------------------
async function fetchStorageStats() {
    try {
        const res = await fetch('/api/storage/stats');
        const data = await res.json();
        const el = document.getElementById('metricDiskUsage');
        if (el) {
            el.textContent = `${data.archive_size_mb} MB / ${data.free_disk_gb} GB Free`;
        }
    } catch (e) {
        console.error(e);
    }
}

async function triggerPurge() {
    const days = prompt('Enter retention cutoff in days (archives older than this will be deleted):', '14');
    if (days === null) return;
    try {
        const res = await fetch(`/api/storage/purge?days=${days}`, { method: 'POST' });
        const data = await res.json();
        alert(`Purge completed: ${data.purged_files} expired PDF archives removed.`);
        fetchArchives();
        fetchStorageStats();
    } catch (e) {
        alert('Purge error: ' + e.message);
    }
}



// --------------------------------------------------------------------------
// Categorized News Reader Modal Functions & Dual Channel Switcher
// --------------------------------------------------------------------------
function updateChannelPillsUI(sourceId = null) {
    const sid = sourceId || (state.currentNewsSource ? state.currentNewsSource.id : null);
    const hasEpaper = isEpaperCookieSource(sid);

    const btnEp = document.getElementById('btnChannelEpaper');
    const btnOn = document.getElementById('btnChannelOnline');
    const badgeOnly = document.getElementById('channelOnlineOnlyBadge');
    const txt = document.getElementById('channelOnlineOnlyText');

    if (!hasEpaper) {
        // NON-COOKIE PAPERS (Times of India, etc.): Strictly Online News only!
        state.currentNewsChannel = 'online';
        if (btnEp) {
            btnEp.style.display = 'none';
            btnEp.classList.remove('active');
        }
        if (badgeOnly) {
            badgeOnly.style.display = 'flex';
            const srcName = state.currentNewsSource ? state.currentNewsSource.name : (sid || 'Publication');
            if (txt) txt.textContent = `🌐 Online News (Google News Live Stream) • ${srcName}`;
        }
        if (btnOn) {
            btnOn.style.display = 'flex';
            btnOn.classList.add('active');
            btnOn.style.background = 'linear-gradient(135deg,rgba(168,85,247,0.25),rgba(129,140,248,0.35))';
            btnOn.style.color = '#c084fc';
            btnOn.style.borderColor = '#c084fc';
            btnOn.style.boxShadow = '0 0 12px rgba(168,85,247,0.25)';
        }
        return;
    }

    // THE 6 ACTIVE COOKIE PUBLICATIONS (The Hindu, FE, Lokmat, Samachar, Loksatta, DT Next): Both channels available!
    if (badgeOnly) badgeOnly.style.display = 'none';
    if (btnEp) btnEp.style.display = 'flex';
    if (btnOn) btnOn.style.display = 'flex';

    const isEpaper = state.currentNewsChannel !== 'online';
    if (isEpaper) {
        if (btnEp) {
            btnEp.classList.add('active');
            btnEp.style.background = 'linear-gradient(135deg,rgba(56,189,248,0.25),rgba(2,132,199,0.35))';
            btnEp.style.color = '#38bdf8';
            btnEp.style.borderColor = '#38bdf8';
            btnEp.style.boxShadow = '0 0 12px rgba(56,189,248,0.25)';
        }
        if (btnOn) {
            btnOn.classList.remove('active');
            btnOn.style.background = 'rgba(30,41,59,0.5)';
            btnOn.style.color = '#94a3b8';
            btnOn.style.borderColor = 'rgba(255,255,255,0.12)';
            btnOn.style.boxShadow = 'none';
        }
    } else {
        if (btnOn) {
            btnOn.classList.add('active');
            btnOn.style.background = 'linear-gradient(135deg,rgba(168,85,247,0.25),rgba(129,140,248,0.35))';
            btnOn.style.color = '#c084fc';
            btnOn.style.borderColor = '#c084fc';
            btnOn.style.boxShadow = '0 0 12px rgba(168,85,247,0.25)';
        }
        if (btnEp) {
            btnEp.classList.remove('active');
            btnEp.style.background = 'rgba(30,41,59,0.5)';
            btnEp.style.color = '#94a3b8';
            btnEp.style.borderColor = 'rgba(255,255,255,0.12)';
            btnEp.style.boxShadow = 'none';
        }
    }
}

window.switchNewsChannel = async function(channel) {
    if (!state.currentNewsSource) return;
    const hasEpaper = isEpaperCookieSource(state.currentNewsSource.id);
    if (channel === 'epaper' && !hasEpaper) {
        return;
    }
    state.currentNewsChannel = channel;
    updateChannelPillsUI(state.currentNewsSource.id);
    await loadCategorizedNews(state.currentNewsSource.id, state.currentNewsCategory || 'all');
};

async function openNewspaperNewsModal(sourceId, initialCategory = 'all') {
    const source = state.sources.find(s => s.id === sourceId);
    if (!source) return;

    state.currentNewsSource = source;
    state.currentNewsCategory = initialCategory;
    state.currentSearchKeyword = '';

    const hasEpaper = isEpaperCookieSource(sourceId);
    if (!hasEpaper) {
        state.currentNewsChannel = 'online';
    } else {
        if (state.currentNewsChannel !== 'online') {
            state.currentNewsChannel = 'epaper';
        }
    }
    updateChannelPillsUI(sourceId);

    // Clear search input in modal
    const modalSearchInput = document.getElementById('modalKeywordSearchInput');
    const modalResetBtn = document.getElementById('btnModalResetSearch');
    if (modalSearchInput) modalSearchInput.value = '';
    if (modalResetBtn) modalResetBtn.style.display = 'none';

    // Header info
    const nameEl = document.getElementById('newsModalSourceName');
    const metaEl = document.getElementById('newsModalSourceMeta');
    const liveBtn = document.getElementById('newsModalLiveBtn');
    const pdfBtn = document.getElementById('newsModalPdfBtn');
    const harvestBtn = document.getElementById('newsModalHarvestBtn');

    if (nameEl) nameEl.textContent = source.name;
    if (metaEl) metaEl.textContent = `${source.state_region} • ${source.category} • ${source.language} Edition`;
    if (liveBtn) {
        liveBtn.href = source.base_url;
        liveBtn.style.display = 'inline-flex';
    }
    if (harvestBtn) harvestBtn.style.display = 'inline-flex';

    // Show categories bar
    const catBar = document.getElementById('newsCategoriesBar');
    if (catBar) catBar.style.display = 'flex';

    // Check if archived PDF exists
    const matchingArchive = state.archives.find(a => a.source_id === source.id);
    if (pdfBtn) {
        if (matchingArchive) {
            pdfBtn.style.display = 'inline-flex';
            pdfBtn.onclick = () => {
                closeNewsModal();
                openPdfPreview(matchingArchive.source_id, matchingArchive.target_date, matchingArchive.filename, `${source.name} - ${matchingArchive.edition} (${matchingArchive.target_date})`);
            };
        } else {
            pdfBtn.style.display = 'none';
        }
    }

    if (harvestBtn) {
        harvestBtn.onclick = () => {
            closeNewsModal();
            triggerSingleHarvest(source.id);
        };
    }

    // Set active category pill
    document.querySelectorAll('.news-cat-pill').forEach(pill => {
        if (pill.dataset.cat === initialCategory) {
            pill.classList.add('active');
        } else {
            pill.classList.remove('active');
        }
    });

    const modal = document.getElementById('newspaperNewsModal');
    if (modal) modal.classList.add('open');

    // Load news
    await loadCategorizedNews(sourceId, initialCategory);
}

function closeNewsModal() {
    const modal = document.getElementById('newspaperNewsModal');
    if (modal) modal.classList.remove('open');
}

async function switchNewsCategory(category) {
    if (!state.currentNewsSource) return;
    state.currentNewsCategory = category;

    document.querySelectorAll('.news-cat-pill').forEach(pill => {
        if (pill.dataset.cat === category) {
            pill.classList.add('active');
        } else {
            pill.classList.remove('active');
        }
    });

    await loadCategorizedNews(state.currentNewsSource.id, category);
}

async function loadCategorizedNews(sourceId, category) {
    const container = document.getElementById('newsArticlesContainer');
    if (!container) return;

    const channel = state.currentNewsChannel || 'epaper';
    const cacheKey = `${channel}:${sourceId}:${category}`;

    // Show loading skeleton
    container.innerHTML = `
        <div class="news-loading-skeleton">
            <div class="skeleton-card"></div>
            <div class="skeleton-card"></div>
            <div class="skeleton-card"></div>
            <div class="skeleton-card"></div>
        </div>
    `;

    try {
        let articles = state.newsCache[cacheKey];
        if (!articles) {
            const res = await fetch(`/api/news/${channel}/${sourceId}?category=${category}`);
            if (!res.ok) throw new Error(await res.text());
            articles = await res.json();
            state.newsCache[cacheKey] = articles;
        }

        renderNewsArticles(articles, category);
    } catch (e) {
        container.innerHTML = `
            <div class="empty-state">
                <div style="font-size:2rem;margin-bottom:0.5rem;">⚠️</div>
                <h4>Could not load ${channel === 'epaper' ? 'ePaper Digital' : 'Online'} ${category.replace('_', ' ')} news</h4>
                <p class="text-secondary" style="margin-top:0.25rem;">${e.message}</p>
                <button class="btn btn-secondary btn-sm" style="margin-top:1rem;" onclick="loadCategorizedNews('${sourceId}', '${category}')">🔄 Retry</button>
            </div>
        `;
    }
}

// --------------------------------------------------------------------------
// Custom Keyword Search Actions
// --------------------------------------------------------------------------
async function triggerKeywordSearch(keywords, sourceId = null) {
    const cleanKw = keywords.trim();
    if (!cleanKw) return;

    // If sourceId not explicitly passed, check if global newspaper selector is active
    if (!sourceId) {
        const sel = document.getElementById('globalKeywordSourceSelect');
        if (sel && sel.value) {
            sourceId = sel.value;
        }
    }

    state.currentSearchKeyword = cleanKw;

    // Header setup in modal
    const nameEl = document.getElementById('newsModalSourceName');
    const metaEl = document.getElementById('newsModalSourceMeta');
    const liveBtn = document.getElementById('newsModalLiveBtn');
    const pdfBtn = document.getElementById('newsModalPdfBtn');
    const harvestBtn = document.getElementById('newsModalHarvestBtn');
    const catBar = document.getElementById('newsCategoriesBar');
    const modalSearchInput = document.getElementById('modalKeywordSearchInput');
    const modalResetBtn = document.getElementById('btnModalResetSearch');
    const globalSelect = document.getElementById('globalKeywordSourceSelect');

    if (globalSelect) globalSelect.value = sourceId || '';
    if (modalSearchInput) modalSearchInput.value = cleanKw;
    if (modalResetBtn) modalResetBtn.style.display = 'inline-flex';

    if (sourceId) {
        const source = state.sources.find(s => s.id === sourceId);
        state.currentNewsSource = source;
        const sourceDisplayName = source ? source.name : sourceId.replace('_', ' ').toUpperCase();
        if (nameEl) nameEl.textContent = `🔍 "${cleanKw}" in ${sourceDisplayName}`;
        if (metaEl) metaEl.textContent = `Isolated search for ${sourceDisplayName} only • Auto-translated to English`;
        if (liveBtn && source) {
            liveBtn.href = source.base_url;
            liveBtn.style.display = 'inline-flex';
        }
        if (harvestBtn) harvestBtn.style.display = 'inline-flex';
        if (catBar) catBar.style.display = 'none';
    } else {
        state.currentNewsSource = null;
        if (nameEl) nameEl.textContent = `🔍 News Search: "${cleanKw}"`;
        if (metaEl) metaEl.textContent = `Searched across 50+ national & regional publications • Auto-translated to English`;
        if (liveBtn) liveBtn.style.display = 'none';
        if (pdfBtn) pdfBtn.style.display = 'none';
        if (harvestBtn) harvestBtn.style.display = 'none';
        if (catBar) catBar.style.display = 'none';
    }

    const modal = document.getElementById('newspaperNewsModal');
    if (modal) modal.classList.add('open');

    const container = document.getElementById('newsArticlesContainer');

    // 1. Instant match against local news cache, strictly restricted to sourceId if provided
    let localMatches = [];
    const kwLower = cleanKw.toLowerCase();
    const kwTokens = kwLower.split(/\s+/).filter(w => w.length > 2);

    Object.keys(state.newsCache).forEach(cacheKey => {
        if (!sourceId || cacheKey.startsWith(`${sourceId}:`)) {
            (state.newsCache[cacheKey] || []).forEach(art => {
                if (sourceId && art.source_id && art.source_id !== sourceId) return;
                const t = (art.title || '').toLowerCase();
                const s = (art.snippet || '').toLowerCase();
                const ot = (art.original_title || '').toLowerCase();
                const os = (art.original_snippet || '').toLowerCase();
                const combinedText = `${t} ${s} ${ot} ${os}`;
                const matchedFull = combinedText.includes(kwLower);
                const matchedTokens = kwTokens.length > 0 && kwTokens.every(tok => combinedText.includes(tok));
                if (matchedFull || matchedTokens) {
                    if (!localMatches.some(m => m.id === art.id || (m.title && m.title.toLowerCase() === t))) {
                        localMatches.push(art);
                    }
                }
            });
        }
    });

    if (localMatches.length > 0) {
        // Instantly render local matches while backend search runs
        renderNewsArticles(localMatches, 'search');
    } else if (container) {
        container.innerHTML = `
            <div class="news-loading-skeleton">
                <div class="skeleton-card"></div>
                <div class="skeleton-card"></div>
                <div class="skeleton-card"></div>
                <div class="skeleton-card"></div>
            </div>
        `;
    }

    try {
        const url = `/api/news/search?q=${encodeURIComponent(cleanKw)}${sourceId ? '&source_id=' + sourceId : ''}`;
        const res = await fetch(url);
        if (!res.ok) throw new Error(await res.text());
        const fetchedArticles = await res.json();

        // Merge local matches and fetched articles (deduplicating and strictly ensuring source isolation)
        const combined = [...localMatches];
        (fetchedArticles || []).forEach(f => {
            if (sourceId && f.source_id && f.source_id !== sourceId) return;
            const fTitle = (f.title || '').toLowerCase();
            if (!combined.some(c => c.id === f.id || (c.title && c.title.toLowerCase() === fTitle))) {
                combined.push(f);
            }
        });

        renderNewsArticles(combined, 'search');
    } catch (e) {
        if (localMatches.length === 0 && container) {
            container.innerHTML = `
                <div class="empty-state">
                    <div style="font-size:2rem;margin-bottom:0.5rem;">⚠️</div>
                    <h4>Search Error</h4>
                    <p class="text-secondary">${e.message}</p>
                    <button class="btn btn-secondary btn-sm" style="margin-top:1rem;" onclick="resetModalSearch()">🔄 Clear Search</button>
                </div>
            `;
        }
    }
}

async function handleModalKeywordSearch() {
    const input = document.getElementById('modalKeywordSearchInput');
    const query = input ? input.value.trim() : '';
    if (!query) return;

    const sourceId = state.currentNewsSource ? state.currentNewsSource.id : null;
    await triggerKeywordSearch(query, sourceId);
}

function resetModalSearch() {
    const input = document.getElementById('modalKeywordSearchInput');
    const resetBtn = document.getElementById('btnModalResetSearch');
    if (input) input.value = '';
    if (resetBtn) resetBtn.style.display = 'none';
    state.currentSearchKeyword = '';

    const catBar = document.getElementById('newsCategoriesBar');
    if (catBar) catBar.style.display = 'flex';

    if (state.currentNewsSource) {
        const nameEl = document.getElementById('newsModalSourceName');
        const metaEl = document.getElementById('newsModalSourceMeta');
        if (nameEl) nameEl.textContent = state.currentNewsSource.name;
        if (metaEl) metaEl.textContent = `${state.currentNewsSource.state_region} • ${state.currentNewsSource.category} • ${state.currentNewsSource.language} Edition`;
        loadCategorizedNews(state.currentNewsSource.id, state.currentNewsCategory);
    } else {
        closeNewsModal();
    }
}

function renderNewsArticles(articles, category) {
    const container = document.getElementById('newsArticlesContainer');
    if (!container) return;

    // Strict category filtering: ensure only articles matching the requested category are displayed, while search allows all categories
    let displayArticles = articles || [];
    if (category && category !== 'all' && category !== 'search') {
        displayArticles = displayArticles.filter(a => !a.category || a.category === category);
    }

    if (!displayArticles || displayArticles.length === 0) {
        const isSearch = category === 'search' || !!state.currentSearchKeyword;
        const hasEpaper = state.currentNewsSource ? isEpaperCookieSource(state.currentNewsSource.id) : false;
        const isEpaper = hasEpaper && (state.currentNewsChannel || 'epaper') === 'epaper';
        const emptyTitle = isSearch
            ? `No articles found matching "${state.currentSearchKeyword || ''}"`
            : (isEpaper
                ? `No ePaper broadsheet articles indexed for this category`
                : `No online news articles found for this category`);
        const emptyDesc = isSearch
            ? `Try searching with fewer words, common names (e.g. Tata, Reliance, Modi, Train, Flood, RBI), or clear the search.`
            : (isEpaper
                ? `Active cookie broadsheet harvesting for this edition hasn't extracted this category yet. You can trigger a harvest or view the Google News Online feed.`
                : `Check another category or visit the official portal.`);

        const altActionBtn = (!isSearch && isEpaper)
            ? `<button class="btn btn-secondary btn-sm" style="margin-top:1rem;" onclick="switchNewsChannel('online')">🌐 Switch to Online News (Google News)</button>`
            : '';

        container.innerHTML = `
            <div class="empty-state">
                <div style="font-size:2.5rem;margin-bottom:0.5rem;">${isSearch ? '🔍' : (isEpaper ? '📰' : '🌐')}</div>
                <h3>${emptyTitle}</h3>
                <p class="text-secondary" style="margin-top:0.35rem;">${emptyDesc}</p>
                ${isSearch ? '<button class="btn btn-secondary btn-sm" style="margin-top:1rem;" onclick="resetModalSearch()">🔄 Clear Search</button>' : ''}
                ${altActionBtn}
            </div>
        `;
        return;
    }

    const categoryBadges = {
        sports: { label: '🏆 Sports', class: 'cat-badge-sports' },
        business: { label: '💼 Business', class: 'cat-badge-business' },
        economic: { label: '📈 Economic', class: 'cat-badge-economic' },
        political: { label: '🏛️ Political', class: 'cat-badge-political' },
        crises_disasters: { label: '🚨 Crises & Disasters', class: 'cat-badge-crises' },
        all: { label: '📰 Top Story', class: 'cat-badge-all' },
    };

    const hasTranslatedArticles = displayArticles.some(a => a.is_translated);
    const statusPill = hasTranslatedArticles
        ? `<span class="live-pill" style="font-size:0.75rem;background:rgba(56,189,248,0.15);border-color:rgba(56,189,248,0.4);color:#38bdf8;"><span class="pulse-dot"></span> 🌐 Translated to English</span>`
        : `<span class="live-pill" style="font-size:0.75rem;"><span class="pulse-dot"></span> Live Feed</span>`;

    const titlePrefix = state.currentSearchKeyword
        ? `Search results for <strong>"${state.currentSearchKeyword}"</strong>`
        : `Showing <strong>${displayArticles.length}</strong> latest stories for <strong>${state.currentNewsSource ? state.currentNewsSource.name : 'Publications'}</strong>`;

    const countHeader = `
        <div class="news-results-count">
            <span>${titlePrefix} (${displayArticles.length} articles)</span>
            ${statusPill}
        </div>
    `;

    const cardsHtml = displayArticles.map(art => {
        const badgeInfo = categoryBadges[art.category] || categoryBadges.all;
        let pubDateStr = 'Today';
        try {
            if (art.published_at) {
                pubDateStr = new Date(art.published_at).toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' });
            }
        } catch (e) {}

        const isEpaper = art.news_type === 'epaper' || !!art.page_number;
        const channelBadge = isEpaper
            ? `<span class="news-channel-badge" style="background:rgba(56,189,248,0.15);color:#38bdf8;border:1px solid rgba(56,189,248,0.4);padding:2px 8px;border-radius:4px;font-size:0.73rem;font-weight:700;">📰 ePaper Digital (Page ${art.page_number || 1})</span>`
            : `<span class="news-channel-badge" style="background:rgba(168,85,247,0.15);color:#c084fc;border:1px solid rgba(168,85,247,0.4);padding:2px 8px;border-radius:4px;font-size:0.73rem;font-weight:700;">🌐 Online News (Google News)</span>`;

        const translationBadge = art.is_translated
            ? `<span class="news-translated-badge" title="Original: ${art.original_title || ''}">🌐 Translated from ${art.original_language || 'Regional'}</span>`
            : '';

        const originalSubtitle = art.is_translated && art.original_title
            ? `<div class="article-original-title" title="Original regional headline">📖 <em>Original:</em> ${art.original_title}</div>`
            : '';

        return `
            <div class="news-article-card">
                <div class="article-top-row">
                    <div style="display:flex;align-items:center;gap:0.4rem;flex-wrap:wrap;">
                        <span class="news-cat-badge ${badgeInfo.class}">${badgeInfo.label}</span>
                        ${channelBadge}
                        ${translationBadge}
                    </div>
                    <span class="article-date">🕒 ${pubDateStr}</span>
                </div>
                <h4 class="article-title">
                    <a href="${art.link}" target="_blank" rel="noopener noreferrer">${art.title}</a>
                </h4>
                ${originalSubtitle}
                ${art.snippet ? `<p class="article-snippet">${art.snippet}</p>` : ''}
                <div class="article-footer">
                    <span class="article-author">📰 ${art.author || art.source_name}</span>
                    <div style="display:flex; gap:0.5rem; align-items:center;">
                        <button class="btn btn-xs" style="background:#25D366;color:#ffffff;border:none;font-weight:600;display:inline-flex;align-items:center;gap:4px;padding:3px 8px;border-radius:4px;" onclick="sendAlertToWhatsApp('${art.id}', event)">
                            💬 WhatsApp
                        </button>
                        <button class="btn btn-xs btn-outline" style="border-color:rgba(245,158,11,0.5);color:#f59e0b;" onclick="openAuditModalForArticle('${art.id}')">
                            🔍 Digital Twin Traceability
                        </button>
                        <a href="${art.link}" target="_blank" rel="noopener noreferrer" class="btn btn-xs btn-outline article-read-btn">
                            Read Full Story ↗
                        </a>
                    </div>
                </div>
            </div>
        `;
    }).join('');

    container.innerHTML = countHeader + `<div class="news-articles-grid">${cardsHtml}</div>`;
}

// --------------------------------------------------------------------------
// Newspaper PDF Upload & OCR Handler Functions
// --------------------------------------------------------------------------
function openUploadModal() {
    resetUploadView();
    const modal = document.getElementById('newspaperUploadModal');
    if (modal) modal.classList.add('open');
}

function closeUploadModal() {
    const modal = document.getElementById('newspaperUploadModal');
    if (modal) modal.classList.remove('open');
}

function resetUploadView() {
    state.uploadedNewsData = null;
    state.currentUploadCategory = 'all';

    const dropzoneContainer = document.getElementById('uploadDropzoneContainer');
    const resultsContainer = document.getElementById('uploadResultsContainer');
    const dropzone = document.getElementById('uploadDropzone');
    const processingBox = document.getElementById('uploadProcessingBox');
    const fileInput = document.getElementById('newspaperFileInput');

    if (dropzoneContainer) dropzoneContainer.style.display = 'flex';
    if (resultsContainer) resultsContainer.style.display = 'none';
    if (dropzone) dropzone.style.display = 'block';
    if (processingBox) processingBox.style.display = 'none';
    if (fileInput) fileInput.value = '';
}

async function processUploadedFile(fileOrFiles) {
    if (!fileOrFiles) return;
    const files = Array.isArray(fileOrFiles) ? fileOrFiles : (fileOrFiles instanceof FileList ? Array.from(fileOrFiles) : [fileOrFiles]);
    const ALLOWED_EXTS = ['.pdf', '.docx', '.doc', '.txt', '.md', '.csv', '.png', '.jpg', '.jpeg', '.webp', '.tiff', '.bmp'];
    const validFiles = files.filter(f => f.name && ALLOWED_EXTS.some(ext => f.name.toLowerCase().endsWith(ext)));

    if (validFiles.length === 0) {
        alert('Please upload valid documents (PDF, Word .docx, Images, or Text).');
        return;
    }

    const dropzone = document.getElementById('uploadDropzone');
    const processingBox = document.getElementById('uploadProcessingBox');
    const stepText = document.getElementById('uploadProcessStepText');
    const subText = document.getElementById('uploadProcessSubText');

    if (dropzone) dropzone.style.display = 'none';
    if (processingBox) processingBox.style.display = 'flex';

    if (validFiles.length === 1) {
        if (stepText) stepText.textContent = `Recognizing text from ${validFiles[0].name}...`;
        if (subText) subText.textContent = 'Extracting content, executing OCR, detecting language, translating, and categorizing news...';
    } else {
        if (stepText) stepText.textContent = `Processing ${validFiles.length} documents concurrently...`;
        if (subText) subText.textContent = 'Multi-file worker queue: rendering pages, running OCR, detecting languages, translating, and categorizing news...';
    }

    const formData = new FormData();
    const isBatch = validFiles.length > 1;

    let endpoint = '/api/newspaper/upload';
    if (isBatch) {
        endpoint = '/api/newspaper/upload-batch';
        validFiles.forEach(f => formData.append('files', f));
    } else {
        formData.append('file', validFiles[0]);
        formData.append('source_name', validFiles[0].name.replace('.pdf', '').replace(/_/g, ' '));
    }

    try {
        const res = await fetch(endpoint, {
            method: 'POST',
            body: formData,
        });

        if (!res.ok) {
            const err = await res.json().catch(() => ({ detail: res.statusText }));
            throw new Error(err.detail || 'Upload failed');
        }

        const data = await res.json();
        state.uploadedNewsData = data;
        state.currentUploadCategory = 'all';

        // Update stats
        const pagesBadge = document.getElementById('uploadStatPages');
        const artsBadge = document.getElementById('uploadStatArticles');
        const transBadge = document.getElementById('uploadStatTranslated');
        if (pagesBadge) pagesBadge.textContent = `📄 ${data.total_pages} Pages Processed`;
        if (artsBadge) artsBadge.textContent = `🗞️ ${data.total_articles} Stories Extracted`;
        if (transBadge) transBadge.textContent = `🌐 ${data.translated_count} Auto-Translated`;

        // Switch to results view
        const dropzoneContainer = document.getElementById('uploadDropzoneContainer');
        const resultsContainer = document.getElementById('uploadResultsContainer');
        if (dropzoneContainer) dropzoneContainer.style.display = 'none';
        if (resultsContainer) resultsContainer.style.display = 'flex';

        // Render category tabs
        switchUploadCategory('all');

    } catch (e) {
        alert(`Failed to process newspaper PDF: ${e.message}`);
        resetUploadView();
    }
}

function switchUploadCategory(cat) {
    state.currentUploadCategory = cat;

    // Update active pill
    document.querySelectorAll('#uploadCategoriesBar .news-cat-pill').forEach(pill => {
        if (pill.dataset.uploadCat === cat) {
            pill.classList.add('active');
        } else {
            pill.classList.remove('active');
        }
    });

    renderUploadedArticles(cat);
}

function renderUploadedArticles(category) {
    const container = document.getElementById('uploadArticlesContainer');
    if (!container) return;

    if (!state.uploadedNewsData || !state.uploadedNewsData.categories) {
        container.innerHTML = `<div class="empty-state"><h3>No stories parsed yet</h3></div>`;
        return;
    }

    const articles = state.uploadedNewsData.categories[category] || [];

    if (articles.length === 0) {
        container.innerHTML = `
            <div class="empty-state">
                <div style="font-size:2.5rem;margin-bottom:0.5rem;">🗞️</div>
                <h3>No stories found in this category</h3>
                <p class="text-secondary">Check another category or review All Stories.</p>
            </div>
        `;
        return;
    }

    const categoryBadges = {
        sports: { label: '🏆 Sports', class: 'cat-badge-sports' },
        business: { label: '💼 Business', class: 'cat-badge-business' },
        economic: { label: '📈 Economic', class: 'cat-badge-economic' },
        political: { label: '🏛️ Political', class: 'cat-badge-political' },
        crises_disasters: { label: '🚨 Crises & Disasters', class: 'cat-badge-crises' },
        all: { label: '📰 Extracted Story', class: 'cat-badge-all' },
    };

    const hasTranslated = articles.some(a => a.is_translated);
    const statusPill = hasTranslated
        ? `<span class="live-pill" style="font-size:0.75rem;background:rgba(56,189,248,0.15);border-color:rgba(56,189,248,0.4);color:#38bdf8;"><span class="pulse-dot"></span> 🌐 Auto-Translated to English</span>`
        : `<span class="live-pill" style="font-size:0.75rem;"><span class="pulse-dot"></span> OCR Text Extracted</span>`;

    const countHeader = `
        <div class="news-results-count">
            <span>Showing <strong>${articles.length}</strong> stories parsed from <strong>${state.uploadedNewsData.filename}</strong></span>
            ${statusPill}
        </div>
    `;

    const cardsHtml = articles.map(art => {
        const badgeInfo = categoryBadges[art.category] || categoryBadges.all;

        const translationBadge = art.is_translated
            ? `<span class="news-translated-badge" title="Original: ${art.original_title || ''}">🌐 Translated from ${art.original_language || 'Regional'}</span>`
            : '';

        const originalSubtitle = art.is_translated && art.original_title
            ? `<div class="article-original-title" title="Original regional headline">📖 <em>Original:</em> ${art.original_title}</div>`
            : '';

        const pageNum = art.page_number || 1;
        const pageBadge = `<span class="article-page-badge" title="Published on Page ${pageNum} of newspaper">📑 Page ${pageNum}</span>`;

        const snapshotBtn = art.page_snapshot_url
            ? `<a href="${art.page_snapshot_url}" target="_blank" class="btn btn-xs btn-outline" style="border-color:rgba(56,189,248,0.5);color:#38bdf8;" title="View high-res scanned page image">👁️ Page ${pageNum} Scan ↗</a>`
            : '';

        return `
            <div class="news-article-card" id="upload_art_${art.id}">
                <div class="article-top-row">
                    <div style="display:flex;align-items:center;gap:0.45rem;flex-wrap:wrap;">
                        <span class="news-cat-badge ${badgeInfo.class}">${badgeInfo.label}</span>
                        ${pageBadge}
                        ${translationBadge}
                    </div>
                    <span class="article-date">📄 Page ${pageNum} • ${art.published_at || 'Extracted'}</span>
                </div>
                <h4 class="article-title" style="color:var(--text-primary);margin-bottom:0.4rem;">
                    ${art.title}
                </h4>
                ${originalSubtitle}
                ${art.snippet ? `<p class="article-snippet">${art.snippet}</p>` : ''}
                <div style="display:flex;justify-content:space-between;align-items:center;margin-top:0.6rem;padding-top:0.4rem;border-top:1px solid rgba(255,255,255,0.06);flex-wrap:wrap;gap:0.4rem;">
                    <div style="font-size:0.74rem;color:var(--text-muted);">
                        OCR: <strong>${Math.round((art.ocr_confidence || 0.98)*100)}%</strong> • Trans: <strong>${Math.round((art.translation_confidence || 1.0)*100)}%</strong>
                    </div>
                    <div style="display:flex;align-items:center;gap:0.4rem;">
                        ${snapshotBtn}
                        <button class="btn btn-xs" style="background:#25D366;color:#ffffff;border:none;font-weight:600;display:inline-flex;align-items:center;gap:4px;padding:3px 8px;border-radius:4px;" onclick="sendAlertToWhatsApp('${art.id}', event)">
                            💬 WhatsApp
                        </button>
                        <button class="btn btn-xs btn-outline" style="border-color:rgba(245,158,11,0.5);color:#f59e0b;" onclick="openAuditModalForArticle('${art.id}')">
                            🔍 Digital Twin (Page ${pageNum})
                        </button>
                    </div>
                </div>
            </div>
        `;
    }).join('');

    container.innerHTML = countHeader + `<div class="news-articles-grid">${cardsHtml}</div>`;
}

// --------------------------------------------------------------------------
// Email News Digest Handler Functions
// --------------------------------------------------------------------------
function openEmailModal(category = 'all') {
    state.selectedEmailCategory = category;

    const modal = document.getElementById('emailDigestModal');
    const statusBox = document.getElementById('emailSendingStatus');
    const sendBtn = document.getElementById('btnSendEmailDigestAction');
    const kwInput = document.getElementById('emailCustomKeywords');
    const previewBox = document.getElementById('emailDigestPreviewBox');

    if (statusBox) statusBox.style.display = 'none';
    if (previewBox) previewBox.style.display = 'none';
    if (sendBtn) {
        sendBtn.disabled = false;
        sendBtn.innerHTML = '🚀 Send Email Digest';
    }
    if (kwInput) {
        kwInput.value = state.currentSearchKeyword || '';
    }

    // Set active category pill
    document.querySelectorAll('#emailCategorySelector .news-cat-pill').forEach(pill => {
        if (pill.dataset.emailCat === category) {
            pill.classList.add('active');
        } else {
            pill.classList.remove('active');
        }
    });

    if (modal) modal.classList.add('open');
}

function closeEmailModal() {
    const modal = document.getElementById('emailDigestModal');
    if (modal) modal.classList.remove('open');
}

async function handlePreviewEmailDigest() {
    const kwInput = document.getElementById('emailCustomKeywords');
    const customKeywords = kwInput ? kwInput.value.trim() : '';
    const category = state.selectedEmailCategory || 'all';

    const previewBtn = document.getElementById('btnPreviewEmailDigest');
    const previewBox = document.getElementById('emailDigestPreviewBox');
    const container = document.getElementById('emailPreviewContentContainer');
    const countSpan = document.getElementById('emailPreviewArticleCount');

    if (previewBtn) previewBtn.disabled = true;
    if (container) container.innerHTML = `<div class="spinner" style="margin:1rem auto;border-top-color:#38bdf8;"></div><div style="text-align:center;font-size:0.8rem;color:#38bdf8;">Aggregating multi-language news & generating English preview...</div>`;
    if (previewBox) previewBox.style.display = 'block';

    try {
        const res = await fetch('/api/email/preview-digest', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                category: category,
                custom_keywords: customKeywords || null,
                max_articles: 25,
            }),
        });

        if (!res.ok) {
            const err = await res.json().catch(() => ({ detail: res.statusText }));
            throw new Error(err.detail || 'Preview generation failed');
        }

        const data = await res.json();
        if (countSpan) countSpan.textContent = data.articles_count;

        if (!data.articles || data.articles.length === 0) {
            if (container) container.innerHTML = `<div style="text-align:center;padding:1rem;color:var(--text-muted);">No articles available in this category.</div>`;
            return;
        }

        const articlesHtml = data.articles.map((art, idx) => `
            <div style="background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.06);border-radius:var(--radius-sm);padding:0.6rem 0.8rem;margin-bottom:0.5rem;">
                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:0.25rem;">
                    <span style="font-weight:700;font-size:0.75rem;color:#38bdf8;">${idx + 1}. ${art.source_name}</span>
                    ${art.is_translated ? `<span style="font-size:0.7rem;color:#0284c7;background:#e0f2fe;padding:1px 6px;border-radius:10px;font-weight:600;">🌐 Auto-Translated from ${art.original_language || 'Regional'}</span>` : ''}
                </div>
                <div style="font-size:0.84rem;font-weight:600;color:var(--text-primary);margin-bottom:0.2rem;">${art.title}</div>
                ${art.original_title && art.is_translated ? `<div style="font-size:0.75rem;color:var(--text-muted);font-style:italic;margin-bottom:0.2rem;">Original: ${art.original_title}</div>` : ''}
                ${art.snippet ? `<p style="font-size:0.75rem;color:var(--text-secondary);margin:0;line-height:1.3;">${art.snippet}</p>` : ''}
            </div>
        `).join('');

        if (container) container.innerHTML = articlesHtml;

    } catch (e) {
        if (container) container.innerHTML = `<div style="color:#ef4444;padding:0.5rem;font-size:0.8rem;">❌ Error: ${e.message}</div>`;
    } finally {
        if (previewBtn) previewBtn.disabled = false;
    }
}

async function handleTestSmtpConnection() {
    const btn = document.getElementById('btnTestSmtpConnection');
    const badge = document.getElementById('smtpConnectionBadge');
    if (btn) btn.disabled = true;

    try {
        const res = await fetch('/api/email/diagnostics');
        const data = await res.json();
        if (data.smtp && data.smtp.success) {
            alert(`✅ Gmail SMTP Connected Successfully!\n\nHost: ${data.smtp.host}:${data.smtp.port} (SSL)\nAuthenticated: ${data.smtp.user}\nLatency: ${data.smtp.latency_ms}ms\nStatus: Healthy & Ready for Dispatch`);
            if (badge) {
                badge.style.color = '#10b981';
                badge.style.borderColor = 'rgba(16,185,129,0.4)';
                badge.innerHTML = `<span class="pulse-dot" style="background:#10b981;"></span> SMTP: Connected (${data.smtp.latency_ms}ms)`;
            }
        } else {
            alert(`❌ Gmail SMTP Connection Failed: ${data.smtp?.error || 'Unknown error'}`);
        }
    } catch (e) {
        alert(`SMTP Test Error: ${e.message}`);
    } finally {
        if (btn) btn.disabled = false;
    }
}

async function handleSendEmailDigest() {
    const recipientInput = document.getElementById('emailRecipientAddress');
    const recipientEmail = recipientInput ? recipientInput.value.trim() : '';
    const kwInput = document.getElementById('emailCustomKeywords');
    const customKeywords = kwInput ? kwInput.value.trim() : '';
    const category = state.selectedEmailCategory || 'all';

    if (!recipientEmail || !recipientEmail.includes('@')) {
        alert('Please enter a valid recipient email address.');
        return;
    }

    const sendBtn = document.getElementById('btnSendEmailDigestAction');
    const statusBox = document.getElementById('emailSendingStatus');
    const statusText = document.getElementById('emailSendingStatusText');

    if (sendBtn) sendBtn.disabled = true;
    if (statusBox) statusBox.style.display = 'block';
    if (statusText) statusText.textContent = `Compiling multi-language ${category} stories, translating to English, and dispatching via Gmail...`;

    try {
        const res = await fetch('/api/news/email-digest', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                category: category,
                recipient_email: recipientEmail,
                custom_keywords: customKeywords || null,
                max_articles: 25,
            }),
        });

        if (!res.ok) {
            const err = await res.json().catch(() => ({ detail: res.statusText }));
            throw new Error(err.detail || 'Email dispatch failed');
        }

        const data = await res.json();
        alert(`✅ Email Digest Successfully Sent!\n\nDelivered to: ${data.recipient_email}\nCategory: ${data.category_name}\nArticles Included: ${data.articles_count} stories\n\nAll regional news headlines and summaries were translated to English.`);
        closeEmailModal();

    } catch (e) {
        alert(`❌ Failed to send email digest: ${e.message}`);
    } finally {
        if (sendBtn) {
            sendBtn.disabled = false;
            sendBtn.innerHTML = '🚀 Send Email Digest';
        }
        if (statusBox) statusBox.style.display = 'none';
    }
}

// --------------------------------------------------------------------------
// Email Workflow Automation & Inbox Monitor Functions
// --------------------------------------------------------------------------
async function openInboxModal() {
    const modal = document.getElementById('inboxMonitorModal');
    if (modal) modal.classList.add('open');
    await Promise.all([
        fetchInboxStatusAndClippings(),
        fetchRealInboxMessages()
    ]);
}

function closeInboxModal() {
    const modal = document.getElementById('inboxMonitorModal');
    if (modal) modal.classList.remove('open');
}

async function fetchInboxStatusAndClippings() {
    try {
        const [statusRes, clippingsRes] = await Promise.all([
            fetch('/api/inbox/status').then(r => r.json()),
            fetch('/api/inbox/clippings').then(r => r.json()),
        ]);

        const countBadge = document.getElementById('inboxClippingsCountBadge');
        const ingestedTotalBadge = document.getElementById('inboxIngestedTotalBadge');
        const total = (clippingsRes || []).length;
        if (countBadge) {
            countBadge.textContent = `${total} Clippings Ingested`;
        }
        if (ingestedTotalBadge) {
            ingestedTotalBadge.textContent = total;
        }

        state.inboxClippings = clippingsRes || [];
        renderInboxClippings(state.inboxClippings);

    } catch (e) {
        console.error('Failed to fetch inbox status:', e);
    }
}

async function fetchRealInboxMessages() {
    const listContainer = document.getElementById('realInboxMessagesList');
    const totalBadge = document.getElementById('inboxLiveTotalBadge');
    const refreshBtn = document.getElementById('btnRefreshRealInbox');

    if (refreshBtn) refreshBtn.innerHTML = '🔄 Loading...';
    if (listContainer && (!state.realInboxMessages || state.realInboxMessages.length === 0)) {
        listContainer.innerHTML = `
            <div style="text-align:center;padding:2.5rem;color:var(--text-muted);">
                <div class="spinner" style="margin:0 auto 0.75rem auto;border-top-color:#a855f7;"></div>
                <div>Connecting to Gmail IMAP SSL (Port 993) & loading live mailbox...</div>
            </div>
        `;
    }

    try {
        const res = await fetch('/api/inbox/messages?limit=30');
        if (!res.ok) {
            const err = await res.json().catch(() => ({ detail: res.statusText }));
            throw new Error(err.detail || `Failed to fetch messages: ${res.statusText}`);
        }
        const data = await res.json();
        state.realInboxMessages = data.messages || [];
        if (totalBadge) totalBadge.textContent = data.total_inbox || data.total_inbox_messages || state.realInboxMessages.length;
        const subBadge = document.getElementById('inboxAccountSubBadge');
        if (subBadge && data.account) subBadge.textContent = data.account;
        renderRealInboxMessages(state.realInboxMessages);
    } catch (e) {
        console.error('Error fetching real inbox:', e);
        if (listContainer) {
            listContainer.innerHTML = `
                <div style="background:rgba(239,68,68,0.1);border:1px solid #ef4444;border-radius:var(--radius-sm);padding:1.25rem;color:#ef4444;font-size:0.85rem;text-align:center;">
                    <div style="font-weight:700;margin-bottom:0.35rem;">❌ Failed to load live inbox</div>
                    <div>${escapeHtml(e.message)}</div>
                </div>
            `;
        }
    } finally {
        if (refreshBtn) refreshBtn.innerHTML = '🔄 Refresh';
    }
}

function renderRealInboxMessages(messages) {
    const listContainer = document.getElementById('realInboxMessagesList');
    if (!listContainer) return;

    if (!messages || messages.length === 0) {
        listContainer.innerHTML = `
            <div class="empty-state" style="padding:2.5rem;text-align:center;">
                <div style="font-size:2.5rem;margin-bottom:0.5rem;">📭</div>
                <h4 style="color:var(--text-primary);margin-bottom:0.25rem;">No incoming messages found</h4>
                <p class="text-secondary" style="font-size:0.85rem;">No emails match the current search or inbox filter.</p>
            </div>
        `;
        return;
    }

    listContainer.innerHTML = messages.map(msg => {
        const hasAttachments = msg.attachments && msg.attachments.length > 0;
        const attachmentBadges = (msg.attachments || []).map(att => {
            const isPdf = att.filename.toLowerCase().endsWith('.pdf');
            const icon = isPdf ? '📕' : '🖼️';
            const sizeKb = Math.round(att.size / 1024);
            return `<span style="display:inline-flex;align-items:center;gap:0.3rem;background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.12);padding:0.2rem 0.55rem;border-radius:4px;font-size:0.72rem;color:var(--text-primary);" title="${escapeHtml(att.filename)} (${sizeKb} KB)">
                <span>${icon}</span>
                <span style="max-width:160px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-weight:600;">${escapeHtml(att.filename)}</span>
                <span style="color:var(--text-muted);font-size:0.68rem;">(${sizeKb}KB)</span>
            </span>`;
        }).join(' ');

        const ruleBadge = msg.is_rule_match
            ? `<span style="background:rgba(16,185,129,0.15);border:1px solid rgba(16,185,129,0.4);color:#10b981;font-size:0.7rem;padding:0.2rem 0.5rem;border-radius:4px;font-weight:600;">⚡ Rule Matched</span>`
            : `<span style="background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.08);color:var(--text-muted);font-size:0.7rem;padding:0.2rem 0.5rem;border-radius:4px;">✉️ Standard Email</span>`;

        let actionHtml = '';
        if (msg.is_ingested) {
            actionHtml = `<span style="color:#10b981;font-weight:600;font-size:0.8rem;display:inline-flex;align-items:center;gap:0.35rem;background:rgba(16,185,129,0.1);padding:0.3rem 0.6rem;border-radius:4px;border:1px solid rgba(16,185,129,0.3);">
                ✅ Ingested (${msg.ingested_articles_count || 0} Stories)
            </span>`;
        } else if (hasAttachments) {
            actionHtml = `<button class="btn btn-xs btn-primary glow-button" style="background:#a855f7;border-color:#a855f7;font-size:0.75rem;padding:0.35rem 0.75rem;font-weight:600;" onclick="ingestRealEmailById('${msg.id}')">
                ⚡ Ingest & Extract
            </button>`;
        } else {
            actionHtml = `<span style="color:var(--text-muted);font-size:0.74rem;">(No attachments)</span>`;
        }

        return `
            <div class="real-inbox-item" style="background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.06);border-radius:var(--radius-sm);padding:0.9rem 1.1rem;transition:all 0.2s ease;">
                <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:0.75rem;margin-bottom:0.4rem;flex-wrap:wrap;">
                    <div style="display:flex;align-items:center;gap:0.5rem;flex-wrap:wrap;">
                        <span style="font-weight:700;color:var(--text-primary);font-size:0.88rem;">${escapeHtml(msg.sender)}</span>
                        ${ruleBadge}
                    </div>
                    <div style="font-size:0.75rem;color:var(--text-muted);white-space:nowrap;">
                        ${escapeHtml(msg.date)}
                    </div>
                </div>

                <div style="font-weight:600;color:#38bdf8;font-size:0.92rem;margin-bottom:0.35rem;line-height:1.4;">
                    ${escapeHtml(msg.subject || '(No Subject)')}
                </div>

                ${msg.snippet ? `<div style="font-size:0.8rem;color:var(--text-secondary);margin-bottom:0.55rem;line-height:1.45;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;">
                    ${escapeHtml(msg.snippet)}
                </div>` : ''}

                <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:0.6rem;padding-top:0.5rem;border-top:1px solid rgba(255,255,255,0.04);">
                    <div style="display:flex;align-items:center;gap:0.4rem;flex-wrap:wrap;">
                        ${hasAttachments ? `<span style="font-size:0.72rem;color:var(--text-muted);">Attachments:</span> ${attachmentBadges}` : '<span style="font-size:0.72rem;color:var(--text-muted);">Text message</span>'}
                    </div>
                    <div>
                        ${actionHtml}
                    </div>
                </div>
            </div>
        `;
    }).join('');
}

async function ingestRealEmailById(messageId) {
    if (!messageId) return;
    const statusBox = document.getElementById('inboxProcessingStatus');
    const statusText = document.getElementById('inboxProcessingStatusText');

    if (statusBox) statusBox.style.display = 'block';
    if (statusText) statusText.textContent = `Downloading attachments from email #${messageId}, running OCR & English translation...`;

    try {
        const res = await fetch(`/api/inbox/ingest-email/${messageId}`, { method: 'POST' });
        if (!res.ok) {
            const err = await res.json().catch(() => ({ detail: res.statusText }));
            throw new Error(err.detail || 'Email ingestion failed');
        }
        const data = await res.json();
        alert(`✅ Email #${messageId} Ingested Successfully!\n\nSubject: ${data.subject}\nArticles Extracted: ${data.articles_count}\nAuto-Translated: ${data.translated_count}\nStories pushed to news pipeline & digital twin audit trail!`);
        
        // Refresh both views
        await Promise.all([
            fetchRealInboxMessages(),
            fetchInboxStatusAndClippings()
        ]);

        // Automatically switch tab to Ingested Clippings
        switchInboxTab('ingested');

    } catch (e) {
        alert(`❌ Email Ingestion Failed: ${e.message}`);
    } finally {
        if (statusBox) statusBox.style.display = 'none';
    }
}

function switchInboxTab(tabName) {
    const tabReal = document.getElementById('tabRealInboxBtn');
    const tabIngested = document.getElementById('tabIngestedClippingsBtn');
    const viewReal = document.getElementById('realInboxView');
    const viewIngested = document.getElementById('ingestedClippingsView');

    if (tabName === 'real') {
        if (tabReal) tabReal.classList.add('active');
        if (tabIngested) tabIngested.classList.remove('active');
        if (viewReal) viewReal.style.display = 'block';
        if (viewIngested) viewIngested.style.display = 'none';
    } else {
        if (tabReal) tabReal.classList.remove('active');
        if (tabIngested) tabIngested.classList.add('active');
        if (viewReal) viewReal.style.display = 'none';
        if (viewIngested) viewIngested.style.display = 'block';
    }
}

function filterRealInbox(query) {
    if (!state.realInboxMessages) return;
    const q = (query || '').toLowerCase().trim();
    if (!q) {
        renderRealInboxMessages(state.realInboxMessages);
        return;
    }
    const filtered = state.realInboxMessages.filter(m => 
        (m.sender && m.sender.toLowerCase().includes(q)) ||
        (m.subject && m.subject.toLowerCase().includes(q)) ||
        (m.snippet && m.snippet.toLowerCase().includes(q))
    );
    renderRealInboxMessages(filtered);
}

async function handleCheckInboxNow() {
    const checkBtn = document.getElementById('btnCheckInboxNow');
    const statusBox = document.getElementById('inboxProcessingStatus');
    const statusText = document.getElementById('inboxProcessingStatusText');

    if (checkBtn) checkBtn.disabled = true;
    if (statusBox) statusBox.style.display = 'block';
    if (statusText) statusText.textContent = 'Connecting to IMAP inbox and checking for matching emails...';

    try {
        const res = await fetch('/api/inbox/check', { method: 'POST' });
        if (!res.ok) {
            const err = await res.json().catch(() => ({ detail: res.statusText }));
            throw new Error(err.detail || 'Inbox check failed');
        }

        const data = await res.json();
        alert(`📬 Inbox Scan Completed!\n\nChecked: ${data.checked_count} emails\nMatched Rules: ${data.matched_count} emails\nIngested Clippings: ${data.ingested_count}`);
        await fetchInboxStatusAndClippings();

    } catch (e) {
        alert(`❌ Inbox Check Failed: ${e.message}`);
    } finally {
        if (checkBtn) checkBtn.disabled = false;
        if (statusBox) statusBox.style.display = 'none';
    }
}

async function handleSimulateClipping() {
    const simBtn = document.getElementById('btnSimulateClipping');
    const statusBox = document.getElementById('inboxProcessingStatus');
    const statusText = document.getElementById('inboxProcessingStatusText');

    if (simBtn) simBtn.disabled = true;
    if (statusBox) statusBox.style.display = 'block';
    if (statusText) statusText.textContent = 'Simulating incoming email from cuttyknowledge2006@gmail.com, running OCR, translating, and pushing to pipeline...';

    try {
        const res = await fetch('/api/inbox/simulate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                sender: 'cuttyknowledge2006@gmail.com',
                subject: 'Regional Newspaper Clipping - Special Edition',
            }),
        });

        if (!res.ok) {
            const err = await res.json().catch(() => ({ detail: res.statusText }));
            throw new Error(err.detail || 'Simulation failed');
        }

        const data = await res.json();
        alert(`✅ Simulated Clipping Ingested!\n\nSender: ${data.sender}\nSubject: ${data.subject}\nStories Extracted: ${data.articles_count}\nAll regional stories auto-translated to English and pushed to main pipeline!`);
        await fetchInboxStatusAndClippings();

    } catch (e) {
        alert(`❌ Simulation Failed: ${e.message}`);
    } finally {
        if (simBtn) simBtn.disabled = false;
        if (statusBox) statusBox.style.display = 'none';
    }
}

async function handleDirectUploadClipping(file) {
    if (!file) return;
    const statusBox = document.getElementById('inboxProcessingStatus');
    const statusText = document.getElementById('inboxProcessingStatusText');

    if (statusBox) statusBox.style.display = 'block';
    if (statusText) statusText.textContent = `Uploading and ingesting clipping ${file.name}... running OCR & English translation...`;

    const formData = new FormData();
    formData.append('file', file);
    formData.append('sender', 'bureau@chennai.com');
    formData.append('subject', `Uploaded Clipping: ${file.name}`);

    try {
        const res = await fetch('/api/inbox/upload-clipping', {
            method: 'POST',
            body: formData,
        });

        if (!res.ok) {
            const err = await res.json().catch(() => ({ detail: res.statusText }));
            throw new Error(err.detail || 'Clipping upload failed');
        }

        const data = await res.json();
        alert(`✅ Clipping Ingested Successfully!\n\nFile: ${data.attachment_filename}\nStories Extracted: ${data.articles_count}\nAuto-Translated: ${data.translated_count}\nPushed to news pipeline and digital twin audit trail!`);
        await fetchInboxStatusAndClippings();

    } catch (e) {
        alert(`❌ Clipping Ingestion Failed: ${e.message}`);
    } finally {
        if (statusBox) statusBox.style.display = 'none';
    }
}

async function handleRunEmailDiagnostics() {
    const diagBox = document.getElementById('emailDiagnosticsBox');
    const container = document.getElementById('emailDiagnosticsContent');
    const btn = document.getElementById('btnRunEmailDiagnostics');

    if (btn) btn.disabled = true;
    if (diagBox) diagBox.style.display = 'block';
    if (container) container.innerHTML = `<div class="spinner" style="margin:1rem auto;border-top-color:#f59e0b;"></div><div style="text-align:center;font-size:0.8rem;color:#f59e0b;">Testing Gmail SMTP SSL & Gmail IMAP SSL connections...</div>`;

    try {
        const res = await fetch('/api/email/diagnostics');
        const data = await res.json();

        const smtpOk = data.smtp && data.smtp.success;
        const imapOk = data.imap && data.imap.success;

        container.innerHTML = `
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:0.75rem;margin-bottom:0.75rem;">
                <div style="background:rgba(0,0,0,0.2);padding:0.75rem;border-radius:var(--radius-sm);border-left:3px solid ${smtpOk ? '#10b981' : '#ef4444'};">
                    <div style="font-weight:700;color:${smtpOk ? '#10b981' : '#ef4444'};margin-bottom:0.25rem;">
                        ${smtpOk ? '✅' : '❌'} OUTBOUND: Gmail SMTP SSL
                    </div>
                    <div>Host: <code>${data.smtp?.host}:${data.smtp?.port}</code></div>
                    <div>User: <code>${data.smtp?.user}</code></div>
                    <div>Latency: <strong>${data.smtp?.latency_ms ? data.smtp.latency_ms + 'ms' : 'N/A'}</strong></div>
                    <div>Status: <strong>${data.smtp?.status?.toUpperCase()}</strong></div>
                    ${data.smtp?.error ? `<div style="color:#ef4444;font-size:0.75rem;">Error: ${data.smtp.error}</div>` : ''}
                </div>

                <div style="background:rgba(0,0,0,0.2);padding:0.75rem;border-radius:var(--radius-sm);border-left:3px solid ${imapOk ? '#a855f7' : '#ef4444'};">
                    <div style="font-weight:700;color:${imapOk ? '#a855f7' : '#ef4444'};margin-bottom:0.25rem;">
                        ${imapOk ? '✅' : '❌'} INBOUND: Gmail IMAP SSL
                    </div>
                    <div>Host: <code>${data.imap?.host}:${data.imap?.port}</code></div>
                    <div>User: <code>${data.imap?.user}</code></div>
                    <div>Total Messages: <strong>${data.imap?.total_messages || 0}</strong></div>
                    <div>Latency: <strong>${data.imap?.latency_ms ? data.imap.latency_ms + 'ms' : 'N/A'}</strong></div>
                    ${data.imap?.error ? `<div style="color:#ef4444;font-size:0.75rem;">Error: ${data.imap.error}</div>` : ''}
                </div>
            </div>

            <div style="background:rgba(255,255,255,0.02);padding:0.6rem 0.8rem;border-radius:var(--radius-sm);border:1px solid rgba(255,255,255,0.05);font-size:0.76rem;">
                <div><strong>Monitored Senders:</strong> <code>${(data.sender_rules || []).join(', ')}</code></div>
                <div style="margin-top:0.2rem;"><strong>Subject Keywords:</strong> <code>${(data.subject_keywords || []).join(', ')}</code></div>
                <div style="margin-top:0.2rem;"><strong>Inbox Auto-Scan Interval:</strong> Every ${data.check_interval_minutes} minutes</div>
            </div>
        `;

    } catch (e) {
        if (container) container.innerHTML = `<div style="color:#ef4444;padding:0.5rem;">❌ Diagnostic error: ${e.message}</div>`;
    } finally {
        if (btn) btn.disabled = false;
    }
}


function renderInboxClippings(clippings) {
    const container = document.getElementById('inboxClippingsContainer');
    if (!container) return;

    if (!clippings || clippings.length === 0) {
        container.innerHTML = `
            <div class="empty-state" style="padding:2rem;">
                <div style="font-size:2.5rem;margin-bottom:0.5rem;">📬</div>
                <h3>No clippings ingested yet</h3>
                <p class="text-secondary">Incoming emails matching <strong>bureau@chennai.com</strong> or subject <strong>"clipping"</strong> will automatically appear here with OCR and English translations. You can also click <strong>"Test Simulation"</strong> above.</p>
            </div>
        `;
        return;
    }

    const categoryBadges = {
        sports: { label: '🏆 Sports', class: 'cat-badge-sports' },
        business: { label: '💼 Business', class: 'cat-badge-business' },
        economic: { label: '📈 Economic', class: 'cat-badge-economic' },
        political: { label: '🏛️ Political', class: 'cat-badge-political' },
        crises_disasters: { label: '🚨 Crises & Disasters', class: 'cat-badge-crises' },
        all: { label: '📰 Ingested Story', class: 'cat-badge-all' },
    };

    container.innerHTML = clippings.map(clip => {
        const storiesHtml = (clip.articles || []).map(art => {
            const badgeInfo = categoryBadges[art.category] || categoryBadges.all;
            const transBadge = art.is_translated
                ? `<span class="news-translated-badge">🌐 Translated from ${art.original_language || 'Regional'}</span>`
                : '';
            const origSubtitle = art.is_translated && art.original_title
                ? `<div class="article-original-title">📖 <em>Original:</em> ${art.original_title}</div>`
                : '';

            return `
                <div style="background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.06);border-radius:var(--radius-sm);padding:0.75rem 1rem;margin-top:0.5rem;">
                    <div style="display:flex;align-items:center;gap:0.4rem;margin-bottom:0.35rem;flex-wrap:wrap;">
                        <span class="news-cat-badge ${badgeInfo.class}">${badgeInfo.label}</span>
                        ${transBadge}
                    </div>
                    <div style="font-size:0.9rem;font-weight:700;color:var(--text-primary);margin-bottom:0.25rem;">
                        ${art.title}
                    </div>
                    ${origSubtitle}
                    ${art.snippet ? `<p style="font-size:0.78rem;color:var(--text-secondary);margin:0.25rem 0 0 0;line-height:1.4;">${art.snippet}</p>` : ''}
                    <div style="display:flex;justify-content:space-between;align-items:center;margin-top:0.6rem;padding-top:0.4rem;border-top:1px solid rgba(255,255,255,0.06);">
                        <div style="font-size:0.74rem;color:var(--text-muted);">
                            OCR: <strong>${Math.round((art.ocr_confidence || 0.98)*100)}%</strong> • Trans: <strong>${Math.round((art.translation_confidence || 1.0)*100)}%</strong>
                        </div>
                        <button class="btn btn-xs btn-outline" style="border-color:rgba(245,158,11,0.5);color:#f59e0b;" onclick="openAuditModalForArticle('${art.id}')">
                            🔍 Digital Twin Traceability
                        </button>
                    </div>
                </div>
            `;
        }).join('');

        return `
            <div class="news-article-card" style="padding:1.25rem;">
                <div class="article-top-row" style="margin-bottom:0.5rem;">
                    <div style="display:flex;align-items:center;gap:0.5rem;flex-wrap:wrap;">
                        <span class="live-pill" style="font-size:0.72rem;background:rgba(168,85,247,0.15);border-color:rgba(168,85,247,0.4);color:#a855f7;">
                            📬 Rule: ${clip.rule_matched}
                        </span>
                        <span style="font-size:0.75rem;color:var(--text-muted);">
                            👤 ${clip.sender}
                        </span>
                    </div>
                    <span class="article-date">🕒 ${clip.date || 'Recent'}</span>
                </div>
                <h4 style="margin:0 0 0.5rem 0;color:var(--text-primary);font-size:1rem;">
                    ${clip.subject}
                </h4>
                <div style="display:flex;align-items:center;gap:0.75rem;font-size:0.78rem;color:var(--text-secondary);margin-bottom:0.75rem;">
                    <span>📎 Attachment: <code>${clip.attachment_filename}</code></span>
                    <span>•</span>
                    <span>🗞️ ${clip.articles_count} Stories Extracted via OCR</span>
                </div>
                <div>${storiesHtml}</div>
            </div>
        `;
    }).join('');
}


// --------------------------------------------------------------------------
// Digital Twin Traceability, Audit Console & Dispute Resolution
// --------------------------------------------------------------------------
state.alerts = [];
state.currentAuditId = null;

async function fetchDigitalTwinAlerts() {
    try {
        const res = await fetch('/api/alerts');
        if (!res.ok) return;
        const alerts = await res.json();
        state.alerts = alerts || [];

        // Update nav badge
        const navBadge = document.getElementById('navAlertsCount');
        if (navBadge) navBadge.textContent = state.alerts.length;

        // Update alerts ticker strip
        const tickerSection = document.getElementById('alertsTickerSection');
        const tickerText = document.getElementById('alertsTickerText');

        if (tickerSection && tickerText) {
            if (state.alerts.length > 0) {
                const latest = state.alerts[0];
                tickerSection.style.display = 'block';
                tickerText.innerHTML = `<strong>[${latest.topic}]</strong> ${latest.translated_text} <span style="font-size:0.75rem;color:var(--text-muted);">(${latest.source_name})</span>`;
            } else {
                tickerSection.style.display = 'none';
            }
        }
    } catch (e) {
        console.error('Error fetching alerts:', e);
    }
}

async function openAuditModal(targetId = null) {
    const modal = document.getElementById('auditTraceabilityModal');
    if (!modal) return;
    modal.classList.add('open');

    // Refresh alerts
    await fetchDigitalTwinAlerts();

    let record = null;

    if (targetId) {
        try {
            const res = await fetch(`/api/traceability/${targetId}`);
            if (res.ok) record = await res.json();
        } catch (e) {
            console.error('Failed to fetch specific traceability record:', e);
        }
    }

    // Default to first alert or first uploaded newspaper article
    if (!record && state.alerts.length > 0) {
        record = state.alerts[0];
    }
    if (!record && window.hardcopyState && window.hardcopyState.articles && window.hardcopyState.articles.length > 0) {
        const hArt = window.hardcopyState.articles[0];
        record = {
            id: hArt.id,
            source_name: hArt.newspaper || 'Uploaded Regional Newspaper',
            topic: hArt.headline_english || hArt.title,
            translated_text: hArt.headline_english || hArt.title,
            summary: hArt.content_english || hArt.snippet,
            ocr_raw_text: hArt.ocr_raw_text || (hArt.headline_original + '\n\n' + (hArt.content_original || '')),
            ocr_confidence: hArt.ocr_confidence || 0.96,
            translation_confidence: 0.95,
            needs_review: hArt.is_low_confidence || false,
            preserved_entities: hArt.preserved_entities || [],
            page_number: hArt.page_number || 1,
            page_snapshot_url: hArt.page_snapshot_url || '/api/snapshots/sample/1',
        };
    }

    if (record) {
        populateAuditModal(record);
    }

    renderAuditAlertsList();
}

function closeAuditModal() {
    const modal = document.getElementById('auditTraceabilityModal');
    if (modal) modal.classList.remove('open');
}

function populateAuditModal(record) {
    state.currentAuditId = record.id || record.article_id;

    // Badges & Meta
    const sevBadge = document.getElementById('auditSeverityBadge');
    if (sevBadge) {
        const sev = (record.severity || 'high').toUpperCase();
        sevBadge.textContent = `🚨 ${sev} PRIORITY`;
        sevBadge.style.background = sev === 'CRITICAL' ? '#ef4444' : '#f59e0b';
    }

    const srcBadge = document.getElementById('auditSourceBadge');
    if (srcBadge) srcBadge.textContent = record.source_name || 'Newspaper Publication';

    const dateBadge = document.getElementById('auditDateBadge');
    if (dateBadge) dateBadge.textContent = `Page ${record.page_number || 1}`;

    // Entities Container
    const entContainer = document.getElementById('auditEntitiesContainer');
    if (entContainer) {
        const entities = record.preserved_entities || ['PayU', 'Nirmala Sitharaman'];
        entContainer.innerHTML = entities.map(e => `
            <span class="badge" style="background:rgba(16,185,129,0.15);color:#10b981;border:1px solid rgba(16,185,129,0.3);font-size:0.75rem;">
                🔒 Preserved: ${e}
            </span>
        `).join('');
    }

    // Tier 1: Translated Text
    const titleEl = document.getElementById('auditTranslatedTitle');
    if (titleEl) titleEl.textContent = record.translated_text || record.title || 'Translated Story';

    const snippetEl = document.getElementById('auditTranslatedSnippet');
    if (snippetEl) snippetEl.textContent = record.summary || record.snippet || '';

    const transConfEl = document.getElementById('auditTransConfidence');
    if (transConfEl) {
        const confVal = Math.round((record.translation_confidence || 0.98) * 100);
        transConfEl.textContent = `${confVal}% Confidence`;
    }

    const reviewBanner = document.getElementById('auditNeedsReviewBanner');
    if (reviewBanner) {
        reviewBanner.style.display = record.needs_review ? 'block' : 'none';
    }

    // Tier 2: OCR Ground Truth
    const ocrConfEl = document.getElementById('auditOCRConfidence');
    if (ocrConfEl) {
        const ocrConfVal = Math.round((record.ocr_confidence || 0.99) * 100);
        ocrConfEl.textContent = `${ocrConfVal}% Confidence`;
    }

    const ocrTextEl = document.getElementById('auditOCRRawText');
    if (ocrTextEl) ocrTextEl.textContent = record.ocr_raw_text || 'OCR ground truth not recorded.';

    // Tier 3: Original Page Snapshot (Real Newspaper)
    const snapImg = document.getElementById('auditSnapshotImage');
    const snapLink = document.getElementById('auditSnapshotLink');
    const snapUrl = record.page_snapshot_url || '/api/snapshots/sample/1';

    if (snapImg) {
        snapImg.src = snapUrl;
        snapImg.onerror = () => {
            snapImg.src = '/api/snapshots/sample/1';
        };
    }
    if (snapLink) snapLink.href = snapUrl;

    const pageInd = document.getElementById('auditPageIndicator');
    if (pageInd) pageInd.textContent = `${record.source_name || 'Original Newspaper'} (Page ${record.page_number || 1})`;

    // Dispute Input
    const editInput = document.getElementById('auditEditTranslationInput');
    if (editInput) editInput.value = record.translated_text || '';
}

// --------------------------------------------------------------------------
// Original Newspaper Switcher for Digital Twin
// --------------------------------------------------------------------------
state.currentSnapshotPaper = 'the_hindu';
state.currentSnapshotPage = 1;

function switchOriginalNewspaper(paperKey, pageNum = 1) {
    state.currentSnapshotPaper = paperKey;
    state.currentSnapshotPage = pageNum;

    // Update active pill button
    const hinduBtn = document.getElementById('btnSnapHindu');
    const toiBtn = document.getElementById('btnSnapTOI');
    const regBtn = document.getElementById('btnSnapRegional');

    if (hinduBtn) hinduBtn.classList.toggle('active', paperKey === 'the_hindu');
    if (toiBtn) toiBtn.classList.toggle('active', paperKey === 'toi');
    if (regBtn) regBtn.classList.toggle('active', paperKey === 'sample_doc' || paperKey === 'sample');

    const snapUrl = `/api/snapshots/${paperKey}/${pageNum}`;
    const snapImg = document.getElementById('auditSnapshotImage');
    const snapLink = document.getElementById('auditSnapshotLink');
    const pageInd = document.getElementById('auditPageIndicator');

    if (snapImg) snapImg.src = snapUrl;
    if (snapLink) snapLink.href = snapUrl;

    const paperNames = {
        the_hindu: 'The Hindu (Chennai BroadSheet)',
        toi: 'The Times of India (Delhi Print)',
        sample_doc: 'Dainik Bhaskar / Regional Print',
        sample: 'The Hindu Print Archive',
    };
    if (pageInd) pageInd.textContent = `${paperNames[paperKey] || 'Original Print'} (Page ${pageNum})`;
}

function changeSnapshotPage(pageNum) {
    switchOriginalNewspaper(state.currentSnapshotPaper || 'the_hindu', pageNum);
}

function renderAuditAlertsList() {
    const container = document.getElementById('auditAlertsListContainer');
    if (!container) return;

    if (!state.alerts || state.alerts.length === 0) {
        container.innerHTML = `
            <div style="padding:1rem;background:rgba(255,255,255,0.02);border-radius:var(--radius-sm);color:var(--text-muted);font-size:0.82rem;text-align:center;">
                No active critical alerts right now. Ingested newspaper stories from TOI, Dainik Bhaskar, or email clippings will automatically populate here.
            </div>
        `;
        return;
    }

    container.innerHTML = state.alerts.map(a => `
        <div style="background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.08);border-radius:var(--radius-sm);padding:0.75rem 1rem;display:flex;justify-content:space-between;align-items:center;gap:1rem;flex-wrap:wrap;">
            <div style="flex:1;">
                <div style="display:flex;align-items:center;gap:0.5rem;margin-bottom:0.25rem;">
                    <span class="badge" style="background:${a.severity === 'critical' ? 'rgba(239,68,68,0.2)' : 'rgba(245,158,11,0.2)'};color:${a.severity === 'critical' ? '#ef4444' : '#f59e0b'};">
                        ${(a.severity || 'high').toUpperCase()}
                    </span>
                    <strong style="color:var(--text-primary);font-size:0.88rem;">${a.topic}</strong>
                    <span style="font-size:0.75rem;color:var(--text-muted);">• ${a.source_name} (Page ${a.page_number})</span>
                </div>
                <div style="font-size:0.82rem;color:var(--text-secondary);line-height:1.4;">
                    ${a.translated_text}
                </div>
            </div>
            <div style="display:flex;align-items:center;gap:0.5rem;flex-wrap:wrap;">
                <button class="btn btn-xs" style="background:#25D366;color:#ffffff;border:none;font-weight:600;display:inline-flex;align-items:center;gap:4px;padding:4px 9px;border-radius:4px;" onclick="sendAlertToWhatsApp('${a.id}', event)">
                    💬 Send to WhatsApp
                </button>
                <button class="btn btn-xs btn-outline" style="border-color:rgba(56,189,248,0.5);color:#38bdf8;" onclick="openAuditModal('${a.id}')">
                    Inspect 3-Tier Traceability ➔
                </button>
            </div>
        </div>
    `).join('');
}

async function sendAlertToWhatsApp(alertId, event) {
    if (event) {
        event.stopPropagation();
    }
    const btn = event ? event.currentTarget : null;
    const originalText = btn ? btn.innerHTML : '';
    if (btn) {
        btn.disabled = true;
        btn.innerHTML = '⏳ Sending...';
    }

    try {
        const res = await fetch(`/api/alerts/${encodeURIComponent(alertId)}/share/whatsapp`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({})
        });
        const data = await res.json();
        if (res.ok && data.success) {
            alert(`✅ Selected alert successfully sent to WhatsApp!\n\nHeadline: ${data.headline || alertId}\nRecipients: ${data.recipients_count}`);
        } else {
            alert(`❌ Failed to send alert to WhatsApp: ${data.detail || data.error || 'Unknown error'}`);
        }
    } catch (e) {
        alert(`❌ WhatsApp send error: ${e.message}`);
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = originalText;
        }
    }
}

async function sendCurrentAuditAlertToWhatsApp() {
    if (!state.currentAuditId) {
        alert('No active alert selected to send.');
        return;
    }
    await sendAlertToWhatsApp(state.currentAuditId);
}

async function sendLatestAlertToWhatsApp() {
    if (state.alerts && state.alerts.length > 0) {
        await sendAlertToWhatsApp(state.alerts[0].id);
    } else {
        alert('No active alerts available to send.');
    }
}

function openAuditModalForArticle(artId) {
    openAuditModal(artId);
}

async function handleApproveTranslation() {
    if (!state.currentAuditId) return;
    try {
        const res = await fetch(`/api/traceability/${state.currentAuditId}/review`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ audit_verdict: 'verified' }),
        });
        if (res.ok) {
            alert('✅ Translation and 3-Tier Traceability Audit Verified & Approved!');
            const reviewBanner = document.getElementById('auditNeedsReviewBanner');
            if (reviewBanner) reviewBanner.style.display = 'none';
        }
    } catch (e) {
        alert(`Failed to approve: ${e.message}`);
    }
}

async function handleUpdateTranslation() {
    if (!state.currentAuditId) return;
    const input = document.getElementById('auditEditTranslationInput');
    const newText = input ? input.value.trim() : '';

    if (!newText) {
        alert('Please enter updated translated text.');
        return;
    }

    try {
        const res = await fetch(`/api/traceability/${state.currentAuditId}/review`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                updated_translation: newText,
                audit_verdict: 'verified',
            }),
        });
        if (res.ok) {
            alert('✏️ Translation Updated & Editorial Audit Logged Successfully!');
            const titleEl = document.getElementById('auditTranslatedTitle');
            if (titleEl) titleEl.textContent = newText;
            const reviewBanner = document.getElementById('auditNeedsReviewBanner');
            if (reviewBanner) reviewBanner.style.display = 'none';
            await fetchDigitalTwinAlerts();
        }
    } catch (e) {
        alert(`Failed to update translation: ${e.message}`);
    }
}

async function handleFlagDispute() {
    if (!state.currentAuditId) return;
    try {
        const res = await fetch(`/api/traceability/${state.currentAuditId}/review`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ audit_verdict: 'disputed' }),
        });
        if (res.ok) {
            alert('⚠️ Audit Record Marked as Disputed. Sent to senior editorial queue.');
            const reviewBanner = document.getElementById('auditNeedsReviewBanner');
            if (reviewBanner) {
                reviewBanner.style.display = 'block';
                reviewBanner.textContent = '⚠️ Translation Disputed by Editorial Reviewer';
            }
        }
    } catch (e) {
        alert(`Failed to flag dispute: ${e.message}`);
    }
}

// --------------------------------------------------------------------------
// Master Event Listeners Setup
// --------------------------------------------------------------------------
function setupEventListeners() {
    // 1. Digital Twin Audit & Traceability Modal
    const btnOpenAudit = document.getElementById('btnOpenAuditModal');
    if (btnOpenAudit) btnOpenAudit.addEventListener('click', () => openAuditModal());

    const btnCloseAudit = document.getElementById('btnCloseAuditModal');
    if (btnCloseAudit) btnCloseAudit.addEventListener('click', closeAuditModal);

    const btnViewActiveAlert = document.getElementById('btnViewActiveAlert');
    if (btnViewActiveAlert) btnViewActiveAlert.addEventListener('click', () => openAuditModal());

    const btnApprove = document.getElementById('btnApproveTranslation');
    if (btnApprove) btnApprove.addEventListener('click', handleApproveTranslation);

    const btnUpdate = document.getElementById('btnUpdateTranslation');
    if (btnUpdate) btnUpdate.addEventListener('click', handleUpdateTranslation);

    const btnDispute = document.getElementById('btnFlagDispute');
    if (btnDispute) btnDispute.addEventListener('click', handleFlagDispute);

    // 2. Main Newspaper Languages Filter Buttons
    document.querySelectorAll('#languageFilters .filter-pill').forEach(pill => {
        pill.addEventListener('click', () => {
            document.querySelectorAll('#languageFilters .filter-pill').forEach(p => p.classList.remove('active'));
            pill.classList.add('active');
            const lang = pill.dataset.lang || 'all';
            state.selectedLanguage = lang.toLowerCase();
            renderSources();
        });
    });

    // 3. Main Catalog Source Search Input
    const sourceSearchInput = document.getElementById('sourceSearchInput');
    if (sourceSearchInput) {
        sourceSearchInput.addEventListener('input', (e) => {
            state.searchQuery = e.target.value.trim();
            renderSources();
        });
        sourceSearchInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                const q = (state.searchQuery || '').trim();
                if (q) {
                    const matchedSources = state.sources.filter(s =>
                        s.name.toLowerCase().includes(q.toLowerCase()) ||
                        s.language.toLowerCase().includes(q.toLowerCase()) ||
                        s.id.toLowerCase().includes(q.toLowerCase())
                    );
                    if (matchedSources.length === 0) {
                        triggerKeywordSearch(q);
                    }
                }
            }
        });
    }

    // 4. Global Keyword News Search Strip
    const btnRunKeywordSearch = document.getElementById('btnRunKeywordSearch');
    const globalKeywordSearchInput = document.getElementById('globalKeywordSearchInput');
    const globalKeywordSourceSelect = document.getElementById('globalKeywordSourceSelect');

    const executeGlobalKeywordSearch = () => {
        const query = globalKeywordSearchInput ? globalKeywordSearchInput.value.trim() : '';
        const sourceId = globalKeywordSourceSelect ? globalKeywordSourceSelect.value : null;
        if (query) triggerKeywordSearch(query, sourceId);
    };

    if (btnRunKeywordSearch) {
        btnRunKeywordSearch.addEventListener('click', executeGlobalKeywordSearch);
    }
    if (globalKeywordSearchInput) {
        globalKeywordSearchInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') executeGlobalKeywordSearch();
        });
    }
    if (globalKeywordSourceSelect) {
        globalKeywordSourceSelect.addEventListener('change', () => {
            const query = globalKeywordSearchInput ? globalKeywordSearchInput.value.trim() : '';
            if (query) executeGlobalKeywordSearch();
        });
    }

    // 5. Newspaper Categorized News Modal Controls
    const btnCloseNews = document.getElementById('btnCloseNewsModal');
    if (btnCloseNews) btnCloseNews.addEventListener('click', closeNewsModal);

    // News Modal Category Buttons (All Stories, Sports, Business, Economic, Political, Crises)
    document.querySelectorAll('#newsCategoriesBar .news-cat-pill').forEach(pill => {
        pill.addEventListener('click', () => {
            const cat = pill.dataset.cat;
            if (cat) switchNewsCategory(cat);
        });
    });

    // News Modal Email Digest Button
    const newsModalEmailBtn = document.getElementById('newsModalEmailBtn');
    if (newsModalEmailBtn) {
        newsModalEmailBtn.addEventListener('click', () => {
            openEmailModal(state.currentNewsCategory || 'all');
        });
    }

    // News Modal In-Paper Keyword Search
    const btnModalKeywordSearch = document.getElementById('btnModalKeywordSearch');
    const modalKeywordSearchInput = document.getElementById('modalKeywordSearchInput');
    const btnModalResetSearch = document.getElementById('btnModalResetSearch');
    if (btnModalKeywordSearch && modalKeywordSearchInput) {
        btnModalKeywordSearch.addEventListener('click', handleModalKeywordSearch);
        modalKeywordSearchInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') handleModalKeywordSearch();
        });
    }
    if (btnModalResetSearch) {
        btnModalResetSearch.addEventListener('click', resetModalSearch);
    }

    // 6. Inbox Modal
    const btnOpenInbox = document.getElementById('btnOpenInboxModal');
    if (btnOpenInbox) btnOpenInbox.addEventListener('click', openInboxModal);

    const btnCloseInbox = document.getElementById('btnCloseInboxModal');
    if (btnCloseInbox) btnCloseInbox.addEventListener('click', closeInboxModal);

    const tabRealInbox = document.getElementById('tabRealInboxBtn');
    if (tabRealInbox) tabRealInbox.addEventListener('click', () => switchInboxTab('real'));

    const tabIngestedClippings = document.getElementById('tabIngestedClippingsBtn');
    if (tabIngestedClippings) tabIngestedClippings.addEventListener('click', () => switchInboxTab('ingested'));

    const btnRefreshInbox = document.getElementById('btnRefreshRealInbox');
    if (btnRefreshInbox) btnRefreshInbox.addEventListener('click', () => fetchRealInboxMessages());

    const inboxSearchInput = document.getElementById('inboxSearchInput');
    if (inboxSearchInput) {
        inboxSearchInput.addEventListener('input', (e) => filterRealInbox(e.target.value));
    }

    const btnCheckInbox = document.getElementById('btnCheckInboxNow');
    if (btnCheckInbox) btnCheckInbox.addEventListener('click', handleCheckInboxNow);

    const btnSimulate = document.getElementById('btnSimulateClipping');
    if (btnSimulate) btnSimulate.addEventListener('click', handleSimulateClipping);

    const btnDirectUpload = document.getElementById('btnDirectUploadClipping');
    const directClippingInput = document.getElementById('directClippingFileInput');
    if (btnDirectUpload && directClippingInput) {
        btnDirectUpload.addEventListener('click', () => directClippingInput.click());
        directClippingInput.addEventListener('change', (e) => {
            if (e.target.files && e.target.files.length > 0) {
                handleDirectUploadClipping(e.target.files[0]);
            }
        });
    }

    const btnRunDiagnostics = document.getElementById('btnRunEmailDiagnostics');
    if (btnRunDiagnostics) btnRunDiagnostics.addEventListener('click', handleRunEmailDiagnostics);

    const btnCloseDiagnostics = document.getElementById('btnCloseDiagnosticsBox');
    if (btnCloseDiagnostics) {
        btnCloseDiagnostics.addEventListener('click', () => {
            const box = document.getElementById('emailDiagnosticsBox');
            if (box) box.style.display = 'none';
        });
    }

    // 7. Email Digest Modal Controls
    const btnOpenEmail = document.getElementById('btnOpenEmailModal');
    if (btnOpenEmail) btnOpenEmail.addEventListener('click', () => openEmailModal('all'));

    const btnCloseEmail = document.getElementById('btnCloseEmailModal');
    if (btnCloseEmail) btnCloseEmail.addEventListener('click', closeEmailModal);

    const btnCancelEmail = document.getElementById('btnCancelEmailModal');
    if (btnCancelEmail) btnCancelEmail.addEventListener('click', closeEmailModal);

    const btnSendEmail = document.getElementById('btnSendEmailDigestAction');
    if (btnSendEmail) btnSendEmail.addEventListener('click', handleSendEmailDigest);

    const btnPreviewEmail = document.getElementById('btnPreviewEmailDigest');
    if (btnPreviewEmail) btnPreviewEmail.addEventListener('click', handlePreviewEmailDigest);

    const btnClosePreview = document.getElementById('btnClosePreviewBox');
    if (btnClosePreview) {
        btnClosePreview.addEventListener('click', () => {
            const box = document.getElementById('emailDigestPreviewBox');
            if (box) box.style.display = 'none';
        });
    }

    const btnTestSmtp = document.getElementById('btnTestSmtpConnection');
    if (btnTestSmtp) btnTestSmtp.addEventListener('click', handleTestSmtpConnection);

    // Email Digest Category Selector Pills
    document.querySelectorAll('#emailCategorySelector .news-cat-pill').forEach(pill => {
        pill.addEventListener('click', () => {
            document.querySelectorAll('#emailCategorySelector .news-cat-pill').forEach(p => p.classList.remove('active'));
            pill.classList.add('active');
            state.selectedEmailCategory = pill.dataset.emailCat || 'all';
        });
    });


    // 8. Upload Hard Copy Modal Controls
    const btnOpenUpload = document.getElementById('btnOpenUploadModal');
    const uploadModal = document.getElementById('newspaperUploadModal') || document.getElementById('uploadHardCopyModal');
    const btnCloseUpload = document.getElementById('btnCloseUploadModal');

    if (btnOpenUpload && uploadModal) {
        btnOpenUpload.addEventListener('click', () => uploadModal.classList.add('open'));
    }
    if (btnCloseUpload && uploadModal) {
        btnCloseUpload.addEventListener('click', () => uploadModal.classList.remove('open'));
    }

    // Upload Categories Switcher Pills
    document.querySelectorAll('#uploadCategoriesBar .news-cat-pill').forEach(pill => {
        pill.addEventListener('click', () => {
            const cat = pill.dataset.uploadCat;
            if (cat) switchUploadCategory(cat);
        });
    });

    // Upload PDF Browse & Dropzone
    const btnBrowseFile = document.getElementById('btnBrowseFile');
    const newspaperFileInput = document.getElementById('newspaperFileInput');
    const uploadDropzone = document.getElementById('uploadDropzone');
    const btnUploadAnother = document.getElementById('btnUploadAnother');

    if (btnBrowseFile && newspaperFileInput) {
        btnBrowseFile.addEventListener('click', (e) => {
            e.stopPropagation();
            newspaperFileInput.click();
        });
    }
    if (uploadDropzone && newspaperFileInput) {
        uploadDropzone.addEventListener('click', (e) => {
            if (e.target !== btnBrowseFile) newspaperFileInput.click();
        });
        uploadDropzone.addEventListener('dragover', (e) => {
            e.preventDefault();
            uploadDropzone.classList.add('dragover');
        });
        uploadDropzone.addEventListener('dragleave', () => {
            uploadDropzone.classList.remove('dragover');
        });
        uploadDropzone.addEventListener('drop', (e) => {
            e.preventDefault();
            uploadDropzone.classList.remove('dragover');
            if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
                processUploadedFile(Array.from(e.dataTransfer.files));
            }
        });
    }
    if (newspaperFileInput) {
        newspaperFileInput.addEventListener('change', (e) => {
            if (e.target.files && e.target.files.length > 0) {
                processUploadedFile(Array.from(e.target.files));
            }
        });
    }
    if (btnUploadAnother) {
        btnUploadAnother.addEventListener('click', resetUploadView);
    }

    // 9. PDF Reader Modal
    const btnClosePdf = document.getElementById('btnClosePdfModal');
    if (btnClosePdf) {
        btnClosePdf.addEventListener('click', () => {
            const pdfModal = document.getElementById('pdfReaderModal') || document.getElementById('pdfPreviewModal');
            const iframe = document.getElementById('pdfPreviewIframe');
            if (iframe) iframe.src = 'about:blank';
            if (pdfModal) pdfModal.classList.remove('open');
        });
    }

    // 10. Cookie Auth Modal
    const btnOpenCookieModal = document.getElementById('btnOpenCookieImportModal');
    const btnCloseCookie = document.getElementById('btnCloseCookieModal');
    const btnCancelCookie = document.getElementById('btnCancelCookie');
    const cookieModal = document.getElementById('cookieImportModal') || document.getElementById('cookieModal');
    
    if (btnOpenCookieModal && cookieModal) {
        btnOpenCookieModal.addEventListener('click', () => cookieModal.classList.add('open'));
    }
    if (btnCloseCookie && cookieModal) {
        btnCloseCookie.addEventListener('click', () => cookieModal.classList.remove('open'));
    }
    if (btnCancelCookie && cookieModal) {
        btnCancelCookie.addEventListener('click', () => cookieModal.classList.remove('open'));
    }

    const saveCookieBtn = document.getElementById('btnSaveCookies');
    if (saveCookieBtn) {
        saveCookieBtn.addEventListener('click', async () => {
            const sourceSelect = document.getElementById('cookieSourceSelect');
            const sourceId = sourceSelect ? sourceSelect.value : '';
            const rawInput = document.getElementById('cookieRawInput');
            const rawText = rawInput ? rawInput.value.trim() : '';

            if (!rawText) {
                alert('Please paste cookie JSON or Netscape formatted text.');
                return;
            }

            try {
                saveCookieBtn.disabled = true;
                saveCookieBtn.textContent = 'Authenticating...';
                const res = await fetch('/api/sessions/import', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ source_id: sourceId, cookies_raw: rawText })
                });
                if (!res.ok) throw new Error(await res.text());
                const data = await res.json();
                alert(`Authentication Successful! Imported ${data.imported_cookies} cookies for ${sourceId}.`);
                if (rawInput) rawInput.value = '';
                if (cookieModal) cookieModal.classList.remove('open');
                fetchSessions();
            } catch (e) {
                alert('Authentication error: ' + e.message);
            } finally {
                saveCookieBtn.disabled = false;
                saveCookieBtn.textContent = 'Save & Authenticate';
            }
        });
    }

    // 11. Archives & Monitor Action Buttons
    const refreshArchBtn = document.getElementById('btnRefreshArchives');
    if (refreshArchBtn) {
        refreshArchBtn.addEventListener('click', () => {
            fetchArchives();
            const input = document.getElementById('archiveSearchInput');
            if (input) input.value = '';
        });
    }

    const archiveSearchInput = document.getElementById('archiveSearchInput');
    if (archiveSearchInput) {
        archiveSearchInput.addEventListener('input', (e) => {
            renderArchives(e.target.value.trim());
        });
    }

    const clearLogsBtn = document.getElementById('btnClearLogs');
    if (clearLogsBtn) {
        clearLogsBtn.addEventListener('click', () => {
            const term = document.getElementById('liveTerminalLogs');
            if (term) term.innerHTML = '<div class="log-entry system">[SYSTEM] Logs cleared. Scheduler running on Asia/Kolkata timezone.</div>';
        });
    }

    // 12. Top Header Actions: Batch Harvest & Purge
    const btnBatch = document.getElementById('btnBatchHarvest');
    if (btnBatch) btnBatch.addEventListener('click', triggerBatchHarvest);

    const btnPurge = document.getElementById('btnPurgeExpired');
    if (btnPurge) {
        btnPurge.addEventListener('click', async () => {
            if (!confirm('Run retention purge to delete expired archives older than policy?')) return;
            try {
                const res = await fetch('/api/harvest/retention/purge', { method: 'POST' });
                const d = await res.json();
                alert(`🧹 Retention Purge Completed: ${d.purged_count || 0} expired files cleaned.`);
                fetchArchives();
                fetchStorageStats();
            } catch(e) {
                alert('Purge error: ' + e.message);
            }
        });
    }

    // 12. Universal Close Listeners: ALL .btn-close buttons
    document.querySelectorAll('.btn-close').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            const parentModal = btn.closest('.modal-backdrop');
            if (parentModal) {
                parentModal.classList.remove('open');
            } else {
                document.querySelectorAll('.modal-backdrop.open').forEach(m => m.classList.remove('open'));
            }
        });
    });

    // 13. Universal Backdrop Click Listener: Click outside modal to close
    document.querySelectorAll('.modal-backdrop').forEach(backdrop => {
        backdrop.addEventListener('click', (e) => {
            if (e.target === backdrop) {
                backdrop.classList.remove('open');
            }
        });
    });

    // 14. Universal Keyboard Shortcut: Press Escape to close all open modals
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            document.querySelectorAll('.modal-backdrop.open').forEach(m => m.classList.remove('open'));
        }
    });

    // Initial alert fetch & background refresh
    fetchDigitalTwinAlerts();
    setInterval(fetchDigitalTwinAlerts, 30000);
}


