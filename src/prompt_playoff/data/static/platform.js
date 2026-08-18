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
    adviceGo('dataset-upload', 'Upload rows of your own')));
  if (!similarityProfile()) notes.push(adviceNote('idle', 'Nothing is checking for reworded rows',
    'Without a similarity model, only rows that match character for character count as duplicates. "Cancel my subscription" and "I would like to cancel my subscription" both go into the set, and the average is then computed over one case counted twice.',
    adviceGo('settings', 'Set one')));
  if (b.llm && Number(b.candidates) === 1) notes.push(adviceNote('warn', 'One sample is one voice repeated',
    'A single sample cannot disagree with itself: no row gets an agreement score, and near-duplicates survive the deduplication. Three or four samples cost more calls and are the reason to turn the engine on at all.'));
  const modes = MODE_EVIDENCE.map(([name, lead]) =>
    `<div><dt>${esc(name)}</dt><dd>${esc(lead)}</dd></div>`).join('');
  return `<h2>What to do about this set</h2>
    <p class="guide-lead">Generated rows are a guess at what your inputs look like. Everything below is about closing the distance between that guess and the traffic the prompt will actually meet.</p>
    <ul class="advice-list">${notes.join('')}</ul>
    <h3>Which mode is worth trusting</h3>
    <dl class="guide-stack">${modes}</dl>
    <h3>Reading what came out</h3>
    <p class="guide-note"><b>Variety and coverage are different questions.</b> Coverage says which axes the rows landed on; variety says whether those rows are actually different sentences. A set can fill every cell with ten wordings of one case, and only the variety number sees it.</p>
    <p class="guide-note"><b>The empty cells are the finding.</b> Coverage counts every axis the mode can produce, not only the ones that got rows. Six full cells out of ten is the news; "sixty examples" is not.</p>
    <p class="guide-note"><b>Nothing is truth until you approve it.</b> Reviewed and flagged rows stay behind when the set is published — approval is the only step this screen will never take for you.</p>
    <p class="guide-note"><b>With the engine off, the set is reproducible.</b> The mutations are rules, so the same name, count and description give the same rows, and two sets can be diffed. With it on, every run is a different set.</p>
    <p class="guide-note">A generated set is for finding where a prompt breaks. Once it breaks somewhere, the rows worth keeping are the ones you <a href="#dataset-upload" data-global-tab="dataset-upload">bring yourself</a>.</p>`;
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
  return `<div class="screen-split builder-split">
    <div class="build-work">
      ${qualityError()}${outcome}${waiting}
      <section class="screen-body">${builderForm()}</section>
      ${latest ? builderDeck(latest) : ''}
      <div class="stage-title">Projects</div>${projects || '<div class="empty">No generated datasets yet.</div>'}
    </div>
    <aside class="screen-guide" data-testid="builder-guide">${builderAdvice(latest)}</aside>
  </div>`;
}

function renderJudge() {
  const current = screenResult('judge');
  // The warning is printed with the verdict, not instead of it: the verdict is
  // still evidence, just weaker evidence than it looks.
  const leak = current?.self_preference_warning ? `<div class="warning">${esc(current.self_preference_warning)}</div>` : '';
  const result = current?.kind === 'judge' ? `<div class="quality-result">${statusCard('Winner', current.winner)}${statusCard('Human gate', 'Pending review', 'warning')}${leak}<p>${esc(current.rationale)}</p></div>` : '';
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
  return `${qualityError()}${gate}${kin}
    <div class="quality-form">
      <label class="wide">Input<textarea id="judge-input"></textarea></label>
      <label>Answer A<textarea id="judge-a"></textarea></label>
      <label>Answer B<textarea id="judge-b"></textarea></label>
      <label class="wide">Judge model<input id="judge-model" placeholder="${esc(judge?.model_id || 'Set one in Settings')}"><small class="field-hint">${judge ? `Blank uses <code>${esc(judge.model_id)}</code> from Settings; type an id to override it for this comparison alone.` : 'Set a judge in Settings, or type an id here for this comparison alone.'} A judge from the same family as <code>${esc(subject)}</code> — the model you are measuring — tends to prefer its own lineage, and the verdict will say so.</small></label>
      <label class="wide">Rubric, one criterion per line<textarea id="judge-rubric">Correctness\nCompleteness\nFollows the requested format</textarea></label>
    </div><div class="form-actions"><button class="primary judge-run" data-action="run-blind-judge">Run blind judge</button></div>${result}`;
}

function renderReviews() {
  // The map's amber circle counts what is unanswered, so it opens this screen
  // on the unanswered ones rather than on the whole history of decisions.
  const only = showingOn('reviews');
  const queue = only ? q.reviews.filter(item => item.status === only) : q.reviews;
  const cards = queue.map(item => `<article class="review-card" data-review-id="${esc(item.id)}"><div><span class="status-chip ${esc(item.status)}">${esc(item.status)}</span> <span class="meta">${esc(item.kind)} · ${esc(item.created_at)}</span></div><h3>${esc(item.title)}</h3><pre>${esc(JSON.stringify(item.payload, null, 2).slice(0, 1800))}</pre>${item.status === 'pending' ? '<div class="quality-actions"><button class="review-approve" data-action="approve-review">Approve</button><button class="ghost review-reject" data-action="reject-review">Reject</button></div>' : ''}</article>`).join('');
  const nothing = only ? `Nothing ${esc(only)} in the review queue.` : 'Review queue is empty.';
  return `${qualityError()}${cards || `<div class="empty">${nothing}</div>`}`;
}

function experimentOptions() {
  return state.experiments.map(item => `<option value="${esc(item.id)}">v${item.version} · ${esc(item.model_id)} · ${esc(item.dataset)}</option>`).join('');
}

function renderRegressions() {
  const current = screenResult('regressions');
  const result = current?.kind === 'regression' ? `<div class="quality-result">${statusCard('Gate', current.status, current.status === 'passed' ? 'passed' : 'failed')}<pre>${esc(JSON.stringify(current.active, null, 2))}</pre>${current.status === 'failed' ? '<div class="quality-actions"><button class="reg-rerun">Rerun candidate</button><button class="ghost reg-accept">Accept new baseline</button></div>' : ''}</div>` : '';
  const gate = state.experiments.length < 2 ? prerequisite('Record at least two benchmark experiments before analyzing a regression.', 'prompt', 'Open Prompt Studio') : '';
  return `${qualityError()}${gate}<div class="quality-form"><label>Baseline<select id="reg-before">${experimentOptions()}</select></label><label>Candidate<select id="reg-after">${experimentOptions()}</select></label><label>Quality tolerance<input id="reg-quality" type="number" step="0.01" min="0" value="0.01"></label><label>Latency tolerance, seconds<input id="reg-latency" type="number" step="0.1" min="0" value="0.1"></label></div><div class="form-actions"><button class="reg-run" data-action="analyze-regression" ${state.experiments.length < 2 ? 'disabled' : ''}>Analyze regression</button></div>${result}`;
}

function renderAnalysis() {
  const current = screenResult('analysis');
  const result = current?.kind === 'analysis' ? `<div class="quality-result">${statusCard('Delta', current.delta)}${statusCard('Decision', current.direction, current.significant ? 'passed' : 'warning')}<pre>${esc(JSON.stringify(current, null, 2))}</pre></div>` : '';
  const slices = current?.kind === 'slices' ? `<div class="table-scroll"><table><thead><tr><th>Slice</th><th>Quality</th><th>Runs</th><th>Failures</th></tr></thead><tbody>${current.rows.map(row => `<tr><td>${esc(row.slice)}</td><td>${Number(row.quality).toFixed(3)}</td><td>${row.runs}</td><td>${row.failures}</td></tr>`).join('')}</tbody></table></div>` : '';
  const sliceGate = state.report ? '' : prerequisite('Slice analysis needs a completed benchmark; confidence comparison can run now.', 'prompt', 'Run a benchmark');
  return `${qualityError()}${sliceGate}<div class="quality-form"><label>Baseline scores<textarea id="stats-before" placeholder="0.80, 0.75, 0.90"></textarea></label><label>Candidate scores<textarea id="stats-after" placeholder="0.84, 0.82, 0.91"></textarea></label></div><div class="form-actions"><button class="stats-run">Compare confidence</button><button class="ghost slices-run" ${state.report ? '' : 'disabled'}>Analyze last benchmark by tags</button></div>${result}${slices}`;
}

function baseBenchmarkPayload() {
  if (!state.chosen || !$('dataset')?.value) throw new Error('Create a prompt and choose a benchmark dataset first.');
  return {technique_id:state.chosen, dataset:$('dataset').value, repeats:Number($('repeats').value || 1)};
}

function renderModelMatrix() {
  const current = screenResult('model-matrix');
  const result = current?.kind === 'matrix' ? `<div class="quality-result">${statusCard('Winner model', current.winner_model)}<div class="table-scroll"><table><thead><tr><th>Model</th><th>Quality</th><th>Latency</th><th>Cost</th></tr></thead><tbody>${current.reports.map(item => `<tr><td>${esc(item.model_id)}</td><td>${item.scorecard.quality.toFixed(3)}</td><td>${item.scorecard.mean_latency_seconds.toFixed(2)}</td><td>${item.scorecard.mean_cost_usd == null ? 'unknown' : item.scorecard.mean_cost_usd.toFixed(6)}</td></tr>`).join('')}</tbody></table></div></div>` : '';
  const gate = state.chosen ? '' : prerequisite('Create and choose a prompt before comparing models.', 'prompt', 'Create a prompt');
  return `${qualityError()}${gate}<label>Model IDs, one per line<textarea id="matrix-models" placeholder="llama3.2:3b\nqwen3:8b"></textarea></label><div class="form-actions"><button class="matrix-run" data-action="run-model-matrix" ${state.chosen ? '' : 'disabled'}>Run matrix</button></div>${result}`;
}

function renderContextLab() {
  const current = screenResult('context-lab');
  const result = current?.kind === 'context' ? `<div class="quality-result">${statusCard('Best context', current.winner_context)}<pre>${esc(JSON.stringify(current.reports.map(item => ({context:item.context, quality:item.report.scorecard.quality})), null, 2))}</pre></div>` : '';
  const gate = state.chosen ? '' : prerequisite('Create a prompt before comparing context variants.', 'prompt', 'Create a prompt');
  return `${qualityError()}${gate}<div class="quality-form"><label>Variant A name<input id="ctx-a-name" value="full"></label><label>Variant B name<input id="ctx-b-name" value="compressed"></label><label>Context A<textarea id="ctx-a"></textarea></label><label>Context B<textarea id="ctx-b"></textarea></label></div><div class="form-actions"><button class="context-run" data-action="compare-contexts" ${state.chosen ? '' : 'disabled'}>Compare contexts</button></div>${result}`;
}

function renderReleases() {
  // Arrived on one stage of the funnel: the table keeps its columns and its
  // buttons, and holds only the releases sitting in that stage.
  const only = showingOn('releases');
  const releases = only ? q.releases.filter(item => item.status === only) : q.releases;
  const rows = releases.map(item => `<tr data-release-id="${esc(item.id)}"><td>${esc(item.name)} v${item.version}</td><td><span class="status-chip ${esc(item.status)}">${esc(item.status)}</span></td><td>${esc(item.technique_id)}</td><td><code>${esc(item.prompt_hash.slice(0, 10))}</code></td><td><div class="quality-actions">${item.status === 'draft' ? '<button data-release-action="test">Test</button>' : ''}${item.status === 'tested' ? '<button data-release-action="approve">Approve</button>' : ''}${item.status === 'approved' ? '<button data-release-action="release">Release</button>' : ''}${item.status === 'production' ? '<button data-release-action="rollback">Rollback</button><button class="ghost" data-release-action="deprecate">Deprecate</button>' : ''}</div></td></tr>`).join('');
  const gate = state.program ? '' : prerequisite('Author a prompt before registering a release.', 'prompt', 'Author a prompt');
  // A table of headings over nothing is a table that lost its rows. Say which
  // of the two it is.
  const table = rows
    ? `<div class="table-scroll"><table><thead><tr><th>Release</th><th>Status</th><th>Technique</th><th>Hash</th><th>Action</th></tr></thead><tbody>${rows}</tbody></table></div>`
    : `<div class="empty">${only ? `No release is sitting at ${esc(only)}.` : 'No releases registered yet.'}</div>`;
  return `${qualityError()}${gate}<div class="quality-form"><label>Release name<input id="release-name" value="production-prompt"></label></div><div class="form-actions"><button class="release-create" data-action="create-release" ${state.program ? '' : 'disabled'}>Register current prompt</button></div>${table}`;
}

/* Three unrelated checks used to sit on one screen as six blank fields in a
 * row. They are three tools, so they are three cards: each says what it answers
 * before it asks for anything, and only one is open at a time. */
const subTool = (id, mark, title, question, body, open=false) => `<details class="sub-tool"${open ? ' open' : ''} data-sub-tool="${id}">
  <summary><span class="sub-mark">${icon(mark)}</span><span class="sub-title"><strong>${esc(title)}</strong><small>${esc(question)}</small></span></summary>
  <div class="sub-body">${body}</div>
</details>`;

function renderProduction() {
  const current = screenResult('production');
  const result = current?.kind === 'production' ? `<div class="quality-result"><pre>${esc(JSON.stringify(current.value, null, 2))}</pre></div>` : '';
  return `${qualityError()}
    ${subTool('drift', 'wave', 'Input drift', 'Are real inputs still like the ones you tested on?', `
      <div class="quality-form">
        <label>Baseline inputs, one per line<textarea id="drift-before"></textarea></label>
        <label>Current inputs, one per line<textarea id="drift-after"></textarea></label>
      </div>
      <div class="sub-actions"><button class="drift-run" type="button">Detect drift</button></div>`, true)}
    ${subTool('trajectory', 'link', 'Agent runs', 'Did the agent call the tools it was supposed to?', `
      <div class="quality-form">
        <label class="wide">Trajectory JSON<textarea id="trajectory-json" placeholder='[{"tool":"search","success":true},{"tool":"browser","success":false,"recovered":true}]'></textarea></label>
        <label>Required tools, comma separated<input id="trajectory-tools" placeholder="search, browser"></label>
      </div>
      <div class="sub-actions"><button class="ghost trajectory-run" type="button">Evaluate trajectory</button></div>`)}
    ${subTool('security', 'shield', 'Injection attempts', 'Does the prompt hold when the input fights it?', `
      <div class="quality-form">
        <label class="wide">Input for the security suite<textarea id="security-input"></textarea></label>
      </div>
      <div class="sub-actions"><button class="ghost security-run" type="button">${state.chosen ? 'Run security evaluation' : 'Generate security cases'}</button></div>`)}
    ${result}`;
}

function datasetSource(name) {
  if (name.startsWith('builder:')) return 'Reviewed builder dataset';
  if (name.startsWith('hf:')) return 'Hugging Face';
  if (name.startsWith('uploaded:')) return 'Session upload';
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
 *   the catalogue   fifty jobs businesses pay a model to do, each mapped to
 *                   the public set closest to its shape. Not rows: the reason
 *                   rows were chosen, including the ten cases with no match.
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
  return (state.catalog?.sets || []).filter(spec => spec.group === group.name);
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
  const title = '<div class="stage-title">Ready-made data, by kind of work</div>';
  if (state.catalogError) return `${title}
    <div class="error">The business catalogue could not be read: ${esc(state.catalogError)}</div>`;
  if (!state.catalog) return `${title}<div class="empty">Reading the catalogue…</div>`;

  const {counts, groups} = state.catalog;
  const open = groups.find(group => group.id === state.catalogGroup);
  const cards = groups.map(group => {
    const stock = groupStock(group);
    const shown = group.id === state.catalogGroup;
    const held = stock.sets ? plural(stock.sets, 'dataset') : 'No datasets yet';
    return `<button type="button" class="cat-tile${shown ? ' open' : ''}"
      data-catalog-group="${esc(group.id)}" aria-expanded="${shown}" aria-controls="catalog-open-panel">
      <img class="cat-art" src="/assets/${esc(group.art)}.webp" alt="" width="72" height="72" loading="lazy" decoding="async">
      <span class="cat-name">${esc(group.name)}</span>
      <span class="cat-headline">${esc(group.headline)}</span>
      <span class="cat-summary">${esc(group.summary)}</span>
      <span class="cat-foot">
        <span class="cat-held">${esc(held)}</span>
        <span class="cat-open">${shown ? 'Hide' : 'Explore'}</span>
      </span>
    </button>`;
  }).join('');

  return `${title}
    <p class="meta catalog-lead">The data that ships with this tool, sorted by the kind of work it stands for.
      Open a category to see its datasets; open a dataset to read its rows before you measure anything against it.
      ${counts.available} of the ${plural(counts.sets, 'dataset')} named here are on this server.</p>
    <div class="catalog-groups">${cards}</div>
    ${open ? renderOpenGroup(open) : ''}`;
}

/* What a tile opens into, under the whole mosaic rather than inside one tile:
 * a tile is a fifth of a row wide, and what is inside a category is a shelf of
 * datasets. Opening it in place would shove the other five tiles down the
 * screen and leave the reader reading a column.
 *
 * The panel says which tile it belongs to and closes from its own corner. The
 * datasets come first because they are the thing you can pick up — each one a
 * click from its own rows — and the companies doing this work come after, as
 * background rather than as the point. */
function renderOpenGroup(group) {
  const stock = groupStock(group);
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
    ${renderGroupSets(group)}
    ${renderCatalogCases(group)}
  </section>`;
}

/* The datasets in a category, each a click from its own rows. A dataset the
 * catalogue names but this server does not have says so plainly instead of
 * linking somewhere empty. */
function renderGroupSets(group) {
  const label = '<div class="cat-panel-label">Datasets in this category</div>';
  const cards = groupSetSpecs(group).map(spec => {
    const rows = state.datasetSizes.get(spec.name) ?? spec.examples;
    const body = `<span class="set-card-title">${esc(spec.title || spec.name)}</span>
      <span class="set-card-facts">${spec.available
        ? `${esc(plural(rows ?? 0, 'example'))} · ${esc(spec.shape || 'text in, text out')}`
        : 'not on this server'}</span>
      <code class="set-card-name">${esc(spec.name)}</code>`;
    return spec.available
      ? `<a class="set-card" href="#dataset-library/${encodeURIComponent(spec.name)}">${body}</a>`
      : `<span class="set-card off">${body}</span>`;
  }).join('');
  if (!cards) return `${label}<div class="empty">Nothing here yet — for this kind of work your own examples are
    the only way to measure anything. Upload them on the “Upload your own” screen.</div>`;
  return `${label}<div class="set-cards">${cards}</div>`;
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
function renderCatalogCases(group) {
  const known = catalogSets();
  const references = new Map((state.catalog.references || []).map(item => [item.id, item]));
  // The ones that can be measured lead. A group read top to bottom then runs
  // from work you can put a number on today to work you cannot, which is the
  // order anybody reading it is looking for anyway.
  const rank = {direct:0, partial:1, none:2};
  const ordered = [...group.cases].sort((a, b) => (rank[a.match] - rank[b.match]) || (a.number - b.number));
  const cards = ordered.map(item => {
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
    return `<article class="case-card" data-match="${esc(item.match)}">
      <div class="case-top">
        <span class="case-no">${String(item.number).padStart(2, '0')}</span>
        ${matchPill(item.match)}
      </div>
      <h4 class="case-task">${esc(item.task)}</h4>
      <div class="case-who">${esc(item.company)}${item.source ? `<span class="case-source">${esc(item.source)}</span>` : ''}</div>
      ${claim}
      <p class="case-story">${esc(item.story)}</p>
      <div class="case-evidence">${evidence}</div>
    </article>`;
  }).join('');
  return `<div class="catalog-cases">
    <div class="cat-panel-label">Who does this work with a model<span class="cat-panel-note">and what they say it did for them</span></div>
    <div class="case-grid">${cards}</div>
    <p class="field-hint">Every figure on these cards is the one the company or its vendor published. None of them
      was measured here, and this tool has checked none of them — the numbers it stands behind are the ones on the
      Measurement screen. The company is a reported user of an LLM for that work, not the source of the data: every
      set here is public, and none of it came from the company beside it.</p>
  </div>`;
}

/* Zone two. The columns a business set has to carry that a bundled one does
 * not: which group of work it stands for, where the rows came from, and under
 * what licence — because these arrived from someone else's repository. */
function renderBusinessZone(names) {
  const known = catalogSets();
  const listed = names.filter(name => known.has(name));
  if (!listed.length) return '';
  const rows = listed.map(name => {
    const spec = known.get(name);
    return `<tr>
      <td><a href="#dataset-library/${encodeURIComponent(name)}">${esc(spec.title)}</a><br><code class="meta">${esc(name)}</code></td>
      <td>${esc(spec.group || '—')}</td>
      <td>${state.datasetSizes.get(name) ?? '—'}</td>
      <td>${esc(spec.shape)}</td>
      <td><a href="${esc(spec.url)}" target="_blank" rel="noreferrer noopener">${esc(spec.source)} ↗</a><br><span class="meta">${esc(spec.license)}</span></td>
    </tr>`;
  }).join('');
  return `<div class="stage-title">Where the ready-made data comes from</div>
    <p class="meta">The same datasets as the tiles above, one row each, with the repository they were sampled from
      and the licence that came with them. What is bundled here is a sample: the examples column is what this
      server holds, not what the source holds.</p>
    <div class="table-scroll"><table class="business-list">
      <thead><tr><th>Dataset</th><th>Category</th><th>Examples</th><th>Shape</th><th>Source</th></tr></thead>
      <tbody>${rows}</tbody>
    </table></div>`;
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
  const cell = value => esc(String(value ?? '').slice(0, 240));
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

/* A bundled set lives inside the installed package: it is the same on every
 * machine that installed this version, and removing it would leave the registry
 * describing rows the server no longer has. Everything the user brought in can
 * go, and the row says which kind it is looking at. */
function datasetIsMine(name) {
  return ['uploaded:', 'hf:', 'builder:'].some(prefix => name.startsWith(prefix));
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

/* Zone three. What was here before the catalogue existed: the task benchmarks
 * that ship with the tool, and the sets you brought yourself. One table,
 * because the Source column is the whole difference between them — and it is
 * the only zone where a row can be deleted. */
function renderOwnZone(entries) {
  if (!entries.length) return '';
  const rows = entries.map(([name, count]) => `<tr>
    <td>${esc(name)}</td><td>${count}</td><td>${esc(datasetSource(name))}</td>
    <td class="row-actions">${deleteCell(name)}</td>
  </tr>`).join('');
  return `<div class="stage-title">Everything else on this server</div>
    <p class="meta">The task benchmarks that ship with the tool, and the sets you uploaded, imported or built.
      Only these can be deleted — the ready-made data above lives inside the installed package.</p>
    <div class="table-scroll"><table class="dataset-list">
      <thead><tr><th>Name</th><th>Examples</th><th>Source</th><th></th></tr></thead>
      <tbody>${rows}</tbody>
    </table></div>`;
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
  const business = names.filter(name => name.startsWith('business:'));
  const own = sets.filter(([name]) => !name.startsWith('business:'));
  // Narrowed to one set, the zones it does not live in would be six group
  // buttons and an empty table above the rows you came to read.
  const zones = only
    ? renderBusinessZone(business) + renderOwnZone(own) + renderCitations(only)
    : renderCatalogZone() + renderBusinessZone(business) + renderOwnZone(own);

  return `${qualityError()}${note}${warning}${zones}${only ? datasetPreview(only, sets[0][1]) : ''}`;
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
  return ({'dataset-builder':renderDatasetBuilder,'judge':renderJudge,'reviews':renderReviews,'regressions':renderRegressions,'analysis':renderAnalysis,'model-matrix':renderModelMatrix,'context-lab':renderContextLab,'releases':renderReleases,'production':renderProduction,'dataset-library':renderDatasetLibrary}[tab] || (() => '<div class="empty">Unknown screen.</div>'))();
}

async function refreshPlatformTab(tab) {
  try {
    if (tab === 'dataset-builder') {
      q.projects = await api('/v1/dataset-projects');
      // Two modes seed from rows this screen does not own: the set being
      // measured, and the set the last run scored. Fetch both, once.
      if (state.report) await loadDatasetRows(state.report.dataset);
      if (state.run.dataset) await loadDatasetRows(state.run.dataset);
    }
    if (tab === 'reviews') q.reviews = await api('/v1/reviews');
    if (tab === 'releases') q.releases = await api('/v1/releases');
    if (tab === 'regressions' && !state.experiments.length) state.experiments = await api('/v1/experiments');
    if (tab === 'dataset-library') {
      await loadDatasets();
      await loadBusinessCatalog();
    }
    q.error = '';
  } catch (error) { q.error = error.message; }
  q.loaded.add(tab);
  if (state.tab === tab) renderDetailPanel(tab);
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
  panel.querySelector('.judge-run')?.addEventListener('click', () => qualityAction(tab, async () => { const result = await api('/v1/evaluate/pairwise', {input:panel.querySelector('#judge-input').value, answer_a:panel.querySelector('#judge-a').value, answer_b:panel.querySelector('#judge-b').value, rubric:panel.querySelector('#judge-rubric').value.split('\n').filter(Boolean), judge_model:judgeRunProfile(panel), subject_models:[modelProfile().model_id]}); setScreenResult(tab, {kind:'judge', ...result}); }));
  panel.querySelectorAll('.review-card').forEach(card => ['approve','reject'].forEach(action => card.querySelector(`.review-${action}`)?.addEventListener('click', () => qualityAction(tab, async () => api(`/v1/reviews/${card.dataset.reviewId}`, {action})))));
  panel.querySelector('.reg-run')?.addEventListener('click', () => qualityAction(tab, async () => { const result=await api('/v1/regressions/analyze', {before_id:panel.querySelector('#reg-before').value, after_id:panel.querySelector('#reg-after').value, quality_tolerance:Number(panel.querySelector('#reg-quality').value), latency_tolerance:Number(panel.querySelector('#reg-latency').value)}); setScreenResult(tab, {kind:'regression', ...result}); }));
  panel.querySelector('.reg-accept')?.addEventListener('click', () => qualityAction(tab, async () => api('/v1/regressions/accept-baseline', {experiment_id:screenResult(tab).comparison.after.id})));
  panel.querySelector('.reg-rerun')?.addEventListener('click', () => qualityAction(tab, async () => { const current=screenResult(tab); const experimentId=current.comparison.after.id; const job=await api('/v1/regressions/rerun', {experiment_id:experimentId}); const rerun=await pollJob(job.id, ()=>{}); setScreenResult(tab, {...current, rerun}); }));
  panel.querySelector('.stats-run')?.addEventListener('click', () => qualityAction(tab, async () => { const result=await api('/v1/analysis/statistics', {before:values(panel.querySelector('#stats-before').value), after:values(panel.querySelector('#stats-after').value)}); setScreenResult(tab, {kind:'analysis', ...result}); }));
  panel.querySelector('.slices-run')?.addEventListener('click', () => qualityAction(tab, async () => { const examples=await api(`/v1/datasets/${encodeURIComponent(state.report.dataset)}`); const rows=await api('/v1/analysis/slices', {examples, runs:state.report.runs}); setScreenResult(tab, {kind:'slices', rows}); }));
  panel.querySelector('.matrix-run')?.addEventListener('click', () => qualityAction(tab, async () => { const ids=panel.querySelector('#matrix-models').value.split('\n').map(x=>x.trim()).filter(Boolean); const base=modelProfile(); const job=await api('/v1/model-matrix', {...baseBenchmarkPayload(), task:await taskProfile(), models:ids.map(model_id=>({...base, model_id}))}); const result=await pollJob(job.id, ()=>{}); setScreenResult(tab, {kind:'matrix', ...result}); }));
  panel.querySelector('.context-run')?.addEventListener('click', () => qualityAction(tab, async () => { const job=await api('/v1/context-lab', {...baseBenchmarkPayload(), task:await taskProfile(), contexts:[{name:panel.querySelector('#ctx-a-name').value, context:panel.querySelector('#ctx-a').value},{name:panel.querySelector('#ctx-b-name').value, context:panel.querySelector('#ctx-b').value}]}); const result=await pollJob(job.id, ()=>{}); setScreenResult(tab, {kind:'context', ...result}); }));
  panel.querySelector('.release-create')?.addEventListener('click', () => qualityAction(tab, async () => api('/v1/releases', {name:panel.querySelector('#release-name').value, technique_id:state.program.technique_id, prompt:state.program}))); 
  panel.querySelectorAll('[data-release-action]').forEach(button => button.addEventListener('click', () => qualityAction(tab, async () => api(`/v1/releases/${button.closest('tr').dataset.releaseId}/action`, {action:button.dataset.releaseAction}))));
  panel.querySelector('.drift-run')?.addEventListener('click', () => qualityAction(tab, async () => { const result=await api('/v1/drift', {baseline_inputs:panel.querySelector('#drift-before').value.split('\n').filter(Boolean), current_inputs:panel.querySelector('#drift-after').value.split('\n').filter(Boolean)}); setScreenResult(tab, {kind:'production', value:result}); }));
  panel.querySelector('.trajectory-run')?.addEventListener('click', () => qualityAction(tab, async () => { const result=await api('/v1/trajectories/evaluate', {steps:JSON.parse(panel.querySelector('#trajectory-json').value), required_tools:panel.querySelector('#trajectory-tools').value.split(',').map(x=>x.trim()).filter(Boolean)}); setScreenResult(tab, {kind:'production', value:result}); }));
  panel.querySelector('.security-run')?.addEventListener('click', () => qualityAction(tab, async () => { const source={id:'security-source', input:panel.querySelector('#security-input').value}; if (state.chosen) { const job=await api('/v1/security-evaluate', {...baseBenchmarkPayload(), task:await taskProfile(), source}); setScreenResult(tab, {kind:'production', value:await pollJob(job.id, ()=>{})}); } else { setScreenResult(tab, {kind:'production', value:await api('/v1/datasets/security-suite', source)}); } }));
}

async function qualityAction(tab, operation) {
  q.error=''; q.loading=true;
  try { await operation(); await refreshPlatformTab(tab); }
  catch (error) { q.error=error.message; if (state.tab === tab) renderDetailPanel(tab); }
  finally { q.loading=false; }
}
