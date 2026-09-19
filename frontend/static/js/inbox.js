/**
 * ePaper Harvester 2.0 - Dedicated Inbox Automation & Clipping Management
 */

const inboxState = {
    realMessages: [],
    clippings: [],
    status: null,
    activeTab: 'real', // 'real' | 'ingested'
    currentSearch: '',
};

document.addEventListener('DOMContentLoaded', () => {
    initClock();
    initInboxTabs();
    initInboxControls();
    loadAllInboxData();
});

// Clock & Utilities
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

function escapeHtml(str) {
    if (!str) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

async function loadAllInboxData() {
    await Promise.all([
        fetchRealInboxMessages(),
        fetchClippingsData()
    ]);
}

// --------------------------------------------------------------------------
// Real IMAP Messages
// --------------------------------------------------------------------------
async function fetchRealInboxMessages() {
    const listContainer = document.getElementById('realInboxMessagesList');
    const metricTotal = document.getElementById('metricTotalEmails');
    const navCount = document.getElementById('navLiveInboxCount');
    const tabCount = document.getElementById('inboxLiveTabCount');
    const refreshBtn = document.getElementById('btnRefreshRealInbox');

    if (refreshBtn) refreshBtn.innerHTML = '🔄 Loading...';

    try {
        const res = await fetch('/api/inbox/messages?limit=40');
        if (!res.ok) {
            const err = await res.json().catch(() => ({ detail: res.statusText }));
            throw new Error(err.detail || 'Failed to fetch inbox messages');
        }
        const data = await res.json();
        inboxState.realMessages = data.messages || [];

        const totalCount = data.total_inbox || data.total_inbox_messages || inboxState.realMessages.length;
        if (metricTotal) metricTotal.textContent = totalCount;
        if (navCount) navCount.textContent = totalCount;
        if (tabCount) tabCount.textContent = totalCount;

        const accountDisplay = document.getElementById('inboxAccountDisplay');
        if (accountDisplay && data.account) accountDisplay.textContent = data.account;

        renderRealMessages(inboxState.realMessages);

    } catch (e) {
        console.error('Failed to load real inbox:', e);
        if (listContainer) {
            listContainer.innerHTML = `
                <div style="background:rgba(239,68,68,0.12);border:1px solid #ef4444;border-radius:var(--radius-md);padding:2rem;text-align:center;color:#ef4444;">
                    <div style="font-size:1.8rem;margin-bottom:0.5rem;">⚠️</div>
                    <div style="font-weight:700;font-size:1.1rem;margin-bottom:0.35rem;">Could not connect to Gmail IMAP SSL</div>
                    <p style="font-size:0.88rem;color:var(--text-secondary);max-width:550px;margin:0 auto 1rem auto;">${escapeHtml(e.message)}</p>
                    <button class="btn btn-sm btn-outline" style="border-color:#ef4444;color:#ef4444;" onclick="fetchRealInboxMessages()">Retry Connection</button>
                </div>
            `;
        }
    } finally {
        if (refreshBtn) refreshBtn.innerHTML = '🔄 Refresh';
    }
}

function renderRealMessages(messages) {
    const listContainer = document.getElementById('realInboxMessagesList');
    if (!listContainer) return;

    if (!messages || messages.length === 0) {
        listContainer.innerHTML = `
            <div style="background:rgba(15,23,42,0.5);border:1px solid rgba(255,255,255,0.06);border-radius:var(--radius-md);padding:3.5rem;text-align:center;">
                <div style="font-size:3rem;margin-bottom:0.75rem;">📭</div>
                <h3 style="color:var(--text-primary);margin-bottom:0.35rem;">No emails match criteria</h3>
                <p style="color:var(--text-secondary);font-size:0.9rem;">Try clearing the search query or clicking "Refresh" above.</p>
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
            return `<span style="display:inline-flex;align-items:center;gap:0.35rem;background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.14);padding:0.25rem 0.65rem;border-radius:6px;font-size:0.75rem;color:var(--text-primary);" title="${escapeHtml(att.filename)} (${sizeKb} KB)">
                <span>${icon}</span>
                <span style="max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-weight:600;">${escapeHtml(att.filename)}</span>
                <span style="color:var(--text-muted);font-size:0.7rem;">(${sizeKb} KB)</span>
            </span>`;
        }).join(' ');

        const ruleBadge = msg.is_rule_match
            ? `<span class="rule-badge-matched">⚡ RULE MATCHED (AUTO-ELIGIBLE)</span>`
            : `<span class="rule-badge-standard">✉️ STANDARD EMAIL</span>`;

        let actionHtml = '';
        if (msg.is_ingested) {
            actionHtml = `<span style="color:#10b981;font-weight:700;font-size:0.85rem;display:inline-flex;align-items:center;gap:0.4rem;background:rgba(16,185,129,0.12);padding:0.4rem 0.85rem;border-radius:6px;border:1px solid rgba(16,185,129,0.35);">
                ✅ Ingested (${msg.ingested_articles_count || 0} Stories)
            </span>`;
        } else if (hasAttachments) {
            actionHtml = `<button class="btn btn-sm btn-primary glow-button" style="background:#a855f7;border-color:#a855f7;font-weight:700;font-size:0.82rem;padding:0.4rem 0.95rem;" onclick="ingestRealEmailById('${msg.id}')">
                ⚡ Ingest & Extract Stories
            </button>`;
        } else {
            actionHtml = `<span style="color:var(--text-muted);font-size:0.8rem;background:rgba(255,255,255,0.03);padding:0.3rem 0.6rem;border-radius:4px;">No attachments</span>`;
        }

        return `
            <div class="inbox-item-card ${msg.is_rule_match ? 'rule-matched' : ''}">
                <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:1rem;margin-bottom:0.5rem;flex-wrap:wrap;">
                    <div style="display:flex;align-items:center;gap:0.65rem;flex-wrap:wrap;">
                        <span style="font-weight:700;color:var(--text-primary);font-size:0.95rem;">${escapeHtml(msg.sender)}</span>
                        ${ruleBadge}
                    </div>
                    <div style="font-size:0.8rem;color:var(--text-muted);white-space:nowrap;">
                        📅 ${escapeHtml(msg.date)}
                    </div>
                </div>

                <div style="font-weight:700;color:#38bdf8;font-size:1.05rem;margin-bottom:0.45rem;line-height:1.4;">
                    ${escapeHtml(msg.subject || '(No Subject)')}
                </div>

                ${msg.snippet ? `<div style="font-size:0.86rem;color:var(--text-secondary);margin-bottom:0.75rem;line-height:1.5;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;">
                    ${escapeHtml(msg.snippet)}
                </div>` : ''}

                <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:0.75rem;padding-top:0.65rem;border-top:1px solid rgba(255,255,255,0.06);">
                    <div style="display:flex;align-items:center;gap:0.5rem;flex-wrap:wrap;">
                        ${hasAttachments ? `<span style="font-size:0.78rem;color:var(--text-muted);font-weight:600;">Attachments:</span> ${attachmentBadges}` : '<span style="font-size:0.78rem;color:var(--text-muted);">Plain text message</span>'}
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
        
        await Promise.all([
            fetchRealInboxMessages(),
            fetchClippingsData()
        ]);

        switchInboxTab('ingested');

    } catch (e) {
        alert(`❌ Email Ingestion Failed: ${e.message}`);
    } finally {
        if (statusBox) statusBox.style.display = 'none';
    }
}

// --------------------------------------------------------------------------
// Ingested Clippings Feed
// --------------------------------------------------------------------------
async function fetchClippingsData() {
    try {
        const [statusRes, clippingsRes] = await Promise.all([
            fetch('/api/inbox/status').then(r => r.json()),
            fetch('/api/inbox/clippings').then(r => r.json()),
        ]);

        inboxState.clippings = clippingsRes || [];
        inboxState.status = statusRes;

        const metricClippings = document.getElementById('metricIngestedClippings');
        const tabCount = document.getElementById('inboxIngestedTabCount');
        const total = inboxState.clippings.length;
        if (metricClippings) metricClippings.textContent = total;
        if (tabCount) tabCount.textContent = total;

        renderClippingsFeed(inboxState.clippings);

    } catch (e) {
        console.error('Failed to fetch clippings:', e);
    }
}

function renderClippingsFeed(clippings) {
    const container = document.getElementById('inboxClippingsContainer');
    if (!container) return;

    if (!clippings || clippings.length === 0) {
        container.innerHTML = `
            <div style="background:rgba(15,23,42,0.5);border:1px solid rgba(255,255,255,0.06);border-radius:var(--radius-md);padding:3.5rem;text-align:center;">
                <div style="font-size:3rem;margin-bottom:0.75rem;">🗞️</div>
                <h3 style="color:var(--text-primary);margin-bottom:0.35rem;">No newspaper clippings ingested yet</h3>
                <p style="color:var(--text-secondary);font-size:0.9rem;max-width:550px;margin:0 auto 1.25rem auto;">
                    Incoming emails with newspaper attachments matching rules will automatically appear here with OCR and English translations. You can also click <strong>"Test Simulation"</strong> or <strong>"Ingest Local File"</strong> above.
                </p>
                <button class="btn btn-sm btn-outline" style="border-color:#38bdf8;color:#38bdf8;" onclick="handleSimulateClipping()">
                    🧪 Ingest Simulated Clipping
                </button>
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
                ? `<div class="article-original-title" style="margin-top:0.3rem;">📖 <em>Original:</em> ${escapeHtml(art.original_title)}</div>`
                : '';

            return `
                <div style="background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.06);border-radius:var(--radius-sm);padding:1rem 1.25rem;margin-top:0.75rem;">
                    <div style="display:flex;align-items:center;gap:0.5rem;margin-bottom:0.4rem;flex-wrap:wrap;">
                        <span class="news-cat-badge ${badgeInfo.class}">${badgeInfo.label}</span>
                        ${transBadge}
                    </div>
                    <div style="font-size:0.98rem;font-weight:700;color:var(--text-primary);margin-bottom:0.35rem;">
                        ${escapeHtml(art.title)}
                    </div>
                    ${origSubtitle}
                    ${art.snippet ? `<p style="font-size:0.84rem;color:var(--text-secondary);margin:0.4rem 0 0 0;line-height:1.5;">${escapeHtml(art.snippet)}</p>` : ''}
                    <div style="display:flex;justify-content:space-between;align-items:center;margin-top:0.75rem;padding-top:0.5rem;border-top:1px solid rgba(255,255,255,0.06);flex-wrap:wrap;gap:0.5rem;">
                        <div style="font-size:0.76rem;color:var(--text-muted);">
                            OCR Confidence: <strong>${Math.round((art.ocr_confidence || 0.98)*100)}%</strong> • Translation: <strong>${Math.round((art.translation_confidence || 1.0)*100)}%</strong>
                        </div>
                        <button class="btn btn-xs btn-outline" style="border-color:rgba(245,158,11,0.5);color:#f59e0b;" onclick="openAuditModalForClippingArticle('${clip.id}', '${art.id}')">
                            🔍 3-Tier Traceability
                        </button>
                    </div>
                </div>
            `;
        }).join('');

        return `
            <div style="background:rgba(15,23,42,0.75);border:1px solid rgba(255,255,255,0.08);border-radius:var(--radius-md);padding:1.5rem;">
                <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:0.75rem;flex-wrap:wrap;gap:0.75rem;">
                    <div>
                        <div style="font-size:0.78rem;color:var(--text-muted);margin-bottom:0.2rem;">
                            Ingested: <strong>${escapeHtml(clip.ingested_at || '')}</strong> • Sender: <strong>${escapeHtml(clip.sender || '')}</strong>
                        </div>
                        <h3 style="margin:0;font-size:1.15rem;color:#38bdf8;">${escapeHtml(clip.subject || '')}</h3>
                    </div>
                    <div style="display:flex;align-items:center;gap:0.5rem;">
                        <span class="badge badge-purple" style="font-size:0.78rem;">${clip.articles ? clip.articles.length : 0} Stories</span>
                        <span class="badge badge-cyan" style="font-size:0.78rem;">${escapeHtml(clip.attachment_filename || 'Attachment')}</span>
                    </div>
                </div>

                <div>
                    ${storiesHtml}
                </div>
            </div>
        `;
    }).join('');
}

// --------------------------------------------------------------------------
// Actions & Controls
// --------------------------------------------------------------------------
function initInboxTabs() {
    const tabReal = document.getElementById('tabRealInboxBtn');
    const tabIngested = document.getElementById('tabIngestedClippingsBtn');

    if (tabReal) tabReal.addEventListener('click', () => switchInboxTab('real'));
    if (tabIngested) tabIngested.addEventListener('click', () => switchInboxTab('ingested'));
}

function switchInboxTab(tabName) {
    inboxState.activeTab = tabName;
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

function initInboxControls() {
    const searchInput = document.getElementById('inboxSearchInput');
    if (searchInput) {
        searchInput.addEventListener('input', (e) => {
            const q = e.target.value.toLowerCase().trim();
            if (!q) {
                renderRealMessages(inboxState.realMessages);
                return;
            }
            const filtered = inboxState.realMessages.filter(m =>
                (m.sender && m.sender.toLowerCase().includes(q)) ||
                (m.subject && m.subject.toLowerCase().includes(q)) ||
                (m.snippet && m.snippet.toLowerCase().includes(q))
            );
            renderRealMessages(filtered);
        });
    }

    const refreshBtn = document.getElementById('btnRefreshRealInbox');
    if (refreshBtn) refreshBtn.addEventListener('click', fetchRealInboxMessages);

    const checkBtn = document.getElementById('btnCheckInboxNow');
    if (checkBtn) checkBtn.addEventListener('click', handleCheckInboxNow);

    const simBtn = document.getElementById('btnSimulateClipping');
    if (simBtn) simBtn.addEventListener('click', handleSimulateClipping);

    const directBtn = document.getElementById('btnDirectUploadClipping');
    const fileInput = document.getElementById('directClippingFileInput');
    if (directBtn && fileInput) {
        directBtn.addEventListener('click', () => fileInput.click());
        fileInput.addEventListener('change', (e) => {
            if (e.target.files && e.target.files.length > 0) {
                handleDirectUploadClipping(e.target.files[0]);
            }
        });
    }

    const diagBtn = document.getElementById('btnRunEmailDiagnostics');
    if (diagBtn) diagBtn.addEventListener('click', handleRunDiagnostics);

    const closeDiagBtn = document.getElementById('btnCloseDiagnosticsBox');
    if (closeDiagBtn) {
        closeDiagBtn.addEventListener('click', () => {
            const box = document.getElementById('emailDiagnosticsBox');
            if (box) box.style.display = 'none';
        });
    }

    const closeAuditBtn = document.getElementById('btnCloseAuditModal');
    if (closeAuditBtn) {
        closeAuditBtn.addEventListener('click', () => {
            const modal = document.getElementById('auditTraceabilityModal');
            if (modal) modal.classList.remove('open');
        });
    }
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
        await loadAllInboxData();

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
        await loadAllInboxData();
        switchInboxTab('ingested');

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
        await loadAllInboxData();
        switchInboxTab('ingested');

    } catch (e) {
        alert(`❌ Clipping Ingestion Failed: ${e.message}`);
    } finally {
        if (statusBox) statusBox.style.display = 'none';
    }
}

async function handleRunDiagnostics() {
    const diagBox = document.getElementById('emailDiagnosticsBox');
    const container = document.getElementById('emailDiagnosticsContent');
    const btn = document.getElementById('btnRunEmailDiagnostics');

    if (btn) btn.disabled = true;
    if (diagBox) diagBox.style.display = 'block';
    if (container) container.innerHTML = `<div class="spinner" style="margin:1rem auto;border-top-color:#f59e0b;"></div><div style="text-align:center;font-size:0.85rem;color:#f59e0b;">Testing Gmail SMTP SSL & Gmail IMAP SSL connections...</div>`;

    try {
        const res = await fetch('/api/email/diagnostics');
        const data = await res.json();

        const smtpOk = data.smtp && data.smtp.success;
        const imapOk = data.imap && data.imap.success;

        container.innerHTML = `
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:1rem;margin-bottom:1rem;">
                <div style="background:rgba(0,0,0,0.25);padding:1rem;border-radius:var(--radius-sm);border-left:3px solid ${smtpOk ? '#10b981' : '#ef4444'};">
                    <div style="font-weight:700;color:${smtpOk ? '#10b981' : '#ef4444'};margin-bottom:0.35rem;">
                        ${smtpOk ? '✅' : '❌'} OUTBOUND: Gmail SMTP SSL
                    </div>
                    <div>Host: <code>${data.smtp?.host}:${data.smtp?.port}</code></div>
                    <div>User: <code>${data.smtp?.user}</code></div>
                    <div>Latency: <strong>${data.smtp?.latency_ms ? data.smtp.latency_ms + 'ms' : 'N/A'}</strong></div>
                    <div>Status: <strong>${data.smtp?.status?.toUpperCase()}</strong></div>
                    ${data.smtp?.error ? `<div style="color:#ef4444;font-size:0.8rem;margin-top:0.25rem;">Error: ${data.smtp.error}</div>` : ''}
                </div>

                <div style="background:rgba(0,0,0,0.25);padding:1rem;border-radius:var(--radius-sm);border-left:3px solid ${imapOk ? '#a855f7' : '#ef4444'};">
                    <div style="font-weight:700;color:${imapOk ? '#a855f7' : '#ef4444'};margin-bottom:0.35rem;">
                        ${imapOk ? '✅' : '❌'} INBOUND: Gmail IMAP SSL
                    </div>
                    <div>Host: <code>${data.imap?.host}:${data.imap?.port}</code></div>
                    <div>User: <code>${data.imap?.user}</code></div>
                    <div>Total Messages: <strong>${data.imap?.total_messages || 0}</strong></div>
                    <div>Latency: <strong>${data.imap?.latency_ms ? data.imap.latency_ms + 'ms' : 'N/A'}</strong></div>
                    ${data.imap?.error ? `<div style="color:#ef4444;font-size:0.8rem;margin-top:0.25rem;">Error: ${data.imap.error}</div>` : ''}
                </div>
            </div>

            <div style="background:rgba(255,255,255,0.03);padding:0.75rem 1rem;border-radius:var(--radius-sm);border:1px solid rgba(255,255,255,0.06);font-size:0.82rem;">
                <div><strong>Monitored Senders:</strong> <code>${(data.sender_rules || []).join(', ')}</code></div>
                <div style="margin-top:0.25rem;"><strong>Subject Keywords:</strong> <code>${(data.subject_keywords || []).join(', ')}</code></div>
                <div style="margin-top:0.25rem;"><strong>Auto-Scan Frequency:</strong> Every ${data.check_interval_minutes} minutes</div>
            </div>
        `;

    } catch (e) {
        if (container) container.innerHTML = `<div style="color:#ef4444;padding:0.75rem;">❌ Diagnostic error: ${e.message}</div>`;
    } finally {
        if (btn) btn.disabled = false;
    }
}

function openAuditModalForClippingArticle(clippingId, articleId) {
    const clipping = (inboxState.clippings || []).find(c => c.id === clippingId);
    if (!clipping) return;
    const article = (clipping.articles || []).find(a => a.id === articleId);
    if (!article) return;

    const modal = document.getElementById('auditTraceabilityModal');
    if (!modal) return;

    const titleEn = document.getElementById('auditTitleEn');
    const contentEn = document.getElementById('auditContentEn');
    const titleOrig = document.getElementById('auditTitleOrig');
    const contentOrig = document.getElementById('auditContentOrig');
    const sourceBadge = document.getElementById('auditSourceBadge');
    const dateBadge = document.getElementById('auditDateBadge');
    const entitiesContainer = document.getElementById('auditEntitiesContainer');
    const snapshotContainer = document.getElementById('auditSnapshotContainer');

    if (titleEn) titleEn.textContent = article.title;
    if (contentEn) contentEn.textContent = article.snippet || article.title;
    if (titleOrig) titleOrig.textContent = article.original_title || article.title;
    if (contentOrig) contentOrig.textContent = article.original_snippet || article.snippet || '(Raw OCR Ground Truth)';
    if (sourceBadge) sourceBadge.textContent = clipping.sender || 'Inbound Clipping';
    if (dateBadge) dateBadge.textContent = clipping.ingested_at || 'Recent';

    if (entitiesContainer) {
        entitiesContainer.innerHTML = (article.entities_preserved || []).map(ent =>
            `<span class="badge badge-cyan" style="font-size:0.75rem;">${escapeHtml(ent)}</span>`
        ).join('');
    }

    if (snapshotContainer) {
        snapshotContainer.innerHTML = `
            <div style="padding:2rem;text-align:center;color:var(--text-secondary);">
                <div style="font-size:2rem;margin-bottom:0.5rem;">📄</div>
                <div>Source Document: <strong>${escapeHtml(clipping.attachment_filename || 'clipping.pdf')}</strong></div>
                <div style="font-size:0.8rem;color:var(--text-muted);margin-top:0.25rem;">Ground truth OCR confidence: ${Math.round((article.ocr_confidence || 0.98)*100)}%</div>
            </div>
        `;
    }

    modal.classList.add('open');
}
