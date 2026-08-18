function renderProgram(p) {
  const allStageText = [];
  const multi = p.stages.length > 1;
  const stages = p.stages.map((s, stageIndex) => {
    const messages = s.messages || [];
    const messageText = messages.map(message => `${String(message.role || 'message').toUpperCase()}\n${message.content || ''}`);
    allStageText.push(`STAGE ${s.stage}\n${messageText.join('\n\n')}`);
    const stageKey = registerCopy(`compiled:stage:${stageIndex}`, messageText.join('\n\n'));
    const slots = (s.deferred_placeholders || []).map(x => `<code>{${esc(x)}}</code>`).join(' ');
    const head = multi
      ? `<div class="prompt-stage-head">
          <div>
            <span class="prompt-step">Call ${stageIndex + 1} of ${p.stages.length}</span>
            <span class="prompt-stage-name">${esc(s.stage)}</span>
            ${slots ? `<span class="prompt-slots">filled at run time: ${slots}</span>` : ''}
          </div>
          ${copyButton(stageKey, 'Copy call', `Copy both messages of call ${stageIndex + 1}, stage ${s.stage}`)}
        </div>`
      : '';
    return `<section class="prompt-stage">${head}
      ${messages.map((message, messageIndex) => {
        const role = String(message.role || 'message').toUpperCase();
        const key = registerCopy(`compiled:stage:${stageIndex}:message:${messageIndex}`, message.content || '');
        // A prompt is one thing made of parts, so the part you came for is
        // marked where it stands rather than lifted out of its own prompt.
        const picked = showingOn('prompt') === promptPartName(p, stageIndex, message);
        return `<div class="prompt-msg${picked ? ' picked' : ''}"${picked ? ' data-picked="true"' : ''}>
          <div class="prompt-msg-head"><span class="prompt-role">${esc(role)}</span>${copyButton(key, 'Copy', `Copy the ${role} message of stage ${s.stage}`)}</div>
          <pre>${esc(message.content || '')}</pre>
        </div>`;
      }).join('')}
    </section>`;
  }).join('');
  const programKey = registerCopy('compiled:program:all', allStageText.join('\n\n'));
  const notes = p.notes.length
    ? `<section class="prompt-notes"><h3>Notes</h3>
        <ul>${p.notes.map(n => `<li>${esc(n)}</li>`).join('')}</ul></section>`
    : '';
  const readyForTask = state.inputSource === 'task';
  const lead = readyForTask
    ? 'Your task is already inside it — copy and paste into your model.'
    : 'Replace <code>{input}</code> with your task or content, then paste it into your model.';
  const callLine = multi
    ? ` This method runs as ${p.stages.length} separate calls: send them in order and paste each answer where the next one asks for it.`
    : '';
  return `<div class="prompt-head">
      <div>
        <h2 class="ready-heading" id="ready-title" tabindex="-1">${readyForTask ? 'Your prompt' : 'Your prompt template'}</h2>
        <p class="prompt-lead">${lead}${esc(callLine)}</p>
      </div>
      <div class="export-actions"><button type="button" class="copy-btn" data-runtime-export="python">Export Python</button><button type="button" class="copy-btn" data-runtime-export="typescript">Export TypeScript</button><button type="button" class="copy-btn copy-all-btn" data-copy-key="${esc(programKey)}" aria-label="${esc(`Copy the full compiled prompt for ${p.technique_title}`)}">${multi ? 'Copy all calls' : 'Copy prompt'}</button></div>
    </div>
    <div class="copy-status" data-copy-status="compiled" role="status" aria-live="polite"></div>
    ${stages}
    <footer class="prompt-foot">
      <span>Method <strong>${esc(p.technique_title)}</strong> · written by ${esc(p.authored_by_model || 'engine')}</span>
      <details class="prompt-spec"><summary>Technical detail</summary>
        <div>${esc(p.technique_id)} v${esc(p.technique_version)} · strategy ${esc(p.strategy)} · ${p.expected_calls} model call(s) · validators: ${esc(p.validators.join(', ') || 'none')}</div>
      </details>
    </footer>
    ${notes}`;
}

/* --------------------------------------------------------------------------
 * A run is set up on the screen that runs it. Measurement asks for examples,
 * Method comparison asks for the same, Optimization also asks how long to
 * search — and each carries only its own button, so nothing on screen belongs
 * to something happening elsewhere.
 * -------------------------------------------------------------------------- */
const RUN_SETUP = {
  report: {lead:'Runs your prompt over every example and scores the answers.',
    fields:['dataset', 'repeats'], estimate:'measure-estimate',
    button:{id:'bench-btn', label:'Measure now', action:'benchmark-prompt'}},
  comparison: {lead:'Scores every recommended method on the same examples, so the ranking is measured rather than assumed.',
    fields:['dataset', 'repeats'], estimate:'measure-estimate',
    button:{id:'compare-btn', label:'Compare all recommended', action:'compare-prompts'}},
  optimization: {lead:'Rewrites the prompt, scores every version, keeps the best one.',
    fields:['dataset', 'repeats', 'rounds', 'backend'], estimate:'optimize-estimate',
    button:{id:'optimize-btn', label:'Optimize the prompt', action:'optimize-prompt'}}
};

/* --------------------------------------------------------------------------
 * What these three screens are working on. They all act on one thing — the
 * prompt written on the Prompt text screen — and none of them used to show it:
 * the screen named a method in one grey line and then asked which examples to
 * run it over, so the thing under measurement was the one thing not on screen. It
 * is stated here instead: whose prompt, in what words, its opening lines, what
 * this screen is about to do to it, and the way back to where it is edited.
 * -------------------------------------------------------------------------- */
const RUN_SUBJECT = {
  report: ['The prompt being measured',
    'This exact text is what runs — only the input changes, one example at a time.'],
  comparison: ['The prompt in the running',
    'Yours runs as written. The other recommended methods have no written text of their own, so each is compiled from your task, and all of them are scored on the same examples.'],
  // The search works from the method in the registry, not from this wording. It
  // is said here because the other two screens now promise the opposite, and a
  // screen that borrows a neighbour's promise is how a number gets misread.
  optimization: ['The prompt being improved',
    'The search starts from the method itself rather than from this wording, writes several versions of it, and keeps whichever scores best.']
};

// The first thing the model is actually sent, which is what "the prompt" means
// to the person reading this screen.
function promptOpening() {
  const messages = state.program?.stages?.[0]?.messages || [];
  const spoken = messages.find(message => message.role === 'user') || messages[0];
  return (spoken?.content || '').trim();
}

// The third zone of the workspace: the rail, the screen, and — on every screen
// of the Prompt section — the prompt itself, in the left column where the
// composer that wrote it stands.
function renderRunSubject(tab) {
  if (!RUN_SUBJECT[tab]) return '';
  return `<div class="run-subject" id="run-subject" data-subject-for="${tab}">${runSubject(tab)}</div>`;
}

function runSubject(tab) {
  const [kicker, note] = RUN_SUBJECT[tab] || RUN_SUBJECT.report;
  if (!state.chosen) {
    return `<div class="subject-empty">Nothing to run yet. These screens work on the prompt from
      <a href="#prompt" data-global-tab="prompt" data-screen="prompt">Prompt text</a> — write it there first.</div>`;
  }
  const task = (state.task?.description || $('description')?.value || '').trim();
  const opening = promptOpening();
  const alternatives = tab === 'comparison' && state.recs.length > 1
    ? ` <span class="subject-more">and ${plural(state.recs.length - 1, 'other recommended method')}</span>` : '';
  return `<div class="subject-top">
      <span class="stage-title">${esc(kicker)}</span>
      <a class="subject-open" href="#prompt" data-global-tab="prompt" data-screen="prompt">Prompt text</a>
    </div>
    <p class="subject-name"><strong>${esc(techniqueTitle(state.chosen))}</strong>${alternatives}</p>
    ${task ? `<p class="subject-task">Your task: ${esc(task.slice(0, 220))}${task.length > 220 ? '…' : ''}</p>` : ''}
    ${opening ? `<pre class="subject-opening">${esc(opening.slice(0, 260))}${opening.length > 260 ? '…' : ''}</pre>` : ''}
    <p class="subject-note">${esc(note)}</p>`;
}

function runField(name) {
  const options = [...state.datasetSizes.entries()]
    .map(([label, size]) => `<option value="${esc(label)}"${label === state.run.dataset ? ' selected' : ''}>${esc(label)} — ${size} examples</option>`).join('');
  switch (name) {
    case 'dataset': return `<label for="run-dataset">Measure against<select id="run-dataset" data-run-field="dataset">${options}</select></label>`;
    case 'repeats': return `<label for="run-repeats">Runs per example<input id="run-repeats" type="number" min="1" max="10" value="${esc(state.run.repeats)}" data-run-field="repeats"></label>`;
    case 'rounds': return `<label for="run-rounds">Rounds<input id="run-rounds" type="number" min="1" max="6" value="${esc(state.run.rounds)}" data-run-field="rounds"></label>`;
    case 'backend': return `<label for="run-backend">How to search<select id="run-backend" data-run-field="backend">${state.backendOptions}</select></label>`;
    default: return '';
  }
}

function renderRunSetup(tab) {
  const setup = RUN_SETUP[tab];
  if (!setup) return '';
  // A section of the screen, not a card on it: the screen already stands on a
  // surface, and a second one of the same colour inside it turns the screen's
  // own name into something floating above a card.
  // No heading of its own: the screen is already named one line above, and the
  // setup is the first thing on it. A second title there only asked the reader
  // to tell two names apart that stand for the same screen.
  return `<section class="run-setup" data-run-setup="${tab}">
    <p class="run-lead">${esc(setup.lead)}</p>
    <div class="quality-form">${setup.fields.map(runField).join('')}</div>
    <div class="meta estimate" id="${setup.estimate}"></div>
    <div class="form-actions"><button id="${setup.button.id}" class="primary" type="button" data-action="${setup.button.action}" disabled>${esc(setup.button.label)}</button></div>
    <div class="progress" id="progress"></div>
  </section>`;
}

const RUN_ACTIONS = {'bench-btn':() => runBenchmark(), 'compare-btn':() => runComparison(), 'optimize-btn':() => runOptimization()};

function wireRunSetup(panel) {
  panel.querySelectorAll('[data-run-field]').forEach(field => field.addEventListener('change', () => {
    state.run[field.dataset.runField] = field.value;
    updateEstimates();
    refreshActions();
  }));
  const button = panel.querySelector('.form-actions button[id]');
  if (button && RUN_ACTIONS[button.id]) button.addEventListener('click', RUN_ACTIONS[button.id]);
  refreshActions();
}

// The dataset list and the backend list both arrive after the first paint.
function refreshRunSetup() {
  const host = document.querySelector('[data-run-setup]');
  if (!host || host.dataset.runSetup !== state.tab) return;
  renderDetailPanel(state.tab);
}

// ---- step 3: measure -------------------------------------------------------
async function pollJob(id, onProgress) {
  for (;;) {
    const job = await api(`/v1/jobs/${id}`);
    if (job.progress && Object.keys(job.progress).length) onProgress(job.progress);
    if (job.status === 'done') return job.result;
    if (job.status === 'error') throw new Error(job.error || 'job failed');
    await new Promise(r => setTimeout(r, 700));
  }
}

function showProgress(p) {
  const node = $('progress');
  if (!node) return;
  if (p.completed != null) node.textContent = `${p.completed}/${p.total} runs — ${p.example_id || ''}`;
  else if (p.phase) node.textContent = `${p.phase} · round ${p.round || '-'} · ${p.candidate || p.generated + ' candidates'}`;
}

function techniqueTitle(id) {
  const rec = state.recs.find(item => item.technique_id === id);
  if (rec) return rec.title;
  const entry = state.techniqueCatalog.get(id);
  return (entry && entry.title) || id;
}

// A greyed-out button has to say why it is grey. The shared line covers the
// gate both halves depend on; each button carries its own reason on hover.
function setAction(id, disabled, reason) {
  // The three run buttons live on the three screens that run them, so on any
  // other screen there is nothing to disable.
  const button = $(id);
  if (!button) return;
  button.disabled = disabled;
  if (disabled && reason) button.title = reason;
  else button.removeAttribute('title');
}

function refreshActions(running = false) {
  const noMethod = 'Create a prompt above first — this measures the method you picked.';
  const inFlight = 'A run is already in progress.';
  // Every one of these ends in a model call, so a missing model disables them
  // for the same reason a missing prompt does — and says so in the same place.
  const noModel = typeof modelIsSet === 'function' && !modelIsSet();
  const missing = 'Set an evaluation model first — see Models & keys.';
  setAction('select-btn', running || noModel, running ? inFlight : missing);
  setAction('bench-btn', running || noModel || !state.chosen, running ? inFlight : noModel ? missing : noMethod);
  setAction('optimize-btn', running || noModel || !state.chosen, running ? inFlight : noModel ? missing : noMethod);
  setAction('compare-btn', running || noModel || state.recs.length < 2,
    running ? inFlight : noModel ? missing : 'Comparing needs at least two recommended methods.');
  // The prompt can be written, or rewritten, while one of these screens is
  // open, so what the screen says it is working on is redrawn with the buttons
  // that would run it.
  const subject = $('run-subject');
  if (subject) subject.innerHTML = runSubject(subject.dataset.subjectFor || state.tab);
  refreshHomeIfVisible();
  updateEstimates();
}



function busy(on) {
  refreshActions(on);
  if (!on) $('progress').textContent = '';
}

async function runBenchmark() {
  busy(true);
  try {
    // The prompt itself goes with the request, not just the name of the method
    // it came from: what is measured has to be the text on the Prompt text
    // screen, including whatever the engine wrote into it.
    const job = await api('/v1/benchmark', {
      task: await taskProfile(), technique_id: state.chosen, prompt: state.program,
      dataset: state.run.dataset, repeats: Number(state.run.repeats)
    });
    state.report = await pollJob(job.id, showProgress);
    state.tab = 'report'; renderDetail();
  } catch (e) { showDetailMessage('report', `<div class="error">${esc(e.message)}</div>`); }
  finally { busy(false); }
}

async function runComparison() {
  busy(true);
  try {
    // Your prompt runs as written; the other methods have no written text of
    // their own, so they are compiled — which is the question being asked.
    const job = await api('/v1/compare', {
      task: await taskProfile(), technique_ids: state.recs.map(r => r.technique_id),
      prompt: state.program, dataset: state.run.dataset, repeats: Number(state.run.repeats)
    });
    const result = await pollJob(job.id, showProgress);
    state.comparison = result.comparison;
    state.tab = 'comparison'; renderDetail();
  } catch (e) { showDetailMessage('comparison', `<div class="error">${esc(e.message)}</div>`); }
  finally { busy(false); }
}

async function runOptimization() {
  busy(true);
  try {
    const job = await api('/v1/optimize', {
      task: await taskProfile(), technique_id: state.chosen,
      dataset: state.run.dataset, repeats: Number(state.run.repeats),
      rounds: Number($('rounds').value), backend: $('backend').value,
      engine_model: engineProfile()
    });
    state.optimization = await pollJob(job.id, showProgress);
    state.tab = 'optimization'; renderDetail();
  } catch (e) { showDetailMessage('optimization', `<div class="error">${esc(e.message)}</div>`); }
  finally { busy(false); }
}

/* --------------------------------------------------------------------------
 * Smart run. The three steps a person has to find and press in order — write,
 * measure, improve — driven from one button, through the same endpoints the
 * three buttons use. It stops at the first step that fails and says which one,
 * because a chain that hides where it broke is worse than three buttons.
 * -------------------------------------------------------------------------- */
async function smartRun(report) {
  const dataset = state.run.dataset;
  const repeats = Number(state.run.repeats);
  if (!dataset) throw new Error('Choose a set of examples first — Datasets › Dataset library.');

  report('step', 'Writing the prompt…');
  if (!await createPrompt()) throw new Error('Describe the task first, then start again.');
  if (!state.chosen) throw new Error('No method fit this task, so there is nothing to measure.');

  report('step', `Measuring ${techniqueTitle(state.chosen)} on ${plural(state.datasetSizes.get(dataset) || 0, 'example')}…`);
  const benchmark = await api('/v1/benchmark', {task: await taskProfile(), technique_id: state.chosen, dataset, repeats});
  state.report = await pollJob(benchmark.id, showProgress);

  report('step', `Improving it over ${plural(Number(state.run.rounds), 'round')}…`);
  const optimize = await api('/v1/optimize', {
    task: await taskProfile(), technique_id: state.chosen, dataset, repeats,
    rounds: Number(state.run.rounds), backend: state.run.backend, engine_model: engineProfile()
  });
  state.optimization = await pollJob(optimize.id, showProgress);
  return state.optimization;
}

function delta(value, betterWhenLower) {
  if (!value) return '<td>—</td>';
  const good = betterWhenLower ? value < 0 : value > 0;
  return `<td class="delta ${good ? 'up' : 'down'}">${value > 0 ? '+' : ''}${value.toFixed(3)}</td>`;
}

/* --------------------------------------------------------------------------
 * The verdict, before the table. A scorecard answers "what are the numbers";
 * the first thing a person actually asks is "is this good, and can I trust
 * it?" — so the sentence comes first, the caveats that would change the answer
 * come second, and only then the eleven metrics.
 * -------------------------------------------------------------------------- */
const BUNDLED_DEMO_SETS = new Set(['agents', 'entity-extraction', 'entity-extraction-hard', 'few-nerd',
  'grounded-qa', 'gsm8k', 'mbpp', 'multiconer-en', 'summarization', 'support-classification', 'translation']);

// The run this one should be read against: the most recent recorded experiment
// on the same dataset and technique, which is what "better or worse" means here.
function previousMeasurement(report) {
  const match = state.experiments.find(item =>
    item.dataset === report.dataset && item.technique_id === report.technique_id);
  const metric = match ? experimentMetric(match) : null;
  return metric ? {version:match.version, quality:metric.quality} : null;
}

function verdictCautions(report) {
  const c = report.scorecard;
  const notes = [];
  if (report.examples < 30) {
    notes.push(`Measured on ${plural(report.examples, 'example')}. That is a small sample: a couple of unlucky rows move this number by several points, so treat it as a direction, not a score.`);
  }
  if (report.repeats === 1) {
    notes.push('One run per example, so nothing here separates a real difference from the model answering differently on a second try. Raise "runs per example" to see the spread.');
  }
  if (BUNDLED_DEMO_SETS.has(report.dataset)) {
    notes.push('These are the bundled demo examples. A score only says something about your prompt once the examples look like your real inputs.');
  }
  if (c.failures) {
    notes.push(`${plural(c.failures, 'answer')} failed outright and count as zero — worth reading before trusting the average.`);
  }
  // A score over rows a model invented is a score about invented rows. It is
  // said here rather than on the builder screen, because here is where the
  // number gets read and believed.
  const held = state.datasetRows.get(report.dataset);
  if (held?.status === 'ready' && held.rows.length) {
    const written = held.rows.filter(row => (row.tags || []).some(tag => tag === 'synthetic' || tag === 'model-generated')).length;
    if (written === held.rows.length) {
      notes.push('Every example here was written by a model. The score describes generated inputs, not traffic you have seen — keep some real rows in the set.');
    } else if (written) {
      notes.push(`${written} of ${held.rows.length} examples were written by a model rather than observed.`);
    }
  }
  return notes;
}

function renderVerdict(report) {
  const c = report.scorecard;
  const percent = Math.round(c.quality * 100);
  const previous = previousMeasurement(report);
  const delta = previous ? c.quality - previous.quality : null;
  const points = delta == null ? null : Math.round(Math.abs(delta) * 100);
  const movement = delta == null ? 'No earlier run on these examples to compare against.'
    : points === 0 ? `Unchanged against v${previous.version} on the same examples.`
    : delta > 0 ? `${plural(points, 'point')} better than v${previous.version} on the same examples.`
    : `${plural(points, 'point')} worse than v${previous.version} on the same examples.`;
  const tone = delta == null ? '' : delta > 0 ? ' up' : delta < 0 ? ' down' : '';
  const cautions = verdictCautions(report);
  // 2πr for the ring below; the arc is the score and nothing else.
  const circumference = 273.3;
  const stat = (label, value, note) => `<div class="stat"><dt>${esc(label)}</dt><dd>${esc(value)}<small>${esc(note)}</small></dd></div>`;
  return `<section class="verdict${tone}">
    <div class="verdict-head">
      <div class="ring" role="img" aria-label="Quality ${c.quality.toFixed(3)} out of 1">
        <svg viewBox="0 0 96 96" aria-hidden="true">
          <circle class="ring-track" cx="48" cy="48" r="43.5"></circle>
          <circle class="ring-fill" cx="48" cy="48" r="43.5" stroke-dasharray="${circumference}" stroke-dashoffset="${(circumference * (1 - Math.max(0, Math.min(1, c.quality)))).toFixed(1)}"></circle>
        </svg>
        <b>${c.quality.toFixed(2)}</b><span>quality</span>
      </div>
      <div class="verdict-words">
        <span class="section-eyebrow">Result</span>
        <p class="verdict-line"><strong>${percent} out of every 100 answers</strong> were judged correct by ${esc(graderMeaning(c.quality_grader))}.</p>
        <p class="verdict-move">${esc(movement)}</p>
        <p class="verdict-sub">${esc(techniqueTitle(report.technique_id))} on ${esc(report.model_id)} · ${esc(report.dataset)}</p>
      </div>
    </div>
    <dl class="stats">
      ${stat('Quality', c.quality.toFixed(3), previous ? `was ${previous.quality.toFixed(3)}` : 'first run')}
      ${stat('Answer time', `${c.mean_latency_seconds.toFixed(2)} s`, 'median per example')}
      ${stat('Examples', String(report.examples), `${plural(report.repeats, 'run')} each`)}
      ${stat('Cost', c.mean_cost_usd == null ? 'unknown' : `$${c.mean_cost_usd.toFixed(6)}`, 'per answer')}
    </dl>
    ${cautions.length ? `<ul class="verdict-cautions">${cautions.map(note => `<li>${esc(note)}</li>`).join('')}</ul>` : ''}
  </section>`;
}

/* --------------------------------------------------------------------------
 * One number for a hundred answers hides the only thing that decides what to do
 * next: whether 0.87 means every answer was slightly off, or that nine in ten
 * were perfect and the rest collapsed. Those two runs need opposite work, so
 * the run is drawn example by example — one block each, worst first — and every
 * block opens the example it stands for.
 * -------------------------------------------------------------------------- */
function runScore(run, grader) {
  if (run.error) return 0;
  if (grader && run.grades[grader] != null) return run.grades[grader];
  const values = Object.values(run.grades);
  return values.length ? values.reduce((total, value) => total + value, 0) / values.length : 0;
}

// One entry per example, holding every repeat of it, ordered worst first.
function exampleScores(report) {
  const grader = report.scorecard.quality_grader;
  const byExample = new Map();
  report.runs.forEach(run => {
    const entry = byExample.get(run.example_id) || {id:run.example_id, runs:[], total:0};
    entry.runs.push(run);
    entry.total += runScore(run, grader);
    byExample.set(run.example_id, entry);
  });
  return [...byExample.values()]
    .map(entry => ({...entry, score: entry.total / entry.runs.length}))
    .sort((a, b) => a.score - b.score || a.id.localeCompare(b.id));
}

// Three states, because that is what a person does about them: right, needs
// reading, wrong. A partly-right answer is not a shade of right.
const scoreTone = score => (score >= 0.999 ? 'good' : score > 0 ? 'part' : 'bad');

function renderRunStrip(report, here) {
  const entries = exampleScores(report);
  if (!entries.length) return '';
  const counted = {good:0, part:0, bad:0};
  entries.forEach(entry => { counted[scoreTone(entry.score)] += 1; });
  const blocks = entries.map(entry => {
    const tone = scoreTone(entry.score);
    const reading = `${entry.id} — ${entry.score.toFixed(2)}`;
    return `<a class="strip-cell ${tone}${entry.id === here ? ' here' : ''}" href="#report/${encodeURIComponent(entry.id)}"
      data-global-tab="report" data-showing="${esc(entry.id)}" title="${esc(reading)}"><span class="sr-only">${esc(reading)}</span></a>`;
  }).join('');
  const parts = [
    counted.good ? `${counted.good} right` : '',
    counted.part ? `${counted.part} partly right` : '',
    counted.bad ? `${counted.bad} wrong` : ''
  ].filter(Boolean).join(' · ');
  return `<div class="stage-title">Example by example</div>
    <p class="meta">${esc(parts)}. One block per example, worst first — open one to see what the model actually answered.</p>
    <div class="run-strip">${blocks}</div>`;
}

// The row as the dataset holds it. An inline run has no set behind it, so the
// card shows what the run itself recorded and says nothing it cannot know.
function datasetRow(report, id) {
  const held = state.datasetRows.get(report.dataset);
  if (!held || held.status !== 'ready') return null;
  return held.rows.find(row => row.id === id) || null;
}

function renderExampleCard(report, entry, full) {
  const source = datasetRow(report, entry.id);
  const tone = scoreTone(entry.score);
  const grader = report.scorecard.quality_grader;
  const cut = (value, limit) => esc(String(value ?? '').slice(0, limit));
  const answers = (full ? entry.runs : entry.runs.slice(0, 1)).map(run => {
    const grades = Object.entries(run.grades)
      .map(([name, value]) => `<span class="grade ${value >= 0.999 ? 'good' : value > 0 ? 'part' : 'bad'}"><b>${esc(name)}</b> ${value.toFixed(2)}</span>`).join('');
    const trouble = run.error || run.schema_errors.join('; ');
    return `<div class="example-answer">
      ${entry.runs.length > 1 ? `<div class="meta">Run ${run.repeat + 1} of ${entry.runs.length} · ${run.latency_seconds.toFixed(2)} s · ${run.prompt_tokens + run.completion_tokens} tokens</div>` : ''}
      <pre>${cut(run.output, full ? 4000 : 300) || '<span class="meta">empty answer</span>'}</pre>
      ${grades ? `<div class="example-grades">${grades}</div>` : ''}
      ${trouble ? `<p class="example-trouble">${esc(trouble)}</p>` : ''}
    </div>`;
  }).join('');
  const asked = source ? `<div class="example-field"><dt>Asked</dt><dd><pre>${cut(source.input, full ? 4000 : 300)}</pre></dd></div>` : '';
  const wanted = source
    ? `<div class="example-field"><dt>Right answer</dt><dd><pre>${source.expected == null || source.expected === '' ? 'none — the graders judge the answer on its own' : cut(source.expected, 1200)}</pre></dd></div>`
    : '';
  return `<article class="example-card ${tone}">
    <div class="example-head">
      <strong>${esc(entry.id)}</strong>
      <span class="state ${tone === 'good' ? 'ok' : tone === 'part' ? 'wait' : 'bad-chip'}">${entry.score.toFixed(2)}${grader ? ` ${esc(grader)}` : ''}</span>
      ${full ? '' : `<a class="example-open" href="#report/${encodeURIComponent(entry.id)}" data-global-tab="report" data-showing="${esc(entry.id)}">Open</a>`}
    </div>
    <dl class="example-fields">${asked}${wanted}
      <div class="example-field"><dt>Answered</dt><dd>${answers}</dd></div>
    </dl>
  </article>`;
}

// Every number on the screen in its own unit. Six decimal places on a count of
// failures said "0.000000 failures", which reads as a measurement rather than
// as none.
const METRIC_FORMAT = {
  ratio: value => Number(value).toFixed(3),
  seconds: value => `${Number(value).toFixed(2)} s`,
  tokens: value => Number(value).toFixed(0),
  calls: value => Number(value).toFixed(1),
  money: value => `$${Number(value).toFixed(6)}`,
  count: value => String(Math.round(value))
};

function renderReport(r) {
  const c = r.scorecard;
  const only = showingOn('report');
  // Opened on one example: the verdict stays, because it says which prompt, on
  // which model, over which set the answer below was produced. The strip stays
  // too — it is how you walk to the next failure without going back up.
  if (only) {
    const entry = exampleScores(r).find(item => item.id === only);
    return `${renderVerdict(r)}
      ${entry ? renderExampleCard(r, entry, true) : `<div class="empty">This run has no example called ${esc(only)}.</div>`}
      ${renderRunStrip(r, only)}`;
  }
  const rows = [
    ['quality — ' + graderMeaning(c.quality_grader), c.quality, r.declared.quality, 'ratio'],
    ['reliability', c.reliability, r.declared.reliability, 'ratio'],
    ['contract pass rate', c.contract_pass_rate, null, 'ratio'],
    ['stability across repeats', c.stability, null, 'ratio'],
    ['mean latency', c.mean_latency_seconds, null, 'seconds'],
    ['p95 latency', c.p95_latency_seconds, null, 'seconds'],
    ['mean tokens', c.mean_total_tokens, null, 'tokens'],
    ['mean cost', c.mean_cost_usd, null, 'money'],
    ['total cost', c.total_cost_usd, null, 'money'],
    ['mean calls', c.mean_calls, null, 'calls'],
    ['failures', c.failures, null, 'count']
  ].map(([label, measured, declared, kind]) => `<tr><td>${esc(label)}</td><td>${measured == null ? 'unknown' : METRIC_FORMAT[kind](measured)}</td><td>${declared == null ? '—' : Number(declared).toFixed(3)}</td></tr>`).join('');
  const graders = Object.entries(c.grades).map(([k, v]) => `<tr><td>${esc(k)}${k === c.quality_grader ? ' <span class="pill">headline</span>' : ''}</td><td class="what">${esc(graderMeaning(k))}</td><td>${v.toFixed(3)}</td></tr>`).join('');
  // The work is in the answers that did not come back right — and only those.
  // Three of them, because a fourth is read the same way as the third.
  const worst = exampleScores(r)
    .filter(entry => scoreTone(entry.score) !== 'good')
    .slice(0, 3)
    .map(entry => renderExampleCard(r, entry, false)).join('');
  return `${renderVerdict(r)}
    ${renderRunStrip(r)}
    <div class="stage-title">Where it went wrong</div>
    ${worst || '<div class="empty">Nothing scored below the top — every example came back right.</div>'}
    <div class="stage-title">Every measurement</div>
    <p class="meta">Measured is what just happened on your examples; declared is what the registry claims for ${esc(r.technique_title || r.technique_id)}. Run with the ${esc(r.strategy)} strategy.</p>
    <table><thead><tr><th>Metric</th><th>Measured</th><th>Declared</th></tr></thead><tbody>${rows}</tbody></table>
    <div class="stage-title">Graders</div>
    <table><thead><tr><th>Grader</th><th class="what">What it measures</th><th>Mean</th></tr></thead><tbody>${graders}</tbody></table>
    ${r.prior != null ? `<div class="warning">Registry prior was ${r.prior.toFixed(2)}; measured quality is ${c.quality.toFixed(2)}. Ranking now uses the measured value.</div>` : ''}`;
}

function renderComparison(c) {
  const rows = c.entries.map((e, i) => `<tr>
    <td>${i === 0 ? '<span class="rank">#1</span> ' : ''}${esc(e.technique_id)}</td>
    <td>${e.weighted_score.toFixed(3)}</td>
    <td>${e.scorecard.quality.toFixed(3)}</td>
    <td>${e.scorecard.reliability.toFixed(3)}</td>
    <td>${e.scorecard.mean_latency_seconds.toFixed(2)}</td>
    <td>${e.scorecard.mean_total_tokens.toFixed(0)}</td><td>${e.scorecard.mean_cost_usd == null ? 'unknown' : `$${e.scorecard.mean_cost_usd.toFixed(6)}`}</td>
    <td>${e.scorecard.mean_calls.toFixed(1)}</td></tr>`).join('');
  return `<h2>Measured comparison</h2>
    <div class="meta">${esc(c.dataset)} on ${esc(c.model_id)} · priorities q${c.priorities.quality.toFixed(2)} r${c.priorities.reliability.toFixed(2)} l${c.priorities.latency.toFixed(2)} t${c.priorities.token_cost.toFixed(2)}</div>
    <table><thead><tr><th>Technique</th><th>Weighted</th><th>Quality</th><th>Reliability</th><th>Latency s</th><th>Tokens</th><th>Cost</th><th>Calls</th></tr></thead><tbody>${rows}</tbody></table>
    <div class="warning">${esc(c.note)}</div>`;
}

function renderOptimization(o) {
  const b = o.baseline_validation, w = o.winner_validation;
  const rows = [
    ['quality', b.quality, w.quality, false],
    ['reliability', b.reliability, w.reliability, false],
    ['mean tokens', b.mean_total_tokens, w.mean_total_tokens, true],
    ['mean latency (s)', b.mean_latency_seconds, w.mean_latency_seconds, true],
    ['mean cost (USD)', b.mean_cost_usd, w.mean_cost_usd, true]
  ].map(([label, base, best, lower]) => `<tr><td>${esc(label)}</td><td>${base == null ? 'unknown' : base.toFixed(6)}</td><td>${best == null ? 'unknown' : best.toFixed(6)}</td>${base == null || best == null ? '<td>—</td>' : delta(best - base, lower)}</tr>`).join('');
  const rounds = o.rounds.map(r => `<div class="meta">round ${r.round}: ${r.evaluated.map(c => `${esc(c.id)} ${c.score != null ? c.score.toFixed(3) : '—'}`).join(' · ')}</div>`).join('');
  const stages = (o.compiled_prompt.stages || []).map(s => `<div class="stage-title">optimized — stage ${esc(s.stage)}</div><pre>${esc(s.user)}</pre>`).join('');
  return `<h2>Optimized against measured results</h2>
    <div class="meta">backend <strong>${esc(o.backend || 'native')}</strong> · proposed by <strong>${esc(o.engine_model_id || o.model_id)}</strong><span class="pill ${o.engine_is_target ? 'prior' : 'measured'}">${o.engine_is_target ? 'same as target' : 'separate engine'}</span> · ${o.train_size} train / ${o.validation_size} held out · ${o.total_calls} model calls · ${o.elapsed_seconds}s · winner <strong>${esc(o.winner.id)}</strong> (${esc(o.winner.origin)})</div>
    ${(o.notes || []).map(n => `<div class="warning">${esc(n)}</div>`).join('')}
    <table><thead><tr><th>Metric (held-out)</th><th>Baseline</th><th>Optimized</th><th>Delta</th></tr></thead><tbody>${rows}</tbody></table>
    <div class="stage-title">search history</div>${rounds}
    <div class="meta">Pareto front: ${o.pareto_front.map(c => esc(c.id)).join(', ')}</div>
    ${stages}`;
}
