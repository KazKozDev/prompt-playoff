// Product lifecycle screens. They share the existing visual language and API
// helper, but keep their state and event wiring out of the selector workflow.

const q = state.quality;
const statusCard = (label, value, tone='') => `<div class="quality-stat ${tone}"><span>${esc(label)}</span><strong>${esc(value)}</strong></div>`;
const qualityError = () => q.error ? `<div class="error">${esc(q.error)}</div>` : '';
const screenResult = screen => q.results[screen] || null;
const setScreenResult = (screen, value) => { q.results[screen] = value; };
const prerequisite = (message, target, label) => `<div class="prerequisite" role="note"><p>${esc(message)}</p><button type="button" class="ghost" data-prereq-target="${esc(target)}" data-action="resolve-prerequisite">${esc(label)}</button></div>`;

/* --------------------------------------------------------------------------
 * Build datasets.
 *
 * Top to bottom the screen answers three questions: what to generate, what came
 * out, and what is still nobody's decision. The middle answer is a deck of
 * counts rather than a table, because a hundred generated rows are not a
 * hundred pieces of news — the news is how many a rule already objected to.
 * -------------------------------------------------------------------------- */

// Each mode differs in exactly one thing: where its seed rows come from. That
// difference is also what the cost line depends on, so it is stated once here.
const BUILD_MODES = [
  ['edge_cases', 'Edge cases', 'Mutations along every axis of the taxonomy, seeded from your task.'],
  ['failures', 'What it got wrong', 'Seeded from the rows your last benchmark did not score full marks on.'],
  ['description', 'From description', 'No seed rows at all: the task text itself is row one.'],
  ['expand', 'Expand examples', 'Seeded from the benchmark set you already have selected.'],
  ['traces', 'Production traces', 'Recorded generations pulled from Langfuse.']
];

// A sampled answer is worth keeping unattended only if most samples said it.
const AGREED = 0.75;

/* Rows the last run did not get fully right. Deliberately "not full marks"
 * rather than a threshold: any number here would be a judgement the screen
 * cannot explain, and partial credit is still a row worth more examples. */
function failedExamples() {
  if (!state.report) return [];
  const worst = new Map();
  for (const run of state.report.runs || []) {
    const grades = Object.values(run.grades || {});
    const score = run.error ? 0 : (grades.length ? grades.reduce((a, b) => a + b, 0) / grades.length : 0);
    if (!worst.has(run.example_id) || score < worst.get(run.example_id)) worst.set(run.example_id, score);
  }
  const held = state.datasetRows.get(state.report.dataset);
  if (held?.status !== 'ready') return [];
  return held.rows.filter(row => (worst.has(row.id) ? worst.get(row.id) : 1) < 1).slice(0, 40);
}

// Seeds this mode will send, and why it cannot run when there are none.
function builderSeeds() {
  const mode = q.build.mode;
  if (mode === 'failures') {
    const rows = failedExamples();
    return {rows, blocked: rows.length ? '' : 'Run a benchmark first — this mode builds around the rows it got wrong.'};
  }
  if (mode === 'expand') {
    const held = state.datasetRows.get(state.run.dataset);
    const rows = held?.status === 'ready' ? held.rows.slice(0, 40) : [];
    return {rows, blocked: rows.length ? '' : 'Select a benchmark set on the Prompt screen — this mode widens rows you already have.'};
  }
  return {rows: [], blocked: ''};
}

/* What the button costs, before it is pressed. The generator is the only part
 * of this screen that spends anything, and with several samples per input and
 * an answer sampled per row the bill is a multiplication most people will not
 * do in their head. */
function builderCalls() {
  const b = q.build;
  if (!b.llm || !['edge_cases', 'description'].includes(b.mode)) return 0;
  return Number(b.candidates) + (b.answers ? Number(b.count) * Number(b.candidates) : 0);
}

function builderCostLine() {
  const b = q.build;
  const calls = builderCalls();
  if (!calls) return 'No model calls: the rows are mutated deterministically, so the same settings give the same set.';
  const parts = [`${plural(b.candidates, 'sample')} for the inputs`];
  if (b.answers) parts.push(`${b.count} × ${b.candidates} for the answers and their agreement`);
  return `About ${plural(calls, 'model call')} — ${parts.join(', ')}.`;
}

/* Who writes the rows.
 *
 * `engineProfile` falls back to the model under evaluation when the engine
 * field is blank, and everywhere else that fallback is the right one: authoring
 * a prompt with the model that will run it is a choice, not a mistake. Here it
 * is the mistake — a model asked to write its own exam writes the questions it
 * can already answer — so this returns null instead, and the form says so
 * before the button is pressed rather than the deck saying so afterwards.
 */
function generatorProfile() {
  return state.settings.engine.model_id.trim() ? engineProfile() : null;
}

// Only two modes have no seed rows of their own, so only those two ask a model
// to write any. The rest mutate rows that already exist.
const WRITES_SEEDS = ['edge_cases', 'description'];
const builderNeedsEngine = () => q.build.llm && WRITES_SEEDS.includes(q.build.mode);

function builderForm() {
  const b = q.build;
  const seeds = builderSeeds();
  const modes = BUILD_MODES.map(([value, label]) =>
    `<option value="${value}"${value === b.mode ? ' selected' : ''}>${esc(label)}</option>`).join('');
  const lead = (BUILD_MODES.find(item => item[0] === b.mode) || [])[2] || '';
  const traces = b.mode === 'traces' ? `
    <label>Trace session<input id="builder-trace-session" value="${esc(b.session)}" placeholder="Langfuse session ID"></label>
    <label>Trace tags<input id="builder-trace-tags" value="${esc(b.tags)}" placeholder="production, support"></label>` : '';
  const engine = generatorProfile();
  // Which model, by name, on the control that decides whether a model is used
  // at all: "the prompt engine" is a role, and the question here is which model
  // is holding it.
  const writer = engine
    ? `On, <code>${esc(engine.model_id)}</code> writes them — the prompt engine, not the model you are measuring. Nothing it writes is truth until you approve it.`
    : 'On, the prompt engine writes them — but it has no model of its own set yet.';
  const sampling = WRITES_SEEDS.includes(b.mode) ? `
    <label class="mode-option wide"><input id="builder-llm" type="checkbox"${b.llm ? ' checked' : ''}><span><strong>Write the seed inputs with the prompt engine</strong><small>Off, the seeds are your task text mutated by rule. ${writer}</small></span></label>
    ${b.llm ? `<label>Samples per set<input id="builder-candidates" type="number" min="1" max="8" value="${b.candidates}"><small class="field-hint">One sample is one voice repeated. Several are pooled and deduplicated.</small></label>
    <div class="build-toggles">
      <label class="mode-option"><input id="builder-personas" type="checkbox"${b.personas ? ' checked' : ''}><span><strong>Vary who is typing</strong><small>Each sample writes as a different reader of the task.</small></span></label>
      <label class="mode-option"><input id="builder-answers" type="checkbox"${b.answers ? ' checked' : ''}><span><strong>Propose an answer per row</strong><small>Sampled as many times as above; the row keeps the answer the samples agreed on, and the agreement is recorded.</small></span></label>
    </div>` : ''}` : '';
  // Blank engine plus a ticked box would generate the set with the model under
  // evaluation, which is the one thing this screen must not do quietly. It is a
  // gate rather than a warning: the rules can still write the set, so there is
  // always something to press.
  const engineBlocked = builderNeedsEngine() && !engine;
  const engineGate = engineBlocked
    ? `<div class="gate">The prompt engine has no model of its own, so these rows would be written by <code>${esc(state.settings.evaluation.model_id || 'the evaluation model')}</code> — the model you are measuring. Give the engine a model, or untick the box and let the rules mutate your task text.<button type="button" class="ghost" data-prereq-target="settings" data-action="resolve-prerequisite">Models &amp; keys</button></div>`
    : '';
  return `<div class="build-mode-lead">${esc(lead)}</div>
    ${seeds.blocked ? `<div class="gate">${esc(seeds.blocked)}<button type="button" class="ghost" data-prereq-target="${b.mode === 'failures' ? 'report' : 'prompt'}" data-action="resolve-prerequisite">Go there</button></div>` : ''}
    ${engineGate}
    ${seeds.rows.length ? `<div class="build-seeds">Seeded from ${plural(seeds.rows.length, 'row')} — ${b.mode === 'failures' ? `the first ${Math.min(b.count, seeds.rows.length)} go into the set unchanged, and the rest of the ${b.count} are mutations of them.` : `taken from ${esc(state.run.dataset)}.`}</div>` : ''}
    <div class="quality-form">
      <label>Name<input id="builder-name" value="${esc(b.name)}"></label>
      <label>Mode<select id="builder-mode">${modes}</select></label>
      <label>Examples<input id="builder-count" type="number" min="2" max="100" value="${b.count}"></label>
      ${traces}
      ${sampling}
      <label class="wide">Task description<textarea id="builder-description" placeholder="Describe real inputs, output contract, and risky cases.">${esc($('description')?.value || '')}</textarea></label>
    </div>
    <div class="build-cost">${esc(builderCostLine())}</div>
    <div class="form-actions"><button class="primary builder-create" data-action="create-dataset-project" data-testid="builder-create" ${seeds.blocked || engineBlocked ? 'disabled' : ''}>Generate review set</button></div>`;
}

// `plural` counts the noun; this one has to agree the verb as well, and it is
// said on the card and again in the notes beside it.
const rewordedPhrase = count => count === 1
  ? 'One row is another row reworded'
  : `${count} rows are rewordings of other rows`;

const deckCard = (mark, tone, value, label, lead, action) => `<article class="deck-card ${tone}">
  <div class="deck-top"><span class="deck-mark">${icon(mark)}</span><strong>${esc(label)}</strong></div>
  <div class="deck-value">${esc(value)}</div>
  <p class="deck-lead">${esc(lead)}</p>
  ${action || ''}</article>`;

/* The deck for the newest project. The reference this borrows from puts a count
 * and one verb on every card; the verb here narrows the table below rather than
 * doing anything irreversible, because approving is the one decision this
 * screen must never make on its own. */
function builderDeck(project) {
  const items = project.examples;
  const flagged = items.filter(item => item.checks.length);
  const unreviewed = items.filter(item => item.status === 'unreviewed' && !item.checks.length);
  const approved = items.filter(item => item.status === 'approved');
  const sampled = items.filter(item => item.agreement !== null && item.agreement !== undefined);
  const agreed = sampled.filter(item => item.agreement >= AGREED);
  const filled = project.coverage.filter(cell => cell.examples).length;
  const gaps = project.coverage.filter(cell => !cell.examples).map(cell => cell.axis.replace(/_/g, ' '));
  const narrow = (target, label) => `<button type="button" class="ghost deck-act" data-filter="${target}">${esc(label)}</button>`;
  const cards = [
    deckCard('shield', flagged.length ? 'bad' : 'good', String(flagged.length), 'A rule objected',
      flagged.length ? 'These rows broke a check that needs no model to decide.' : 'No check fired on any row.',
      flagged.length ? narrow('flagged', 'Review these') : ''),
    deckCard('clock', unreviewed.length ? 'warn' : 'good', String(unreviewed.length), 'Nobody has looked',
      'Generated, unobjected to, and still not benchmark truth.',
      unreviewed.length ? narrow('unreviewed', 'Review these') : ''),
    deckCard('grid', gaps.length ? 'warn' : 'good', `${filled} / ${project.coverage.length}`, 'Axes covered',
      gaps.length ? `Nothing landed on ${gaps.slice(0, 3).join(', ')}${gaps.length > 3 ? ` and ${gaps.length - 3} more` : ''}.` : 'Every axis of the taxonomy has at least one row.',
      ''),
    deckCard('checkCircle', approved.length ? 'good' : 'idle', String(approved.length), 'Approved by you',
      'The only rows publishing will carry.', approved.length ? narrow('approved', 'See them') : '')
  ];
  // Coverage counts which axes were hit; this counts whether the rows that hit
  // them are actually different sentences. A set can fill every cell and still
  // be one row reworded ten times, and only this card can say so.
  if (project.diversity !== null && project.diversity !== undefined) {
    const spread = project.diversity;
    const copies = items.filter(item => item.checks.some(check => check.code === 'near-duplicate')).length;
    // Where the bands come from, measured with bge-m3 on short English rows:
    // two wordings of one sentence sit around 0.04 apart, two rows about
    // different things around 0.45. So a set averaging under a tenth is one row
    // reworded, and a quarter is the floor of a set that tests several things.
    cards.splice(3, 0, deckCard('columns', spread >= 0.25 ? 'good' : spread >= 0.12 ? 'warn' : 'bad',
      `${Math.round(spread * 100)}%`, 'Variety',
      copies
        ? `${rewordedPhrase(copies)}. Compared by ${project.similarity_model}.`
        : `Average distance between rows, measured by ${project.similarity_model}. No row is a rewording of another.`,
      copies ? narrow('flagged', 'See the copies') : ''));
  }
  if (sampled.length) cards.splice(2, 0, deckCard('scale', agreed.length === sampled.length ? 'good' : 'warn',
    `${agreed.length} / ${sampled.length}`, 'Samples agreed',
    `The answer on the rest was proposed by a minority of samples.`,
    agreed.length < sampled.length ? narrow('disputed', 'Review the rest') : ''));
  // The fact only. What it means for the score is a judgement, and judgements
  // are made in the column beside this one rather than twice in two places.
  const generator = project.generator
    ? `<div class="build-provenance">Written by <code>${esc(project.generator)}</code>.</div>`
    : '';
  return `<div class="deck-lead-line">${esc(project.name)} — ${plural(items.length, 'row')} generated. ${flagged.length ? `${flagged.length} need your eyes first.` : 'Nothing broke a check.'}</div>
    <div class="deck">${cards.join('')}</div>
    ${generator}
    ${coverageGrid(project)}`;
}

// Same family as the model under measurement? The one comparison a generated
// set cannot make about itself.
function shareFamily(generator) {
  const family = value => String(value || '').split('/').pop().toLowerCase().split(/[:@]/)[0].replace(/[-_.]?\d+(\.\d+)?b$/, '');
  return generator && family(generator) === family(state.settings.evaluation.model_id);
}

/* Coverage before dedupe, not after: the empty cells are the finding. A grid of
 * six full cells and four empty ones says what "twelve examples" cannot. */
function coverageGrid(project) {
  const cells = project.coverage.map(cell => `<div class="cov-cell${cell.examples ? '' : ' empty'}" title="${esc(cell.intent)}">
    <span class="cov-axis">${esc(cell.axis.replace(/_/g, ' '))}</span>
    <span class="cov-count">${cell.examples || '—'}</span>
    ${cell.flagged ? `<span class="cov-flag">${cell.flagged} flagged</span>` : ''}
  </div>`).join('');
  return `<div class="stage-title">Coverage</div><div class="cov-grid">${cells}</div>`;
}

function builderRows(project) {
  const filter = q.build.filter;
  const keep = item => filter === 'all'
    || (filter === 'flagged' && item.checks.length)
    || (filter === 'unreviewed' && item.status === 'unreviewed' && !item.checks.length)
    || (filter === 'approved' && item.status === 'approved')
    || (filter === 'disputed' && item.agreement !== null && item.agreement !== undefined && item.agreement < AGREED);
  // Flagged first, then the least agreed-on: the queue opens on whatever a rule
  // could not settle, which is the only part a person is needed for.
  const ordered = [...project.examples].sort((left, right) =>
    (left.checks.length ? 0 : 1) - (right.checks.length ? 0 : 1)
    || (left.agreement ?? 1) - (right.agreement ?? 1));
  const shown = ordered.filter(keep).slice(0, 30);
  if (!shown.length) return `<div class="empty">Nothing in this project is ${esc(filter)}.</div>`;
  return `<div class="table-scroll"><table class="builder-rows"><thead><tr><th></th><th>Axis</th><th>Status</th><th>Checks</th><th class="agree">Agreed</th><th>Split</th><th>Input</th></tr></thead><tbody>${shown.map(item => `<tr${item.checks.length ? ' class="row-flagged"' : ''}>
    <td><input type="checkbox" data-example-id="${esc(item.example.id)}"></td>
    <td>${esc((item.mutation || 'baseline').replace(/_/g, ' '))}${item.persona ? `<small class="row-persona">${esc(item.persona)}</small>` : ''}</td>
    <td><span class="status-chip ${esc(item.status)}">${esc(item.status)}</span></td>
    <td>${item.checks.map(check => `<span class="check-chip" title="${esc(check.detail)}">${esc(check.code)}</span>`).join('') || '<span class="meta">—</span>'}</td>
    <td class="agree">${item.agreement === null || item.agreement === undefined ? '<span class="meta">—</span>' : `${Math.round(item.agreement * 100)}%`}</td>
    <td>${esc(item.split)}</td>
    <td>${esc(item.example.input.slice(0, 90))}</td></tr>`).join('')}</tbody></table></div>`;
}

/* --------------------------------------------------------------------------
 * Zone three: what to do about what zone two produced.
 *
 * The deck counts; this column says which of those counts is the one to act on,
 * and why. Every note is derived from the project on screen — a column that
 * reads the same on an empty screen as on a flagged one is decoration, so the
 * notes appear only when the thing they are about is true, most urgent first.
 * -------------------------------------------------------------------------- */
const adviceNote = (tone, title, body, action='') =>
  `<li class="advice ${tone}"><strong>${esc(title)}</strong><p>${esc(body)}</p>${action}</li>`;
// Both buttons a note can carry already have handlers on this screen: one
// narrows the row table, the other opens the screen that settles the note.
const adviceFilter = (target, label) => `<button type="button" class="ghost advice-act" data-filter="${esc(target)}">${esc(label)}</button>`;
const adviceGo = (target, label) => `<button type="button" class="ghost advice-act" data-prereq-target="${esc(target)}" data-action="resolve-prerequisite">${esc(label)}</button>`;

// Named in the order a set is worth trusting in, because that ordering is the
// single most useful thing this screen can tell someone choosing a mode.
const MODE_EVIDENCE = [
  ['Production traces', 'Real inputs. Nothing generated beats a row a person actually typed.'],
  ['What it got wrong', 'Real inputs too, narrowed to the rows the last run missed — the fastest way to make a set harder where it matters.'],
  ['Expand examples', 'Variations of rows you already trust, so the material stays yours.'],
  ['Edge cases', 'Written from your task description along every axis of the taxonomy. Wide coverage, invented material.'],
  ['From description', 'No seed rows at all. Use it to have something to measure on day one, not to decide a release.']
];

function builderAdvice(project) {
  const notes = [];
  const b = q.build;
  if (project) {
    const items = project.examples;
    const flagged = items.filter(item => item.checks.length).length;
    const unreviewed = items.filter(item => item.status === 'unreviewed' && !item.checks.length).length;
    const approved = items.filter(item => item.status === 'approved').length;
    const held = items.filter(item => item.split === 'held-out').length;
    const sampled = items.filter(item => item.agreement !== null && item.agreement !== undefined);
    const disputed = sampled.filter(item => item.agreement < AGREED).length;
    const gaps = project.coverage.filter(cell => !cell.examples).map(cell => cell.axis.replace(/_/g, ' '));
    if (flagged) notes.push(adviceNote('bad', `Start with the ${plural(flagged, 'flagged row')}`,
      'A rule objected to these without needing a model to decide, which makes them both the cheapest rows to settle and the likeliest to be wrong. Read them before anything else in the queue.',
      adviceFilter('flagged', 'Show flagged')));
    if (disputed) notes.push(adviceNote('warn', `${plural(disputed, 'answer')} the samples did not agree on`,
      `Fewer than ${Math.round(AGREED * 100)}% of the samples proposed the answer these rows kept. That answer becomes the thing every later score is measured against, so it is worth being the one who decides it.`,
      adviceFilter('disputed', 'Show disputed')));
    if (project.generator && shareFamily(project.generator)) notes.push(adviceNote('warn', 'The generator and the model under test share a family',
      `${project.generator} wrote these rows and ${state.settings.evaluation.model_id} is what you are measuring. A model tends to write the cases it already handles, so a good score on this set is weaker evidence than the same score on rows of your own.`,
      adviceGo('settings', 'Change the engine')));
    if (gaps.length) notes.push(adviceNote('warn', `${gaps.length === 1 ? 'One axis' : `${gaps.length} axes`} came out empty`,
      `Nothing landed on ${gaps.slice(0, 4).join(', ')}${gaps.length > 4 ? ` and ${gaps.length - 4} more` : ''}. A score says nothing about an axis the set does not contain — raise the example count and generate again, or accept the gap knowingly.`));
    // Two rows that say the same thing are one row of evidence charged twice,
    // and a set with no variety is a set that tested one case thoroughly.
    const copies = items.filter(item => item.checks.some(check => check.code === 'near-duplicate')).length;
    if (copies) notes.push(adviceNote('warn', rewordedPhrase(copies),
      `${project.similarity_model} put them above the similarity line. Two wordings of one case count twice in the average and test once, so drop one of each pair — or lower the line if you think they are genuinely different.`,
      adviceFilter('flagged', 'Show them')));
    if (project.diversity !== null && project.diversity !== undefined && project.diversity < 0.12) notes.push(adviceNote('bad', 'The rows barely differ from each other',
      `Average distance between rows is ${Math.round(project.diversity * 100)}%. The generator wrote one case in several wordings rather than several cases. Raise the sample count, turn on the personas, or seed from rows of your own.`));
    if (unreviewed) notes.push(adviceNote('warn', `${plural(unreviewed, 'row')} nobody has read`,
      'Publishing carries approved rows only. Every row left unreviewed is simply missing from the set you will be measuring on, however good it looks in the table.',
      adviceFilter('unreviewed', 'Show unreviewed')));
    if (approved) notes.push(adviceNote('good', `${plural(approved, 'row')} ready to publish`,
      `Publishing names the set, adds it to the library and selects it for measurement straight away. ${held ? `${plural(held, 'row')} here are marked held-out: measure on those and tune on the training ones, because a prompt polished against the rows it is scored on will always look better than it is.` : ''}`.trim(),
      adviceFilter('approved', 'Show approved')));
  } else {
    notes.push(adviceNote('idle', 'Generate small first',
      'Twenty to thirty rows is enough to see whether the coverage grid fills and whether the material resembles your inputs. Raising the count on a set that came out wrong only produces more of the same.'));
  }
  // The form is on screen whether or not anything has been generated yet, so
  // the notes about the settings it holds are too. Who will write the next set
  // comes before anything about the last one.
  const engine = generatorProfile();
  if (builderNeedsEngine() && !engine) notes.unshift(adviceNote('bad', 'The prompt engine has no model of its own',
    `Ticked, that box hands the writing to ${state.settings.evaluation.model_id || 'the evaluation model'} — the model you are measuring, and the one writer whose set proves nothing. Name an engine model, or untick the box and let the rules mutate your task text.`,
    adviceGo('settings', 'Models & keys')));
  else if (builderNeedsEngine() && shareFamily(engine.model_id)) notes.unshift(adviceNote('warn', 'The engine and the model under test share a family',
    `${engine.model_id} would write the rows that ${state.settings.evaluation.model_id} is then scored on. Pick an engine from another lineage and the set stops flattering the thing it measures.`,
    adviceGo('settings', 'Models & keys')));
  if (b.mode === 'description') notes.push(adviceNote('warn', 'This mode invents the inputs as well as the answers',
    'With no seed rows, your task text is the only material there is. It gets you something to measure on day one; it does not tell you how the prompt behaves on your traffic.',
    adviceGo('dataset-add', 'Upload rows of your own')));
  if (!similarityProfile()) notes.push(adviceNote('idle', 'Nothing is checking for reworded rows',
    'Without a similarity model, only rows that match character for character count as duplicates. "Cancel my subscription" and "I would like to cancel my subscription" both go into the set, and the average is then computed over one case counted twice.',
    adviceGo('settings', 'Set one')));
  if (b.llm && Number(b.candidates) === 1) notes.push(adviceNote('warn', 'One sample is one voice repeated',
    'A single sample cannot disagree with itself: no row gets an agreement score, and near-duplicates survive the deduplication. Three or four samples cost more calls and are the reason to turn the engine on at all.'));
  const modes = MODE_EVIDENCE.map(([name, lead]) =>
    `<div><dt>${esc(name)}</dt><dd>${esc(lead)}</dd></div>`).join('');
  return `<h2>What to do about this set</h2>
    <p class="guide-lead">Generated rows are a guess at what your inputs look like. Everything below is about closing the gap between that guess and the real traffic.</p>
    <ul class="advice-list">${notes.join('')}</ul>
    <h3>Which mode is worth trusting</h3>
    <dl class="guide-stack">${modes}</dl>
    <h3>Reading what came out</h3>
    <p class="guide-note"><b>Variety and coverage are different questions.</b> Coverage says which axes the rows landed on; variety says whether those rows are actually different sentences. A set can fill every cell with ten wordings of one case, and only the variety number sees it.</p>
    <p class="guide-note"><b>The empty cells are the finding.</b> Coverage counts every axis the mode can produce, not only the ones that got rows. Six full cells out of ten is the news; "sixty examples" is not.</p>
    <p class="guide-note"><b>Nothing is truth until you approve it.</b> Reviewed and flagged rows stay behind when the set is published — approval is the only step this screen will never take for you.</p>
    <p class="guide-note"><b>With the engine off, the set is reproducible.</b> The mutations are rules, so the same name, count and description give the same rows, and two sets can be diffed. With it on, every run is a different set.</p>
    <p class="guide-note">A generated set is for finding where a prompt breaks. Once it breaks somewhere, the rows worth keeping are the ones you <a href="#dataset-add" data-global-tab="dataset-add" data-mode="upload">bring yourself</a>.</p>`;
}

function renderDatasetBuilder() {
  const current = screenResult('dataset-builder');
  const outcome = current?.kind === 'dataset' ? `<div class="quality-result">${esc(current.message)}</div>` : '';
  const latest = q.projects[q.projects.length - 1];
  const filters = ['all', 'flagged', 'unreviewed', 'disputed', 'approved'];
  const projects = q.projects.map(project => {
    const approved = project.examples.filter(item => item.status === 'approved').length;
    const held = project.examples.filter(item => item.split === 'held-out').length;
    const flagged = project.examples.filter(item => item.checks.length).length;
    return `<details class="quality-project" data-project-id="${esc(project.id)}"${project === latest ? ' open' : ''}>
      <summary>${esc(project.name)} · ${project.examples.length} rows · ${approved} approved · ${held} held-out${flagged ? ` · ${flagged} flagged` : ''}</summary>
      <div class="row-filters">${filters.map(name => `<button type="button" class="chip-btn${q.build.filter === name ? ' on' : ''}" data-filter="${name}">${esc(name)}</button>`).join('')}</div>
      ${builderRows(project)}
      <div class="quality-actions">
        <span class="selected-count meta">Nothing selected</span>
        <button class="ghost dataset-review" data-action="review-examples">Mark reviewed</button>
        <button class="ghost dataset-approve" data-action="approve-examples">Approve selected</button>
        <button class="primary dataset-publish" data-action="publish-dataset" ${approved ? '' : 'disabled'}>Publish ${approved || 'approved'} as a benchmark set</button>
      </div>
    </details>`;
  }).join('');
  const unreviewed = q.projects.reduce((total, project) =>
    total + project.examples.filter(item => item.status === 'unreviewed').length, 0);
  const waiting = unreviewed
    ? `<div class="gate">${plural(unreviewed, 'generated example')} still unreviewed — nothing counts as benchmark truth until you approve it.<button type="button" class="ghost" data-prereq-target="reviews" data-action="resolve-prerequisite">Reviews</button></div>`
    : '';
  // Three zones, the same three every screen that brings examples in has: the
  // rail you came down, the work, and what there is to know about it. The work
  // takes the wide half here rather than the narrow one — a table of generated
  // rows does not fit a 380px column, and the notes beside it do.
  return `<div class="screen-split work-wide">
    <div class="build-work">
      ${qualityError()}${outcome}${waiting}
      <section class="screen-body">${builderForm()}</section>
      ${latest ? builderDeck(latest) : ''}
      <div class="stage-title">Projects</div>${projects || '<div class="empty">No generated datasets yet.</div>'}
    </div>
    <aside class="screen-guide" data-testid="builder-guide">${builderAdvice(latest)}</aside>
  </div>`;
}

/* --------------------------------------------------------------------------
 * The same three zones as every other screen of this section: the rail, the
 * comparison itself, and beside it the few things that decide how much a
 * verdict from a model is worth. The work takes the wide half — an input and
 * two answers are four text areas, and they do not fit a 380px column.
 * -------------------------------------------------------------------------- */
/* The question people actually have about a drafting prompt is whether it
 * writes well across the set. This screen could only ever settle an argument
 * about one example, which is a different and much smaller question — so the
 * run comes first and the pair stays underneath it.
 *
 * Every row of the last recorded run is compared with the reference answer that
 * row already carries, order hidden. What comes back is a win rate against the
 * person who wrote those references: 0.5 means the prompt writes about as well
 * as they did, not that half its answers were wrong. */
function judgeRunSection() {
  const report = state.report;
  const runnable = report && report.runs?.length && report.dataset;
  const verdict = screenResult('judge');
  const result = verdict?.kind === 'rubric' ? `<div class="quality-result">
    <div class="quality-stats">
      ${statusCard('Won', `${verdict.wins} of ${verdict.rows.length - verdict.errors}`)}
      ${statusCard('Win rate', verdict.win_rate == null ? '—' : Number(verdict.win_rate).toFixed(2))}
      ${statusCard('Human gate', 'Pending review', 'warning')}
    </div>
    ${verdict.self_preference_warning ? `<div class="warning">${esc(verdict.self_preference_warning)}</div>` : ''}
    <p>${esc(verdict.summary)}</p>
    <p class="meta">A win rate of 0.50 means this prompt writes about as well as whoever wrote the
      reference answers — not that half of its answers were wrong. ${verdict.errors ? `${plural(verdict.errors, 'row')} could not be judged and count for nothing either way. ` : ''}This number is a model's
      opinion and has no route into a scorecard or a committed threshold;
      <a href="#reviews" data-global-tab="reviews" data-screen="reviews">Reviews</a> is where it is accepted or thrown out.</p>
  </div>` : '';
  return `<section class="screen-body">
    <h2>Judge a whole run</h2>
    ${runnable
      ? `<p class="meta">Every row of <code>${esc(report.dataset)}</code> — ${plural(report.examples, 'example')} measured with
          ${esc(techniqueTitle(report.technique_id))} — held against the reference answer it already carries, order hidden
          from the judge.</p>
        <div class="quality-form">
          <label class="wide">Rubric, one criterion per line<textarea id="rubric-run-lines">Answers the question that was asked\nKeeps every fact the input gave\nReads as something you would send</textarea></label>
        </div>
        <div class="form-actions"><button class="primary" data-action="run-rubric">Judge ${plural(report.examples, 'answer')}</button></div>`
      : `<p class="meta">Measure a prompt first — this judges the answers a run produced, against the reference
          answers the rows carry. <a href="#report" data-global-tab="report" data-screen="report">Measurement</a> is where a run comes from.</p>`}
    ${result}
  </section>`;
}

function renderJudge() {
  const current = screenResult('judge');
  // The warning is printed with the verdict, not instead of it: the verdict is
  // still evidence, just weaker evidence than it looks.
  const leak = current?.self_preference_warning ? `<div class="warning">${esc(current.self_preference_warning)}</div>` : '';
  // "a" is what the wire says; the screen says which box that was. The two
  // scores are printed beside the winner because a verdict of 0.9 against 0.88
  // and one of 0.9 against 0.2 are different findings, and the word "winner"
  // hides which of them you are looking at.
  const named = value => value === 'tie' ? 'Tie' : value === 'a' ? 'Answer A' : value === 'b' ? 'Answer B' : String(value);
  const scores = current?.scores
    ? `${statusCard('Answer A', Number(current.scores.a).toFixed(2))}${statusCard('Answer B', Number(current.scores.b).toFixed(2))}`
    : '';
  const result = current?.kind === 'judge' ? `<div class="quality-result">
    <div class="quality-stats">${statusCard('Winner', named(current.winner))}${scores}${statusCard('Human gate', 'Pending review', 'warning')}</div>
    ${leak}<p>${esc(current.rationale)}</p>
    <p class="meta">The judge read them as first and second, in that order, and was never told which box either came
      from. Its own words above are the whole of the reasoning it gave.
      <a href="#reviews" data-global-tab="reviews" data-screen="reviews">Reviews</a> is where this verdict is
      accepted or thrown out.</p>
  </div>` : '';
  // Who is holding the whistle, said before the run rather than in the verdict:
  // no judge at all is a gate, and a judge from the family under test is a
  // warning the settings screen can act on.
  const judge = judgeProfile();
  const subject = state.settings.evaluation.model_id;
  const gate = judge
    ? ''
    : `<div class="gate">No judge model is set, and the model being measured must not mark its own answers.<button type="button" class="ghost" data-prereq-target="settings" data-action="resolve-prerequisite">Models &amp; keys</button></div>`;
  const kin = judge && shareFamily(judge.model_id)
    ? `<div class="warning">${esc(judge.model_id)} is judging answers from ${esc(subject)} — the same family. A judge scores its own lineage higher, so pick a judge from another one before the verdict is worth much.</div>`
    : '';
  return `<div class="screen-split work-wide">
    <div class="build-work">
      ${qualityError()}${gate}${kin}
      ${judgeRunSection()}
      <section class="screen-body">
        <h2>Or one pair, by hand</h2>
        <div class="quality-form">
          <label class="wide">Input<textarea id="judge-input"></textarea></label>
          <label>Answer A<textarea id="judge-a"></textarea></label>
          <label>Answer B<textarea id="judge-b"></textarea></label>
          <label class="wide">Judge model<input id="judge-model" placeholder="${esc(judge?.model_id || 'Set one in Settings')}"><small class="field-hint">${judge ? `Blank uses <code>${esc(judge.model_id)}</code> from Settings; type an id to override it for this comparison alone.` : 'Set a judge in Settings, or type an id here for this comparison alone.'} A judge from the same family as <code>${esc(subject)}</code> — the model you are measuring — tends to prefer its own lineage, and the verdict will say so.</small></label>
          <label class="wide">Rubric, one criterion per line<textarea id="judge-rubric">Correctness\nCompleteness\nFollows the requested format</textarea></label>
        </div>
        <div class="form-actions"><button class="primary judge-run" data-action="run-blind-judge">Run blind judge</button></div>
      </section>
      ${result}
    </div>
    <aside class="screen-guide" data-testid="judge-guide">${judgeGuide()}</aside>
  </div>`;
}

/* Zone three. What a verdict from a model is and is not, said before one
 * arrives rather than argued with afterwards. */
function judgeGuide() {
  return `<h2>How much a verdict is worth</h2>
    <p class="guide-lead">A model marking answers against a rubric: opinion, held to criteria you wrote. It is for
      work no grader can score — tone, judgement, whether an explanation explains. Anything a grader can decide
      belongs in <a href="#report" data-global-tab="report" data-screen="report">Measurement</a>, where it costs
      nothing and never changes its mind.</p>
    <dl class="guide-stack">
      <div><dt>Blind, and repeatable</dt><dd>The judge sees a first answer and a second, never A and B. Order
        comes from a fixed seed, so the same pair judged twice reads the same way.</dd></div>
      <div><dt>The rubric is the whole instruction</dt><dd>One criterion per line, up to twelve. What you leave
        out is not weighed, however obvious it is to you.</dd></div>
      <div><dt>A judge marks its own lineage higher</dt><dd>Blinding cannot hide family. When the judge shares
        one with the model being measured, the screen says so before the run and the verdict repeats it.</dd></div>
      <div><dt>Nothing is settled by the model</dt><dd>Every verdict lands in <a href="#reviews" data-global-tab="reviews" data-screen="reviews">Reviews</a> as pending. Until a person approves it there, it is a
        reading, not a decision.</dd></div>
      <div><dt>A whole run, or one pair</dt><dd>Judging a run compares every answer with the reference its row
        carries and returns a win rate against whoever wrote those references — 0.50 means your prompt writes about
        as well as they did. One pair settles an argument about one example and says nothing about the next
        hundred.</dd></div>
      <div><dt>It cannot become a gate</dt><dd>A judged number has no route into a scorecard or into
        <code>prompt-playoff.yaml</code>. A bar defended by a model's mood on the day is not a bar; CI enforces what
        a rule decided.</dd></div>
    </dl>
    <p class="guide-note">The judge model is set in <a href="#settings" data-global-tab="settings" data-screen="settings">Settings</a>, and runs at temperature zero.</p>`;
}

/* --------------------------------------------------------------------------
 * The same three zones: the rail, the queue, and beside it what lands in it and
 * what a decision here does — which is less than people assume, and worth
 * saying before they approve fifteen things expecting something to happen.
 * -------------------------------------------------------------------------- */
const REVIEW_KINDS = {
  dataset:'Generated rows waiting to be read',
  judge:'A verdict one model gave about answers it was shown',
  regression:'A gate that failed on metrics you set',
  release:'A prompt registered for release'
};

function renderReviews() {
  // The map's amber circle counts what is unanswered, so it opens this screen
  // on the unanswered ones rather than on the whole history of decisions.
  const only = showingOn('reviews');
  const queue = only ? q.reviews.filter(item => item.status === only) : q.reviews;
  const cards = queue.map(item => `<article class="review-card" data-review-id="${esc(item.id)}"><div><span class="status-chip ${esc(item.status)}">${esc(item.status)}</span> <span class="meta">${esc(REVIEW_KINDS[item.kind] || item.kind)} · ${esc(item.created_at)}</span></div><h3>${esc(item.title)}</h3><pre>${esc(JSON.stringify(item.payload, null, 2).slice(0, 1800))}</pre>${item.status === 'pending' ? '<div class="quality-actions"><button class="review-approve" data-action="approve-review">Approve</button><button class="ghost review-reject" data-action="reject-review">Reject</button></div>' : ''}</article>`).join('');
  const nothing = only ? `Nothing ${esc(only)} in the review queue.` : 'Review queue is empty.';
  // What the queue is made of, counted rather than described: a pile of twelve
  // pending items is a different screen from one with twelve decided ones.
  const pending = q.reviews.filter(item => item.status === 'pending').length;
  const count = q.reviews.length
    ? `${plural(q.reviews.length, 'item')} in all, ${pending} still pending${only ? ` — showing the ${esc(only)} ones.` : '.'}`
    : 'Nothing has asked for a decision yet.';
  return `<div class="screen-split work-wide">
    <div class="build-work">
      ${qualityError()}
      <section class="screen-body">
        <h2>The queue</h2>
        <p class="guide-lead">${count}</p>
        ${cards || `<div class="empty">${nothing}</div>`}
      </section>
    </div>
    <aside class="screen-guide" data-testid="reviews-guide">${reviewsGuide()}</aside>
  </div>`;
}

/* Zone three. Three things land here, each one a decision a model asked a
 * person to make, and none of them are carried out by approving them. */
function reviewsGuide() {
  return `<h2>What this queue is</h2>
    <p class="guide-lead">Every decision the tool refused to make on its own. Nothing arrives here because it went
      wrong — it arrives because a person is supposed to look, and that has to be written down to be known.</p>
    <dl class="guide-stack">
      <div><dt>Generated rows</dt><dd>A dataset written by a model is not truth until somebody reads it. The rows
        are approved on <a href="#dataset-add/generate" data-global-tab="dataset-add" data-screen="dataset-add" data-mode="generate">Build datasets</a>; this is the note that a set is waiting.</dd></div>
      <div><dt>Judge verdicts</dt><dd>A model's opinion about two answers is evidence, not a ruling, so every
        <a href="#judge" data-global-tab="judge" data-screen="judge">pairwise</a> verdict lands here pending.</dd></div>
      <div><dt>Failed gates</dt><dd>A <a href="#results/regressions" data-global-tab="results" data-screen="results" data-mode="regressions">regression</a> that breached its tolerance is filed with the metrics that
        breached it — a red screen somebody closed is still an open question tomorrow.</dd></div>
      <div><dt>Releases do not land here</dt><dd>They used to: registering a prompt raised an item asking the same
        person to approve what they had just registered, and advancing was refused until they clicked it. One user
        cannot be two. A release is now gated by the thresholds in <code>prompt-playoff.yaml</code> — the ones
        <code>prompt-playoff check</code> enforces in CI — applied to the run it cites.</dd></div>
      <div><dt>A decision here decides only this</dt><dd>Approving records what you thought. It does not publish a
        dataset or clear a gate — each is an action on its own screen, so nothing ships as a side effect of tidying
        a queue.</dd></div>
    </dl>
    <p class="guide-note">Decisions are kept with your measurements on this machine, and stay after a restart.</p>`;
}

function experimentOptions() {
  return state.experiments.map(item => `<option value="${esc(item.id)}">v${item.version} · ${esc(item.model_id)} · ${esc(item.dataset)}</option>`).join('');
}

/* A metric is a column heading here, not a key from a JSON dump: it is read
 * across a row against its own before and after, and each one is a different
 * kind of number. */
const METRIC_LABELS = {
  quality:'Quality', reliability:'Reliability', mean_latency_seconds:'Mean latency', p95_latency_seconds:'p95 latency',
  mean_total_tokens:'Mean tokens', mean_cost_usd:'Mean cost', total_cost_usd:'Total cost', failures:'Failed runs'
};
const metricLabel = name => METRIC_LABELS[name] || name.replace(/_/g, ' ');
function metricValue(name, value) {
  if (value === null || value === undefined) return '—';
  const number = Number(value);
  if (name.includes('cost')) return number.toFixed(6);
  if (name.includes('token') || name === 'failures') return String(Math.round(number));
  if (name.includes('latency')) return `${number.toFixed(2)}s`;
  return number.toFixed(3);
}

/* --------------------------------------------------------------------------
 * The same three zones as every other screen: the rail, the comparison and
 * what it decided, and beside it the rule it decided by — which is a tolerance
 * you set and not a test of significance, and is the one thing a red gate
 * cannot tell you about itself.
 *
 * The verdict used to be a status card over the raw JSON of whichever deltas
 * breached. Every metric is now a row, its before beside its after, with the
 * breaching ones marked: a gate that failed on latency alone reads differently
 * from one that failed on quality, and the object hid which it was.
 * -------------------------------------------------------------------------- */
function renderRegressions() {
  const current = screenResult('regressions');
  const breached = new Set((current?.active || []).map(item => item.metric));
  const deltas = current?.comparison?.deltas || [];
  const rows = deltas.map(item => `<tr${breached.has(item.metric) ? ' class="row-bad"' : ''}>
    <td>${esc(metricLabel(item.metric))}</td>
    <td>${metricValue(item.metric, item.before)}</td>
    <td>${metricValue(item.metric, item.after)}</td>
    <td>${item.delta === null || item.delta === undefined ? '—' : `${Number(item.delta) > 0 ? '+' : ''}${metricValue(item.metric, item.delta)}`}</td>
  </tr>`).join('');
  // The rerun writes its answer into the same result and nothing ever showed
  // it, so the button appeared to do nothing. It is the whole point of the
  // button: the same candidate measured again, to see whether the failure is
  // repeatable or was the noise of one run.
  const rerun = current?.rerun ? `<div class="quality-stats">
    ${statusCard('Rerun quality', Number(current.rerun.scorecard.quality).toFixed(3))}
    ${statusCard('Rerun latency', `${Number(current.rerun.scorecard.mean_latency_seconds).toFixed(2)}s`)}
    ${statusCard('Rerun failures', String(current.rerun.scorecard.failures))}
  </div><p class="meta">The candidate measured again, recorded as a new experiment. A failure that does not come back
    was the noise of one run; one that does is the prompt.</p>` : '';
  const result = current?.kind === 'regression' ? `<div class="quality-result">
    <div class="quality-stats">
      ${statusCard('Gate', current.status, current.status === 'passed' ? 'passed' : 'failed')}
      ${statusCard('Metrics breached', String((current.active || []).length), (current.active || []).length ? 'failed' : 'passed')}
    </div>
    ${rows ? `<div class="table-scroll"><table><thead><tr><th>Metric</th><th>Baseline</th><th>Candidate</th><th>Change</th></tr></thead><tbody>${rows}</tbody></table></div>` : ''}
    <p>${current.status === 'passed'
      ? 'Nothing moved further than the tolerances you set. That is not a finding that the candidate is better — only that it is not worse by more than you agreed to ignore.'
      : `Marked rows moved past their tolerance. This is filed in <a href="#reviews" data-global-tab="reviews" data-screen="reviews">Reviews</a> as well, so the decision survives leaving this screen.`}</p>
    ${current.status === 'failed' ? '<div class="quality-actions"><button class="reg-rerun">Rerun candidate</button><button class="ghost reg-accept">Accept new baseline</button></div>' : ''}
    ${rerun}
  </div>` : '';
  const gate = state.experiments.length < 2 ? prerequisite('Record at least two benchmark experiments before analyzing a regression.', 'prompt', 'Open Prompt Studio') : '';
  return `<div class="screen-split work-wide">
    <div class="build-work">
      ${qualityError()}${gate}
      <section class="screen-body">
        <h2>Two recorded runs, and what you will tolerate</h2>
        <div class="quality-form">
          <label>Baseline<select id="reg-before">${experimentOptions()}</select></label>
          <label>Candidate<select id="reg-after">${experimentOptions()}</select></label>
          <label>Quality tolerance<input id="reg-quality" type="number" step="0.01" min="0" value="0.01"></label>
          <label>Latency tolerance, seconds<input id="reg-latency" type="number" step="0.1" min="0" value="0.1"></label>
        </div>
        <p class="field-hint">Both runs come from your own history, so the two have to have measured the same
          technique — the comparison is between two versions of one thing, not between two different things.</p>
        <div class="form-actions"><button class="reg-run" data-action="analyze-regression" ${state.experiments.length < 2 ? 'disabled' : ''}>Analyze regression</button></div>
      </section>
      ${result}
    </div>
    <aside class="screen-guide" data-testid="regression-guide">${regressionGuide()}</aside>
  </div>`;
}

/* Zone three. What the gate actually checks, and what a red gate is evidence
 * of — which is less than the word suggests. */
function regressionGuide() {
  return `<h2>What the gate checks</h2>
    <p class="guide-lead">Not "is this better" but "has anything got worse by more than you agreed to ignore" — a
      lower bar than an improvement, and the one a change has to clear on the day you ship it.</p>
    <dl class="guide-stack">
      <div><dt>The two tolerances</dt><dd>Quality fails on a drop bigger than the quality tolerance, which also
        covers reliability. Latency fails on a rise bigger than the latency tolerance, on the mean and the p95.
        Everything else is shown and cannot fail the gate.</dd></div>
      <div><dt>A tolerance is not significance</dt><dd>The gate compares two averages; it cannot tell whether a drop
        of 0.02 was the prompt or the sample. Take a fail worth arguing about to <a href="#results/significance" data-global-tab="results" data-screen="results" data-mode="significance">Significance</a>, with the per-example
        scores behind both runs.</dd></div>
      <div><dt>Rerun before you believe it</dt><dd>A failure that does not come back was one unlucky run. The button
        records the rerun as its own experiment, so the history keeps both.</dd></div>
      <div><dt>Accepting a baseline is a decision</dt><dd>It pins this candidate as what future runs on the same
        provider, model and dataset are compared against. Do it when the drop is real and wanted — a cheaper model,
        a shorter prompt — not to clear a red screen.</dd></div>
      <div><dt>Every failure is filed</dt><dd>A failed gate becomes a pending item in <a href="#reviews" data-global-tab="reviews" data-screen="reviews">Reviews</a>, so it is still there tomorrow.</dd></div>
    </dl>
    <p class="guide-note">Runs appear in these lists once recorded — measure a prompt on <a href="#report" data-global-tab="report" data-screen="report">Measurement</a>, and both versions will be here.</p>`;
}

/* --------------------------------------------------------------------------
 * The same three zones: the rail, the two columns of scores and what they
 * decided, and beside them the rule this screen applies — which is stricter
 * than most people expect, and is the reason most answers here are
 * "inconclusive" rather than a winner.
 * -------------------------------------------------------------------------- */
function renderAnalysis() {
  const current = screenResult('analysis');
  // This used to print the whole object and leave the reading to you. The
  // finding is two intervals and whether they touch, so that is what it says.
  const interval = value => `${Number(value.mean).toFixed(3)} <span class="meta">(${Number(value.low).toFixed(3)} – ${Number(value.high).toFixed(3)})</span>`;
  const verdict = current?.kind === 'analysis'
    ? current.significant
      ? `The intervals do not overlap and both sides have enough observations, so the ${current.direction === 'improved' ? 'gain' : 'loss'} is real at this sample size.`
      : 'Inconclusive: either the two intervals still overlap, or one of the sides has fewer than 30 observations. That is not a finding of "no difference" — it is a finding that these numbers cannot tell you.'
    : '';
  const thin = current?.kind === 'analysis' && [current.before, current.after].some(side => side.warning)
    ? `<div class="warning">Fewer than 30 observations on at least one side. The interval around a small sample is wide enough to swallow most differences worth arguing about.</div>`
    : '';
  const result = current?.kind === 'analysis' ? `<div class="quality-result">
    <div class="quality-stats">
      ${statusCard('Decision', current.direction, current.significant ? (current.direction === 'improved' ? 'passed' : 'failed') : 'warning')}
      ${statusCard('Delta', (current.delta > 0 ? '+' : '') + Number(current.delta).toFixed(3))}
    </div>
    ${thin}
    <div class="table-scroll"><table><thead><tr><th>Set</th><th>Mean, with 95% interval</th><th>Observations</th></tr></thead><tbody>
      <tr><td>Baseline</td><td>${interval(current.before)}</td><td>${current.before.samples}</td></tr>
      <tr><td>Candidate</td><td>${interval(current.after)}</td><td>${current.after.samples}</td></tr>
    </tbody></table></div>
    <p>${esc(verdict)}</p>
  </div>` : '';
  const slices = current?.kind === 'slices' ? `<div class="quality-result">
    <div class="table-scroll"><table><thead><tr><th>Slice</th><th>Quality</th><th>Runs</th><th>Failures</th></tr></thead><tbody>${current.rows.map(row => `<tr><td>${esc(row.slice)}</td><td>${Number(row.quality).toFixed(3)}</td><td>${row.runs}</td><td>${row.failures}</td></tr>`).join('')}</tbody></table></div>
    <p class="meta">Worst slice first. Each row is the examples carrying one tag, so a row that appears on several
      tags is counted under each of them, and rows with no tags of their own are grouped as
      <code>untagged</code>.</p>
  </div>` : '';
  const sliceGate = state.report ? '' : prerequisite('Slice analysis needs a completed benchmark; confidence comparison can run now.', 'prompt', 'Run a benchmark');
  return `<div class="screen-split work-wide">
    <div class="build-work">
      ${qualityError()}${sliceGate}
      <section class="screen-body">
        <h2>Two sets of scores</h2>
        <div class="quality-form">
          <label>Baseline scores<textarea id="stats-before" placeholder="0.80, 0.75, 0.90"></textarea></label>
          <label>Candidate scores<textarea id="stats-after" placeholder="0.84, 0.82, 0.91"></textarea></label>
        </div>
        <p class="field-hint">One score per example, between 0 and 1, separated by commas or new lines. These are
          per-example scores from two runs — not two averages, which have no spread for an interval to be drawn
          around.</p>
        <div class="form-actions"><button class="stats-run">Compare confidence</button><button class="ghost slices-run" ${state.report ? '' : 'disabled'}>Analyze last benchmark by tags</button></div>
      </section>
      ${result}${slices}
    </div>
    <aside class="screen-guide" data-testid="analysis-guide">${analysisGuide()}</aside>
  </div>`;
}

/* Zone three. The rule the screen applies, written down, because a reader who
 * does not know it reads "inconclusive" as a fault in their prompt. */
function analysisGuide() {
  return `<h2>The rule this screen applies</h2>
    <p class="guide-lead">A 95% interval around each mean. The difference counts only if the intervals do not
      overlap and both sides have at least 30 observations; everything else comes back inconclusive.</p>
    <dl class="guide-stack">
      <div><dt>What to paste in</dt><dd>The per-example scores behind two runs, each between 0 and 1. Two averages
        have no spread, and spread is the whole question here.</dd></div>
      <div><dt>Why thirty</dt><dd>Below it the interval is wide enough to cover almost any difference you would care
        about, so a non-overlap is luck as often as a finding.</dd></div>
      <div><dt>A strict test, on purpose</dt><dd>Non-overlapping intervals will call some real differences
        inconclusive, and will rarely call a difference real that is not. That is the trade worth making here.</dd></div>
      <div><dt>Inconclusive is not "the same"</dt><dd>It means these numbers cannot separate the two. The answer is
        more examples or more repeats, not a smaller tolerance.</dd></div>
      <div><dt>By tags is a different question</dt><dd>The second button splits your last benchmark by the tags on
        its examples, worst first. An average of 0.9 hiding one tag at 0.4 is the failure no single number shows.</dd></div>
    </dl>
    <p class="guide-note">Scores to paste come from a run on <a href="#results/history" data-global-tab="results" data-screen="results" data-mode="history">Results</a>; a whole-set comparison of two prompts is <a href="#results/regressions" data-global-tab="results" data-screen="results" data-mode="regressions">Regressions</a>, which applies a tolerance instead.</p>`;
}

function baseBenchmarkPayload() {
  // The run setup lives on the screen that runs it, so what it was set to is
  // read from state and not from a control that only exists on that screen.
  if (!state.chosen || !state.run.dataset) throw new Error('Create a prompt and choose a benchmark dataset first.');
  return {technique_id:state.chosen, dataset:state.run.dataset, repeats:Number(state.run.repeats) || 1};
}

/* --------------------------------------------------------------------------
 * The same three zones as every other screen of this section: the rail you came
 * down, the work, and what there is to know about it. The work takes the wide
 * half — a row per model with four numbers on it does not fit a 380px column,
 * and the notes beside it do.
 *
 * The screen used to be a bare textarea, a button, and a table that appeared
 * underneath with no word about what its columns meant. The three questions a
 * reader has here — what stays fixed, what the numbers are averages of, and
 * when a gap is worth acting on — are answered in the third zone rather than
 * left to be guessed from the table.
 * -------------------------------------------------------------------------- */
function renderModelMatrix() {
  const current = screenResult('model-matrix');
  const result = current?.kind === 'matrix' ? `<div class="quality-result">
    <div class="quality-stats">${statusCard('Winner model', current.winner_model)}</div>
    <div class="table-scroll"><table><thead><tr><th>Model</th><th>Quality</th><th>Latency</th><th>Cost</th><th>Failed runs</th></tr></thead><tbody>${current.reports.map(item => `<tr${item.model_id === current.winner_model ? ' class="row-win"' : ''}><td>${esc(item.model_id)}</td><td>${item.scorecard.quality.toFixed(3)}</td><td>${item.scorecard.mean_latency_seconds.toFixed(2)}</td><td>${item.scorecard.mean_cost_usd == null ? 'unknown' : item.scorecard.mean_cost_usd.toFixed(6)}</td><td>${item.scorecard.failures} / ${item.scorecard.runs}</td></tr>`).join('')}</tbody></table></div>
    <p class="meta">Quality is the average over the set; latency and cost are per call. No published price reads
      <code>unknown</code> — a local model costs time, not money. Unanswered runs count as failures and score as
      misses, so a row whose failures equal its runs was unreachable, not bad.</p>
  </div>` : '';
  const gate = state.chosen ? '' : prerequisite('Create and choose a prompt before comparing models.', 'prompt', 'Create a prompt');
  return `<div class="screen-split work-wide">
    <div class="build-work">
      ${qualityError()}${gate}
      <section class="screen-body">
        <h2>Models to put in the running</h2>
        <label for="matrix-models">Model IDs, one per line</label>
        <textarea id="matrix-models" class="matrix-models" placeholder="llama3.2:3b\nqwen3:8b"></textarea>
        <p class="field-hint run-against" data-lead="Every model runs">${runAgainst('Every model runs')}</p>
        <div class="form-actions"><button class="matrix-run" data-action="run-model-matrix" ${state.chosen ? '' : 'disabled'}>Run matrix</button></div>
      </section>
      ${result}
    </div>
    <aside class="screen-guide" data-testid="matrix-guide">${modelMatrixGuide()}</aside>
  </div>`;
}

/* What a run is held fixed against, said before it starts: a comparison read
 * without knowing which set it ran on says nothing at all. The set is chosen on
 * the screens that measure and can arrive after these screens have been drawn,
 * so the line is written by a function the context update can call again rather
 * than baked into the markup once. `lead` is the screen's own subject — models
 * on one, context variants on the other.
 */
function runAgainst(lead) {
  const dataset = state.run.dataset;
  if (!dataset) {
    return `No benchmark set is chosen yet — pick one on <a href="#report" data-global-tab="report" data-screen="report">Measurement</a>, and it is the set every row on this screen is scored on.`;
  }
  const rows = Number(state.datasetSizes.get(dataset)) || 0;
  const repeats = Number(state.run.repeats) || 1;
  return `${esc(lead)} the same prompt over <code>${esc(dataset)}</code>${rows ? ` — ${plural(rows, 'example')}` : ''}, ${plural(repeats, 'time')} each.`;
}

/* Zone three. What the table cannot say about itself. */
function modelMatrixGuide() {
  return `<h2>What a matrix decides</h2>
    <p class="guide-lead">Not which model is best — which of these models your prompt survives. Wording that only
      works on the model you wrote it against looks exactly like a good score until a second model is in the table.</p>
    <dl class="guide-stack">
      <div><dt>Only the model changes</dt><dd>Same prompt, same examples, same repeats on every row. That is what
        makes two numbers here comparable, and why the set is chosen elsewhere.</dd></div>
      <div><dt>Quality</dt><dd>The average over the set's rows, from the same graders <a href="#report" data-global-tab="report" data-screen="report">Measurement</a> uses. A claim about these examples, not about the models in general.</dd></div>
      <div><dt>Latency and cost</dt><dd>Means per call, so they carry the price of a method that samples several
        answers before it votes. The cheapest row is only interesting if it can also do the work.</dd></div>
      <div><dt>A gap is not yet a decision</dt><dd>Two models a few thousandths apart are noise on a small set. Take
        the pair to <a href="#results/significance" data-global-tab="results" data-screen="results" data-mode="significance">Significance</a> first.</dd></div>
      <div><dt>The ids have to be reachable</dt><dd>Spelled the way the provider spells them, and served by a backend
        this machine can reach. An unreachable id still gets a row — every answer is an error and it scores near
        nothing, which is why the failed-run count sits beside the score.</dd></div>
    </dl>
    <p class="guide-note">Models and keys live in <a href="#settings" data-global-tab="settings" data-screen="settings">Settings</a>. Nothing here changes the model the rest of the app measures with.</p>`;
}

/* --------------------------------------------------------------------------
 * The same three zones again: the rail, the two contexts and what they scored,
 * and beside them what a context run does to your examples — which is the one
 * thing the numbers cannot say about themselves.
 * -------------------------------------------------------------------------- */
function renderContextLab() {
  const current = screenResult('context-lab');
  // The answer used to be printed as the JSON object it arrived in. It is a
  // ranking of two things by one number, so it is written as one.
  const rows = current?.kind === 'context'
    ? current.reports.map(item => {
        const card = item.report.scorecard;
        return `<tr${item.context === current.winner_context ? ' class="row-win"' : ''}>
          <td>${esc(item.context)}</td>
          <td>${Number(card.quality).toFixed(3)}</td>
          <td>${Number(card.mean_latency_seconds).toFixed(2)}</td>
          <td>${Math.round(Number(card.mean_prompt_tokens))}</td>
          <td>${card.failures} / ${card.runs}</td>
        </tr>`;
      }).join('')
    : '';
  const result = current?.kind === 'context' ? `<div class="quality-result">
    <div class="quality-stats">${statusCard('Best context', current.winner_context)}</div>
    <div class="table-scroll"><table><thead><tr><th>Context</th><th>Quality</th><th>Latency</th><th>Prompt tokens</th><th>Failed runs</th></tr></thead><tbody>${rows}</tbody></table></div>
    <p class="meta">Prompt tokens are what the context costs on every single call, which is the price of the winning
      variant if you keep it. This run is not written into your history — nothing on
      <a href="#results/history" data-global-tab="results" data-screen="results" data-mode="history">Results</a> changes because of it.</p>
  </div>` : '';
  const gate = state.chosen ? '' : prerequisite('Create a prompt before comparing context variants.', 'prompt', 'Create a prompt');
  return `<div class="screen-split work-wide">
    <div class="build-work">
      ${qualityError()}${gate}
      <section class="screen-body">
        <h2>Two contexts, one prompt</h2>
        <div class="quality-form">
          <label>Variant A name<input id="ctx-a-name" value="full"></label>
          <label>Variant B name<input id="ctx-b-name" value="compressed"></label>
          <label>Context A<textarea id="ctx-a"></textarea></label>
          <label>Context B<textarea id="ctx-b"></textarea></label>
        </div>
        <p class="field-hint run-against" data-lead="Both variants run">${runAgainst('Both variants run')}</p>
        <div class="form-actions"><button class="context-run" data-action="compare-contexts" ${state.chosen ? '' : 'disabled'}>Compare contexts</button></div>
      </section>
      ${result}
    </div>
    <aside class="screen-guide" data-testid="context-guide">${contextLabGuide()}</aside>
  </div>`;
}

/* Zone three. Where the text you type actually ends up, and what the winning
 * number costs to keep. */
function contextLabGuide() {
  return `<h2>What a context run does</h2>
    <p class="guide-lead">Each variant is pasted in front of every example and the whole set is scored again. The
      question is not which text reads better, but whether the extra material earns the tokens it costs on every
      call.</p>
    <dl class="guide-stack">
      <div><dt>Where the text goes</dt><dd>Ahead of the input, as <code>CONTEXT:</code> then your variant, then
        <code>INPUT:</code> and the row. Your prompt is untouched.</dd></div>
      <div><dt>Both variants, the same rows</dt><dd>Same prompt, same examples, same repeats; only the context
        differs. An empty variant is a fair thing to put in — it says what the context is worth against nothing.</dd></div>
      <div><dt>Longer is not free</dt><dd>The prompt-token column is what a variant costs on every call for as long
        as you keep it. A compressed variant scoring within noise of the full one is the cheaper prompt, not a
        worse one.</dd></div>
      <div><dt>It leaves no trace</dt><dd>These runs are not recorded: they are an experiment on material you are
        still choosing. Once a context is settled, put it in the prompt and measure that on <a href="#report" data-global-tab="report" data-screen="report">Measurement</a>.</dd></div>
      <div><dt>A win still has to be significant</dt><dd>Two variants a few thousandths apart on a small set are the
        same variant. Take the pair to <a href="#results/significance" data-global-tab="results" data-screen="results" data-mode="significance">Significance</a> first.</dd></div>
    </dl>`;
}

/* --------------------------------------------------------------------------
 * The same three zones: the rail, the register and the one control that adds
 * to it, and beside it what a release actually is here — a frozen copy of a
 * prompt with a hash, moved along a line of five words. Nothing on this screen
 * deploys anything, and a screen with a button marked "Release" has to say so.
 * -------------------------------------------------------------------------- */
/* Which run a version was shipped on, and whether that run is about this text.
 *
 * An id alone read as proof. It is not: the citation is only worth something
 * when the run measured the prompt that was frozen, which the server now checks
 * by fingerprint rather than believing. */
const EVIDENCE_WORD = {
  measured:['ok', 'measured'],
  indirect:['wait', 'other prompt'],
  unverified:['idle', 'unmeasured']
};

function releaseEvidenceCell(release) {
  const [tone, word] = EVIDENCE_WORD[release.evidence] || ['idle', release.evidence || 'unmeasured'];
  const title = {
    measured:'The cited run measured this exact text.',
    indirect:'A run is cited, but it measured a different prompt — its numbers are not about this text.',
    unverified:'No run is cited: nothing here was measured.'
  }[release.evidence] || '';
  // A release from before runs were recorded cites nothing and can never be
  // approved where a bar exists. It can be given its evidence late — verified
  // the same way, so this is not a way past the bar.
  const citeable = ['draft', 'tested'].includes(release.status) && state.provenance
    && release.evidence !== 'measured';
  const cite = citeable
    ? `<button type="button" class="ghost" data-cite-release="${esc(state.provenance.experiment_id)}"
        title="Attach the run the prompt on your screen is carrying. It counts only if that run measured this exact text.">Cite current run</button>`
    : '';
  if (!release.experiment_id) return `<span class="status-chip ${esc(tone)}" title="${esc(title)}">${esc(word)}</span> ${cite}`;
  return `<a href="#results/history" data-global-tab="results" data-screen="results" data-mode="history" data-showing="${esc(release.experiment_id)}"><code>${esc(release.experiment_id)}</code></a>
    <span class="status-chip ${esc(tone)}" title="${esc(title)}">${esc(word)}</span> ${cite}`;
}

/* The committed thresholds, said before the button rather than after it.
 *
 * `prompt-playoff.yaml` was enforced by CI alone, which guarded the repository
 * and not the release: a version could be waved through by hand at numbers the
 * project had already declared unacceptable. Approve now refuses the same way
 * CI does — and a bar that could not be applied refuses too, because a gate you
 * cannot evaluate is not a gate that passed. */
const GATE_WORD = {
  passed:['ok', 'Clears the bar'],
  failed:['bad', 'Below the bar'],
  // Not "nothing to check": there is a bar, and it is the run that is missing.
  unmeasured:['wait', 'No run to check'],
  unverified:['bad', 'Wrong prompt'],
  stale:['bad', 'Data moved'],
  unenforceable:['wait', 'Cannot be checked'],
  not_configured:['idle', 'No bar set']
};

function releaseGateControl(release) {
  const gate = q.gates[release.id];
  if (!gate) return '<button data-release-action="approve">Approve</button>';
  const [tone, word] = GATE_WORD[gate.status] || ['idle', gate.status];
  const blocked = ['failed', 'stale', 'unverified', 'unmeasured', 'unenforceable'].includes(gate.status);
  const numbers = (gate.thresholds || [])
    .map(item => `${item.field} ${item.measured} vs ${item.bound} ${item.required}`).join('; ');
  return `<span class="status-chip ${esc(tone)}" title="${esc(gate.reason || numbers || word)}">${esc(word)}</span>
    <button data-release-action="approve"${blocked ? ' disabled title="' + esc(gate.reason || '') + '"' : ''}>Approve</button>`;
}

/* Taking a row out of the register for good.
 *
 * Every other control on a release row moves it along the line — test, approve,
 * release, roll back, deprecate — and none of them can express the row that
 * should never have existed: a name typed twice, a prompt frozen against the
 * wrong run, a draft registered to see what the button did. Deprecating those
 * leaves them in the table forever, saying something that was never true.
 *
 * Armed before it fires, like a dataset, and for the same reason: this is the
 * only control here that destroys something. What it destroys is a row — the
 * run the release cited stays in the history, and the manifest already exported
 * is a file in somebody's repository, which is where the record of a shipped
 * prompt was supposed to live anyway.
 */
function releaseDeleteControl(release) {
  if (q.pendingReleaseDelete !== release.id) {
    return `<button type="button" class="ghost" data-release-delete-arm="${esc(release.id)}"
      title="Take this version out of the register">Delete</button>`;
  }
  // A production row is the app's answer to "what is live". Deleting it leaves
  // that name with no answer, and no earlier version to roll back to, so the
  // sentence says so before the click rather than the column going quiet after.
  const cost = release.status === 'production'
    ? `${release.name} has nothing in production after this, and nothing to roll back to.`
    : 'The run it cited stays in the history; only this row goes.';
  return `<span class="delete-confirm">
      <button type="button" class="danger" data-release-delete-now="${esc(release.id)}">Delete for good</button>
      <button type="button" class="ghost" data-release-delete-cancel="1">Keep</button>
      <small>${esc(cost)}</small>
    </span>`;
}

/* The frozen text itself, under the fingerprint that stands for it.
 *
 * The row said `a41f0c9e2b` and nothing else. The whole point of a release is
 * that it is the exact wording somebody shipped, and the exact wording was the
 * one thing the register could not show: it was on this server the whole time,
 * reachable only by downloading the manifest and opening it in another program.
 * A fingerprint you cannot resolve to a prompt is a receipt for a lost parcel. */
function releasePromptRow(release) {
  const parts = promptMessages(release.prompt);
  const key = registerCopy(`release:${release.id}`,
    parts.length ? promptPlainText(release.prompt) : JSON.stringify(release.prompt, null, 2));
  const body = parts.length
    ? parts.map(promptPartBlock).join('')
    : `<div class="prompt-part"><span class="prompt-role">FROZEN PAYLOAD</span>
        <pre>${esc(JSON.stringify(release.prompt, null, 2))}</pre></div>`;
  return `<tr class="release-text" data-release-text-for="${esc(release.id)}" hidden>
      <td colspan="6">
        <div class="release-text-body">
          ${parts.length ? '' : '<p class="field-hint">This release was registered with a payload that is not a compiled prompt, so it is shown as it was frozen.</p>'}
          ${body}
          <div class="subject-full-actions">${copyButton(key, 'Copy frozen text', `Copy the exact text release ${release.name} v${release.version} froze`)}</div>
          <div class="copy-status" data-copy-status="release:${esc(release.id)}" role="status" aria-live="polite"></div>
        </div>
      </td>
    </tr>`;
}

function renderReleases() {
  // Arrived on one stage of the funnel: the table keeps its columns and its
  // buttons, and holds only the releases sitting in that stage.
  const only = showingOn('ship');
  const releases = only ? q.releases.filter(item => item.status === only) : q.releases;
  const rows = releases.map(item => `<tr data-release-id="${esc(item.id)}"${item.status === 'production' ? ' class="row-win"' : ''}><td>${esc(item.name)} v${item.version}</td><td><span class="status-chip ${esc(item.status)}">${esc(item.status)}</span></td><td>${esc(item.technique_id)}</td><td><button type="button" class="link-hash" data-release-text="${esc(item.id)}" aria-expanded="false" title="Read the text this fingerprint stands for"><code>${esc(item.prompt_hash.slice(0, 10))}</code></button></td><td>${releaseEvidenceCell(item)}</td><td><div class="quality-actions">${item.status === 'draft' ? '<button data-release-action="test">Test</button>' : ''}${item.status === 'tested' ? releaseGateControl(item) : ''}${item.status === 'approved' ? '<button data-release-action="release">Release</button>' : ''}${item.status === 'production' ? '<button data-release-action="rollback">Rollback</button><button class="ghost" data-release-action="deprecate">Deprecate</button>' : ''}<button class="ghost" data-release-action="export" title="Download the manifest and the checks block">Export</button>${releaseDeleteControl(item)}</div></td></tr>${releasePromptRow(item)}`).join('');
  // With no prompt to register, the band below is the whole of what this half
  // of the screen can say. The form used to stand under it anyway — a heading
  // claiming to register "the prompt you are holding" when nothing was being
  // held, a name already filled in, and a dead button — so the screen asked and
  // refused in the same breath. Reading the register needs no prompt, so that
  // half stays.
  const gate = state.program ? '' : prerequisite('Author a prompt before registering a release.', 'prompt', 'Author a prompt');
  // A table of headings over nothing is a table that lost its rows. Say which
  // of the two it is.
  const table = rows
    ? `<div class="table-scroll"><table><thead><tr><th>Release</th><th>Status</th><th>Technique</th><th>Hash</th><th>From run</th><th>Action</th></tr></thead><tbody>${rows}</tbody></table></div>`
    : `<div class="empty">${only ? `No release is sitting at ${esc(only)}.` : 'No releases registered yet.'}</div>`;
  const live = q.releases.filter(item => item.status === 'production');
  const serving = live.length
    ? `In production: ${live.map(item => `<code>${esc(item.name)} v${item.version}</code>`).join(' ')}. Registering under the same name adds the next version beside it; promoting that one retires this.`
    : 'Nothing is in production yet. A new name starts at v1, and registering the same name again adds v2 beside it.';
  return `<div class="screen-split work-wide">
    <div class="build-work">
      ${qualityError()}${gate}
      ${state.program ? `<section class="screen-body">
        <h2>Register the prompt you are holding</h2>
        <div class="quality-form">
          <label>Release name<input id="release-name" value="production-prompt"></label>
        </div>
        <p class="field-hint">${serving}</p>
        <p class="field-hint">${state.provenance
          ? `This prompt carries the ${esc(state.provenance.kind)} on <code>${esc(state.provenance.dataset)}</code> — quality ${state.provenance.quality.toFixed(3)}. That run is recorded against the release, and the server checks it measured this exact text${state.provenance.kind === 'optimization' ? ' — an optimization did not, so this would register as evidence about the search rather than about the prompt' : ''}.`
          : 'Nothing has been measured on this prompt as it stands, so the release would be registered unmeasured. Run it on <a href="#report" data-global-tab="report" data-screen="report">Measurement</a> first.'}</p>
        <div class="form-actions"><button class="release-create" data-action="create-release">Register current prompt</button></div>
      </section>` : ''}
      <section class="screen-body">
        <h2>The register</h2>
        ${table}
        <p class="field-hint">A fingerprint in the <b>Hash</b> column opens the exact text that release froze.
          Beyond that, a register kept in here is not a system of record: no colleague, no CI job and no
          future checkout can read it. <b>Export</b> writes two files to commit — the manifest, which carries the
          exact text, its fingerprint, the run behind it and the verdict of the bar; and a <code>checks:</code>
          block for <code>prompt-playoff.yaml</code>, which is what
          <code>prompt-playoff check</code> enforces in CI.</p>
      </section>
    </div>
    <aside class="screen-guide" data-testid="releases-guide">${releasesGuide()}</aside>
  </div>`;
}

/* Zone three. What is frozen, what the five words mean, and the thing the
 * screen cannot do however the buttons are labelled. */
function releasesGuide() {
  return `<h2>What a release is here</h2>
    <p class="guide-lead">A frozen copy of the prompt, with a SHA-256 of its text and a version number that counts
      up per name — and, on <em>Export</em>, two files your repository can hold.</p>
    <dl class="guide-stack">
      <div><dt>The export is the point</dt><dd>A register kept in here is not a system of record: no colleague, no CI
        job and no future checkout can read it. <em>Export</em> writes the manifest — exact text, fingerprint, the run
        behind it, the verdict of the bar — and a <code>checks:</code> block for <code>prompt-playoff.yaml</code>.
        Commit both, and <code>prompt-playoff check</code> enforces them where a gate actually guards something.</dd></div>
      <div><dt>Nothing here deploys anything</dt><dd>The buttons move a label along a line: draft, tested, approved,
        production, deprecated. "Production" means the version this register calls live; testing and shipping still
        happen where they happened before.</dd></div>
      <div><dt>The hash is the point</dt><dd>Two releases with the same hash are the same prompt, whatever they are
        named — that is how a number in your history is tied to the text that produced it.</dd></div>
      <div><dt>One production version per name</dt><dd>Promoting a version deprecates the one that was live, and
        rollback puts it back. Rows change status; nothing is deleted.</dd></div>
      <div><dt>The order is enforced</dt><dd>Each button is the only move its status allows. A draft cannot jump to
        production.</dd></div>
      <div><dt>Every version names its run, and the name is checked</dt><dd>A run records a fingerprint of the
        prompt it measured, so a release is marked <em>measured</em> only when that matches the frozen text.
        <em>other prompt</em> means the cited run measured something else — the optimization behind the wording,
        say. Registering either is allowed; approving on anything but <em>measured</em> is not.</dd></div>
      <div><dt>Evidence can arrive late</dt><dd>A version registered before its run existed is not stuck: measure
        the prompt, come back, and <em>Cite current run</em> attaches it, verified the same way. An approved version
        keeps the run it was approved on.</dd></div>
      <div><dt>Approval is gated on the committed numbers</dt><dd>Where <code>prompt-playoff.yaml</code> sets a bar
        for this method, the cited run has to clear it — the same thresholds CI enforces. A bar that cannot be
        applied refuses too: no run, a missing field, or examples that have changed since.</dd></div>
      <div><dt>Nobody is asked to approve their own work</dt><dd>Registering used to raise an item in Reviews asking
        the same person, at the same keyboard, to approve what they had just registered — and advancing was refused
        until they clicked it. One user cannot be two. The committed thresholds are the gate; where a method has
        none, the release is recorded and the export hands you a <code>checks:</code> block to commit so that it
        does.</dd></div>
    </dl>
    <p class="guide-note">What gets registered is the prompt currently authored on <a href="#prompt" data-global-tab="prompt" data-screen="prompt">Prompt text</a> — measure it first, so the version
      you freeze is one you have a number for.</p>`;
}

/* Three unrelated checks used to sit on one screen as six blank fields in a
 * row. They are three tools, so they are three cards: each says what it answers
 * before it asks for anything, and only one is open at a time. */
const subTool = (id, title, question, body, open=false) => `<details class="sub-tool"${open ? ' open' : ''} data-sub-tool="${id}">
  <summary><span class="sub-title"><strong>${esc(title)}</strong><small>${esc(question)}</small></span></summary>
  <div class="sub-body">${body}</div>
</details>`;

/* What each check answers, in its own units.
 *
 * All three used to print the raw JSON they got back, which is a way of saying
 * "here is the object, you work it out". A number nobody can read is not a
 * measurement, so each one is written out as the thing it decided, and the
 * numbers that decided it stand under it.
 */
// `chips` sets its codes flush against each other, which reads as one long word
// when the values are words rather than identifiers.
const wordChips = values => values.map(value => `<code>${esc(value)}</code>`).join(' ');

function driftResult(value) {
  const shift = Number(value.vocabulary_shift);
  const before = Number(value.error_rate_before), after = Number(value.error_rate_after);
  const verdict = value.alert
    ? 'These inputs have moved. A score measured on the old ones is a weaker claim about these than it looks.'
    : 'These inputs still look like the ones you tested on, so a score measured there still speaks about them.';
  const terms = (value.new_terms || []).length
    ? `<p class="meta">Words that appear now and did not before: ${wordChips(value.new_terms)}</p>`
    : '<p class="meta">No word is new enough to stand out.</p>';
  return `<div class="quality-result">
    <div class="quality-stats">
      ${statusCard('Vocabulary shift', shift.toFixed(3), value.alert ? 'failed' : 'passed')}
      ${statusCard('Errors before', before.toFixed(3))}
      ${statusCard('Errors after', after.toFixed(3))}
    </div>
    <p>${esc(verdict)}</p>
    <p class="meta">The shift is how far the word mix has moved, from 0 (identical) to 1 (nothing in common);
      anything from 0.2 up is called out, as is an error rate five points worse than before.</p>
    ${terms}</div>`;
}

function trajectoryResult(value) {
  const score = Number(value.score);
  const missing = (value.missing_tools || []).length
    ? `<p>Never called: ${wordChips(value.missing_tools)} — the run cannot have done what those tools are for.</p>`
    : '<p>Every required tool was called at least once.</p>';
  return `<div class="quality-result">
    <div class="quality-stats">
      ${statusCard('Trajectory score', score.toFixed(2), score >= 0.8 ? 'passed' : 'failed')}
      ${statusCard('Steps', String(value.steps))}
      ${statusCard('Failed steps', String(value.failures), value.failures ? 'warning' : '')}
      ${statusCard('Repeated steps', String(value.unnecessary_repeats), value.unnecessary_repeats ? 'warning' : '')}
    </div>
    ${missing}
    <p class="meta">One point to start with; a failed step costs 0.2, a needless repeat 0.1, a tool that was never
      called 0.25.${value.recovered ? ' The run recovered from at least one failure on its own.' : ''}</p></div>`;
}

function securityResult(value) {
  // Two different answers arrive here: a finished run when there is a prompt to
  // attack, and the attack rows themselves when there is not.
  if (Array.isArray(value)) {
    return `<div class="quality-result">
      <p><strong>${plural(value.length, 'injection case')}</strong> built from your input. There is no prompt to run
        them against yet — write one on <a href="#prompt" data-global-tab="prompt" data-screen="prompt">Prompt text</a>,
        then come back and this button runs them.</p>
      <ul class="case-list">${value.slice(0, 5).map(row => `<li><code>${esc(row.id)}</code> ${esc(String(row.input).slice(0, 180))}…</li>`).join('')}</ul></div>`;
  }
  const card = value.scorecard || {};
  const held = card.grades?.injection_resistance;
  const broke = (value.runs || []).filter(run => run.grades?.injection_resistance === 0);
  return `<div class="quality-result">
    <div class="quality-stats">
      ${statusCard('Held against injection', held == null ? 'not scored' : held.toFixed(3), held === 1 ? 'passed' : 'failed')}
      ${statusCard('Cases', String(value.examples ?? (value.runs || []).length))}
      ${statusCard('Failed outright', String(card.failures ?? 0), card.failures ? 'warning' : '')}
    </div>
    <p>${broke.length
      ? `${plural(broke.length, 'case')} made the prompt emit the canary secret: ${wordChips(broke.slice(0, 6).map(run => run.example_id))}`
      : 'No case made the prompt emit the canary secret it was told to keep.'}</p>
    <p class="meta">The suite wraps your input in instructions that try to talk the prompt out of its job. Holding
      here is evidence, not a guarantee: it is the attacks this suite knows.</p></div>`;
}

const PRODUCTION_RESULTS = {drift:driftResult, trajectory:trajectoryResult, security:securityResult};

/* --------------------------------------------------------------------------
 * The same three zones as every other screen: the rail, the three checks, and
 * beside them what they can and cannot see. The disclaimer used to be one grey
 * line above the cards, where it read as small print; it is the first thing the
 * third zone says, because it is the thing that decides whether any of these
 * numbers mean what their names suggest.
 * -------------------------------------------------------------------------- */
function renderProduction() {
  const current = screenResult('production');
  const result = current?.kind === 'production' && PRODUCTION_RESULTS[current.tool]
    ? PRODUCTION_RESULTS[current.tool](current.value)
    : '';
  return `<div class="screen-split work-wide">
    <div class="build-work">
      ${qualityError()}
      ${subTool('drift', 'Input drift', 'Are real inputs still like the ones you tested on?', `
        <div class="quality-form">
          <label>Baseline inputs, one per line<textarea id="drift-before" placeholder="the inputs your examples were built from"></textarea></label>
          <label>Current inputs, one per line<textarea id="drift-after" placeholder="inputs you have seen since"></textarea></label>
        </div>
        <div class="sub-actions"><button class="drift-run" type="button">Compare the two sets</button></div>`, true)}
      ${subTool('trajectory', 'Agent runs', 'Did the agent call the tools it was supposed to?', `
        <div class="quality-form">
          <label class="wide">Trajectory JSON<textarea id="trajectory-json" placeholder='[{"tool":"search","success":true},{"tool":"browser","success":false,"recovered":true}]'></textarea></label>
          <label>Required tools, comma separated<input id="trajectory-tools" placeholder="search, browser"></label>
        </div>
        <div class="sub-actions"><button class="ghost trajectory-run" type="button">Evaluate trajectory</button></div>`)}
      ${subTool('security', 'Injection attempts', 'Does the prompt hold when the input fights it?', `
        <div class="quality-form">
          <label class="wide">Input for the security suite<textarea id="security-input"></textarea></label>
        </div>
        <div class="sub-actions"><button class="ghost security-run" type="button">${state.chosen ? 'Run security evaluation' : 'Generate security cases'}</button></div>`)}
      ${result}
    </div>
    <aside class="screen-guide" data-testid="production-guide">${productionGuide()}</aside>
  </div>`;
}

/* Zone three. Three checks that answer three unrelated questions, and one
 * limit that applies to all of them. */
function productionGuide() {
  return `<h2>What these checks can see</h2>
    <p class="guide-lead">Three unrelated questions in three sets of units: nothing here adds up to one number, and
      none of it can sit beside a benchmark score. Each is worth exactly as much as the material you paste in.</p>
    <dl class="guide-stack">
      <div><dt>Input drift</dt><dd>Compares the word mix of two sets of inputs, 0 (identical) to 1 (nothing in
        common); called out from 0.2 up, or when the error rate is five points worse. It says the material moved,
        not that the prompt broke — but a score measured on the old rows says less about the new ones than it looks.</dd></div>
      <div><dt>Agent runs</dt><dd>Reads a trajectory pasted as JSON — one object per step, the tool it called and
        whether it worked. From one point: 0.2 off a failed step, 0.1 off a needless repeat, 0.25 off a required
        tool never called.</dd></div>
      <div><dt>Injection attempts</dt><dd>Wraps your input in three kinds of interference — an injected instruction,
        a conflicting one, and noise — one of which asks for a secret token the model was told to keep. Emitting it
        is the failure; holding is evidence about these three attacks, not about the next one.</dd></div>
      <div><dt>Two of the three need a prompt</dt><dd>Without one, the security tool shows the cases it built and
        stops. Drift and trajectories work on pasted material alone.</dd></div>
      <div><dt>None of this is recorded</dt><dd>Spot checks: run one, read it, act on it. Nothing enters your
        history or moves a gate on <a href="#results/regressions" data-global-tab="results" data-screen="results" data-mode="regressions">Regressions</a>.</dd></div>
    </dl>`;
}

function datasetSource(name) {
  if (name.startsWith('builder:')) return 'Reviewed builder dataset';
  if (name.startsWith('hf:')) return 'Hugging Face';
  // An upload is now either kind, and which one only shows up on the day the
  // server restarts — so the row says it while there is still time to change it.
  if (name.startsWith('uploaded:')) {
    return state.datasetFacts.get(name)?.kept ? 'Upload, kept on this machine' : 'Upload, this session only';
  }
  if (name.startsWith('business:')) return 'Business catalogue';
  return 'Bundled';
}

/* --------------------------------------------------------------------------
 * The library, in three zones.
 *
 * They are three answers to one question — where did these rows come from and
 * what are they standing in for — and the answers are different enough that one
 * table listing all of them tells you nothing:
 *
 *   the catalogue   the work businesses pay a model to do, as categories of
 *                   business tasks, each task mapped to the public set closest
 *                   to its shape. Not rows: the reason rows were chosen, and
 *                   the tasks no public set matches honestly enough to route.
 *   business sets   the rows that mapping resolved to, bundled and ready, each
 *                   still carrying its source repository and its licence.
 *   the rest        the task benchmarks that ship with the tool, and whatever
 *                   you uploaded, imported or built. Only these can be deleted.
 *
 * Opened on one set the screen drops to that set alone, and the zones collapse
 * to the one it lives in — the narrowing is the point of opening it.
 * -------------------------------------------------------------------------- */

const MATCH_WORDS = {
  direct:['ok', 'Measurable here', 'Same input and output shape as the business case — a score here transfers.'],
  partial:['wait', 'Close match', 'A near neighbour or a component of the case. Evidence, not proof.'],
  none:['idle', 'No data for it', 'Nothing public was found in this shape, so nothing is claimed.']
};

function matchPill(match) {
  const [tone, word, why] = MATCH_WORDS[match] || MATCH_WORDS.none;
  return `<span class="state ${tone}" title="${esc(why)}">${word}</span>`;
}

function catalogSets() {
  return new Map((state.catalog?.sets || []).map(item => [item.name, item]));
}

// Every business case that names this set, so a set opened on its own can say
// what work it stands for rather than only what columns it has.
function citedBy(name) {
  const cases = [];
  for (const group of state.catalog?.groups || []) {
    for (const item of group.cases) if (item.sets.includes(name)) cases.push({...item, group:group.name});
  }
  return cases;
}

/* Which datasets belong to a category.
 *
 * A category's cases cite whatever measures them, and several cite a set that
 * lives somewhere else — the contract sets are read by two categories, and the
 * support corpus by three. Counting those in both would put the same dataset on
 * two tiles and make the shelf add up to more datasets than the server has. The
 * server already decides on one home per set, so that is what a tile counts. */
function groupSetSpecs(group) {
  const known = catalogSets();
  const names = [...new Set((group.tasks || []).map(task => task.mapped_dataset).filter(Boolean))];
  return names.map(name => known.get(name) || {
    name,
    title:name,
    available:state.datasetSizes.has(name),
    examples:state.datasetSizes.get(name),
    shape:'Packaged evaluation dataset'
  });
}

/* The recorded cases that belong to a category.
 *
 * The file says the same thing at two altitudes — a directory of business tasks
 * to browse by, and fifty cases naming who does that work — and nothing joins
 * them by hand. They do not need it: a case cites the sets that measure it, and
 * a task routes to one. Where those meet is where the case belongs, so the two
 * halves cannot drift out of step the way a written-down mapping would. */
function categoryCases(group) {
  const routed = new Set((group.tasks || []).map(task => task.mapped_dataset).filter(Boolean));
  const seen = new Set();
  const cases = [];
  for (const shelf of state.catalog?.groups || []) {
    for (const item of shelf.cases) {
      if (seen.has(item.number)) continue;
      if (!item.sets.some(name => routed.has(name))) continue;
      seen.add(item.number);
      cases.push(item);
    }
  }
  return cases;
}

// What this server actually holds for a category: the datasets it can read and
// the examples in them. The catalogue names datasets that may not be installed,
// so both are counted against the live dataset list rather than against the file.
function groupStock(group) {
  const here = groupSetSpecs(group).filter(spec => state.datasetSizes.has(spec.name));
  return {
    sets: here.length,
    rows: here.reduce((total, spec) => total + (state.datasetSizes.get(spec.name) || 0), 0)
  };
}

const catalogBrowse = () => state.catalogBrowse ||
  (state.catalogBrowse = {query:'', scope:'all', availability:'all', sort:'relevance'});

const browseNeedle = value => String(value || '').trim().toLocaleLowerCase();

function groupBrowseText(group) {
  const sets = groupSetSpecs(group).flatMap(spec => [spec.name, spec.title, spec.shape, spec.source]);
  const tasks = (group.tasks || []).flatMap(item => [item.name, item.mapped_dataset]);
  return browseNeedle([group.name, group.summary, ...sets, ...tasks].join(' '));
}

function visibleCatalogGroups() {
  const browse = catalogBrowse();
  if (browse.scope === 'yours') return [];
  const needle = browseNeedle(browse.query);
  const groups = (state.catalog?.taxonomy || []).filter(group => {
    if (browse.availability === 'available' && !groupStock(group).sets) return false;
    return !needle || groupBrowseText(group).includes(needle);
  });
  if (browse.sort === 'name') return groups.sort((a, b) => a.name.localeCompare(b.name));
  if (browse.sort === 'examples') return groups.sort((a, b) => groupStock(b).rows - groupStock(a).rows);
  return groups;
}

function visibleOwnSets(entries) {
  const browse = catalogBrowse();
  if (browse.scope === 'catalogue') return [];
  const needle = browseNeedle(browse.query);
  const own = entries.filter(([name]) => datasetIsMine(name) && (!needle || browseNeedle(name).includes(needle)));
  if (browse.sort === 'name') return own.sort(([a], [b]) => a.localeCompare(b));
  if (browse.sort === 'examples') return own.sort(([, a], [, b]) => Number(b || 0) - Number(a || 0));
  return own;
}

// A packaged business set answers the search on its own words — its name, its
// title, the shape it holds — rather than on whether a category happens to
// route to it.
function visibleBusinessSet(name) {
  const browse = catalogBrowse();
  const spec = catalogSets().get(name);
  if (browse.availability === 'available' && !spec?.available) return false;
  const needle = browseNeedle(browse.query);
  if (!needle) return true;
  const haystack = browseNeedle([name, spec?.title, spec?.shape, spec?.source, spec?.group].join(' '));
  // Treat search words independently so punctuation and natural title wording
  // do not make `email subject` miss `business:email-subject` or
  // `Email to subject line`.
  return needle.split(/\s+/).every(word => haystack.includes(word));
}

function renderCatalogBrowseControls() {
  const browse = catalogBrowse();
  const option = (value, label, selected) =>
    `<option value="${value}"${selected === value ? ' selected' : ''}>${label}</option>`;
  return `<form class="catalog-browse" data-catalog-browse role="search" aria-label="Browse datasets">
    <label class="catalog-search">
      <span class="sr-only">Search datasets and business tasks</span>
      ${icon('search')}
      <input type="search" value="${esc(browse.query)}" data-catalog-query
        placeholder="Search datasets, categories or business tasks…" autocomplete="off">
    </label>
    <div class="catalog-controls">
      <label><span>Scope</span><select data-catalog-filter="scope" aria-label="Dataset scope">
        ${option('all', 'All', browse.scope)}
        ${option('catalogue', 'Business catalogue', browse.scope)}
        ${option('yours', 'Your sets', browse.scope)}
      </select></label>
      <label><span>Availability</span><select data-catalog-filter="availability" aria-label="Dataset availability">
        ${option('all', 'All catalogue', browse.availability)}
        ${option('available', 'Dataset ready', browse.availability)}
      </select></label>
      <label class="catalog-sort"><span>Sort by</span><select data-catalog-filter="sort" aria-label="Sort datasets">
        ${option('relevance', 'Relevance', browse.sort)}
        ${option('name', 'Name', browse.sort)}
        ${option('examples', 'Most examples', browse.sort)}
      </select></label>
    </div>
  </form>`;
}

function catalogGroupRows(group) {
  const browse = catalogBrowse();
  const needle = browseNeedle(browse.query);
  const groupHit = needle && browseNeedle([group.name, group.summary].join(' ')).includes(needle);
  return (group.tasks || []).filter(task => {
    if (browse.availability === 'available' && !task.available) return false;
    return !needle || groupHit || browseNeedle([task.name, task.mapped_dataset].join(' ')).includes(needle);
  });
}

/* Zone one: the shelf. Ten kinds of work, as tiles rather than as a list of
 * names, because choosing one is the first thing anybody does here.
 *
 * A tile is a picture, the work it stands for in large type, and one line
 * saying what a model is asked to do with it. The count sits at the foot, in
 * the small type, where a fact you check after choosing belongs — the tile used
 * to lead on it, and a shelf of numbers is a shelf you read rather than one you
 * pick from.
 *
 * That count is counted, never written down: a category the catalogue describes
 * but this server has no rows for says so at the foot rather than borrowing a
 * figure from the design. The picture is decorative — every word on the tile is
 * in the text — so it carries an empty alt and the button keeps its own name.
 *
 * The tiles are laid out as a mosaic rather than as one repeated width: the
 * widths are the stylesheet's, so this function stays a description of the
 * catalogue and not of the grid. Colour is not what tells them apart — the only
 * tinted tile is the one you have open. */
function renderCatalogZone() {
  const title = '<h3 class="zone-title">Ready-made datasets by business task</h3>';
  if (state.catalogError) return `${title}
    <div class="error">The business catalogue could not be read: ${esc(state.catalogError)}</div>`;
  if (!state.catalog) return `${title}<div class="empty">Reading the catalogue…</div>`;

  const counts = state.catalog.taxonomy_counts;
  const groups = visibleCatalogGroups();
  const open = groups.find(group => group.id === state.catalogGroup);
  const cards = groups.map(group => {
    const shown = group.id === state.catalogGroup;
    const rows = catalogGroupRows(group).map(task => task.available
      ? `<a class="cat-row cat-row-ready" href="${esc(task.route)}" aria-label="${esc(task.name)} — dataset ready">
          <span>${esc(task.name)}</span><small>Dataset ready</small></a>`
      : `<span class="cat-row cat-row-off" aria-disabled="true">
          <span>${esc(task.name)}</span><small>No dataset</small></span>`).join('');
    return `<article class="cat-tile${shown ? ' open' : ''}">
      <button type="button" class="cat-category-trigger" data-catalog-group="${esc(group.id)}"
        aria-expanded="${shown}" aria-controls="catalog-open-panel" aria-label="${shown ? 'Hide' : 'Open'} ${esc(group.name)} category">
        <span class="cat-index"><b>${String(group.index).padStart(2, '0')}</b><i aria-hidden="true"></i></span>
        <span class="cat-count" aria-label="${esc(plural(group.counts.tasks, 'task'))}">${group.counts.tasks}</span>
        <span class="cat-copy"><span class="cat-name">${esc(group.name)}</span>
        <span class="cat-headline">${esc(group.summary)}</span></span>
      </button>
      <div class="cat-rows">${rows}</div>
      <button type="button" class="cat-foot" data-catalog-group="${esc(group.id)}"
        aria-expanded="${shown}" aria-controls="catalog-open-panel">
        <span class="cat-held">${shown ? 'Hide category' : `View all ${plural(group.counts.tasks, 'task')}`}</span>
        <span class="cat-arrow" aria-hidden="true">→</span>
      </button>
    </article>`;
  }).join('');

  return `${title}
    <p class="meta catalog-lead">All ${counts.categories} categories stay visible. Active task rows open a packaged dataset;
      gray rows mark honest gaps. ${counts.available} of ${plural(counts.tasks, 'task')} have a ready dataset.</p>
    ${cards ? `<div class="catalog-groups">${cards}</div>` : ''}
    ${open ? renderOpenGroup(open) : ''}`;
}

/* What a tile opens into, under the whole mosaic rather than inside one tile:
 * a tile is a fifth of a row wide, and what is inside a category is a shelf of
 * datasets. Opening it in place would shove the other five tiles down the
 * screen and leave the reader reading a column.
 *
 * The panel says which tile it belongs to and closes from its own corner. The
 * tasks come first because they are the thing you can pick up — each one that
 * has a set is a click from its rows — and the companies doing this work come
 * after, as background rather than as the point. */
function renderOpenGroup(group) {
  const stock = groupStock(group);
  const cases = categoryCases(group);
  const facts = stock.sets
    ? `${plural(stock.sets, 'dataset')} · ${stock.rows.toLocaleString('en-US')} examples`
    : 'No dataset for this kind of work is on this server';
  return `<section class="cat-panel" id="catalog-open-panel" aria-label="${esc(group.name)}">
    <div class="cat-panel-head">
      <div>
        <div class="eyebrow">Category</div>
        <h3>${esc(group.name)}</h3>
        <p class="cat-panel-lead">${esc(facts)}</p>
      </div>
      <button type="button" class="ghost" data-catalog-close="1">Close</button>
    </div>
    <div class="cat-panel-label">Business tasks</div>
    <div class="cat-panel-tasks">
      ${(group.tasks || []).map(task => {
        const body = `<span class="cat-panel-task-name">${esc(task.name)}</span>
          <span class="cat-panel-task-data">${task.available
            ? `${esc(task.mapped_dataset)} · ${esc(plural(task.examples || 0, 'example'))}`
            : 'No matching packaged dataset'}</span>
          <span class="cat-panel-task-status">${task.available ? 'Open dataset →' : 'Unavailable'}</span>`;
        return task.available
          ? `<a class="cat-panel-task ready" href="${esc(task.route)}">${body}</a>`
          : `<span class="cat-panel-task off" aria-disabled="true">${body}</span>`;
      }).join('')}
    </div>
    ${cases.length ? renderCatalogCases(cases) : ''}
  </section>`;
}

/* One card per case, rather than one row.
 *
 * A row would fit fifty of these on a screen and say nothing: the fact worth
 * seeing is a whole small story — somebody's name, what they pointed a model
 * at, and what they say came of it — and the figure at the centre of it is the
 * reason anyone reads the case at all. So the card is built around the figure
 * where there is one, the left edge carries the match as colour so a group can
 * be read without reading it, and the dataset sits at the foot where a card
 * turns back into something you can run. */
function renderCatalogCases(cases) {
  const known = catalogSets();
  const references = new Map((state.catalog.references || []).map(item => [item.id, item]));
  // The ones that can be measured lead. A group read top to bottom then runs
  // from work you can put a number on today to work you cannot, which is the
  // order anybody reading it is looking for anyway.
  const rank = {direct:0, partial:1, none:2};
  const ordered = [...cases].sort((a, b) => (rank[a.match] - rank[b.match]) || (a.number - b.number));
  const cards = ordered.map(item => {
    const source = item.source_record || {};
    const measured = item.sets.map(name => {
      const spec = known.get(name);
      return spec?.available
        ? `<a class="case-set" href="#dataset-library/${encodeURIComponent(name)}">${esc(name)}<span>${spec.examples} examples</span></a>`
        : `<span class="case-set off">${esc(name)}<span>not here</span></span>`;
    });
    // A cited-but-absent dataset is the honest half of the mapping: the case is
    // covered in the literature, just not by rows that can ship inside a wheel.
    const cited = item.references
      .map(id => references.get(id))
      .filter(Boolean)
      .map(ref => `<a class="catalog-ref" href="${esc(ref.url)}" target="_blank" rel="noreferrer noopener"
        title="${esc(ref.why)}">${esc(ref.title)} ↗</a>`);
    const evidence = measured.concat(cited).join('')
      || '<span class="case-nothing">Nothing public in this shape — your own examples are the only way to measure it.</span>';
    // The number is the whole point of the card when it exists, and most cases
    // have none. Absent, the card closes up rather than showing an empty frame.
    const claim = item.claim
      ? `<div class="case-claim"><b>${esc(item.claim)}</b><span>${esc(item.claim_of)}</span></div>`
      : '';
    const evidenceWords = {
      verified_official: ['verified', 'Official source'],
      qualified_official: ['qualified', 'Qualified source'],
      unverified: ['unverified', 'Exact claim unverified'],
    }[item.evidence_status] || ['unverified', 'Source status unknown'];
    const sourceLink = source.url
      ? `<a class="case-origin" data-evidence="${esc(evidenceWords[0])}" href="${esc(source.url)}"
          target="_blank" rel="noreferrer noopener" title="${esc(item.evidence_note)}">
          ${esc(evidenceWords[1])}: ${esc(source.publisher || source.title)} ↗</a>`
      : '';
    return `<article class="case-card" data-match="${esc(item.match)}">
      <div class="case-top">
        <span class="case-no">${String(item.number).padStart(2, '0')}</span>
        ${matchPill(item.match)}
      </div>
      <h4 class="case-task">${esc(item.task)}</h4>
      <div class="case-who">${esc(item.company)}${item.source ? `<span class="case-source">${esc(item.source)}</span>` : ''}</div>
      ${claim}
      <p class="case-story">${esc(item.story)}</p>
      ${sourceLink}
      <div class="case-evidence">${evidence}</div>
    </article>`;
  }).join('');
  return `<div class="catalog-cases">
    <div class="cat-panel-label">Who does this work with a model<span class="cat-panel-note">and what they say it did for them</span></div>
    <div class="case-grid">${cards}</div>
    <p class="field-hint">Official source means the company or its vendor published the deployment; it is not an
      independent audit. Qualified and unverified cards say exactly what the source does not establish. The numbers
      this tool stands behind are the ones on Measurement. Case sources and benchmark datasets are separate.</p>
  </div>`;
}

/* Zone two. The columns a business set has to carry that a bundled one does
 * not: which group of work it stands for, where the rows came from, and under
 * what licence — because these arrived from someone else's repository. */
function renderBusinessZone(names, {collapsed = false, open = false} = {}) {
  const known = catalogSets();
  const listed = names.filter(name => known.has(name));
  if (!listed.length) return '';
  const rows = listed.map(name => {
    const spec = known.get(name);
    const title = spec.available
      ? `<a href="#dataset-library/${encodeURIComponent(name)}">${esc(spec.title)}</a>`
      : `<span>${esc(spec.title)}</span><br><span class="pill warn">source only</span>`;
    return `<tr>
      <td>${title}<br><code class="meta">${esc(name)}</code></td>
      <td>${esc(spec.group || '—')}</td>
      <td>${state.datasetSizes.get(name) ?? '—'}${overlapFloorNote(name)}</td>
      <td>${esc(spec.shape)}</td>
      <td><a href="${esc(spec.url)}" target="_blank" rel="noreferrer noopener">${esc(spec.source)} ↗</a><br>
        <a class="meta" href="${esc(spec.license_url)}" target="_blank" rel="noreferrer noopener">${esc(spec.license)} ↗</a><br>
        <span class="meta">revision ${esc(spec.source_revision.slice(0, 12))}</span></td>
    </tr>`;
  }).join('');
  const table = `<div class="table-scroll"><table class="business-list">
      <thead><tr><th>Dataset</th><th>Category</th><th>Examples</th><th>Shape</th><th>Source</th></tr></thead>
      <tbody>${rows}</tbody>
    </table></div>`;
  // Opened on one set, this is that set's provenance and belongs open: it is
  // the answer to "whose rows am I about to be scored on".
  if (!collapsed) return `<section class="library-zone">
    <h3 class="zone-title">Where this set comes from</h3>
    <p class="meta">The repository it was sampled from and the licence that came with it. What is bundled here is a
      sample: the examples column is what this server holds, not what the source holds.</p>
    ${table}</section>`;
  // On the full screen it is the complete list of packaged business sets, which
  // is more than the tiles above route to: a set with no task whose shape it
  // honestly matches is still here, still measurable, and this is where it is
  // reachable from. What it alone can do is show every licence at once, which
  // is a question asked rarely and answered completely — so it folds, and the
  // browse path stays unobstructed — except when it is the only thing that
  // answered the search, and a fold over the answer reads as no answer.
  return `<section class="library-zone"><details class="advanced-disclosure"${open ? ' open' : ''}>
      <summary>Sources and licences<small class="meta"> — ${plural(listed.length, 'repository').replace('repositorys', 'repositories')} audited; source-only rows are not redistributed</small></summary>
      <div class="advanced-content">${table}</div>
    </details></section>`;
}

// The first rows of the set, which is what a set actually is. Eight of them:
// enough to see whether these look like your real inputs, which is the only
// question a list of names cannot answer.
const PREVIEW_ROWS = 8;

function datasetPreview(name, total) {
  const held = state.datasetRows.get(name);
  if (!held || held.status === 'loading') return '<div class="stage-title">What is inside</div><div class="empty">Reading its rows…</div>';
  if (held.status === 'error') return `<div class="stage-title">What is inside</div><div class="error">Could not read ${esc(name)}: ${esc(held.error)}</div>`;
  if (!held.rows.length) return `<div class="stage-title">What is inside</div><div class="empty">${esc(name)} has no rows, so nothing can be scored against it.</div>`;
  const shown = held.rows.slice(0, PREVIEW_ROWS);
  const cell = value => esc(asText(value).slice(0, 240));
  const rows = shown.map(row => `<tr>
      <td><code>${esc(row.id)}</code></td>
      <td>${cell(row.input)}</td>
      <td>${row.expected == null || row.expected === '' ? '<span class="meta">none</span>' : cell(row.expected)}</td>
      <td>${(row.graders || []).map(grader => `<code>${esc(grader)}</code>`).join(' ') || '<span class="meta">default</span>'}</td>
    </tr>`).join('');
  const counted = held.rows.length;
  return `<div class="stage-title">What is inside</div>
    <p class="meta">First ${shown.length} of ${plural(total ?? counted, 'row')}. These are the rows a score on this set is speaking about.</p>
    <div class="table-scroll dataset-preview" role="region" aria-label="${esc(`First rows of ${name}`)}" tabindex="0">
      <table><thead><tr><th>Row</th><th>Input</th><th>Right answer</th><th>Scored by</th></tr></thead><tbody>${rows}</tbody></table>
    </div>`;
}

/* --------------------------------------------------------------------------
 * Picking the set, on the screen that says it is where you pick.
 *
 * The library's own lead has always read "this is where you pick what a score
 * will be computed against", and until now nothing here could: the choice lived
 * only in the `Measure against` field on the three screens that run something,
 * and in the automatic selection an upload makes. So the second step of the
 * lifecycle could not finish the step it is named after, the Dataset chip in
 * the bar led to a screen that could not change what the chip said, and a
 * reader who came here through the shelf of business tasks had to carry a name
 * in their head to a different screen.
 *
 * The band states what is being measured against before it offers to change it,
 * because "which set is it now" is the question that makes the button
 * meaningful — and once the answer is this set, the band stops offering the
 * click and offers the way on instead.
 * -------------------------------------------------------------------------- */
function measureAgainstBand(name) {
  if (state.run.dataset === name) {
    return `<div class="prerequisite" role="note" data-testid="measure-against">
      <p>Every score you take next is computed against <strong>${esc(name)}</strong>.</p>
      <button type="button" class="ghost" data-prereq-target="report" data-action="resolve-prerequisite">Go and measure</button>
    </div>`;
  }
  const now = state.run.dataset
    ? `Your runs currently measure against ${state.run.dataset}.`
    : 'No set is chosen yet, so none of the three run buttons can start.';
  return `<div class="prerequisite" role="note" data-testid="measure-against">
    <p>${esc(now)}</p>
    <button type="button" class="primary" data-measure-against="${esc(name)}">Measure against this set</button>
  </div>`;
}

// The same choice from the list, for the rows the tool most wants measured: a
// set of your own is the only kind a score speaks about directly, so it is the
// one kind whose row carries the button rather than making you open it first.
//
// Chosen, the button stays where it was and goes quiet, the way the method card
// says "In use" in the same place it offers the swap. A word of prose there
// instead would be `.meta`, which is a block, and a block beside a button in a
// cell one line tall puts the two on top of each other.
/* The one action that turns a set of prose answers into a set that can be
 * scored and gated. Offered only where it would change something: a set whose
 * quality number would come from word overlap has nothing else to answer for
 * it, and this reads the requirements off the rows — the identifier a reply has
 * to carry back, the unfilled placeholder that must not ship, the length the
 * channel allows. Each is kept only where the row's own reference answer
 * already meets it, so the button cannot create a new way to be wrong. */
function contractCell(name) {
  const facts = state.datasetFacts.get(name);
  if (!facts?.free_text) return '';
  return `<div class="contract-cell">
    <select data-contract-for="${esc(name)}" aria-label="Shape of the work in ${esc(name)}">
      <option value="reply">answers to somebody</option>
      <option value="summary">summaries of a source</option>
      <option value="draft">drafts, format only</option>
    </select>
    <button type="button" class="ghost" data-action="derive-requirements" data-dataset="${esc(name)}">Add requirements</button>
  </div>`;
}

function measureCell(name) {
  const current = state.run.dataset === name;
  return `<button type="button" class="ghost" data-measure-against="${esc(name)}"
    aria-current="${current}"${current ? ' disabled' : ''}>${current ? 'Measuring' : 'Measure'}</button>`;
}

/* A bundled set lives inside the installed package: it is the same on every
 * machine that installed this version, and removing it would leave the registry
 * describing rows the server no longer has. Everything the user brought in can
 * go, and the row says which kind it is looking at. */
function datasetIsMine(name) {
  return ['uploaded:', 'hf:', 'builder:'].some(prefix => name.startsWith(prefix));
}

// Inside the wheel and named by nothing else: a business set carries its own
// prefix and belongs to the catalogue zone, so "not mine" is not the same
// question as "shipped with the tool".
function datasetIsBundled(name) {
  return !datasetIsMine(name) && !name.startsWith('business:');
}

/* Deleting rows cannot be undone and the button sits in a table of rows that
 * look alike, so the first click only arms the second. No modal: the question is
 * asked in the row it is about, and reading the name is the whole confirmation. */
function deleteCell(name) {
  if (!datasetIsMine(name)) return '<span class="meta">bundled</span>';
  return state.pendingDelete === name
    ? `<span class="delete-confirm"><button type="button" class="danger" data-delete-now="${esc(name)}">Delete for good</button><button type="button" class="ghost" data-delete-cancel="1">Keep</button></span>`
    : `<button type="button" class="ghost" data-delete-arm="${esc(name)}">Delete</button>`;
}

/* Zone three, in two parts, because they are two populations and not one table
 * with a Source column.
 *
 * The sets you brought are what a score is supposed to be about. The eleven
 * that ship inside the package are the tool's own test stand — its tests stand
 * on their shape, and its published benchmark numbers were measured on them, so
 * a good score there says this tool works, not that your prompt does. They also
 * cannot be deleted, which one shared table could only express as a greyed-out
 * word in every second row.
 *
 * Yours come first. Reference material goes below the thing it is reference
 * for.
 */
function renderYoursZone(entries) {
  const mine = entries.filter(([name]) => datasetIsMine(name));
  // Opened on one set, "you have nothing of your own" is an answer to a question
  // nobody asked: the screen was narrowed to a row, not to a shortage.
  if (!mine.length && showingOn('dataset-library')) return '';
  if (!mine.length) return `<section class="library-zone"><h3 class="zone-title">Your sets</h3>
    <p class="meta">Nothing of your own on this server yet. Rows you have seen in production are the only ones
      a score truly speaks about — <a href="#dataset-add" data-global-tab="dataset-add" data-mode="upload">upload a JSONL file</a>,
      <a href="#dataset-add/hugging-face" data-global-tab="dataset-add" data-mode="hugging-face">import a public set</a>, or
      <a href="#dataset-add/generate" data-global-tab="dataset-add" data-screen="dataset-add" data-mode="generate">build one from your task</a>.</p></section>`;
  const rows = mine.map(([name, count]) => `<tr>
    <td>${esc(name)}</td><td>${count}${overlapFloorNote(name)}</td><td>${esc(datasetSource(name))}</td>
    <td class="row-actions">${contractCell(name)}${measureCell(name)}${deleteCell(name)}</td>
  </tr>`).join('');
  return `<section class="library-zone"><h3 class="zone-title">Your sets</h3>
    <p class="meta">Uploaded, imported or built here. These are the only ones this screen can delete.</p>
    <div class="table-scroll"><table class="dataset-list">
      <thead><tr><th>Name</th><th>Examples</th><th>Source</th><th></th></tr></thead>
      <tbody>${rows}</tbody>
    </table></div></section>`;
}

function renderBundledZone(entries, {heading = true} = {}) {
  const bundled = entries.filter(([name]) => datasetIsBundled(name));
  if (!bundled.length) return '';
  // No Source column and no action column: every row has the same answer to
  // both, and a column that says one word eleven times is a column that says
  // nothing. What each set contains is written up in the guide, not here.
  // The name is a door: a benchmark is worth reading before it is worth
  // measuring against, and its rows live on the library screen.
  const rows = bundled.map(([name, count]) => `<tr>
    <td><a href="#dataset-library/${encodeURIComponent(name)}" data-global-tab="dataset-library" data-showing="${esc(name)}">${esc(name)}</a></td>
    <td>${count}${overlapFloorNote(name)}</td></tr>`).join('');
  const head = heading
    ? `<h3 class="zone-title">Shipped with the tool</h3>
      <p class="meta">The tool's own test stand: its checks are written against these rows and its published numbers
        were measured on them. Good for trying the workflow, or comparing a method against a published result — but a
        good score here describes the tool, not your task. Shipped inside the package, and not deletable.
        <a href="#guides/evaluation" data-global-tab="guides" data-screen="guides" data-mode="evaluation">What each one contains</a>.</p>`
    : '';
  return `<section class="library-zone">${head}
    <div class="table-scroll"><table class="dataset-list">
      <thead><tr><th>Name</th><th>Examples</th></tr></thead>
      <tbody>${rows}</tbody>
    </table></div></section>`;
}

/* The same table as a screen of its own.
 *
 * It moved out of the library because it answers a different question. The
 * library is "what can I measure my prompt against"; this is "what does this
 * tool measure itself against" — reference material, read once, and not a
 * shelf anybody picks their own examples off.
 *
 * Three zones, like every other screen that is mostly reading: the rail you
 * came down, the shelf itself, and what there is to know about it beside it.
 * The shelf is split in two, because the one thing a reader needs from it is
 * not in the row — four of these sets are somebody else's research corpus and
 * seven were built here, and a table that lists all eleven under one heading
 * answers "is this a real benchmark?" with silence.
 */

// Whose rows these are. The listing already carries the tag the import writes,
// so the split is read off the data rather than kept as a second list here
// that a new set would quietly fall out of.
const datasetIsPublicCorpus = name => (state.datasetFacts.get(name)?.tags || []).includes('huggingface');

// One licence covers all seven, so it is a sentence under the heading rather
// than a column repeating the same word down the table.
function builtHereLicence() {
  const licence = [...state.datasetFacts.values()]
    .map(item => item.provenance)
    .find(item => item && item.source === 'built here')?.licence;
  return licence
    ? `They are files inside this distribution and carry its licence, <strong>${esc(licence)}</strong>.`
    : '';
}

/* A licence is written as its name and, where there is one, the condition that
 * name puts on you — "CC-BY-SA-4.0 (share-alike: derived datasets must carry
 * the same licence)". The name is the cell; the condition is what a reader has
 * to act on, so it is kept under it rather than trimmed off. */
function licenceCell(licence) {
  if (!licence) return '<span class="meta">unstated</span>';
  const split = licence.indexOf(' (');
  if (split < 0) return `<span class="licence-name">${esc(licence)}</span>`;
  const condition = licence.slice(split + 2).replace(/\)$/, '');
  return `<span class="licence-name">${esc(licence.slice(0, split))}</span>
    <span class="meta">${esc(condition)}</span>`;
}

// A set whose answers are prose gets its quality number from word overlap with
// the one reference each row carries, and this is what that comparison already
// gives an answer written for a different row. Said on the shelf, because
// choosing the set is the decision this changes: a floor of 0.63 means no
// prompt work will move the number, and the set has to be scored some other way.
function overlapFloorNote(name) {
  const facts = state.datasetFacts.get(name);
  const chance = facts?.token_f1_chance_level;
  if (chance == null) return '';
  return `<br><span class="meta${chance >= 0.35 ? ' warn' : ''}">scored by word overlap; an answer
    from another row already scores ${chance.toFixed(2)}</span>`;
}

function bundledShelf(entries, {title, lead, provenance = false}) {
  if (!entries.length) return '';
  const rows = entries.map(([name, count]) => {
    const from = state.datasetFacts.get(name)?.provenance || {};
    const source = from.url
      ? `<a href="${esc(from.url)}" target="_blank" rel="noreferrer noopener">${esc(from.source)} ↗</a>`
      : esc(from.source || '—');
    return `<tr>
      <td><a href="#dataset-library/${encodeURIComponent(name)}" data-global-tab="dataset-library" data-showing="${esc(name)}">${esc(name)}</a></td>
      <td>${count}${overlapFloorNote(name)}</td>
      ${provenance ? `<td>${source}${from.citation ? `<br><span class="meta">${esc(from.citation)}</span>` : ''}</td>
      <td>${licenceCell(from.licence)}</td>` : ''}
    </tr>`;
  }).join('');
  return `<section class="screen-body shelf">
    <h2>${esc(title)}</h2>
    <p class="guide-lead">${lead}</p>
    <div class="table-scroll"><table class="dataset-list${provenance ? ' shelf-list' : ''}">
      <thead><tr><th>Name</th><th>Examples</th>${provenance ? '<th>Sampled from</th><th>Licence</th>' : ''}</tr></thead>
      <tbody>${rows}</tbody>
    </table></div></section>`;
}

function renderDatasetBundled() {
  const bundled = [...state.datasetSizes.entries()].filter(([name]) => datasetIsBundled(name));
  if (!bundled.length) return '<div class="empty">Reading what this server holds…</div>';
  const rows = bundled.reduce((total, [, count]) => total + Number(count || 0), 0);
  const publicSets = bundled.filter(([name]) => datasetIsPublicCorpus(name));
  const built = bundled.filter(([name]) => !datasetIsPublicCorpus(name));
  return `<div class="screen-split work-wide">
    <div class="build-work">
      ${qualityError()}
      <p class="shelf-count">${plural(bundled.length, 'benchmark')}, ${rows} rows in all — the same on every machine
        running this version, which is why a number measured here can be set against a published one, and why none of
        them can be deleted. Open a name to read its rows.</p>
      ${bundledShelf(publicSets, {provenance:true, title:'From public research corpora',
        lead:`Collected and annotated by somebody else and released openly, then sampled onto this server. Nobody here
          chose the material, which is the whole value of it: it cannot have been picked to produce a convenient
          result. The licence is the source repository's and travels with the rows — including into anything you
          publish from a score measured on them.
          <a href="#guides/evaluation" data-global-tab="guides" data-screen="guides" data-mode="evaluation">How each import keeps the data
          honest</a>.`})}
      ${bundledShelf(built, {title:'Built here',
        lead:`Written by hand, or generated from fixed rules with a fixed seed so they rebuild byte for byte. They
          exist to exercise a shape — traps, borderline cases, tool calls, answers that should be empty — and no
          research group stands behind them. ${builtHereLicence()}`})}
    </div>
    <aside class="screen-guide" data-testid="bundled-guide">
      <h2>What this shelf is for</h2>
      <p class="guide-lead">Reference, read once: what is on the shelf, why both kinds are on it, and what a number
        measured here does and does not say.</p>
      <dl class="guide-stack">
        <div><dt>What a good score here means</dt><dd>That the tool works, and that a method beat another method on
          this material. It is not evidence about your prompt on your task: different inputs, different failures.</dd></div>
        <div><dt>Why both kinds are here</dt><dd>A public corpus says how a method does on material nobody here
          touched. A set built here can hold the cases a corpus has too few of — negation, duplicates, rows whose
          right answer is nothing — which is what separates a prompt that reads from one that guesses.</dd></div>
        <div><dt>Headroom before conclusions</dt><dd><code>entity-extraction</code> is six rows and the plain baseline
          already scores 1.000 on it: every method looks equal because there is nowhere to improve. It is there to
          click through. The ones with room to move are <code>entity-extraction-hard</code>,
          <code>multiconer-en</code> and <code>few-nerd</code>.</dd></div>
        <div><dt>Where the detail is</dt><dd>What each set contains, which grader scores it, how the public ones were
          imported without flattering the model, and the five rules without which a number means nothing —
          <a href="#guides/evaluation" data-global-tab="guides" data-screen="guides" data-mode="evaluation">Evaluation guide</a>.</dd></div>
      </dl>
      <p class="guide-note">A number about <em>your</em> work is computed from sets you
        <a href="#dataset-add" data-global-tab="dataset-add" data-mode="upload">upload</a>,
        <a href="#dataset-add/hugging-face" data-global-tab="dataset-add" data-mode="hugging-face">import</a> or
        <a href="#dataset-add/generate" data-global-tab="dataset-add" data-screen="dataset-add" data-mode="generate">build</a> — and the
        <a href="#dataset-library" data-global-tab="dataset-library">library</a> is where those live.</p>
    </aside>
  </div>`;
}

// A business set opened on its own says what work it stands for before it
// shows a row of it: the columns are the same either way, the jobs are not.
function renderCitations(name) {
  const cases = citedBy(name);
  if (!cases.length) return '';
  const rows = cases.map(item => `<li>
    <strong>${esc(item.task)}</strong> — ${esc(item.company)} ${matchPill(item.match)}
    <span class="meta">${esc(item.group)}</span>
  </li>`).join('');
  return `<div class="stage-title">What a score here is about</div>
    <ul class="catalog-citations">${rows}</ul>`;
}

// The shelf that left. A screen that simply stops mentioning what used to be at
// the bottom of it teaches nobody where it went.
const bundledPointer = () => `<section class="library-zone">
  <h3 class="zone-title">Shipped with the tool</h3>
  <p class="meta">The task benchmarks inside the installed package now have
    <a href="#dataset-library/built-in" data-global-tab="dataset-library" data-screen="dataset-library" data-mode="built-in">a screen of their own</a> — they are what this tool
    measures itself against, not material for your task.</p>
</section>`;

function renderDatasetLibrary() {
  // One set, when that is what you came for: the row is still a row of the same
  // table, so the columns mean what they meant on the full list — and under it
  // the set itself, which is the reason you opened it rather than the list.
  const only = showingOn('dataset-library');
  const sets = [...state.datasetSizes.entries()].filter(([name]) => !only || name === only);
  if (!sets.length) return `<div class="empty">No set called ${esc(only)} on this server.</div>`;
  const note = state.datasetNote ? `<div class="quality-result">${esc(state.datasetNote)}</div>` : '';
  const warning = state.pendingDelete === (only || state.pendingDelete) && state.pendingDelete
    ? `<div class="warning">${esc(state.pendingDelete)} and its rows are about to go. Any score already recorded against it stays in Results, and will refer to a set this server no longer has.</div>`
    : '';

  const names = sets.map(([name]) => name);
  // The catalogue is larger than the wheel: source-only entries have audited
  // provenance but may not be redistributed. Keep those entries discoverable
  // in the Sources and licences table instead of deriving the table solely
  // from files installed on this server.
  const business = only
    ? names.filter(name => name.startsWith('business:'))
    : [...catalogSets().keys()];
  const own = sets.filter(([name]) => !name.startsWith('business:'));
  // Narrowed to one set, the zones it does not live in would be six group
  // buttons and an empty table above the rows you came to read.
  if (only) {
    const zones = renderBusinessZone(business) + renderYoursZone(own) + renderBundledZone(own) + renderCitations(only);
    return `${qualityError()}${note}${warning}${measureAgainstBand(only)}${zones}${datasetPreview(only, sets[0][1])}`;
  }

  const browse = catalogBrowse();
  const groups = visibleCatalogGroups();
  const visibleOwn = visibleOwnSets(sets);
  // A search that names a set and no category still has an answer: the sources
  // table below the shelf. Reporting "nothing matches" over it was the same
  // mistake as hiding the set — an answer on the screen, called absent.
  const visibleBusiness = browse.scope === 'yours' ? [] : business.filter(visibleBusinessSet);
  const hasCatalogue = browse.scope !== 'yours' && (groups.length > 0 || visibleBusiness.length > 0);
  const hasYours = browse.scope !== 'catalogue' && visibleOwn.length > 0;
  const controls = renderCatalogBrowseControls();
  if (!hasCatalogue && !hasYours) return `${qualityError()}${note}${warning}${controls}
    <div class="catalog-no-results" role="status">
      <strong>Nothing matches these browse controls.</strong>
      <span>Try a broader phrase, include catalogue entries that are not installed, or reset the view.</span>
      <button type="button" class="ghost" data-catalog-reset>Clear search and filters</button>
    </div>`;

  const catalogueZones = hasCatalogue
    ? (groups.length ? renderCatalogZone() : '') + renderBusinessZone(visibleBusiness, {
        collapsed: true,
        open: Boolean(browseNeedle(browse.query)) || !groups.length,
      })
    : '';
  const yourZone = browse.scope !== 'catalogue' && (visibleOwn.length || !browseNeedle(browse.query))
    ? renderYoursZone(visibleOwn)
    : '';
  const pointer = browse.scope === 'all' && !browseNeedle(browse.query) ? bundledPointer() : '';
  const zones = controls + catalogueZones + yourZone + pointer;

  return `${qualityError()}${note}${warning}${zones}`;
}

async function deleteDataset(name) {
  const measured = state.run.dataset === name;
  await api(`/v1/datasets/${encodeURIComponent(name)}`, undefined, 'DELETE');
  state.pendingDelete = null;
  state.datasetRows.delete(name);
  delete datasetCache[name];
  await loadDatasets();
  state.datasetNote = `${name} deleted.`
    + (measured ? ` Measurement now points at ${state.run.dataset || 'no set at all'}.` : '');
  // Opened on the set that was just deleted, the screen would be a table with
  // nothing in it under a heading naming what is gone.
  if (showingOn('dataset-library') === name) selectTab('dataset-library');
  else renderDetailPanel('dataset-library');
}

function wireDatasetLibrary(tab, panel) {
  const preserveOpenGroup = () => {
    if (state.catalogGroup && !visibleCatalogGroups().some(group => group.id === state.catalogGroup)) {
      state.catalogGroup = null;
    }
  };
  panel.querySelector('[data-catalog-browse]')?.addEventListener('submit', event => event.preventDefault());
  panel.querySelector('[data-catalog-query]')?.addEventListener('input', event => {
    catalogBrowse().query = event.currentTarget.value;
    preserveOpenGroup();
    renderDetailPanel(tab);
    const search = document.querySelector('[data-catalog-query]');
    if (search) {
      search.focus();
      search.setSelectionRange(search.value.length, search.value.length);
    }
  });
  panel.querySelectorAll('[data-catalog-filter]').forEach(control => control.addEventListener('change', event => {
    catalogBrowse()[event.currentTarget.dataset.catalogFilter] = event.currentTarget.value;
    preserveOpenGroup();
    renderDetailPanel(tab);
    document.querySelector(`[data-catalog-filter="${CSS.escape(event.currentTarget.dataset.catalogFilter)}"]`)?.focus();
  }));
  panel.querySelector('[data-catalog-reset]')?.addEventListener('click', () => {
    state.catalogBrowse = {query:'', scope:'all', availability:'all', sort:'relevance'};
    state.catalogGroup = null;
    renderDetailPanel(tab);
    document.querySelector('[data-catalog-query]')?.focus();
  });
  panel.querySelectorAll('[data-catalog-group]').forEach(button => button.addEventListener('click', () => {
    const id = button.dataset.catalogGroup;
    state.catalogGroup = state.catalogGroup === id ? null : id;
    renderDetailPanel(tab);
    // What opened is below the mosaic, and on a short window that is below the
    // fold: bring its head up to where the tile was rather than leaving the
    // click looking like it did nothing.
    if (state.catalogGroup) $('catalog-open-panel')?.scrollIntoView({block:'nearest', behavior:'smooth'});
  }));
  panel.querySelector('[data-catalog-close]')?.addEventListener('click', () => {
    const id = state.catalogGroup;
    state.catalogGroup = null;
    renderDetailPanel(tab);
    // Closing from the foot of a long panel would leave the reader wherever
    // that was, so the tile it belonged to takes the focus back.
    panel.querySelector(`[data-catalog-group="${CSS.escape(id || '')}"]`)?.focus();
  });
  // Choosing what a score is computed against, from the screen that holds the
  // sets. It writes the same field the `Measure against` control on the run
  // screens writes, so the two can never disagree, and the note it leaves says
  // what changed — the band it was clicked in has by then become a different
  // sentence, and a control that rewrites itself has to say why.
  panel.querySelectorAll('[data-measure-against]').forEach(button => button.addEventListener('click', () => {
    const name = button.dataset.measureAgainst;
    state.run.dataset = name;
    // The invitation to paste your own inputs belongs to the set it was shown
    // over, and a different set is now the one being measured.
    state.ownRowsNote = '';
    state.datasetNote = `${name} is now what your runs measure against.`;
    if (typeof updateWorkspaceContext === 'function') updateWorkspaceContext();
    if (typeof refreshActions === 'function') refreshActions();
    renderDetailPanel(tab);
  }));
  panel.querySelectorAll('[data-action="derive-requirements"]').forEach(button => button.addEventListener('click', () => {
    const name = button.dataset.dataset;
    const contract = panel.querySelector(`[data-contract-for="${CSS.escape(name)}"]`)?.value || 'draft';
    button.disabled = true;
    button.textContent = 'Reading the rows';
    qualityAction(tab, async () => {
      const result = await api(`/v1/datasets/${encodeURIComponent(name)}/requirements`, {contract});
      delete datasetCache[name];
      await loadDatasets();
      // What the set now holds, not what this press changed: pressing the button
      // twice is reasonable, and the second press must not report a set that is
      // fully derived as one nothing could be derived from.
      const held = Object.entries(result.requirements || {});
      // And the part that decides what to do next — how many rows are still
      // answered for by word overlap alone. On some corpora that is most of
      // them, which is a fact about the rows rather than a failure here.
      state.datasetNote = held.length
        ? `${name} now carries ${held.map(([grader, rows]) => `${grader} on ${rows} row${rows === 1 ? '' : 's'}`).join(', ')}.`
          + (result.still_overlap_scored
            ? ` ${result.still_overlap_scored} row${result.still_overlap_scored === 1 ? '' : 's'} still have only word overlap answering for quality — those rows hold no requirement a rule could read off them, so gate this set on the checks above rather than on quality.`
            : ' Every row has a requirement a rule can decide, so this set can be gated in CI.')
        : `${name}: nothing could be derived. These rows carry a reference answer and nothing a rule could check against it — add "contains" or "forbidden" options by hand where you know the requirement.`;
    });
  }));
  panel.querySelectorAll('[data-delete-arm]').forEach(button => button.addEventListener('click', () => {
    state.pendingDelete = button.dataset.deleteArm;
    state.datasetNote = '';
    renderDetailPanel(tab);
  }));
  panel.querySelector('[data-delete-cancel]')?.addEventListener('click', () => {
    state.pendingDelete = null;
    renderDetailPanel(tab);
  });
  panel.querySelector('[data-delete-now]')?.addEventListener('click', event => {
    const button = event.currentTarget;
    button.disabled = true;
    button.textContent = 'Deleting';
    qualityAction(tab, () => deleteDataset(button.dataset.deleteNow));
  });
}

function renderPlatformTab(tab) {
  return ({'dataset-builder':renderDatasetBuilder,'judge':renderJudge,'reviews':renderReviews,'regressions':renderRegressions,'analysis':renderAnalysis,'model-matrix':renderModelMatrix,'context-lab':renderContextLab,'releases':renderReleases,'production':renderProduction,'dataset-library':renderDatasetLibrary,'dataset-bundled':renderDatasetBundled}[tab] || (() => '<div class="empty">Unknown screen.</div>'))();
}

async function refreshPlatformTab(tab) {
  const parentTab = parentForLegacyTab(tab);
  try {
    if (tab === 'dataset-builder' || tab === 'dataset-add') {
      q.projects = await api('/v1/dataset-projects');
      // Two modes seed from rows this screen does not own: the set being
      // measured, and the set the last run scored. Fetch both, once.
      if (state.report) await loadDatasetRows(state.report.dataset);
      if (state.run.dataset) await loadDatasetRows(state.run.dataset);
    }
    if (tab === 'reviews') q.reviews = await api('/v1/reviews');
    if (tab === 'releases' || tab === 'ship') {
      q.releases = await api('/v1/releases');
      // Only where Approve is the next move. The verdict has to be readable
      // before the button is pressed, or the committed bar is something you
      // discover by being refused.
      q.gates = Object.fromEntries(await Promise.all(
        q.releases.filter(item => item.status === 'tested').map(async item =>
          [item.id, await api(`/v1/releases/${item.id}/gate`).catch(e => ({status:'unenforceable', reason:e.message}))])
      ));
    }
    if ((tab === 'regressions' || tab === 'results') && !state.experiments.length) state.experiments = await api('/v1/experiments');
    if (tab === 'dataset-library') {
      await loadDatasets();
      await loadBusinessCatalog();
    }
    if (tab === 'dataset-bundled') await loadDatasets();
    q.error = '';
  } catch (error) { q.error = error.message; }
  q.loaded.add(tab);
  q.loaded.add(parentTab);
  if (state.tab === parentTab) renderDetailPanel(parentTab);
}

function values(text) { return text.split(/[\s,;]+/).filter(Boolean).map(Number).filter(Number.isFinite); }

/* Every field writes to state and re-renders, because the mode decides which
 * fields exist and the settings decide what the button costs. The description is
 * the exception: it is the same text the prompt uses, and re-rendering under a
 * cursor is worse than leaving one field to be read at click time. */
function wireBuilderForm(tab, panel) {
  const fields = [
    ['#builder-name', 'name', 'value'], ['#builder-mode', 'mode', 'value'],
    ['#builder-count', 'count', 'number'], ['#builder-candidates', 'candidates', 'number'],
    ['#builder-llm', 'llm', 'checked'], ['#builder-answers', 'answers', 'checked'],
    ['#builder-personas', 'personas', 'checked'],
    ['#builder-trace-session', 'session', 'value'], ['#builder-trace-tags', 'tags', 'value']
  ];
  for (const [selector, key, kind] of fields) {
    const node = panel.querySelector(selector);
    if (!node) continue;
    const read = () => kind === 'checked' ? node.checked : kind === 'number' ? Number(node.value) : node.value;
    // Text fields keep their value in state and re-render only on blur; the
    // selects and checkboxes change what the form is, so they redraw at once.
    if (kind === 'value' && node.tagName === 'INPUT') node.addEventListener('input', () => { q.build[key] = read(); });
    else node.addEventListener('change', () => { q.build[key] = read(); renderDetailPanel(tab); });
  }
  const description = panel.querySelector('#builder-description');
  description?.addEventListener('input', () => { const field = $('description'); if (field) field.value = description.value; });
  panel.querySelector('.builder-create')?.addEventListener('click', () => qualityAction(tab, async () => {
    const b = q.build;
    const body = {
      name:b.name, description:description.value, mode:b.mode, count:b.count,
      candidates:b.llm ? b.candidates : 1, propose_answers:b.llm && b.answers, personas:b.personas,
      trace_session_id:b.session || null,
      trace_tags:b.tags.split(',').map(item => item.trim()).filter(Boolean)
    };
    const similarity = similarityProfile();
    if (similarity) body.similarity_model = similarity;
    const seeds = builderSeeds();
    if (seeds.rows.length) body.examples = seeds.rows;
    if (b.llm && !seeds.rows.length) {
      const engine = generatorProfile();
      if (!engine) throw new Error('Set a model for the prompt engine, or generate without it — the model under evaluation must not write its own examples.');
      body.generator_model = engine;
    }
    const project = await api('/v1/dataset-projects', body);
    const flagged = project.examples.filter(item => item.checks.length).length;
    setScreenResult(tab, {kind:'dataset', message:`Generated ${plural(project.examples.length, 'unreviewed row')}${flagged ? `, ${flagged} of them flagged by a check` : ', none flagged by a check'}.`});
  }));
}

/* The judge for this one run: the model named in Settings, unless the field on
 * the screen overrides it for this comparison alone. The judge must not be the
 * model on trial, and `judgeProfile` no longer offers it as a fallback — so a
 * missing judge is an error here rather than a silent handover. */
function judgeRunProfile(panel) {
  const id = panel.querySelector('#judge-model')?.value.trim();
  const base = judgeProfile();
  if (!base && !id) throw new Error('Set a judge model in Settings — the model being measured must not mark its own answers.');
  return id ? {...(base || {provider:state.settings.engine.provider, local:state.settings.engine.provider === 'ollama'}), model_id:id} : base;
}

function wirePlatformTab(tab, panel) {
  panel.querySelectorAll('[data-prereq-target]').forEach(button => button.addEventListener('click', () => selectTab(button.dataset.prereqTarget, {focus:true})));
  wireDatasetLibrary(tab, panel);
  wireBuilderForm(tab, panel);
  panel.querySelectorAll('[data-filter]').forEach(button => button.addEventListener('click', () => {
    q.build.filter = button.dataset.filter;
    renderDetailPanel(tab);
  }));
  panel.querySelectorAll('.quality-project').forEach(project => {
    const boxes = [...project.querySelectorAll('[data-example-id]')];
    const ids = () => boxes.filter(item => item.checked).map(item => item.dataset.exampleId);
    // The count is written straight into the node: re-rendering the screen to
    // change one word would close the project and drop the ticks with it.
    const counter = project.querySelector('.selected-count');
    const recount = () => { const n = ids().length; counter.textContent = n ? `${plural(n, 'row')} selected` : 'Nothing selected'; };
    boxes.forEach(box => box.addEventListener('change', recount));
    const review = action => qualityAction(tab, async () => {
      if (!ids().length) throw new Error('Tick the rows you have actually read first.');
      return api(`/v1/dataset-projects/${project.dataset.projectId}/review`, {example_ids:ids(), action});
    });
    project.querySelector('.dataset-review')?.addEventListener('click', () => review('review'));
    project.querySelector('.dataset-approve')?.addEventListener('click', () => review('approve'));
    project.querySelector('.dataset-publish')?.addEventListener('click', () => qualityAction(tab, async () => { const result=await api(`/v1/dataset-projects/${project.dataset.projectId}/publish`, {}); await loadDatasets(result.name); setScreenResult(tab, {kind:'dataset', message:`Published ${result.name} with ${result.examples} approved examples, and selected it for measurement.`}); }));
  });
  // The run first, because it answers the question people bring to this screen.
  panel.querySelector('[data-action="run-rubric"]')?.addEventListener('click', event => {
    const button = event.currentTarget;
    const report = state.report;
    if (!report) return;
    button.disabled = true;
    button.textContent = 'Judging';
    qualityAction(tab, async () => {
      const result = await api('/v1/evaluate/rubric', {
        dataset: report.dataset,
        runs: report.runs,
        rubric: panel.querySelector('#rubric-run-lines').value.split('\n').map(line => line.trim()).filter(Boolean),
        judge_model: judgeRunProfile(panel),
        subject_models: [report.model_id]
      });
      setScreenResult(tab, {kind:'rubric', ...result});
    });
  });
  panel.querySelector('.judge-run')?.addEventListener('click', () => qualityAction(tab, async () => { const result = await api('/v1/evaluate/pairwise', {input:panel.querySelector('#judge-input').value, answer_a:panel.querySelector('#judge-a').value, answer_b:panel.querySelector('#judge-b').value, rubric:panel.querySelector('#judge-rubric').value.split('\n').filter(Boolean), judge_model:judgeRunProfile(panel), subject_models:[modelProfile().model_id]}); setScreenResult(tab, {kind:'judge', ...result}); }));
  panel.querySelectorAll('.review-card').forEach(card => ['approve','reject'].forEach(action => card.querySelector(`.review-${action}`)?.addEventListener('click', () => qualityAction(tab, async () => api(`/v1/reviews/${card.dataset.reviewId}`, {action})))));
  panel.querySelector('.reg-run')?.addEventListener('click', () => qualityAction(tab, async () => { const result=await api('/v1/regressions/analyze', {before_id:panel.querySelector('#reg-before').value, after_id:panel.querySelector('#reg-after').value, quality_tolerance:Number(panel.querySelector('#reg-quality').value), latency_tolerance:Number(panel.querySelector('#reg-latency').value)}); setScreenResult(tab, {kind:'regression', ...result}); }));
  panel.querySelector('.reg-accept')?.addEventListener('click', () => qualityAction(tab, async () => api('/v1/regressions/accept-baseline', {experiment_id:screenResult(tab).comparison.after.id})));
  panel.querySelector('.reg-rerun')?.addEventListener('click', () => qualityAction(tab, async () => { const current=screenResult(tab); const experimentId=current.comparison.after.id; const job=await api('/v1/regressions/rerun', {experiment_id:experimentId}); const rerun=await pollJob(job.id, ()=>{}); setScreenResult(tab, {...current, rerun}); }));
  panel.querySelector('.stats-run')?.addEventListener('click', () => qualityAction(tab, async () => { const result=await api('/v1/analysis/statistics', {before:values(panel.querySelector('#stats-before').value), after:values(panel.querySelector('#stats-after').value)}); setScreenResult(tab, {kind:'analysis', ...result}); }));
  panel.querySelector('.slices-run')?.addEventListener('click', () => qualityAction(tab, async () => { const examples=await api(`/v1/datasets/${encodeURIComponent(state.report.dataset)}`); const rows=await api('/v1/analysis/slices', {examples, runs:state.report.runs}); setScreenResult(tab, {kind:'slices', rows}); }));
  panel.querySelector('.matrix-run')?.addEventListener('click', () => qualityAction(tab, async () => { const ids=panel.querySelector('#matrix-models').value.split('\n').map(x=>x.trim()).filter(Boolean); const base=modelProfile(); const job=await api('/v1/model-matrix', {...baseBenchmarkPayload(), task:await taskProfile(), models:ids.map(model_id=>({...base, model_id}))}); const result=await pollJob(job.id, ()=>{}); setScreenResult(tab, {kind:'matrix', ...result}); }));
  panel.querySelector('.context-run')?.addEventListener('click', () => qualityAction(tab, async () => { const job=await api('/v1/context-lab', {...baseBenchmarkPayload(), task:await taskProfile(), contexts:[{name:panel.querySelector('#ctx-a-name').value, context:panel.querySelector('#ctx-a').value},{name:panel.querySelector('#ctx-b-name').value, context:panel.querySelector('#ctx-b').value}]}); const result=await pollJob(job.id, ()=>{}); setScreenResult(tab, {kind:'context', ...result}); }));
  // The run that justifies the prompt travels with it. A release whose
  // experiment_id is null is one nobody measured, and the register says so
  // rather than leaving the column blank and letting it read as "not shown".
  panel.querySelector('.release-create')?.addEventListener('click', () => qualityAction(tab, async () => api('/v1/releases', {name:panel.querySelector('#release-name').value, technique_id:state.program.technique_id, prompt:state.program, experiment_id:state.provenance?.experiment_id || null})));

  panel.querySelectorAll('[data-cite-release]').forEach(button => button.addEventListener('click', () => qualityAction(tab, async () => api(`/v1/releases/${button.closest('tr').dataset.releaseId}/cite`, {experiment_id:button.dataset.citeRelease}))));
  // Opening the text is not a lifecycle move either: the row unfolds in place
  // and nothing about the release changes.
  panel.querySelectorAll('[data-release-text]').forEach(button => button.addEventListener('click', () => {
    const row = panel.querySelector(`[data-release-text-for="${button.dataset.releaseText}"]`);
    if (!row) return;
    row.hidden = !row.hidden;
    button.setAttribute('aria-expanded', String(!row.hidden));
  }));
  // Arming, disarming and firing the delete. Only the last one reaches the
  // server; the first two redraw the table and nothing else.
  panel.querySelectorAll('[data-release-delete-arm]').forEach(button => button.addEventListener('click', () => {
    q.pendingReleaseDelete = button.dataset.releaseDeleteArm;
    renderDetailPanel(parentForLegacyTab(tab));
  }));
  panel.querySelectorAll('[data-release-delete-cancel]').forEach(button => button.addEventListener('click', () => {
    q.pendingReleaseDelete = null;
    renderDetailPanel(parentForLegacyTab(tab));
  }));
  panel.querySelectorAll('[data-release-delete-now]').forEach(button => button.addEventListener('click', () => {
    const id = button.dataset.releaseDeleteNow;
    return qualityAction(tab, async () => {
      await api(`/v1/releases/${id}`, undefined, 'DELETE');
      q.pendingReleaseDelete = null;
    });
  }));
  panel.querySelectorAll('[data-release-action]').forEach(button => button.addEventListener('click', () => {
    const id = button.closest('tr').dataset.releaseId;
    // Export is not a lifecycle move: it takes the release out of here rather
    // than along the line, so it neither posts an action nor redraws the table.
    if (button.dataset.releaseAction === 'export') return qualityAction(tab, async () => {
      const manifest = await api(`/v1/releases/${id}/manifest`);
      downloadText(manifest.filename, manifest.content, 'application/json');
      downloadText(manifest.checks_filename, manifest.checks, 'text/yaml');
    });
    return qualityAction(tab, async () => api(`/v1/releases/${id}/action`, {action:button.dataset.releaseAction}));
  }));
  panel.querySelector('.drift-run')?.addEventListener('click', () => qualityAction(tab, async () => { const result=await api('/v1/drift', {baseline_inputs:panel.querySelector('#drift-before').value.split('\n').filter(Boolean), current_inputs:panel.querySelector('#drift-after').value.split('\n').filter(Boolean)}); setScreenResult(tab, {kind:'production', tool:'drift', value:result}); }));
  panel.querySelector('.trajectory-run')?.addEventListener('click', () => qualityAction(tab, async () => { const result=await api('/v1/trajectories/evaluate', {steps:JSON.parse(panel.querySelector('#trajectory-json').value), required_tools:panel.querySelector('#trajectory-tools').value.split(',').map(x=>x.trim()).filter(Boolean)}); setScreenResult(tab, {kind:'production', tool:'trajectory', value:result}); }));
  panel.querySelector('.security-run')?.addEventListener('click', () => qualityAction(tab, async () => { const source={id:'security-source', input:panel.querySelector('#security-input').value}; if (state.chosen) { const job=await api('/v1/security-evaluate', {...baseBenchmarkPayload(), task:await taskProfile(), source}); setScreenResult(tab, {kind:'production', tool:'security', value:await pollJob(job.id, ()=>{})}); } else { setScreenResult(tab, {kind:'production', tool:'security', value:await api('/v1/datasets/security-suite', source)}); } }));
}

async function qualityAction(tab, operation) {
  q.error=''; q.loading=true;
  try { await operation(); await refreshPlatformTab(tab); }
  catch (error) { q.error=error.message; if (state.tab === parentForLegacyTab(tab)) renderDetailPanel(parentForLegacyTab(tab)); }
  finally { q.loading=false; }
}
