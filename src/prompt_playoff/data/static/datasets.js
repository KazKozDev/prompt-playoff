async function loadDatasets(selectedName) {
  try {
    const list = await api('/v1/datasets');
    state.datasetSizes = new Map(list.map(d => [d.name, d.examples]));
    // What the listing knows about a set beyond how many rows it has. The
    // shelf of bundled benchmarks reads the tags from here to say which of them
    // came out of somebody else's corpus, rather than being told in prose that
    // can drift away from the rows.
    state.datasetFacts = new Map(list.map(d => [d.name, d]));
    const names = list.map(d => d.name);
    // Nothing is chosen for you. The set decides what every number on every
    // screen is worth, so falling back to whichever set happened to sort first
    // meant the bar reported a choice nobody made — and a measurement taken on
    // it looked exactly like one that had been aimed. A set that has gone away
    // is dropped for the same reason: better an empty field than a stale name.
    if (selectedName && names.includes(selectedName)) state.run.dataset = selectedName;
    if (state.run.dataset && !names.includes(state.run.dataset)) state.run.dataset = '';
    refreshRunSetup();
    updateEstimates();
    updateWorkspaceContext();
    refreshActions();
    refreshHomeIfVisible();
    return list;
  } catch (e) {
    state.datasetSizes = new Map();
    state.datasetFacts = new Map();
    state.run.dataset = '';
    refreshRunSetup();
    updateEstimates();
    updateWorkspaceContext();
    if (selectedName) throw e;
    return [];
  }
}

/* The mapping from business work to public datasets, fetched once a session.
 * It is a file on the server rather than a request to anything, so a failure
 * here is a broken install and not an outage — but the library screen still
 * has two working zones without it, so the error is shown in its own zone
 * rather than taking the screen down. */
async function loadBusinessCatalog() {
  if (state.catalog) return state.catalog;
  try {
    state.catalog = await api('/v1/datasets/catalog');
    state.catalogError = '';
  } catch (error) {
    state.catalog = null;
    state.catalogError = error.message;
  }
  return state.catalog;
}

// The split is computed server-side with Python's round(), which sends halves
// to the even neighbour; Math.round sends them up. Match it so the example
// counts shown here are the ones the optimizer will actually use.
function roundHalfToEven(value) {
  const nearest = Math.round(value);
  if (Math.abs(value - Math.trunc(value)) !== 0.5) return nearest;
  return nearest % 2 === 0 ? nearest : nearest - 1;
}

/* A set opened on its own is opened to be looked at, and a row saying "agents,
 * 120, bundled" is what the list already said. So the rows themselves are
 * fetched — the material every score on this server is computed against — and
 * only then: one set, asked for once, cached for the session. */
async function loadDatasetRows(name) {
  if (!name || state.datasetRows.has(name)) return;
  state.datasetRows.set(name, {status:'loading'});
  try {
    state.datasetRows.set(name, {status:'ready', rows: await api(`/v1/datasets/${encodeURIComponent(name)}`)});
  } catch (error) {
    state.datasetRows.set(name, {status:'error', error:error.message});
  }
  // Two screens wait on this: the library opened on one set, and a measurement
  // opened on one example, which needs the row to say what was asked.
  if (state.tab === 'dataset-library' && showingOn('dataset-library') === name) renderDetailPanel('dataset-library');
  if (state.tab === 'report' && state.report?.dataset === name) renderDetailPanel('report');
}

// What a click costs is invisible until it is running, and the numbers here
// reach the thousands. Spell them out while the fields can still be changed.
function updateEstimates() {
  const examples = state.datasetSizes.get(state.run.dataset);
  // Either estimate may be off-screen: each lives on the screen that runs it.
  const measure = $('measure-estimate');
  const optimize = $('optimize-estimate');
  if (!Number.isFinite(examples) || examples < 1) {
    if (measure) measure.textContent = '';
    if (optimize) optimize.textContent = '';
    return;
  }
  const count = (value, word) => `<strong>${plural(value, word)}</strong>`;
  const repeats = Math.max(1, Number(state.run.repeats) || 1);
  const rounds = Math.max(1, Number(state.run.rounds) || 1);
  const perCall = Number(state.program && state.program.expected_calls) || 1;
  const calls = perCall > 1 ? `, ${perCall} model calls each` : '';

  const single = examples * repeats;
  const methods = state.recs.length;
  if (measure) measure.innerHTML = `Benchmark: ${count(single, 'run')}${calls}.`
    + (methods > 1 ? ` Compare all ${methods}: ${count(single * methods, 'run')}.` : '');

  // Mirrors the optimizer defaults: a 34% held-out split, baseline plus one
  // bootstrapped candidate scored in round 1, three fresh ones per later round,
  // then baseline and winner re-scored on the held-out part.
  const holdout = Math.max(1, roundHalfToEven(examples * 0.34));
  const train = Math.max(1, examples - holdout);
  const versions = 2 + 3 * (rounds - 1);
  const runs = versions * train * repeats + 2 * holdout * repeats;
  if (optimize) optimize.innerHTML = `Optimize: about ${count(runs, 'run')}${calls}`
    + ` — up to ${versions} versions over ${plural(train, 'training example')},`
    + ` then baseline and winner on ${plural(holdout, 'held-out example')}.`
    + ' Writing each version costs one more call to the prompt engine.';
}

/* --------------------------------------------------------------------------
 * Bringing your own examples is a screen, not a file input tucked into a panel:
 * it is one of the three answers to "where do examples come from". Uploaded
 * sets enter the same named-dataset path every measure action uses; no inline
 * examples and no client-only special cases.
 *
 * The screen is two blocks beside the rail rather than one column: the control
 * that takes the file sits next to the rail, a block of its own rather than a
 * field with four hints under it, and what the file has to be holds the wider
 * half beside it — it is reference, and reference wants the room.
 * -------------------------------------------------------------------------- */
function renderDatasetUpload() {
  return `<div class="screen-split">
    <section class="screen-body">
      <h2>Upload</h2>
      <label for="dataset-file">Your examples, as JSONL</label>
      <div class="upload-row">
        <input id="dataset-file" type="file" accept=".jsonl,application/x-ndjson,application/jsonl" aria-describedby="upload-status">
        <button id="upload-btn" class="primary upload-btn" type="button" data-action="upload-dataset" disabled>Upload</button>
      </div>
      <div id="upload-status" class="upload-status" role="status" aria-live="polite"></div>
      <p class="field-hint">One example per line, up to 10 MiB. The count you get back is the number of rows every later score is an average over.</p>
      <!-- Off by default, and asked rather than assumed: these rows came off the
           reader's own machine, and writing them to disk is a promise to make on
           purpose. Off, the set behaves as it always has — usable now, gone when
           the server restarts. -->
      <label class="keep-rows"><input type="checkbox" id="upload-keep">
        <span><strong>Keep on this machine</strong><small>Writes the rows next to your measurements, so the set is
          still here after a restart. Leave it off and they live in this server's memory only — every run you
          record against them stays in Results afterwards, naming a set this server no longer has.</small></span></label>
    </section>
    <aside class="screen-guide" data-testid="upload-guide">
      <h2>What the file has to be</h2>
      <p class="guide-lead">JSONL: one JSON object per line, not one array. Blank lines are skipped; the first line that will not parse fails the whole upload by its line number, and nothing from that file is kept.</p>
      <pre class="guide-sample">{"id":"1","input":"Ada Lovelace worked in London.","expected":{"people":["Ada Lovelace"],"places":["London"]}}
{"id":"2","input":"Nobody is named here.","expected":{"people":[],"places":[]}}</pre>
      <dl class="guide-fields">
        <div>
          <dt>id</dt>
          <dd>Required. Your name for the row, so a failure in a report points back at something you recognise.</dd>
        </div>
        <div>
          <dt>input</dt>
          <dd>Required. What the prompt is given, one row per run.</dd>
        </div>
        <div>
          <dt>expected</dt>
          <dd>The answer it should have produced — a string, or an object when the task returns JSON. Leave it out and the graders that compare an answer have nothing to compare.</dd>
        </div>
        <div>
          <dt>response_schema<br>graders<br>tags</dt>
          <dd>Optional. A JSON Schema the answer must fit, the graders to run instead of the ones inferred from your rows, and labels of your own.</dd>
        </div>
      </dl>
      <h3>What happens after you press Upload</h3>
      <ol class="guide-steps">
        <li>Every line is parsed and counted before anything is stored.</li>
        <li>The set is selected for measurement straight away — the score you get next is computed against your rows, not the demo ones.</li>
        <li>It appears in the <a href="#dataset-library" data-global-tab="dataset-library">dataset library</a>, named <code>uploaded:</code> plus your file name.</li>
      </ol>
      <p class="guide-note">UTF-8. A kept set is written as a JSONL file next to your measurements, where ordinary
        tools can read, copy or delete it.</p>
      <p class="guide-note">No file of your own yet? <a href="#dataset-add/hugging-face" data-global-tab="dataset-add" data-mode="hugging-face">Import one from Hugging Face</a> or <a href="#dataset-add/generate" data-global-tab="dataset-add" data-screen="dataset-add" data-mode="generate">build one from your task</a>.</p>
    </aside>
  </div>`;
}

async function runUpload() {
  const input = $('dataset-file');
  const btn = $('upload-btn');
  const status = $('upload-status');
  const file = input.files[0];
  if (!file) return;

  btn.disabled = true;
  btn.textContent = 'Uploading';
  btn.setAttribute('aria-busy', 'true');
  status.className = 'upload-status';
  status.textContent = `Uploading ${file.name}…`;
  try {
    const form = new FormData();
    form.append('file', file);
    form.append('keep', $('upload-keep')?.checked ? 'true' : 'false');
    const res = await fetch('/v1/datasets/upload', { method:'POST', body:form });
    if (!res.ok) throw new Error(await apiError(res));
    const uploaded = await res.json();
    delete datasetCache[uploaded.name];
    const datasets = await loadDatasets(uploaded.name);
    if (!datasets.some(dataset => dataset.name === uploaded.name)) throw new Error(`Uploaded ${uploaded.name}, but it is not available in the dataset list.`);
    status.className = 'upload-status success';
    // Which of the two promises was made is said back, because the difference
    // only shows up on the day the server restarts.
    status.textContent = `${uploaded.name} uploaded — ${uploaded.examples} examples. Selected for measurement.`
      + (uploaded.kept ? ' Kept on this machine.' : ' Held for this server session only.');
  } catch (e) {
    status.className = 'upload-status error-text';
    status.textContent = e.message;
  } finally {
    btn.disabled = false;
    btn.textContent = 'Upload';
    btn.removeAttribute('aria-busy');
  }
}

function wireDatasetUpload(panel) {
  const input = panel.querySelector('#dataset-file');
  const button = panel.querySelector('#upload-btn');
  input?.addEventListener('change', () => {
    button.disabled = !input.files.length;
    const status = panel.querySelector('#upload-status');
    status.textContent = ''; status.className = 'upload-status';
  });
  button?.addEventListener('click', runUpload);
}

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
  btn.textContent = 'Searching';
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
 *
 * Same two blocks beside the rail as the upload screen, for the same reason:
 * the search next to the rail, and what an import is across the rest. Three
 * deliberate clicks are hard to read off a button, so they are written down
 * beside it rather than discovered one at a time.
 * -------------------------------------------------------------------------- */
function renderDatasetHub() {
  return `<div class="screen-split">
    <section class="screen-body hub-search">
      <h2>Search</h2>
      <label for="hub-task">What your prompt has to do</label>
      <textarea id="hub-task" rows="3">${esc($('description')?.value || '')}</textarea>
      <p class="field-hint">The same task the prompt uses. The query is built from these words — edit them if the search comes back off-target.</p>
      <button id="hub-btn" class="primary" type="button" data-testid="hub-search">Search Hugging Face</button>
      <div id="hub-status" class="upload-status" role="status" aria-live="polite"></div>
      <div id="hub-results" class="hub-results"></div>
    </section>
    <aside class="screen-guide" data-testid="hub-guide">
      <h2>What an import gets you</h2>
      <p class="guide-lead">Public material, not your traffic. Hub rows say whether a prompt holds up on text that resembles your inputs; your own examples still say it best.</p>
      <h3>Three clicks, none of them automatic</h3>
      <ol class="guide-steps">
        <li><b>Search.</b> The prompt engine writes the queries from your task, or your own wording is used when it cannot. The line above the results says which, and what was searched for.</li>
        <li><b>Look at the columns.</b> A candidate opens on its real config, split and first rows. Nothing is chosen for you — only you can tell whether the material looks like your inputs.</li>
        <li><b>Import.</b> You pick the column to send and the column holding the right answer — up to 500 rows, 60 by default.</li>
      </ol>
      <h3>What happens after you import</h3>
      <ol class="guide-steps">
        <li>The set is named <code>hf:</code> plus the dataset, selected for measurement straight away, and listed in the <a href="#dataset-library" data-global-tab="dataset-library">dataset library</a>.</li>
        <li>Rows missing their input or their answer are skipped; the count you get back is what was actually kept.</li>
        <li>Leave the right answer at <em>— none —</em> and there is nothing to compare against: the graders that score quality need it.</li>
      </ol>
      <p class="guide-note">Unlike an uploaded file, these rows are written to disk — the material is public, and re-importing would mean downloading it again and repeating your column choices.</p>
      <p class="guide-note">This screen needs the network: <code>huggingface.co</code> for the catalogue, <code>datasets-server.huggingface.co</code> for columns and rows. Nothing else in the app leaves your machine.</p>
      <p class="guide-note">Rather use your own? <a href="#dataset-add" data-global-tab="dataset-add" data-mode="upload">Upload a JSONL file</a> or <a href="#dataset-add/generate" data-global-tab="dataset-add" data-screen="dataset-add" data-mode="generate">build a set from your task</a>.</p>
    </aside>
  </div>`;
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
    importBtn.textContent = 'Importing';
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
  const name = state.run.dataset;
  if (!name) return null;
  if (!datasetCache[name]) {
    try { datasetCache[name] = await api(`/v1/datasets/${encodeURIComponent(name)}`); }
    catch { return null; }
  }
  return datasetCache[name][0] || null;
}
