const API_URL = 'https://us-east1-nyc-health-law-bot.cloudfunctions.net/law-bot';

const CODE_FILES = {
  'NYC Health Code':  'data/nyc-health-code.json',
  'NYC Admin Code':   'data/nyc-admin-code.json',
  'NYS Sanitary Code': 'data/nys-sanitary-code.json',
};
const sectionCache = {};  // filename -> { section: fullText }

const form        = document.getElementById('search-form');
const input       = document.getElementById('question');
const loadingEl   = document.getElementById('loading');
const errorEl     = document.getElementById('error');
const errorMsg    = document.getElementById('error-msg');
const resultsEl   = document.getElementById('results');
const summaryEl   = document.getElementById('summary');
const citationsEl = document.getElementById('citations');
const additionalEl = document.getElementById('additional');
const additionalSection = document.getElementById('additional-section');

form.addEventListener('submit', async (e) => {
  e.preventDefault();
  const question = input.value.trim();
  if (!question) return;

  setLoading(true);
  clearResults();

  try {
    const resp = await fetch(API_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt: question }),
    });
    const data = await resp.json();
    if (data.error) throw new Error(data.error);
    render(data.answer);
  } catch (err) {
    showError(err.message);
  } finally {
    setLoading(false);
  }
});

function render(answer) {
  const { summary, citations } = answer;

  // Build section-number -> anchor map for linking section-refs in summary
  const sectionMap = {};
  for (const c of citations) sectionMap[c.section] = c.anchor;

  // Render summary markdown then linkify section references
  let html = marked.parse(summary);
  html = html.replace(/§([\d.\-]+)/g, (match, sec) => {
    const anchor = sectionMap[sec];
    return anchor
      ? `<a href="#${anchor}" class="section-link" data-anchor="${anchor}">${match}</a>`
      : match;
  });
  summaryEl.innerHTML = html;

  // Clicking a section-link scrolls to and expands the citation
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

  const cited      = citations.filter(c => c.cited_in_summary);
  const additional = citations.filter(c => !c.cited_in_summary);

  citationsEl.innerHTML = '';
  cited.forEach(c => citationsEl.appendChild(makeCard(c)));

  additionalEl.innerHTML = '';
  additionalSection.hidden = additional.length === 0;
  additional.forEach(c => additionalEl.appendChild(makeCard(c)));

  resultsEl.hidden = false;
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
    body.innerHTML = highlightPassages(text, citation.relevant_passages);
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

function setLoading(on) {
  loadingEl.hidden = !on;
}

function showError(msg) {
  errorMsg.textContent = msg;
  errorEl.hidden = false;
}

function clearResults() {
  errorEl.hidden = true;
  resultsEl.hidden = true;
  summaryEl.innerHTML = '';
  citationsEl.innerHTML = '';
  additionalEl.innerHTML = '';
}
