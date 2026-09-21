const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];

let selectedFiles = [];
let selectedApiJobs = [];
let selectedTypes = ['FACE', 'PLATE', 'EMAIL', 'PHONE', 'NAME', 'ID'];
let currentUser = null;

function showAuthView() {
  $('#authView')?.classList.remove('hidden');
  $('#appView')?.classList.add('hidden');
}

function showAppView() {
  $('#authView')?.classList.add('hidden');
  $('#appView')?.classList.remove('hidden');
}

const signInTab = $('#signInTab');
const createTab = $('#createTab');
const loginForm = $('#loginForm');
const signupForm = $('#signupForm');
const authMessage = $('#authMessage');

function setAuthMessage(text, isError = true) {
  if (!authMessage) return;
  authMessage.textContent = text || '';
  authMessage.style.color = isError ? '#b91c1c' : '#166534';
}

function switchAuth(mode) {
  const signIn = mode === 'signin';
  signInTab?.classList.toggle('active', signIn);
  createTab?.classList.toggle('active', !signIn);
  loginForm?.classList.toggle('hidden', !signIn);
  signupForm?.classList.toggle('hidden', signIn);
  setAuthMessage('');
}

signInTab?.addEventListener('click', () => switchAuth('signin'));
createTab?.addEventListener('click', () => switchAuth('signup'));

loginForm?.addEventListener('submit', async (e) => {
  e.preventDefault();
  setAuthMessage('');
  const button = loginForm.querySelector('button[type="submit"]');
  const formData = new FormData(loginForm);
  if (button) { button.disabled = true; button.textContent = 'Signing in...'; }
  try {
    const response = await fetch('/api/auth/login', { method: 'POST', body: formData });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || 'Unable to sign in.');
    currentUser = data.user;
    onAuthenticated();
  } catch (error) {
    setAuthMessage(error.message);
  } finally {
    if (button) { button.disabled = false; button.textContent = 'Sign in'; }
  }
});

signupForm?.addEventListener('submit', async (e) => {
  e.preventDefault();
  setAuthMessage('');
  const button = signupForm.querySelector('button[type="submit"]');
  const formData = new FormData(signupForm);
  if (button) { button.disabled = true; button.textContent = 'Creating account...'; }
  try {
    const response = await fetch('/api/auth/signup', { method: 'POST', body: formData });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || 'Unable to create account.');

    const loginData = new FormData();
    loginData.append('email', formData.get('email'));
    loginData.append('password', formData.get('password'));
    const loginResponse = await fetch('/api/auth/login', { method: 'POST', body: loginData });
    const loginResult = await loginResponse.json();
    if (!loginResponse.ok) throw new Error(loginResult.detail || 'Account created. Please sign in.');

    currentUser = loginResult.user;
    onAuthenticated();
  } catch (error) {
    setAuthMessage(error.message);
  } finally {
    if (button) { button.disabled = false; button.textContent = 'Create account'; }
  }
});

function onAuthenticated() {
  showAppView();
  $$('.username').forEach((el) => { el.textContent = currentUser?.username || ''; });
  if ($('#sidebarUser')) $('#sidebarUser').textContent = currentUser?.username || 'User';
  showPage('dashboard');
  loadApiIncoming();
}

$('#logoutBtn')?.addEventListener('click', async () => {

  try { await fetch('/api/auth/logout', { method: 'POST' }); } catch (e) { console.error(e); }

  currentUser = null;

  showAuthView();

  switchAuth('signin');

});

const generateApiTokenBtn = document.getElementById('generateApiTokenBtn');
const apiTokenMessage = document.getElementById('apiTokenMessage');
const apiTokenResult = document.getElementById('apiTokenResult');
const apiTokenValue = document.getElementById('apiTokenValue');

async function loadApiTokenStatus() {
  const status = document.getElementById('apiTokenStatus');
  const noToken = document.getElementById('apiTokenNoToken');
  const prefix = document.getElementById('apiTokenPrefix');
  const last4 = document.getElementById('apiTokenLast4');
  const created = document.getElementById('apiTokenCreated');
  const lastUsed = document.getElementById('apiTokenLastUsed');
  const expires = document.getElementById('apiTokenExpires');

  if (!status) return;

  try {
    const response = await fetch('/api/auth/api-token', {
      credentials: 'include'
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || 'Unable to load token status.');

    if (data.has_token && data.is_active) {
      status.classList.remove('hidden');
      noToken?.classList.add('hidden');
      if (prefix) prefix.textContent = `${data.token_prefix}...`;
      if (last4) last4.textContent = data.token_last4 ? `...${data.token_last4}` : '—';
      if (created) created.textContent = data.created_at || '—';
      if (lastUsed) lastUsed.textContent = data.last_used_at || 'Never';
      if (expires) {
        if (data.expires_at && typeof data.days_remaining === 'number') {
          expires.textContent = `${formatUsageDate(data.expires_at)} (${data.days_remaining}d left)`;
        } else {
          expires.textContent = '—';
        }
      }
    } else {
      status.classList.add('hidden');
      noToken?.classList.remove('hidden');
      const noTokenText = noToken?.querySelector('div');
      if (noTokenText) {
        noTokenText.textContent = (data.has_token && data.is_expired)
          ? 'Your previous PrivacyHub API token has expired. Generate a new one below.'
          : 'No active PrivacyHub API token has been generated yet.';
      }
    }
  } catch (error) {
    console.error('Failed to load API token status:', error);
  }
}

function formatUsageDate(value) {
  if (!value) return '—';
  return value.replace('T', ' ');
}

async function loadApiUsage() {
  const recent = document.getElementById('usageRecent');
  try {
    const response = await fetch('/api/auth/api-usage', {
      credentials: 'include'
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || 'Unable to load API usage.');

    document.getElementById('usageTotal').textContent = data.total_requests ?? 0;
    document.getElementById('usageSuccess').textContent = data.successful_requests ?? 0;
    document.getElementById('usageReview').textContent = data.review_requests ?? 0;
    document.getElementById('usageRateLimited').textContent = data.rate_limited_requests ?? 0;
    document.getElementById('usageFailed').textContent = data.failed_requests ?? 0;
    document.getElementById('usageLast').textContent = formatUsageDate(data.last_request);

    if (!recent) return;
    if (!data.recent?.length) {
      recent.innerHTML = '<div class="muted">No API requests recorded yet.</div>';
      return;
    }

    recent.innerHTML = data.recent.map((item) => `
      <div class="usage-row">
        <div>
          <strong>${item.endpoint}</strong>
          <span>${formatUsageDate(item.request_time)}</span>
        </div>
        <div class="usage-row-right">
          <span class="usage-status ${String(item.status).toLowerCase()}">${item.status}</span>
          <span>${item.job_id || '—'}</span>
        </div>
      </div>
    `).join('');
  } catch (error) {
    console.error('Failed to load API usage:', error);
    if (recent) recent.innerHTML = '<div class="muted">Unable to load usage data.</div>';
  }
}

if (generateApiTokenBtn) {
  generateApiTokenBtn.addEventListener('click', async () => {
    generateApiTokenBtn.disabled = true;
    apiTokenMessage.textContent = 'Generating API token...';

    try {
      const response = await fetch('/api/auth/api-token', {
        method: 'POST',
        credentials: 'include'
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || 'Failed to generate API token.');

      if (data.created_new) {
        apiTokenValue.textContent = data.token;
        apiTokenResult.classList.remove('hidden');
        apiTokenMessage.textContent = 'API token generated successfully. Save it now — it will not be shown again.';
      } else {
        apiTokenResult.classList.add('hidden');
        apiTokenMessage.textContent = data.message || 'You already have an active API token.';
      }
      await loadApiTokenStatus();
    } catch (error) {
      apiTokenMessage.textContent = error.message;
    } finally {
      generateApiTokenBtn.disabled = false;
    }
  });
}

const copyApiTokenBtn = document.getElementById('copyApiTokenBtn');

copyApiTokenBtn?.addEventListener('click', async () => {
  const value = apiTokenValue?.textContent || '';
  if (!value) return;

  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(value);
    } else {
      // Fallback for browsers/contexts without the async Clipboard API.
      const textarea = document.createElement('textarea');
      textarea.value = value;
      textarea.style.position = 'fixed';
      textarea.style.opacity = '0';
      document.body.appendChild(textarea);
      textarea.select();
      document.execCommand('copy');
      textarea.remove();
    }

    const original = copyApiTokenBtn.textContent;
    copyApiTokenBtn.textContent = 'Copied!';
    copyApiTokenBtn.classList.add('copied');
    setTimeout(() => {
      copyApiTokenBtn.textContent = original;
      copyApiTokenBtn.classList.remove('copied');
    }, 1500);
  } catch (error) {
    console.error('Failed to copy API token:', error);
    apiTokenMessage.textContent = 'Could not copy automatically — please select and copy the token manually.';
  }
});

const revokeApiTokenBtn = document.getElementById('revokeApiTokenBtn');

revokeApiTokenBtn?.addEventListener('click', async () => {
  const confirmed = window.confirm(
    'Revoke your PrivacyHub API token? Any application using it will stop working immediately. You can generate a new one right after.'
  );
  if (!confirmed) return;

  revokeApiTokenBtn.disabled = true;
  revokeApiTokenBtn.textContent = 'Revoking...';

  try {
    const response = await fetch('/api/auth/api-token/revoke', {
      method: 'POST',
      credentials: 'include'
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || 'Unable to revoke token.');

    apiTokenResult.classList.add('hidden');
    apiTokenMessage.textContent = data.message || 'Token revoked.';
    await loadApiTokenStatus();
  } catch (error) {
    apiTokenMessage.textContent = error.message;
  } finally {
    revokeApiTokenBtn.disabled = false;
    revokeApiTokenBtn.textContent = 'Revoke Token';
  }
});

function showPage(page) {
  $$('.page').forEach((p) => p.classList.remove('active-page'));
  $(`#${page}`)?.classList.add('active-page');
  $$('.nav-item').forEach((item) => item.classList.toggle('active', item.dataset.page === page));
  if (page === 'dashboard') loadDashboard();
  if (page === 'protect') loadApiIncoming();
  if (page === 'review') loadReview();
  if (page === 'approved') loadApproved();
  if (page === 'xtreme1') loadUnifiedDeliveryReady();
  if (page === 'api-access') { loadApiTokenStatus(); loadApiUsage(); }
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

$$('.nav-item').forEach((item) => item.addEventListener('click', () => showPage(item.dataset.page)));
$$('[data-page-jump]').forEach((item) => item.addEventListener('click', () => showPage(item.dataset.pageJump)));

// ---------------- privacy options ----------------
const privacyOptions = [
  ['FACE', 'Faces'],
  ['PLATE', 'License plates'],
  ['EMAIL', 'Email addresses'],
  ['PHONE', 'Phone numbers'],
  ['NAME', 'Names'],
  ['ID', 'IDs'],
];

function renderPrivacyOptions() {
  const container = $('#privacyTypes');
  if (!container) return;
  container.innerHTML = privacyOptions.map(([value, label]) => `
    <label class="check">
      <input type="checkbox" value="${value}" checked>
      <span>${label}</span>
    </label>`).join('');
  container.addEventListener('change', () => {
    selectedTypes = $$('#privacyTypes input:checked').map((x) => x.value);
  });
}
renderPrivacyOptions();

// ---------------- multi-image upload ----------------
const filesInput = $('#files');
const dropzone = $('#dropzone');
const browseFiles = $('#browseFiles');

function addFiles(fileList) {
  const incoming = [...fileList].filter((file) => file.type.startsWith('image/'));
  if (!incoming.length) return;

  // Merge instead of replacing. This deliberately keeps the current selection
  // when the user clicks "Add images" multiple times.
  const existingKeys = new Set(selectedFiles.map((file) => `${file.name}|${file.size}|${file.lastModified}`));
  for (const file of incoming) {
    const key = `${file.name}|${file.size}|${file.lastModified}`;
    if (!existingKeys.has(key)) {
      selectedFiles.push(file);
      selectedApiJobs.push(null);
      existingKeys.add(key);
    }
  }
  renderPreviews();
}

browseFiles?.addEventListener('click', (e) => {
  e.preventDefault();
  e.stopPropagation();
  filesInput?.click();
});

filesInput?.addEventListener('change', (e) => {
  addFiles(e.target.files);
  e.target.value = '';
});

if (dropzone) {
  ['dragenter', 'dragover'].forEach((name) => dropzone.addEventListener(name, (e) => {
    e.preventDefault();
    e.stopPropagation();
    dropzone.classList.add('dragover');
  }));
  ['dragleave', 'dragend'].forEach((name) => dropzone.addEventListener(name, (e) => {
    e.preventDefault();
    e.stopPropagation();
    dropzone.classList.remove('dragover');
  }));
  dropzone.addEventListener('drop', (e) => {
    e.preventDefault();
    e.stopPropagation();
    dropzone.classList.remove('dragover');
    addFiles(e.dataTransfer?.files || []);
  });
  dropzone.addEventListener('click', (e) => {
    if (e.target === browseFiles) return;
    filesInput?.click();
  });
}

function formatFileSize(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function updateFileCount() {
  const el = $('#fileCount');
  if (el) el.textContent = `${selectedFiles.length} image${selectedFiles.length === 1 ? '' : 's'}`;
}

function renderPreviews() {
  const preview = $('#preview');
  if (!preview) return;
  updateFileCount();
  preview.innerHTML = '';

  selectedFiles.forEach((file, index) => {
    const url = URL.createObjectURL(file);
    preview.insertAdjacentHTML('beforeend', `
      <div class="preview">
        <div class="zoomable"><img src="${url}" alt="${escapeHtml(file.name)}"><button type="button" class="zoom-btn" data-url="${url}" data-name="${escapeHtml(file.name)}" title="View full size">⤢</button></div>
        <div class="preview-name" title="${escapeHtml(file.name)}">${escapeHtml(file.name)}</div>
        <div class="tiny">${formatFileSize(file.size)}</div>
        <button type="button" class="remove-file" data-index="${index}">Remove</button>
      </div>`);
  });

  $$('.remove-file').forEach((button) => button.addEventListener('click', () => {
    const removeIndex = Number(button.dataset.index);
    selectedFiles.splice(removeIndex, 1);
    selectedApiJobs.splice(removeIndex, 1);
    renderPreviews();
  }));
  wireZoomButtons();
}

function escapeHtml(value) {
  return String(value).replace(/[&<>'"]/g, (char) => ({ '&':'&amp;', '<':'&lt;', '>':'&gt;', "'":'&#39;', '"':'&quot;' }[char]));
}

// ---------------- lightbox ----------------
function openLightbox(url, caption) {
  const lightbox = $('#lightbox');
  const img = $('#lightboxImg');
  if (!lightbox || !img) return;
  img.src = url;
  img.alt = caption || '';
  if ($('#lightboxCaption')) $('#lightboxCaption').textContent = caption || '';
  lightbox.classList.remove('hidden');
}
function closeLightbox() {
  $('#lightbox')?.classList.add('hidden');
  if ($('#lightboxImg')) $('#lightboxImg').src = '';
}
$('#lightboxClose')?.addEventListener('click', closeLightbox);
$('#lightbox')?.addEventListener('click', (e) => { if (e.target === $('#lightbox')) closeLightbox(); });
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeLightbox(); });
function wireZoomButtons() {
  $$('.zoom-btn').forEach((button) => button.addEventListener('click', (e) => {
    e.stopPropagation();
    openLightbox(button.dataset.url, button.dataset.name || '');
  }));
}

// ---------------- staged API incoming ----------------
async function loadApiIncoming() {
  const container = $('#apiIncomingList');
  const count = $('#apiIncomingCount');
  if (!container) return;
  try {
    const response = await fetch('/api/incoming');
    if (response.status === 401) { showAuthView(); return; }
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || 'Unable to load incoming API images.');
    const images = data.images || [];
    if (count) count.textContent = `${images.length} waiting`;
    if (!images.length) {
      container.innerHTML = '<div class="empty"><strong>No incoming API images.</strong><br><span class="tiny">External applications will appear here after they upload through the PrivacyHub API.</span></div>';
      return;
    }
    container.innerHTML = images.map((item) => `
      <div class="preview api-incoming-item">
        <div class="zoomable"><img src="${item.url}" alt="${escapeHtml(item.filename)}"><button type="button" class="zoom-btn" data-url="${item.url}" data-name="${escapeHtml(item.filename)}" title="View full size">⤢</button></div>
        <div class="preview-name" title="${escapeHtml(item.filename)}">${escapeHtml(item.filename)}</div>
        <div class="tiny">From external API · Destination: ${escapeHtml(item.destination)}</div>
        <button type="button" class="primary add-api-file" data-job-id="${escapeHtml(item.job_id)}" data-url="${item.url}" data-filename="${escapeHtml(item.filename)}">Add to protection</button>
      </div>`).join('');
    $$('.add-api-file').forEach((button) => button.addEventListener('click', () => addApiIncomingToSelection(button)));
    wireZoomButtons();
  } catch (error) {
    console.error('Incoming API error:', error);
    container.innerHTML = '<div class="empty">Unable to load incoming API images.</div>';
  }
}

async function addApiIncomingToSelection(button) {
  const jobId = button.dataset.jobId;
  try {
    button.disabled = true;
    button.textContent = 'Adding...';
    const response = await fetch(button.dataset.url);
    if (!response.ok) throw new Error('Unable to load the staged image.');
    const blob = await response.blob();
    const file = new File([blob], button.dataset.filename, { type: blob.type || 'image/jpeg' });
    const exists = selectedFiles.some((item) => item.name === file.name && item.size === file.size);
    if (!exists) {
      selectedFiles.push(file);
      selectedApiJobs.push(jobId);
      renderPreviews();
    }
    button.textContent = 'Added to protection';
    button.classList.remove('primary');
    button.classList.add('secondary');
  } catch (error) {
    console.error(error);
    alert(error.message || 'Unable to add the API image.');
    button.disabled = false;
    button.textContent = 'Add to protection';
  }
}

// ---------------- protection ----------------
$('#protectBtn')?.addEventListener('click', async () => {
  if (!selectedFiles.length) { alert('Please select at least one image.'); return; }
  if (!selectedTypes.length) { alert('Please select at least one privacy type.'); return; }

  const formData = new FormData();
  selectedFiles.forEach((file) => formData.append('files', file));
  formData.append('selected_types', JSON.stringify(selectedTypes));
  formData.append('api_job_ids', JSON.stringify(selectedApiJobs));

  const protectBtn = $('#protectBtn');
  protectBtn.disabled = true;
  protectBtn.innerHTML = 'Protecting...';
  const jobBox = $('#jobBox');
  const outcome = $('#outcome');
  if (jobBox) { jobBox.classList.remove('hidden'); jobBox.innerHTML = '<div class="job-text" id="progressText">Starting...</div><div class="progress"><i id="progressBar"></i></div>'; }
  outcome?.classList.add('hidden');

  try {
    const response = await fetch('/api/protect', { method: 'POST', body: formData });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || 'Protection failed.');
    const job = await pollJob(data.job_id);
    renderOutcome(job);
    selectedFiles = [];
    selectedApiJobs = [];
    renderPreviews();
    await loadDashboard();
  } catch (error) {
    console.error(error);
    alert(error.message || 'Something went wrong while protecting the images.');
  } finally {
    protectBtn.disabled = false;
    protectBtn.innerHTML = 'Protect Images <span>→</span>';
  }
});

async function pollJob(jobId) {
  while (true) {
    const response = await fetch(`/api/jobs/${encodeURIComponent(jobId)}`);
    const job = await response.json();
    updateProgress(job);
    if (job.status === 'completed') return job;
    if (job.status === 'failed') throw new Error(job.message || 'Processing failed.');
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
}

function updateProgress(job) {
  if ($('#progressText')) $('#progressText').textContent = job.message || 'Processing...';
  if ($('#progressBar') && job.total) $('#progressBar').style.width = `${Math.round((job.current / job.total) * 100)}%`;
}

function statusLabel(status) {
  if (status === 'APPROVED') return 'Auto-approved';
  if (status === 'REJECTED') return 'Rejected';
  return 'Needs review';
}

function renderOutcome(job) {
  const outcome = $('#outcome');
  if (!outcome) return;
  const results = job.results || [];
  const approved = results.filter((r) => r.review_status === 'APPROVED').length;
  const review = results.filter((r) => r.review_status === 'REVIEW').length;
  const rejected = results.filter((r) => r.review_status === 'REJECTED').length;

  outcome.classList.remove('hidden');
  outcome.innerHTML = `
    <div class="card-title-row"><div class="mini-icon blue">✓</div><h2>Protection complete</h2></div>
    <div class="outcome-grid">
      <div class="outcome-stat"><div class="label">Processed</div><div class="value">${results.length}</div></div>
      <div class="outcome-stat"><div class="label">Auto-approved</div><div class="value">${approved}</div></div>
      <div class="outcome-stat"><div class="label">Needs review</div><div class="value">${review}</div></div>
      <div class="outcome-stat"><div class="label">Rejected</div><div class="value">${rejected}</div></div>
    </div>
    <p class="tiny">Images needing verification remain outside the approved dataset until reviewed.</p>
    <h3 class="outcome-subhead">Per-image results</h3>
    <div class="outcome-images">${results.map((r) => `
      <div class="image-card"><div class="zoomable"><img src="${r.output_url}" alt="${escapeHtml(r.display_name)}"><button type="button" class="zoom-btn" data-url="${r.output_url}" data-name="${escapeHtml(r.display_name)}">⤢</button></div>
      <div class="image-card-body"><div class="image-card-name">${escapeHtml(r.display_name)}</div><span class="status ${r.review_status.toLowerCase()}">${statusLabel(r.review_status)}</span><p class="tiny">Faces: ${r.faces} · Plates: ${r.plates} · Text PII: ${r.text_pii}</p></div></div>`).join('')}</div>`;
  wireZoomButtons();
}

// ---------------- dashboard ----------------
async function loadDashboard() {
  const stats = $('#stats');
  if (!stats) return;
  try {
    const response = await fetch('/api/dashboard');
    if (response.status === 401) { showAuthView(); return; }
    if (!response.ok) return;
    const data = await response.json();
    currentUser = data.user;
    $$('.username').forEach((el) => { el.textContent = data.user.username; });
    if ($('#sidebarUser')) $('#sidebarUser').textContent = data.user.username;
    const counts = data.counts || {};
    stats.innerHTML = `
      <div class="stat"><div class="label">Processed</div><div class="value">${counts.processed ?? 0}</div><div class="note">Images run through the pipeline</div></div>
      <div class="stat"><div class="label">Approved</div><div class="value">${counts.approved ?? 0}</div><div class="note">Cleared for annotation</div></div>
      <div class="stat"><div class="label">Needs review</div><div class="value">${counts.review ?? 0}</div><div class="note">Awaiting human verification</div></div>
      <div class="stat"><div class="label">Rejected</div><div class="value">${counts.rejected ?? 0}</div><div class="note">Removed from the dataset</div></div>`;
    updatePipeline(counts);
  } catch (error) { console.error('Dashboard error:', error); }
}

function updatePipeline(counts) {
  const processed = counts.processed ?? 0;
  const approved = counts.approved ?? 0;
  const setActive = (id, active) => $(`#${id}`)?.classList.toggle('active', active);
  setActive('pipeStep1', true);
  setActive('pipeStep2', processed > 0);
  setActive('pipeStep3', processed > 0);
  setActive('pipeStep4', processed > 0);
  setActive('pipeStep5', approved > 0);
}

// ---------------- review ----------------
async function loadReview() {
  const container = $('#reviewList');
  if (!container) return;
  container.innerHTML = '<div class="muted">Loading review queue...</div>';
  try {
    const response = await fetch('/api/results');
    if (response.status === 401) { showAuthView(); return; }
    const data = await response.json();
    const pending = (data.results || []).filter((r) => r.review_status === 'REVIEW');
    if (!pending.length) { container.innerHTML = '<div class="empty"><strong>No images waiting for review.</strong><br><span class="tiny">Low-confidence results will appear here after processing.</span></div>'; return; }
    container.innerHTML = pending.map((item) => `
      <div class="review-item"><div class="zoomable"><img src="${item.output_url}" alt="${escapeHtml(item.display_name)}"><button type="button" class="zoom-btn" data-url="${item.output_url}" data-name="${escapeHtml(item.display_name)}">⤢</button></div>
      <div class="review-info"><span class="status review">Needs review</span><h3>${escapeHtml(item.display_name)}</h3><p class="tiny">Faces: ${item.faces} · Plates: ${item.plates} · Text PII: ${item.text_pii}</p><p class="muted">Inspect the protected image, then confirm whether it is safe for annotation.</p><div class="review-actions"><button class="primary approve-btn" data-filename="${escapeHtml(item.filename)}">Approve</button><button class="secondary reject-btn" data-filename="${escapeHtml(item.filename)}">Reject</button></div></div></div>`).join('');
    $$('.approve-btn').forEach((b) => b.addEventListener('click', () => updateReview(b.dataset.filename, 'approve')));
    $$('.reject-btn').forEach((b) => b.addEventListener('click', () => updateReview(b.dataset.filename, 'reject')));
    wireZoomButtons();
  } catch (error) { console.error('Review error:', error); container.innerHTML = '<div class="empty">Unable to load review queue.</div>'; }
}

async function updateReview(filename, action) {
  try {
    const response = await fetch(`/api/review/${encodeURIComponent(filename)}/${action}`, { method: 'POST' });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || 'Unable to update review.');
    await loadReview();
    await loadDashboard();
  } catch (error) { console.error(error); alert(error.message); }
}

// ---------------- approved dataset ----------------
async function loadApproved() {
  const container = $('#approvedGrid');
  const countEl = $('#approvedCount');
  if (!container) return;
  container.innerHTML = '<div class="muted">Loading approved dataset...</div>';
  try {
    const response = await fetch('/api/approved');
    if (response.status === 401) { showAuthView(); return; }
    const data = await response.json();
    const images = data.images || [];
    if (countEl) countEl.textContent = `${images.length} image${images.length === 1 ? '' : 's'} ready for delivery`;
    if (!images.length) { container.innerHTML = '<div class="empty">No approved images yet.</div>'; return; }
    container.innerHTML = images.map((item) => `
      <div class="image-card"><div class="zoomable"><img src="${item.url}" alt="${escapeHtml(item.filename)}"><button type="button" class="zoom-btn" data-url="${item.url}" data-name="${escapeHtml(item.filename)}">⤢</button></div>
      <div class="image-card-body"><div class="image-card-name">${escapeHtml(item.filename)}</div><span class="status approved">Approved</span>${item.faces != null ? `<p class="tiny">Faces: ${item.faces} · Plates: ${item.plates} · Text PII: ${item.text_pii}</p>` : ''}</div></div>`).join('');
    wireZoomButtons();
  } catch (error) { console.error('Approved dataset error:', error); container.innerHTML = '<div class="empty">Unable to load approved dataset.</div>'; }
}

// ---------------- Xtreme1 ----------------
async function loadUnifiedDeliveryReady() {
  const readyEl = $('#deliveryReadyMessage');
  if (!readyEl) return;
  try {
    const response = await fetch('/api/delivery/pending');
    if (response.status === 401) { showAuthView(); return; }
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || 'Unable to load delivery queue.');
    const images = data.images || [];
    const apiCount = data.counts?.api ?? images.filter((item) => item.source === 'API').length;
    const privacyHubCount = data.counts?.privacyhub ?? images.filter((item) => item.source === 'PRIVACYHUB').length;
    if (!images.length) {
      readyEl.textContent = 'No approved images are ready for delivery.';
      return;
    }
    const destination = getApiDestination();
    if (destination === 'RETURN') {
      readyEl.textContent = apiCount
        ? `${apiCount} approved API image${apiCount === 1 ? '' : 's'} ready to return.`
        : 'No approved API images are ready for Return Image.';
    } else if (destination === 'XTREME1') {
      readyEl.textContent = `${images.length} approved image${images.length === 1 ? '' : 's'} ready for Xtreme1 (${apiCount} API, ${privacyHubCount} PrivacyHub).`;
    } else {
      readyEl.textContent = 'Webhook delivery is coming soon.';
    }
  } catch (error) {
    console.error('Unified delivery queue error:', error);
    readyEl.textContent = 'Unable to load approved images for delivery.';
  }
}

$('#verifyDataset')?.remove();
$('#exportBtn')?.remove();

function getApiDestination() {
  return document.querySelector('input[name="apiDestination"]:checked')?.value || 'RETURN';
}

function updateApiDestinationUI() {
  const destination = getApiDestination();
  $('#xtremeApiFields')?.classList.toggle('hidden', destination !== 'XTREME1');
  $('#webhookApiFields')?.classList.toggle('hidden', destination !== 'WEBHOOK');
  $$('.destination-option').forEach((option) => {
    const radio = option.querySelector('input');
    option.classList.toggle('active', radio?.checked);
  });
  loadUnifiedDeliveryReady();
}

$$('input[name="apiDestination"]').forEach((radio) => {
  radio.addEventListener('change', updateApiDestinationUI);
});

async function runApiDelivery() {
  const message = $('#apiDeliveryMessage');
  const button = $('#apiDeliveryBtn');
  const destination = getApiDestination();

  if (destination === 'XTREME1') {
    const datasetId = $('#apiDatasetId')?.value?.trim() || '';
    const token = $('#apiXtremeToken')?.value?.trim() || '';
    if (!datasetId) { if (message) message.textContent = 'Enter the Xtreme1 Dataset ID.'; return; }
    if (!token) { if (message) message.textContent = 'Enter the Xtreme1 Bearer Token.'; return; }
  }

  if (destination === 'WEBHOOK') {
    if (message) message.textContent = 'Webhook delivery is reserved for the next API phase.';
    return;
  }

  button.disabled = true;
  button.innerHTML = 'Delivering...';
  if (message) message.textContent = 'Delivering approved images...';

  try {
    const queueResponse = await fetch('/api/delivery/pending');
    const queueData = await queueResponse.json();
    if (!queueResponse.ok) throw new Error(queueData.detail || 'Unable to load delivery queue.');
    let images = queueData.images || [];

    if (destination === 'RETURN') {
      images = images.filter((item) => item.source === 'API');
    }

    if (!images.length) {
      if (message) {
        message.textContent = destination === 'RETURN'
          ? 'No approved API images are ready for Return Image.'
          : 'No approved images are ready for Xtreme1.';
      }
      return;
    }

    let delivered = 0;
    let failed = 0;
    const errors = [];

    for (const item of images) {
      const formData = new FormData();
      formData.append('filename', item.filename);
      formData.append('source', item.source);
      formData.append('destination', destination);
      if (destination === 'XTREME1') formData.append('dataset_id', $('#apiDatasetId').value.trim());
      const headers = {};
      if (destination === 'XTREME1') headers['X-Xtreme1-Token'] = $('#apiXtremeToken').value.trim();

      const response = await fetch('/api/delivery/run', { method: 'POST', headers, body: formData });
      const data = await response.json();
      if (!response.ok) {
        failed += 1;
        errors.push(`${item.original_filename}: ${data.detail || 'delivery failed'}`);
        continue;
      }
      delivered += 1;
    }

    if (message) {
      if (failed) {
        message.textContent = `${delivered} delivered, ${failed} failed. ${errors[0] || ''}`;
      } else if (destination === 'RETURN') {
        message.textContent = `${delivered} image${delivered === 1 ? '' : 's'} marked ready for return to the calling application.`;
      } else {
        message.textContent = `${delivered} image${delivered === 1 ? '' : 's'} delivered to Xtreme1.`;
      }
    }

    await loadUnifiedDeliveryReady();
    await loadApproved();
    await loadDashboard();
  } catch (error) {
    console.error('Delivery error:', error);
    if (message) message.textContent = error.message || 'Delivery failed.';
  } finally {
    button.disabled = false;
    button.innerHTML = 'Run Delivery <span>→</span>';
  }
}

$('#apiDeliveryBtn')?.addEventListener('click', runApiDelivery);

updateApiDestinationUI();

// ---------------- initial load ----------------
document.addEventListener('DOMContentLoaded', async () => {
  renderPreviews();
  try {
    const response = await fetch('/api/auth/me');
    if (response.ok) {
      const data = await response.json();
      currentUser = data.user;
      onAuthenticated();
    } else showAuthView();
  } catch (error) { showAuthView(); }
});
