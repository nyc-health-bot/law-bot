const API_URL = 'https://us-east1-nyc-health-law-bot.cloudfunctions.net/law-bot';

// --- SESSION ---

let _sessionId = sessionStorage.getItem('session_id');
if (!_sessionId) {
  _sessionId = crypto.randomUUID();
  sessionStorage.setItem('session_id', _sessionId);
}

// --- AUTH ---

let _authToken = null;
let _lastPrompt = '';

const authGateEl     = document.getElementById('auth-gate');
const searchSection  = document.getElementById('search-section');
const authFormEl     = document.getElementById('auth-form');
const authEmailEl    = document.getElementById('auth-email');
const authSubmitEl   = document.getElementById('auth-submit');
const authMsgEl      = document.getElementById('auth-msg');

function showAuthGate(message, isError) {
  authGateEl.hidden = false;
  searchSection.hidden = true;
  if (message) {
    authMsgEl.textContent = message;
    authMsgEl.className = isError === false ? 'success' : 'error';
    authMsgEl.hidden = false;
  }
}

function showSearch(token) {
  _authToken = token;
  authGateEl.hidden = true;
  searchSection.hidden = false;
}

// AUTH TEMPORARILY DISABLED — skip login gate
(async function initAuth() {
  showSearch('disabled');
})();

authFormEl.addEventListener('submit', async (e) => {
  e.preventDefault();
  const email = authEmailEl.value.trim().toLowerCase();

  authSubmitEl.disabled = true;
  authSubmitEl.textContent = 'Sending…';
  authMsgEl.hidden = true;

  try {
    const resp = await fetch(API_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ type: 'send-link', email }),
    });
    const data = await resp.json();
    if (data.ok) {
      authMsgEl.textContent = `A link has been sent to ${email}. Check your inbox to access the tool.`;
      authMsgEl.className = 'success';
      authMsgEl.hidden = false;
      authEmailEl.value = '';
    } else {
      authMsgEl.textContent = data.error || 'Failed to send email. Please try again.';
      authMsgEl.className = 'error';
      authMsgEl.hidden = false;
    }
  } catch {
    authMsgEl.textContent = 'Failed to send email. Please try again.';
    authMsgEl.className = 'error';
    authMsgEl.hidden = false;
  } finally {
    authSubmitEl.disabled = false;
    authSubmitEl.textContent = 'Send Link';
  }
});

// --- SEARCH ---

const CODE_FILES = {
  'NYC Health Code':            'data/nyc-health-code.json',
  'Rules of the City of New York': 'data/nyc-rules.json',
  'NYC Admin Code':             'data/nyc-admin-code.json',
  'NYS Sanitary Code':          'data/nys-sanitary-code.json',
};
const sectionCache = {};  // filename -> { section: fullText }

const form             = document.getElementById('search-form');
const input            = document.getElementById('question');
const loadingEl        = document.getElementById('loading');
const slowMsgEl        = document.getElementById('slow-msg');
const errorEl          = document.getElementById('error');
const errorMsg         = document.getElementById('error-msg');
const resultsEl        = document.getElementById('results');
const summaryEl        = document.getElementById('summary');
const summaryPendingEl = document.getElementById('summary-pending');
const citationsEl      = document.getElementById('citations');
const citationsSection = document.getElementById('citations-section');
const additionalEl     = document.getElementById('additional');
const additionalSection = document.getElementById('additional-section');

form.addEventListener('submit', async (e) => {
  e.preventDefault();
  const question = input.value.trim();
  if (!question) return;

  setLoading(true);
  clearResults();

  let citations = [];
  let rawSummary = '';
  _lastPrompt = question;

  try {
    const resp = await fetch(API_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt: question, token: _authToken }),
    });

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buf += decoder.decode(value, { stream: true });
      const parts = buf.split('\n\n');
      buf = parts.pop();

      for (const part of parts) {
        if (!part.startsWith('data: ')) continue;
        let event;
        try { event = JSON.parse(part.slice(6)); } catch { continue; }

        if (event.type === 'metadata') {
          citations = event.citations;
          setLoading(false);
          renderCitationShells(citations);
          summaryPendingEl.hidden = false;
          resultsEl.hidden = false;
        } else if (event.type === 'chunk') {
          summaryPendingEl.hidden = true;
          rawSummary += event.text;
          summaryEl.textContent = rawSummary;
        } else if (event.type === 'done') {
          finalizeSummary(event.summary, event.cited_sections, citations);
        } else if (event.type === 'passages') {
          applyPassages(citations, event.passages);
          renderFeedback();
        } else if (event.type === 'auth_error') {
          setLoading(false);
          const msg = event.reason === 'expired'
            ? 'Your access link has expired. Enter your email to request a new one.'
            : 'Invalid access link. Enter your email to request a new one.';
          showAuthGate(msg);
          return;
        } else if (event.type === 'error') {
          throw new Error(event.message);
        }
      }
    }
  } catch (err) {
    showError(err.message);
    setLoading(false);
  }
});

function renderCitationShells(citations) {
  citationsEl.innerHTML = '';
  additionalEl.innerHTML = '';
  additionalSection.hidden = true;
  citations.forEach(c => citationsEl.appendChild(makeCard(c)));
}

function finalizeSummary(summary, citedSections, citations) {
  const cited = new Set(citedSections);
  const sectionMap = {};
  for (const c of citations) sectionMap[c.section] = c.anchor;

  let html = marked.parse(summary);
  html = html.replace(/§([\w.\-]+)/g, (match, sec) => {
    const anchor = sectionMap[sec];
    return anchor
      ? `<a href="#${anchor}" class="section-link" data-anchor="${anchor}">${match}</a>`
      : match;
  });
  summaryEl.innerHTML = html;

  summaryEl.querySelectorAll('a.section-link').forEach(a => {
    a.addEventListener('click', (e) => {
      e.preventDefault();
      const card = document.getElementById(a.dataset.anchor);
      if (card) {
        collapseAll();
        expandCard(card);
        card.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
    });
  });

  summaryPendingEl.hidden = true;

  const citedList      = citations.filter(c => cited.has(c.section));
  const additionalList = citations.filter(c => !cited.has(c.section));

  citationsEl.innerHTML = '';
  citationsSection.hidden = citedList.length === 0;
  citedList.forEach(c => { c.cited_in_summary = true; citationsEl.appendChild(makeCard(c)); });

  additionalEl.innerHTML = '';
  additionalSection.hidden = additionalList.length === 0;
  additionalList.forEach(c => { c.cited_in_summary = false; additionalEl.appendChild(makeCard(c)); });
}

function applyPassages(citations, passages) {
  for (const [idx, passList] of Object.entries(passages)) {
    const c = citations[parseInt(idx)];
    if (c) c.relevant_passages = passList;
  }
  // Re-render any already-expanded card bodies with highlights
  document.querySelectorAll('.citation-card').forEach(card => {
    const body = card.querySelector('.citation-body');
    if (body.dataset.loaded && body._fullText && card._citation && card._citation.relevant_passages) {
      body.innerHTML = highlightPassages(body._fullText, card._citation.relevant_passages);
    }
  });
}

function makeCard(citation) {
  const card = document.createElement('div');
  card.className = 'citation-card';
  card.id = citation.anchor;
  card._citation = citation;

  const codeLabel = citation.full_title.replace(/§[\d.\-]+/, '').trim();

  const header = document.createElement('div');
  header.className = 'citation-header';
  header.innerHTML =
    `<span class="section-id">§${escHtml(citation.section)}</span>` +
    `<span class="section-title">${escHtml(citation.section_title || '')}</span>` +
    `<span class="code-label">${escHtml(codeLabel)}</span>` +
    `<span class="toggle-icon">▶</span>`;

  const body = document.createElement('div');
  body.className = 'citation-body';
  body.hidden = true;

  header.addEventListener('click', () => toggleCard(card));

  card.appendChild(header);
  card.appendChild(body);
  return card;
}

async function toggleCard(card) {
  const body = card.querySelector('.citation-body');
  const icon = card.querySelector('.toggle-icon');
  if (!body.hidden) {
    body.hidden = true;
    icon.textContent = '▶';
  } else {
    collapseAll();
    await expandCard(card);
  }
}

function collapseAll() {
  document.querySelectorAll('.citation-card').forEach(c => {
    c.querySelector('.citation-body').hidden = true;
    c.querySelector('.toggle-icon').textContent = '▶';
  });
}

async function expandCard(card) {
  const body = card.querySelector('.citation-body');
  const icon = card.querySelector('.toggle-icon');
  if (!body.dataset.loaded) {
    body.textContent = 'Loading…';
    body.hidden = false;
    icon.textContent = '▼';
    const citation = card._citation;
    const text = await fetchSectionText(citation);
    body._fullText = text;
    body.innerHTML = highlightPassages(text, citation.relevant_passages || []);
    body.dataset.loaded = '1';
  } else {
    body.hidden = false;
    icon.textContent = '▼';
  }
}

async function fetchSectionText(citation) {
  const filename = CODE_FILES[citation.code];
  if (!filename) return citation.text;
  if (!sectionCache[filename]) {
    try {
      const resp = await fetch(filename);
      sectionCache[filename] = await resp.json();
    } catch {
      return citation.text;  // fallback to chunk text on network error
    }
  }
  return sectionCache[filename][citation.section] || citation.text;
}

function highlightPassages(text, passages) {
  if (!passages || passages.length === 0) return escHtml(text.trim());

  const ranges = [];
  for (const p of passages) {
    // Exact match first, then whitespace-normalized fallback
    let start = text.indexOf(p);
    if (start !== -1) {
      ranges.push({ start, end: start + p.length });
    } else {
      const r = findNormalized(text, p);
      if (r) ranges.push(r);
    }
  }
  ranges.sort((a, b) => a.start - b.start);

  let html = '';
  let pos = 0;
  for (const r of ranges) {
    if (r.start < pos) continue;
    html += escHtml(text.slice(pos, r.start));
    html += `<mark>${escHtml(text.slice(r.start, r.end))}</mark>`;
    pos = r.end;
  }
  html += escHtml(text.slice(pos));
  return html;
}

// Finds passage in text after collapsing all whitespace including non-breaking
// spaces ( ) common in scraped PDFs, then maps back to original indices.
function findNormalized(text, passage) {
  const isSpace = c => /\s/.test(c) || c === ' ' || c === ' ' || c === ' ';
  const origIdx = [];
  let prevSpace = false;
  for (let i = 0; i < text.length; i++) {
    if (isSpace(text[i])) {
      if (!prevSpace) { origIdx.push(i); prevSpace = true; }
    } else {
      origIdx.push(i);
      prevSpace = false;
    }
  }
  const normText    = origIdx.map(i => isSpace(text[i]) ? ' ' : text[i]).join('');
  const normPassage = passage.split('').map(c => isSpace(c) ? ' ' : c).join('').replace(/ +/g, ' ').trim();
  const ni = normText.indexOf(normPassage);
  if (ni === -1) {
    console.warn('Passage not found:', JSON.stringify(passage.slice(0, 80)));
    return null;
  }
  return { start: origIdx[ni], end: origIdx[ni + normPassage.length - 1] + 1 };
}

function escHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

let _slowTimer = null;

function setLoading(on) {
  loadingEl.hidden = !on;
  slowMsgEl.hidden = true;
  clearTimeout(_slowTimer);
  if (on) _slowTimer = setTimeout(() => { slowMsgEl.hidden = false; }, 8000);
}

function showError(msg) {
  errorMsg.textContent = msg;
  errorEl.hidden = false;
}

function clearResults() {
  errorEl.hidden = true;
  resultsEl.hidden = true;
  summaryPendingEl.hidden = true;
  summaryEl.innerHTML = '';
  citationsEl.innerHTML = '';
  citationsSection.hidden = true;
  additionalEl.innerHTML = '';
  const fb = document.getElementById('feedback-section');
  if (fb) fb.remove();
}

// --- FEEDBACK ---

function renderFeedback() {
  const existing = document.getElementById('feedback-section');
  if (existing) existing.remove();

  const section = document.createElement('section');
  section.id = 'feedback-section';

  const label = document.createElement('p');
  label.className = 'feedback-label';
  label.textContent = 'Was this answer helpful?';

  const starsEl = document.createElement('div');
  starsEl.className = 'star-rating';

  for (let i = 1; i <= 5; i++) {
    const star = document.createElement('button');
    star.type = 'button';
    star.className = 'star';
    star.dataset.value = i;
    star.textContent = '★';
    star.setAttribute('aria-label', `${i} star${i > 1 ? 's' : ''}`);
    star.addEventListener('mouseover', () => highlightStars(starsEl, i));
    star.addEventListener('mouseout', () => highlightStars(starsEl, starsEl.dataset.rating || 0));
    star.addEventListener('click', () => selectRating(section, starsEl, i));
    starsEl.appendChild(star);
  }

  section.appendChild(label);
  section.appendChild(starsEl);
  resultsEl.appendChild(section);
}

function highlightStars(container, count) {
  count = parseInt(count) || 0;
  container.querySelectorAll('.star').forEach((s, idx) => {
    s.classList.toggle('lit', idx < count);
  });
}

function selectRating(section, starsEl, rating) {
  starsEl.dataset.rating = rating;
  highlightStars(starsEl, rating);
  starsEl.querySelectorAll('.star').forEach(s => s.disabled = true);

  const existing = section.querySelector('.feedback-response');
  if (existing) existing.remove();

  if (rating <= 3) {
    renderFeedbackForm(section, rating);
  } else {
    const thanks = document.createElement('p');
    thanks.className = 'feedback-response feedback-thanks';
    thanks.textContent = 'Thank you for the feedback!';
    section.appendChild(thanks);
    submitFeedback(rating, '', '');
  }
}

function renderFeedbackForm(section, rating) {
  const form = document.createElement('div');
  form.className = 'feedback-response feedback-form';

  const heading = document.createElement('p');
  heading.className = 'feedback-form-heading';
  heading.textContent = 'Help us improve — what went wrong?';

  const reasons = [
    ['wrong',      'The answer was wrong or misleading'],
    ['missing',    'Important information was missing'],
    ['unanswered', "It didn't answer my question"],
    ['confusing',  'The format was hard to follow'],
    ['other',      'Something else'],
  ];

  const radioGroup = document.createElement('div');
  radioGroup.className = 'feedback-radios';
  for (const [value, labelText] of reasons) {
    const row = document.createElement('label');
    row.className = 'feedback-radio-row';
    const input = document.createElement('input');
    input.type = 'radio';
    input.name = 'feedback-reason';
    input.value = value;
    row.appendChild(input);
    row.appendChild(document.createTextNode(' ' + labelText));
    radioGroup.appendChild(row);
  }

  const textarea = document.createElement('textarea');
  textarea.className = 'feedback-textarea';
  textarea.placeholder = 'Anything else? (optional)';
  textarea.rows = 3;

  const submitBtn = document.createElement('button');
  submitBtn.type = 'button';
  submitBtn.className = 'feedback-submit';
  submitBtn.textContent = 'Send feedback';
  submitBtn.addEventListener('click', () => {
    const selected = form.querySelector('input[name="feedback-reason"]:checked');
    const reason = selected ? selected.value : '';
    const comment = textarea.value.trim();
    submitFeedback(rating, reason, comment);
    form.innerHTML = '';
    const thanks = document.createElement('p');
    thanks.className = 'feedback-thanks';
    thanks.textContent = 'Thank you — your feedback helps us improve.';
    form.appendChild(thanks);
  });

  form.appendChild(heading);
  form.appendChild(radioGroup);
  form.appendChild(textarea);
  form.appendChild(submitBtn);
  section.appendChild(form);
}

async function submitFeedback(rating, reason, comment) {
  try {
    await fetch(API_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        type: 'feedback',
        session_id: _sessionId,
        prompt: _lastPrompt,
        rating,
        reason,
        comment,
      }),
    });
  } catch {
    // best-effort; ignore network errors
  }
}
