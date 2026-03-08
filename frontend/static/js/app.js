/**
 * LitReview AI — Frontend App
 */

let currentJobId = null;
let pollInterval = null;
let resultData = null;

// ===== NAV =====
document.querySelectorAll('.pill[data-tab]').forEach(pill => {
  pill.addEventListener('click', () => {
    const tab = pill.dataset.tab;
    switchTab(tab);
  });
});

function switchTab(tab) {
  document.querySelectorAll('.pill').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
  document.querySelector(`.pill[data-tab="${tab}"]`)?.classList.add('active');
  document.getElementById(`tab-${tab}`)?.classList.add('active');
}

// ===== CHIPS =====
document.querySelectorAll('.chip[data-topic]').forEach(chip => {
  chip.addEventListener('click', () => {
    document.getElementById('topic-input').value = chip.dataset.topic;
    document.getElementById('topic-input').focus();
  });
});

// ===== SLIDER =====
const slider = document.getElementById('paper-count');
const display = document.getElementById('paper-count-display');
slider.addEventListener('input', () => { display.textContent = slider.value; });

// ===== GENERATE =====
async function startReview() {
  const topic = document.getElementById('topic-input').value.trim();
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
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ topic, max_papers: maxPapers }),
    });

    if (!resp.ok) {
      const err = await resp.json();
      throw new Error(err.detail || 'Failed to start review');
    }

    const data = await resp.json();
    currentJobId = data.job_id;

    // Switch to progress view
    document.getElementById('progress-topic-label').textContent = `"${topic}"`;
    switchTab('progress');
    startPolling();

  } catch (e) {
    showToast(`❌ ${e.message}`);
    btn.disabled = false;
    btn.innerHTML = '<span class="btn-icon">⚡</span> Generate Literature Review <span class="btn-arrow">→</span>';
  }
}

// ===== POLLING =====
function startPolling() {
  clearPolling();
  pollInterval = setInterval(pollStatus, 2500);
  pollStatus(); // immediate first poll
}

function clearPolling() {
  if (pollInterval) { clearInterval(pollInterval); pollInterval = null; }
}

async function pollStatus() {
  if (!currentJobId) return;

  try {
    const resp = await fetch(`/api/review/${currentJobId}/status`);
    if (!resp.ok) return;
    const data = await resp.json();

    updateProgressUI(data);

    if (data.status === 'completed') {
      clearPolling();
      await loadResults();
    } else if (data.status === 'failed') {
      clearPolling();
      showError(data.error || 'Pipeline failed');
    }
  } catch (e) {
    console.error('Poll error:', e);
  }
}

function updateProgressUI(data) {
  // Progress bar
  document.getElementById('progress-bar-fill').style.width = `${data.progress}%`;
  document.getElementById('progress-percent').textContent = `${data.progress}%`;

  // Current agent
  if (data.current_agent) {
    document.getElementById('current-agent-label').textContent = data.current_agent;
  }

  // Activate pipeline step
  const agentStepMap = {
    'Search': 'search',
    'PDF': 'pdf',
    'Summarization': 'summarize',
    'Comparison': 'compare',
    'Writer': 'write',
    'Planner': 'search',
  };
  for (const [keyword, step] of Object.entries(agentStepMap)) {
    if (data.current_agent && data.current_agent.includes(keyword)) {
      document.querySelectorAll('.pipeline-step').forEach(s => s.classList.remove('active'));
      document.querySelector(`.pipeline-step[data-step="${step}"]`)?.classList.add('active');
      break;
    }
  }

  // Papers found
  if (data.papers_found && data.papers_found.length > 0) {
    const section = document.getElementById('papers-found-section');
    section.style.display = 'block';
    const list = document.getElementById('papers-found-list');
    list.innerHTML = data.papers_found.map(p =>
      `<div class="paper-chip">
        <span class="paper-chip-year">${p.year || '?'}</span>
        <span>${escHtml(p.title || 'Unknown title')}</span>
      </div>`
    ).join('');
  }

  // Logs
  const terminal = document.getElementById('log-terminal');
  if (data.logs && data.logs.length) {
    terminal.innerHTML = data.logs.map(log => {
      const time = new Date(log.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
      const cls = `log-msg-${log.level || 'info'}`;
      return `<div class="log-line">
        <span class="log-time">${time}</span>
        <span class="${cls}">${escHtml(log.message)}</span>
      </div>`;
    }).join('') + '<div class="log-line"><span class="log-cursor"></span></div>';
    terminal.scrollTop = terminal.scrollHeight;
  }
}

// ===== LOAD RESULTS =====
async function loadResults() {
  try {
    const resp = await fetch(`/api/review/${currentJobId}/result`);
    if (!resp.ok) throw new Error('Failed to load results');
    resultData = await resp.json();

    // Populate results tab
    document.getElementById('results-title').textContent = resultData.topic || 'Literature Review';
    document.getElementById('results-stats').textContent =
      `${resultData.papers_count} papers reviewed · ${(resultData.markdown?.length / 1000).toFixed(1)}k characters`;

    // Render markdown
    document.getElementById('review-rendered').innerHTML = marked.parse(resultData.markdown || '');
    document.getElementById('review-markdown-raw').textContent = resultData.markdown || '';
    document.getElementById('review-latex-raw').textContent = resultData.latex || '';

    // Show results nav
    document.getElementById('nav-results').style.display = '';

    // Switch to results
    switchTab('results');
    showToast('✅ Literature review complete!');

    // Reset generate button
    const btn = document.getElementById('btn-generate');
    btn.disabled = false;
    btn.innerHTML = '<span class="btn-icon">⚡</span> Generate Literature Review <span class="btn-arrow">→</span>';

  } catch (e) {
    showError(e.message);
  }
}

function showError(msg) {
  document.getElementById('current-agent-label').textContent = `❌ Error: ${msg}`;
  document.getElementById('agent-pulse')?.style?.setProperty('background', 'var(--red)');
  showToast(`❌ ${msg}`);
  const btn = document.getElementById('btn-generate');
  if (btn) {
    btn.disabled = false;
    btn.innerHTML = '<span class="btn-icon">⚡</span> Generate Literature Review <span class="btn-arrow">→</span>';
  }
}

// ===== VIEW TOGGLE =====
function switchView(view) {
  document.querySelectorAll('.toggle-btn').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.result-view').forEach(v => v.classList.remove('active'));
  document.getElementById(`btn-${view}`).classList.add('active');
  document.getElementById(`view-${view}`).classList.add('active');
}

// ===== DOWNLOADS =====
function downloadMarkdown() {
  if (!resultData?.markdown) return;
  const blob = new Blob([resultData.markdown], { type: 'text/markdown' });
  downloadBlob(blob, `literature_review_${currentJobId?.slice(0,8) || 'result'}.md`);
}

function downloadLatex() {
  if (!resultData?.latex) return;
  const blob = new Blob([resultData.latex], { type: 'text/plain' });
  downloadBlob(blob, `literature_review_${currentJobId?.slice(0,8) || 'result'}.tex`);
}

function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = filename; a.click();
  URL.revokeObjectURL(url);
  showToast(`📥 Downloading ${filename}`);
}

function copyMarkdown() {
  if (!resultData?.markdown) return;
  navigator.clipboard.writeText(resultData.markdown).then(() => {
    showToast('📋 Copied to clipboard!');
  });
}

function newReview() {
  currentJobId = null;
  resultData = null;
  document.getElementById('nav-results').style.display = 'none';
  document.getElementById('topic-input').value = '';
  document.getElementById('log-terminal').innerHTML = '';
  document.getElementById('papers-found-section').style.display = 'none';
  document.getElementById('progress-bar-fill').style.width = '0%';
  document.getElementById('progress-percent').textContent = '0%';
  document.getElementById('current-agent-label').textContent = 'Initializing pipeline...';
  document.querySelectorAll('.pipeline-step').forEach(s => s.classList.remove('active'));
  switchTab('generate');
}

// ===== TOAST =====
let toastTimeout;
function showToast(msg) {
  const toast = document.getElementById('toast');
  toast.textContent = msg;
  toast.classList.add('show');
  clearTimeout(toastTimeout);
  toastTimeout = setTimeout(() => toast.classList.remove('show'), 3500);
}

// ===== UTILS =====
function escHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// Enter key on input
document.getElementById('topic-input').addEventListener('keydown', e => {
  if (e.key === 'Enter') startReview();
});
