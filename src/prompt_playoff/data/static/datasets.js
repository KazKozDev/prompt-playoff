async function loadDatasets(selectedName) {
  try {
    const list = await api('/v1/datasets');
    state.datasetSizes = new Map(list.map(d => [d.name, d.examples]));
    $('dataset').innerHTML = list.map(d => `<option value="${esc(d.name)}">${esc(d.name)} — ${d.examples} examples</option>`).join('');
    if (selectedName && list.some(d => d.name === selectedName)) $('dataset').value = selectedName;
    updateEstimates();
    updateWorkspaceContext();
    refreshActions();
    refreshHomeIfVisible();
    return list;
  } catch (e) {
    state.datasetSizes = new Map();
    $('dataset').innerHTML = '<option>no datasets</option>';
    updateEstimates();
    updateWorkspaceContext();
    if (selectedName) throw e;
    return [];
  }
}

// The split is computed server-side with Python's round(), which sends halves
// to the even neighbour; Math.round sends them up. Match it so the example
// counts shown here are the ones the optimizer will actually use.
function roundHalfToEven(value) {
  const nearest = Math.round(value);
  if (Math.abs(value - Math.trunc(value)) !== 0.5) return nearest;
  return nearest % 2 === 0 ? nearest : nearest - 1;
}

// What a click costs is invisible until it is running, and the numbers here
// reach the thousands. Spell them out while the fields can still be changed.
function updateEstimates() {
  const examples = state.datasetSizes.get($('dataset').value);
  const measure = $('measure-estimate');
  const optimize = $('optimize-estimate');
  if (!Number.isFinite(examples) || examples < 1) {
    measure.textContent = optimize.textContent = '';
    return;
  }
  const count = (value, word) => `<strong>${plural(value, word)}</strong>`;
  const repeats = Math.max(1, Number($('repeats').value) || 1);
  const rounds = Math.max(1, Number($('rounds').value) || 1);
  const perCall = Number(state.program && state.program.expected_calls) || 1;
  const calls = perCall > 1 ? `, ${perCall} model calls each` : '';

  const single = examples * repeats;
  const methods = state.recs.length;
  measure.innerHTML = `Benchmark: ${count(single, 'run')}${calls}.`
    + (methods > 1 ? ` Compare all ${methods}: ${count(single * methods, 'run')}.` : '');

  // Mirrors the optimizer defaults: a 34% held-out split, baseline plus one
  // bootstrapped candidate scored in round 1, three fresh ones per later round,
  // then baseline and winner re-scored on the held-out part.
  const holdout = Math.max(1, roundHalfToEven(examples * 0.34));
  const train = Math.max(1, examples - holdout);
  const versions = 2 + 3 * (rounds - 1);
  const runs = versions * train * repeats + 2 * holdout * repeats;
  optimize.innerHTML = `Optimize: about ${count(runs, 'run')}${calls}`
    + ` — up to ${versions} versions over ${plural(train, 'training example')},`
    + ` then baseline and winner on ${plural(holdout, 'held-out example')}.`
    + ' Writing each version costs one more call to the prompt engine.';
}

// Uploaded datasets enter the same named-dataset path used by every measure
// action; no inline examples or client-only special cases are introduced.
$('dataset-file').addEventListener('change', () => {
  $('upload-btn').disabled = !$('dataset-file').files.length;
  $('upload-status').textContent = '';
  $('upload-status').className = 'upload-status';
});

$('upload-btn').addEventListener('click', async () => {
  const input = $('dataset-file');
  const btn = $('upload-btn');
  const status = $('upload-status');
  const file = input.files[0];
  if (!file) return;

  btn.disabled = true;
  btn.textContent = 'Uploading…';
  btn.setAttribute('aria-busy', 'true');
  status.className = 'upload-status';
  status.textContent = `Uploading ${file.name}…`;
  try {
    const form = new FormData();
    form.append('file', file);
    const res = await fetch('/v1/datasets/upload', { method:'POST', body:form });
    if (!res.ok) throw new Error(await apiError(res));
    const uploaded = await res.json();
    delete datasetCache[uploaded.name];
    const datasets = await loadDatasets(uploaded.name);
    if (!datasets.some(dataset => dataset.name === uploaded.name)) throw new Error(`Uploaded ${uploaded.name}, but it is not available in the dataset list.`);
    status.className = 'upload-status success';
    status.textContent = `${uploaded.name} uploaded — ${uploaded.examples} examples. Selected for measurement.`;
  } catch (e) {
    status.className = 'upload-status error-text';
    status.textContent = e.message;
  } finally {
    btn.disabled = false;
    btn.textContent = 'Upload';
    btn.removeAttribute('aria-busy');
  }
});

// ---- finding examples on the Hugging Face Hub ------------------------------
// Three deliberate clicks: search, open a candidate, import it. Nothing is
// fetched or selected on the user's behalf, because the Hub's answer to a short
// query is often wrong and only the person who wrote the task can tell.
function hubMessage(text, kind) {
  const node = $('hub-status');
  node.textContent = text;
  node.className = 'upload-status' + (kind ? ` ${kind}` : '');
}

function hubNumber(value) {
  return Number(value || 0).toLocaleString('en-US');
}

async function runHubSearch() {
  const description = ($('hub-task') || $('description')).value.trim();
  if (!description) {
    hubMessage('Describe the task above first — the search is built from your words.', 'error-text');
    ($('hub-task') || $('description')).focus();
    return;
  }
  const btn = $('hub-btn');
  btn.disabled = true;
  btn.textContent = 'Searching…';
  btn.setAttribute('aria-busy', 'true');
  hubMessage('Asking the Hugging Face Hub…');
  $('hub-results').innerHTML = '';
  try {
    const found = await api('/v1/datasets/hub/search', {
      description,
      // Known only after a prompt exists; the search works without it, just wider.
      task_type: (state.task && state.task.task_type) || null,
      engine_model: engineProfile()
    });
    state.hub = { ...found, open:null, preview:null };
    hubMessage(found.candidates.length
      ? `${plural(found.candidates.length, 'candidate')} — check that the examples look like your inputs before importing.`
      : 'Nothing matched. Try naming the material in English, or upload your own examples.');
    renderHubResults();
  } catch (e) {
    hubMessage(e.message, 'error-text');
  } finally {
    btn.disabled = false;
    btn.textContent = 'Search Hugging Face';
    btn.removeAttribute('aria-busy');
  }
}

/* --------------------------------------------------------------------------
 * Importing examples is a screen, not a button in a disclosure: it is one of
 * the three answers to "where do examples come from", and the only thing in the
 * app that touches the network. The task text is the same one the prompt uses —
 * edited here, it is edited there.
 * -------------------------------------------------------------------------- */
function renderDatasetHub() {
  return `<section class="hub-search">
    <label for="hub-task">What your prompt has to do</label>
    <textarea id="hub-task" rows="3">${esc($('description')?.value || '')}</textarea>
    <p class="field-hint">The query is built from these words — edit them here if the search comes back off-target. This is the same task the prompt uses.</p>
    <button id="hub-btn" class="primary" type="button" data-testid="hub-search">Search Hugging Face</button>
    <div id="hub-status" class="upload-status" role="status" aria-live="polite"></div>
    <div id="hub-results" class="hub-results"></div>
  </section>`;
}

function wireDatasetHub(panel) {
  const task = panel.querySelector('#hub-task');
  task?.addEventListener('input', () => { const field = $('description'); if (field) field.value = task.value; });
  panel.querySelector('#hub-btn')?.addEventListener('click', runHubSearch);
  if (state.hub) renderHubResults();
}

function renderHubResults() {
  const node = $('hub-results');
  if (!state.hub || !state.hub.candidates.length) { node.innerHTML = ''; return; }
  const { queries, source, candidates, open, notes } = state.hub;
  const how = source === 'engine' ? 'written by the prompt engine' : 'taken from your wording';
  // Above the cards: a list that answers nothing the user asked still looks
  // like six good datasets, and the cards themselves cannot say so.
  node.innerHTML = (notes || []).map(note => `<div class="warning">${esc(note)}</div>`).join('')
    + `<div class="hub-queries">Searched for ${queries.map(q => `<code>${esc(q)}</code>`).join(', ')} — ${how}.</div>`
    + candidates.map(item => hubCard(item, item.dataset === open)).join('');
  node.querySelectorAll('.hub-pick').forEach(button => {
    button.addEventListener('click', () => openHubCandidate(button.dataset.dataset));
  });
  wireHubDetail();
}

function hubCard(item, open) {
  const facts = [
    `${hubNumber(item.downloads)} downloads`,
    item.likes ? `${hubNumber(item.likes)} likes` : '',
    item.size_category,
    ...item.task_categories.slice(0, 2)
  ].filter(Boolean);
  return `<div class="hub-card${open ? ' open' : ''}">
    <span class="hub-name">${esc(item.dataset)}</span>
    <div class="hub-facts">${facts.map(esc).join(' · ')}</div>
    ${item.summary ? `<p class="hub-summary">${esc(item.summary)}</p>` : ''}
    <a class="hub-link" href="${esc(item.url)}" target="_blank" rel="noreferrer noopener">Open on huggingface.co ↗</a><br>
    <button class="ghost hub-pick" type="button" data-dataset="${esc(item.dataset)}">${open ? 'Hide columns' : 'Look at the columns'}</button>
    ${open ? hubDetail() : ''}
  </div>`;
}

async function openHubCandidate(dataset) {
  if (state.hub.open === dataset) {
    state.hub.open = state.hub.preview = null;
    renderHubResults();
    return;
  }
  state.hub.open = dataset;
  state.hub.preview = null;
  renderHubResults();
  hubMessage(`Reading the columns of ${dataset}…`);
  try {
    state.hub.preview = await api(`/v1/datasets/hub/preview?dataset=${encodeURIComponent(dataset)}`);
    hubMessage('');
  } catch (e) {
    state.hub.open = null;
    hubMessage(e.message, 'error-text');
  }
  renderHubResults();
}

function hubDetail() {
  const preview = state.hub.preview;
  if (!preview) return '<div class="hub-detail meta">Reading its columns…</div>';
  const options = (values, selected) => values
    .map(value => `<option value="${esc(value)}"${value === selected ? ' selected' : ''}>${esc(value)}</option>`).join('');
  const columns = preview.columns.map(column => column.name);
  const sample = preview.rows[0] || {};
  const rowText = Object.entries(sample)
    .map(([key, value]) => `${key}: ${String(value === null ? '' : value).slice(0, 220)}`)
    .join('\n');
  return `<div class="hub-detail">
    <div class="hub-row">
      <div><label for="hub-config">Config</label><select id="hub-config">${options(preview.configs, preview.config)}</select></div>
      <div><label for="hub-split">Split</label><select id="hub-split">${options(preview.splits, preview.split)}</select></div>
    </div>
    <div class="hub-row">
      <div><label for="hub-input">Column to send</label><select id="hub-input">${options(columns, preview.suggested_input)}</select></div>
      <div><label for="hub-expected">Right answer</label><select id="hub-expected"><option value="">— none —</option>${options(columns, preview.suggested_expected)}</select></div>
    </div>
    ${rowText ? `<div class="hub-sample">${esc(rowText)}</div>` : ''}
    ${preview.notes.map(note => `<p class="hub-note">${esc(note)}</p>`).join('')}
    <label for="hub-limit">How many examples to import</label>
    <input id="hub-limit" type="number" value="60" min="2" max="500">
    <button id="hub-import" type="button">Import these examples</button>
  </div>`;
}

function wireHubDetail() {
  const importBtn = $('hub-import');
  if (!importBtn) return;
  // Config and split change what the columns are, so re-read them rather than
  // importing against a preview that describes a different split.
  ['hub-config', 'hub-split'].forEach(id => $(id).addEventListener('change', async () => {
    hubMessage('Reading that split…');
    try {
      state.hub.preview = await api('/v1/datasets/hub/preview'
        + `?dataset=${encodeURIComponent(state.hub.open)}`
        + `&config=${encodeURIComponent($('hub-config').value)}`
        + `&split=${encodeURIComponent($('hub-split').value)}`);
      hubMessage('');
    } catch (e) { hubMessage(e.message, 'error-text'); }
    renderHubResults();
  }));
  importBtn.addEventListener('click', async () => {
    const preview = state.hub.preview;
    importBtn.disabled = true;
    importBtn.textContent = 'Importing…';
    hubMessage(`Importing rows from ${state.hub.open}…`);
    try {
      const imported = await api('/v1/datasets/hub/import', {
        dataset: state.hub.open,
        config: $('hub-config').value || preview.config,
        split: $('hub-split').value || preview.split,
        input_column: $('hub-input').value,
        expected_column: $('hub-expected').value || null,
        limit: Number($('hub-limit').value)
      });
      delete datasetCache[imported.name];
      await loadDatasets(imported.name);
      state.hub.open = state.hub.preview = null;
      renderHubResults();
      const graded = imported.has_expected
        ? `${imported.has_expected} carry a right answer`
        : 'none carry a right answer, so quality cannot be scored';
      const kept = imported.saved_to ? ` Saved to ${imported.saved_to}, so it survives a restart.` : '';
      hubMessage(`${imported.name} imported — ${plural(imported.examples, 'example')}, ${graded}. Selected for measurement.${kept}`, 'success');
    } catch (e) {
      hubMessage(e.message, 'error-text');
      importBtn.disabled = false;
      importBtn.textContent = 'Import these examples';
    }
  });
}

// Backends whose dependency is missing are shown but disabled, so the option
// list explains what is possible rather than failing at click time.

const datasetCache = {};
async function firstExample() {
  const name = $('dataset').value;
  if (!name) return null;
  if (!datasetCache[name]) {
    try { datasetCache[name] = await api(`/v1/datasets/${encodeURIComponent(name)}`); }
    catch { return null; }
  }
  return datasetCache[name][0] || null;
}
