/**
 * LitReview AI — Frontend
 *
 * Transport: WebSocket (primary) → HTTP polling (fallback if WS unavailable)
 * Error recovery: Retry button resumes from last successful checkpoint
 */

'use strict';

// ─── State ────────────────────────────────────────────────────────────────────
let currentJobId  = null;
let resultData    = null;
let _ws           = null;          // active WebSocket
let _pollInterval = null;          // fallback polling interval
let _wsRetries    = 0;             // WS reconnect counter
const WS_MAX_RETRIES = 3;

// ─── Navigation ───────────────────────────────────────────────────────────────
document.querySelectorAll('.pill[data-tab]').forEach(pill => {
  pill.addEventListener('click', () => switchTab(pill.dataset.tab));
});

function switchTab(tab) {
  document.querySelectorAll('.pill').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
  document.querySelector(`.pill[data-tab="${tab}"]`)?.classList.add('active');
  document.getElementById(`tab-${tab}`)?.classList.add('active');
}

// ─── Topic chips ──────────────────────────────────────────────────────────────
document.querySelectorAll('.chip[data-topic]').forEach(chip => {
  chip.addEventListener('click', () => {
    document.getElementById('topic-input').value = chip.dataset.topic;
    document.getElementById('topic-input').focus();
  });
});

// ─── Slider ───────────────────────────────────────────────────────────────────
const slider  = document.getElementById('paper-count');
const display = document.getElementById('paper-count-display');
slider.addEventListener('input', () => { display.textContent = slider.value; });

// ─── Start review ─────────────────────────────────────────────────────────────
async function startReview() {
  const topic     = document.getElementById('topic-input').value.trim();
  const maxPapers = parseInt(slider.value);
  if (!topic) {
    showToast('⚠️ Please enter a research topic');
    document.getElementById('topic-input').focus();
    return;
  }

  const btn = document.getElementById('btn-generate');
  btn.disabled = true;
  btn.innerHTML = '<span class="btn-icon">⏳</span> Starting...';

  try {
    const resp = await fetch('/api/review', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ topic, max_papers: maxPapers }),
    });
    if (!resp.ok) {
      const err = await resp.json();
      throw new Error(err.detail || 'Failed to start review');
    }
    const data = await resp.json();
    currentJobId = data.job_id;

    _resetProgressUI();
    document.getElementById('progress-topic-label').textContent = `"${topic}"`;
    switchTab('progress');

    _openWebSocket(currentJobId);

  } catch (e) {
    showToast(`❌ ${e.message}`);
    _enableGenerateBtn();
  }
}

// ─── WebSocket transport ──────────────────────────────────────────────────────

function _wsUrl(jobId) {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  return `${proto}://${location.host}/api/ws/${jobId}`;
}

function _openWebSocket(jobId) {
  _closeWebSocket();           // close any lingering connection
  _wsRetries = 0;
  _connectWS(jobId);
}

function _connectWS(jobId) {
  let ws;
  try {
    ws = new WebSocket(_wsUrl(jobId));
  } catch (e) {
    console.warn('WebSocket construction failed:', e);
    _startPollingFallback(jobId);
    return;
  }

  _ws = ws;

  ws.onopen = () => {
    console.log('WS connected for job', jobId);
    _wsRetries = 0;
    // Stop polling fallback if it somehow started
    _stopPollingFallback();
  };

  ws.onmessage = (event) => {
    let msg;
    try { msg = JSON.parse(event.data); } catch { return; }
    _handleWsMessage(msg, jobId);
  };

  ws.onerror = (e) => {
    console.warn('WS error:', e);
  };

  ws.onclose = (event) => {
    console.log('WS closed, code:', event.code);
    _ws = null;

    // If job is still running, try to reconnect or fall back to polling
    const job = _getLocalJobStatus();
    if (job && !['completed', 'failed'].includes(job)) {
      if (_wsRetries < WS_MAX_RETRIES) {
        _wsRetries++;
        console.log(`WS reconnect attempt ${_wsRetries}/${WS_MAX_RETRIES}`);
        setTimeout(() => _connectWS(jobId), 1500 * _wsRetries);
      } else {
        console.warn('WS reconnect exhausted — falling back to polling');
        _startPollingFallback(jobId);
      }
    }
  };
}

function _closeWebSocket() {
  if (_ws) {
    try { _ws.close(); } catch {}
    _ws = null;
  }
}

/** Track the last known status so onclose knows whether to reconnect */
let _lastKnownStatus = 'queued';
function _getLocalJobStatus() { return _lastKnownStatus; }

function _handleWsMessage(msg, jobId) {
  switch (msg.type) {

    case 'snapshot':
      // Full state dump on connect — replay all logs & current state
      _lastKnownStatus = msg.status;
      _replaySnapshot(msg);
      break;

    case 'progress':
      _lastKnownStatus = msg.status || _lastKnownStatus;
      _applyProgress(msg);
      break;

    case 'log':
      _appendLog(msg);
      break;

    case 'papers':
      _updatePapers(msg.papers);
      break;

    case 'completed':
      _lastKnownStatus = 'completed';
      _closeWebSocket();
      _stopPollingFallback();
      loadResults();
      break;

    case 'failed':
      _lastKnownStatus = 'failed';
      _closeWebSocket();
      _stopPollingFallback();
      _showFailureWithRetry(msg.error || 'Pipeline failed', msg.checkpoint || 0);
      break;

    case 'ping':
      // Server heartbeat — no action needed
      break;

    case 'error':
      showToast(`❌ ${msg.error}`);
      break;
  }
}

// ─── Polling fallback ─────────────────────────────────────────────────────────

function _startPollingFallback(jobId) {
  if (_pollInterval) return;
  showToast('ℹ️ Using polling mode (WebSocket unavailable)');
  _pollInterval = setInterval(() => _pollOnce(jobId), 2500);
  _pollOnce(jobId);
}

function _stopPollingFallback() {
  if (_pollInterval) { clearInterval(_pollInterval); _pollInterval = null; }
}

async function _pollOnce(jobId) {
  try {
    const resp = await fetch(`/api/review/${jobId}/status`);
    if (!resp.ok) return;
    const data = await resp.json();
    _lastKnownStatus = data.status;

    _applyProgress(data);
    if (data.logs) _renderAllLogs(data.logs);
    if (data.papers_found?.length) _updatePapers(data.papers_found);

    if (data.status === 'completed') {
      _stopPollingFallback();
      loadResults();
    } else if (data.status === 'failed') {
      _stopPollingFallback();
      _showFailureWithRetry(data.error || 'Pipeline failed', data.checkpoint || 0);
    }
  } catch (e) {
    console.error('Poll error:', e);
  }
}

// ─── UI update helpers ────────────────────────────────────────────────────────

function _replaySnapshot(snap) {
  _applyProgress(snap);
  if (snap.papers_found?.length) _updatePapers(snap.papers_found);
  if (snap.logs?.length)          _renderAllLogs(snap.logs);
  if (snap.status === 'failed')   _showFailureWithRetry(snap.error || '', snap.checkpoint || 0);
}

function _applyProgress(data) {
  if (data.progress != null) {
    document.getElementById('progress-bar-fill').style.width = `${data.progress}%`;
    document.getElementById('progress-percent').textContent  = `${data.progress}%`;
  }
  if (data.current_agent) {
    document.getElementById('current-agent-label').textContent = data.current_agent;
  }
  // Highlight matching pipeline step
  const map = {
    'Search': 'search', 'PDF': 'pdf', 'Summarization': 'summarize',
    'Comparison': 'compare', 'Writer': 'write', 'Planner': 'search',
  };
  for (const [kw, step] of Object.entries(map)) {
    if (data.current_agent?.includes(kw)) {
      document.querySelectorAll('.pipeline-step').forEach(s => s.classList.remove('active'));
      document.querySelector(`.pipeline-step[data-step="${step}"]`)?.classList.add('active');
      break;
    }
  }
}

function _renderAllLogs(logs) {
  const terminal = document.getElementById('log-terminal');
  terminal.innerHTML = logs.map(_logLine).join('') +
    '<div class="log-line"><span class="log-cursor"></span></div>';
  terminal.scrollTop = terminal.scrollHeight;
}

function _appendLog(entry) {
  const terminal = document.getElementById('log-terminal');
  // Remove cursor line if present
  const cursor = terminal.querySelector('.log-cursor');
  if (cursor) cursor.parentElement.remove();
  terminal.insertAdjacentHTML('beforeend', _logLine(entry));
  terminal.insertAdjacentHTML('beforeend',
    '<div class="log-line"><span class="log-cursor"></span></div>');
  terminal.scrollTop = terminal.scrollHeight;
}

function _logLine(log) {
  const time = new Date(log.timestamp).toLocaleTimeString([], {
    hour: '2-digit', minute: '2-digit', second: '2-digit'
  });
  const cls = `log-msg-${log.level || 'info'}`;
  return `<div class="log-line">
    <span class="log-time">${time}</span>
    <span class="${cls}">${escHtml(log.message)}</span>
  </div>`;
}

function _updatePapers(papers) {
  if (!papers?.length) return;
  document.getElementById('papers-found-section').style.display = 'block';
  document.getElementById('papers-found-list').innerHTML = papers.map(p =>
    `<div class="paper-chip">
      <span class="paper-chip-year">${p.year || '?'}</span>
      <span>${escHtml(p.title || 'Unknown title')}</span>
    </div>`
  ).join('');
}

// ─── Failure + retry ─────────────────────────────────────────────────────────

const STAGE_NAMES = {
  0: 'beginning',
  1: 'PDF extraction (stage 2)',
  2: 'Summarization (stage 3)',
  3: 'Comparative analysis (stage 4)',
  4: 'Writing (stage 5)',
};

function _showFailureWithRetry(errorMsg, checkpoint) {
  document.getElementById('current-agent-label').textContent = `❌ ${errorMsg}`;

  // Show retry card
  const resumeFrom = STAGE_NAMES[checkpoint] || 'beginning';
  let retryCard = document.getElementById('retry-card');
  if (!retryCard) {
    retryCard = document.createElement('div');
    retryCard.id = 'retry-card';
    retryCard.className = 'retry-card';
    document.getElementById('tab-progress').appendChild(retryCard);
  }

  const canResume = checkpoint > 0;
  retryCard.innerHTML = `
    <div class="retry-icon">⚠️</div>
    <div class="retry-info">
      <div class="retry-title">Pipeline Failed</div>
      <div class="retry-msg">${escHtml(errorMsg)}</div>
      ${canResume
        ? `<div class="retry-checkpoint">
             ✅ Progress saved — will resume from <strong>${escHtml(resumeFrom)}</strong>
           </div>`
        : '<div class="retry-checkpoint">No checkpoint saved — will restart from beginning</div>'
      }
    </div>
    <div class="retry-actions">
      <button class="btn-retry" onclick="retryJob()">
        🔄 ${canResume ? 'Resume' : 'Retry'}
      </button>
      <button class="btn-retry btn-retry-secondary" onclick="newReview()">
        ✚ New Review
      </button>
    </div>
  `;
  retryCard.style.display = 'flex';

  showToast(`❌ ${errorMsg}`);
  _enableGenerateBtn();
}

async function retryJob() {
  if (!currentJobId) return;

  const retryCard = document.getElementById('retry-card');
  if (retryCard) retryCard.style.display = 'none';

  const btn = document.getElementById('btn-generate');
  btn.disabled = true;

  try {
    const resp = await fetch(`/api/review/${currentJobId}/retry`, { method: 'POST' });
    if (!resp.ok) {
      const err = await resp.json();
      throw new Error(err.detail || 'Retry failed');
    }
    const data = await resp.json();
    showToast(`🔄 ${data.message}`);

    // Reset log terminal for clarity then reconnect WS
    document.getElementById('log-terminal').innerHTML = '';
    _openWebSocket(currentJobId);

  } catch (e) {
    showToast(`❌ ${e.message}`);
    _enableGenerateBtn();
  }
}

// ─── Load results ─────────────────────────────────────────────────────────────
async function loadResults() {
  try {
    const resp = await fetch(`/api/review/${currentJobId}/result`);
    if (!resp.ok) throw new Error('Failed to load results');
    resultData = await resp.json();

    document.getElementById('results-title').textContent =
      resultData.topic || 'Literature Review';
    document.getElementById('results-stats').textContent =
      `${resultData.papers_count} papers · ` +
      `${(resultData.markdown?.length / 1000).toFixed(1)}k chars`;

    // Render views
    document.getElementById('review-rendered').innerHTML =
      marked.parse(resultData.markdown || '');
    document.getElementById('review-markdown-raw').textContent = resultData.markdown || '';
    document.getElementById('review-latex-raw').textContent    = resultData.latex    || '';

    // APA view
    const apaContainer = document.getElementById('review-apa-raw');
    if (resultData.apa) {
      apaContainer.innerHTML = resultData.apa.split('\n').map(line => {
        if (line.startsWith('#'))
          return `<h4 class="apa-section-title">${line.replace(/^#+\s*/, '')}</h4>`;
        if (line.startsWith('*'))
          return `<p class="apa-subtitle">${line.replace(/\*/g, '')}</p>`;
        if (line.match(/^\[\d+\]/)) {
          const num  = line.match(/^\[(\d+)\]/)[1];
          const text = line.replace(/^\[\d+\]\s*/, '').replace(/\*(.*?)\*/g, '<em>$1</em>');
          return `<div class="apa-entry">
            <span class="apa-num">[${num}]</span>
            <span class="apa-text">${text}</span>
          </div>`;
        }
        return line.trim() ? `<p>${line}</p>` : '';
      }).join('');
    } else {
      apaContainer.innerHTML = '<p class="apa-empty">APA references not available.</p>';
    }

    document.getElementById('nav-results').style.display = '';
    switchTab('results');
    showToast('✅ Literature review complete!');
    _enableGenerateBtn();

  } catch (e) {
    showError(e.message);
  }
}

// ─── Reset / helpers ──────────────────────────────────────────────────────────

function _resetProgressUI() {
  document.getElementById('log-terminal').innerHTML = '';
  document.getElementById('papers-found-section').style.display = 'none';
  document.getElementById('progress-bar-fill').style.width = '0%';
  document.getElementById('progress-percent').textContent = '0%';
  document.getElementById('current-agent-label').textContent = 'Initializing pipeline...';
  document.querySelectorAll('.pipeline-step').forEach(s => s.classList.remove('active'));
  const rc = document.getElementById('retry-card');
  if (rc) rc.style.display = 'none';
}

function _enableGenerateBtn() {
  const btn = document.getElementById('btn-generate');
  if (btn) {
    btn.disabled = false;
    btn.innerHTML = '<span class="btn-icon">⚡</span> Generate Literature Review <span class="btn-arrow">→</span>';
  }
}

function showError(msg) {
  document.getElementById('current-agent-label').textContent = `❌ Error: ${msg}`;
  showToast(`❌ ${msg}`);
  _enableGenerateBtn();
}

// ─── View toggle ──────────────────────────────────────────────────────────────
function switchView(view) {
  document.querySelectorAll('.toggle-btn').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.result-view').forEach(v  => v.classList.remove('active'));
  document.getElementById(`btn-${view}`).classList.add('active');
  document.getElementById(`view-${view}`).classList.add('active');
}

// ─── Downloads ────────────────────────────────────────────────────────────────
function downloadMarkdown() {
  if (!resultData?.markdown) return;
  _downloadBlob(
    new Blob([resultData.markdown], { type: 'text/markdown' }),
    `literature_review_${currentJobId?.slice(0, 8) || 'result'}.md`
  );
}

function downloadLatex() {
  if (!resultData?.latex) return;
  _downloadBlob(
    new Blob([resultData.latex], { type: 'text/plain' }),
    `literature_review_${currentJobId?.slice(0, 8) || 'result'}.tex`
  );
}

function downloadApa() {
  if (!resultData?.apa) return showToast('⚠️ APA references not available');
  _downloadBlob(
    new Blob([resultData.apa], { type: 'text/markdown' }),
    `references_apa_${currentJobId?.slice(0, 8) || 'result'}.md`
  );
}

function copyApa() {
  if (!resultData?.apa) return showToast('⚠️ APA references not available');
  navigator.clipboard.writeText(resultData.apa)
    .then(() => showToast('📋 APA references copied!'));
}

function copyMarkdown() {
  if (!resultData?.markdown) return;
  navigator.clipboard.writeText(resultData.markdown)
    .then(() => showToast('📋 Copied to clipboard!'));
}

function _downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a   = document.createElement('a');
  a.href = url; a.download = filename; a.click();
  URL.revokeObjectURL(url);
  showToast(`📥 Downloading ${filename}`);
}

// ─── New review ───────────────────────────────────────────────────────────────
function newReview() {
  _closeWebSocket();
  _stopPollingFallback();
  currentJobId = null;
  resultData   = null;
  _lastKnownStatus = 'queued';

  document.getElementById('nav-results').style.display = 'none';
  document.getElementById('topic-input').value = '';
  _resetProgressUI();
  switchTab('generate');
}

// ─── Toast ────────────────────────────────────────────────────────────────────
let _toastTimeout;
function showToast(msg) {
  const toast = document.getElementById('toast');
  toast.textContent = msg;
  toast.classList.add('show');
  clearTimeout(_toastTimeout);
  _toastTimeout = setTimeout(() => toast.classList.remove('show'), 3500);
}

// ─── Utilities ────────────────────────────────────────────────────────────────
function escHtml(str) {
  return String(str)
    .replace(/&/g,  '&amp;')
    .replace(/</g,  '&lt;')
    .replace(/>/g,  '&gt;')
    .replace(/"/g,  '&quot;');
}

document.getElementById('topic-input').addEventListener('keydown', e => {
  if (e.key === 'Enter') startReview();
});
