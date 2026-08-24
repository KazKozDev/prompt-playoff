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
        // A worked example is not part of the instruction, and a reader who
        // cannot tell them apart cannot judge either.
        if (message.demo) {
          return `<div class="prompt-msg demo">
            <div class="prompt-msg-head"><span class="prompt-role">${esc(role)}</span><span class="demo-tag">worked example</span>${copyButton(key, 'Copy', `Copy the ${role} side of a worked example`)}</div>
            <pre>${esc(message.content || '')}</pre>
          </div>`;
        }
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
  const demos = p.stages.reduce((total, stage) =>
    total + (stage.messages || []).filter(message => message.demo).length, 0) / 2;
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
      <div class="export-actions">${demos ? `<button type="button" class="copy-btn" data-action="drop-demos">Remove ${plural(demos, 'example')}</button>` : ''}<button type="button" class="copy-btn" data-runtime-export="python">Export Python</button><button type="button" class="copy-btn" data-runtime-export="typescript">Export TypeScript</button><button type="button" class="copy-btn copy-all-btn" data-copy-key="${esc(programKey)}" aria-label="${esc(`Copy the full compiled prompt for ${p.technique_title}`)}">${multi ? 'Copy all calls' : 'Copy prompt'}</button></div>
    </div>
    <div class="copy-status" data-copy-status="compiled" role="status" aria-live="polite"></div>
    ${demos ? `<p class="prompt-lead">${plural(demos, 'worked example')} sit ahead of your request — the search
      found ${demos > 1 ? 'them' : 'it'} helped and kept ${demos > 1 ? 'them' : 'it'}. Your own text is untouched
      underneath, and removing ${demos > 1 ? 'them' : 'it'} leaves exactly what you wrote.</p>` : ''}
    ${stages}
    <footer class="prompt-foot">
      <span>Method <strong>${esc(p.technique_title)}</strong> · ${p.artifact_source === 'optimizer'
        ? `optimized wording, proposed by ${esc(p.authored_by_model || 'the engine')}`
        : `written by ${esc(p.authored_by_model || 'engine')}`}${provenanceLine()}</span>
      <details class="prompt-spec"><summary>Technical detail</summary>
        <div>${esc(p.technique_id)} v${esc(p.technique_version)} · strategy ${esc(p.strategy)} · ${p.expected_calls} model call(s) · validators: ${esc(p.validators.join(', ') || 'none')}</div>
      </details>
    </footer>
    ${notes}
    ${nextStep()}`;
}

/* --------------------------------------------------------------------------
 * What to do with the prompt that has just appeared.
 *
 * The screen ended at a copy button, and the whole argument of the tool — that
 * a prompt nobody measured is a prompt nobody can defend — was left to whoever
 * thought to open the rail. It is stated here instead, at the foot of the thing
 * it is about, and it names the state the prompt is actually in: unmeasured,
 * measured, or measured and improved. Only the step that has not been taken is
 * offered, so the block disappears rather than turning into a row of buttons.
 * -------------------------------------------------------------------------- */
function nextStep() {
  const step = (tab, title, lead, label) => `<aside class="next-step" data-testid="next-step">
      <div><strong>${esc(title)}</strong><small>${esc(lead)}</small></div>
      <a class="next-go" href="#${tab}" data-global-tab="${tab}" data-screen="${tab}">${esc(label)}</a>
    </aside>`;
  if (!state.provenance) {
    return step('report', 'Nothing has been measured yet',
      'This wording is a proposal until it has been run over examples. That takes one screen.',
      'Measure it');
  }
  if (!state.optimization) {
    return step('optimization', `Measured — quality ${state.provenance.quality.toFixed(3)}`,
      'The search rewrites this prompt, scores every version against the same examples and keeps the best one.',
      'Try to improve it');
  }
  return step('regressions', 'Measured and improved',
    'Before it goes anywhere near real users, compare it against the run it is meant to replace.',
    'Check for regressions');
}

// The run this prompt has a number from, named where the prompt is read. A
// prompt with nothing here is one no measurement stands behind, whatever is on
// the neighbouring screens.
function provenanceLine() {
  const from = state.provenance;
  if (!from) return '';
  const word = from.kind === 'optimization' ? 'optimization' : 'measurement';
  return ` · backed by the ${word} on ${esc(from.dataset)}, quality ${from.quality.toFixed(3)}`;
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
  // Two backends, two different things, and the difference is exactly what the
  // reader needs. The native search rewrites this text; a DSPy backend searches
  // the recipe's own instruction block, so its candidates are not rewrites of
  // these words even though they are still measured against them.
  optimization: ['The prompt being improved', () => state.run.backend?.startsWith('dspy:')
    ? `This exact text is the one to beat: it runs as written, and every number is measured against it. ${state.run.backend} searches the method's own instructions, though, so the versions challenging it are not rewrites of these words.`
    : 'This exact text is what the search starts from and what every number is measured against. Each version it tries is a rewrite of these words.']
};

// The first thing the model is actually sent, which is what "the prompt" means
// to the person reading this screen.
function promptOpening() {
  const messages = state.program?.stages?.[0]?.messages || [];
  const spoken = messages.find(message => message.role === 'user') || messages[0];
  return (spoken?.content || '').trim();
}

/* The whole text, not the first 260 characters of it.
 *
 * The column showed an opening that stopped mid-sentence and a link away to the
 * screen that holds the rest. On a screen whose entire subject is this text —
 * "this exact text is what runs" — the text has to be readable where that claim
 * is made, or the claim is about something the reader cannot see. The opening
 * stays as the glance; the disclosure under it is the prompt. */
function subjectFullText() {
  const parts = promptMessages(state.program);
  if (!parts.length) return '';
  const multi = (state.program?.stages || []).length > 1;
  const key = registerCopy('subject:full', promptPlainText(state.program));
  return `<details class="subject-full" data-testid="subject-full">
      <summary>Read the whole prompt (${plural(parts.length, 'message')})</summary>
      <div class="subject-full-body">
        ${parts.map(promptPartBlock).join('')}
        <div class="subject-full-actions">${copyButton(key, multi ? 'Copy all calls' : 'Copy prompt', 'Copy the full text of the prompt this screen is working on')}</div>
        <div class="copy-status" data-copy-status="subject:full" role="status" aria-live="polite"></div>
      </div>
    </details>`;
}

// The third zone of the workspace: the rail, the screen, and — on every screen
// of the Prompt section — the prompt itself, in the left column where the
// composer that wrote it stands. Under it, on the screen that measures, how
// the measurement is taken.
function renderRunSubject(tab) {
  if (!RUN_SUBJECT[tab]) return '';
  return `<div class="run-subject" id="run-subject" data-subject-for="${tab}">${subjectBody(tab)}</div>`;
}

function subjectBody(tab) {
  return runSubject(tab) + measurementNote(tab);
}

// The column is redrawn from state, so anything it reads that arrives later —
// the grader wording, the rows of a set, the business catalogue — comes back
// through here rather than through a second copy of the markup.
function refreshRunSubject() {
  const subject = $('run-subject');
  if (subject) subject.innerHTML = subjectBody(subject.dataset.subjectFor || state.tab);
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
    ${subjectFullText()}
    <p class="subject-note">${esc(typeof note === 'function' ? note() : note)}</p>`;
}

/* --------------------------------------------------------------------------
 * What "measured" means, beside the button that measures.
 *
 * The screen held the prompt, a set of examples and a button, and then handed
 * back a scorecard of eleven numbers — with nothing in between saying how the
 * second came out of the first. So the run is written out as the three things
 * it actually is: the same prompt sent once per example, each answer scored by
 * code rather than by a model, and those scores folded into the two headline
 * numbers.
 *
 * It is written from the run about to happen, not from measurement in general:
 * the set named in the field above, the graders those rows actually carry, and
 * the order the server picks the headline grader by — so what it says will
 * happen is what the scorecard will have done.
 * -------------------------------------------------------------------------- */

// Where the rows came from. It is the first thing a score depends on and the
// one thing the score itself cannot show, so the kind of set is named before
// any number is taken on it.
function setOrigin(name) {
  if (!name) return null;
  if (name.startsWith('uploaded:')) {
    return {label:'Your own file',
      note:'Rows you brought here. A score on these is the only kind that speaks about your own work directly.'};
  }
  if (name.startsWith('hf:')) {
    return {label:'Imported from Hugging Face',
      note:'A public set someone else collected and annotated, sampled onto this server. Nobody here tuned it to produce a convenient result.'};
  }
  if (name.startsWith('builder:')) {
    return {label:'Generated here',
      note:'Rows written from your task rather than observed. A score over written rows describes written rows — keep real ones in the set.'};
  }
  if (name.startsWith('business:')) {
    const spec = typeof catalogSets === 'function' ? catalogSets().get(name) : null;
    if (!spec) return {label:'From the business catalogue', note:'The public set that catalogue maps this job to.'};
    return {label:`Sampled from ${spec.source}`, url:spec.url,
      note:`${spec.shape} Licence: ${spec.license}.`};
  }
  return {label:'Shipped with the tool',
    note:'One of the benchmarks inside the installed package: this tool\u2019s own test stand, useful for trying the workflow out and for comparing a method against a published result. A good score here describes the tool, not your task.'};
}

/* Which graders will run, read off the rows themselves.
 *
 * A dataset names its graders per row, because arithmetic and translation
 * cannot be checked the same way; a row that names none is scored by graders
 * inferred from the shape of its expected answer. Both are said, since "no
 * graders listed" and "no graders" are not the same sentence.
 */
function setGraders(name) {
  const held = state.datasetRows.get(name);
  if (!held || held.status === 'loading') return {status:'loading'};
  if (held.status === 'error') return {status:'error', error:held.error};
  const named = [];
  let inferred = 0;
  held.rows.forEach(row => {
    const listed = row.graders || [];
    if (!listed.length) inferred += 1;
    listed.forEach(grader => { if (!named.includes(grader)) named.push(grader); });
  });
  return {status:'ready', named, inferred, rows:held.rows.length};
}

// The rows of the chosen set, and the catalogue a business set is described
// by, are both fetched on demand — asked for once, and the column redrawn when
// they land.
function ensureMeasurementFacts() {
  const name = state.run.dataset;
  if (name && !state.datasetRows.has(name)) loadDatasetRows(name).then(refreshRunSubject);
  if (name && name.startsWith('business:') && !state.catalog) loadBusinessCatalog().then(refreshRunSubject);
}

function graderChip(name, headline) {
  const role = headline === name ? 'headline' : state.contractGraders.has(name) ? 'contract' : '';
  return `<li class="grader-line${role ? ` ${role}` : ''}">
    <code>${esc(name)}</code>${role ? `<span class="grader-role">${role === 'headline' ? 'quality' : 'reliability'}</span>` : ''}
    <span>${esc(graderMeaning(name))}</span></li>`;
}

function measurementGraders(name) {
  const found = setGraders(name);
  if (found.status === 'loading') return '<p class="how-note">Reading which graders these rows carry…</p>';
  if (found.status === 'error') return `<p class="how-note">Could not read the rows of ${esc(name)}: ${esc(found.error)}</p>`;
  // Inputs and nothing else. Naming the graders that would have run is no use
  // here; what the reader needs is which half of the scorecard will be blank.
  const facts = state.datasetFacts.get(name);
  if (facts && facts.examples && !facts.has_expected && !found.named.length) {
    return `<p class="how-note">No row here carries a right answer, so <strong>nothing will score
      correctness</strong>. The run measures repeatability, time and cost — and the shape of the answer, if the task
      says it must be JSON. Write the right answer into some rows and the same run returns a quality number.</p>`;
  }
  const validators = state.program?.validators || [];
  const all = [...found.named, ...validators.filter(item => !found.named.includes(item))];
  if (!all.length) {
    return `<p class="how-note">No row here names a grader, so each answer is scored by graders inferred from the
      shape of its expected answer — word overlap for prose, per-item overlap for a list, the label for a category.</p>
      <p class="how-note warn"><b>If these rows hold prose</b> — a reply, a summary, an email — the inferred score is
      word overlap with your reference answer, and ${esc(graderCaveat('token_f1') || '')}</p>`;
  }
  const headline = state.qualityPreference.find(item => all.includes(item)) || null;
  const inferred = found.inferred
    ? `<p class="how-note">${found.inferred} of ${plural(found.rows, 'row')} name no grader of their own; those are scored
      by graders inferred from the shape of the expected answer.</p>`
    : '';
  const added = validators.length
    ? `<p class="how-note">${validators.length === 1 ? 'The last one comes' : `The last ${validators.length} come`}
      from the method itself — its own contract checks, which score nothing when they do not apply.</p>`
    : '';
  // Said before the run rather than after it. Learning that the headline number
  // cannot decide this task is worth an hour when it arrives with the number,
  // and worth the whole run when it arrives before one.
  const warning = graderCaveat(headline);
  return `<ul class="grader-list">${all.map(item => graderChip(item, headline)).join('')}</ul>
    ${headline ? `<p class="how-note">Quality will be <code>${esc(headline)}</code>: the first of these in the order the
      scorecard prefers for a headline number. The rest are shown beside it on the report.</p>` : ''}
    ${warning ? `<p class="how-note warn"><b>Before you read that number:</b> ${esc(warning)}</p>` : ''}
    ${inferred}${added}`;
}

function measurementNote(tab) {
  if (tab !== 'report') return '';
  ensureMeasurementFacts();
  const name = state.run.dataset;
  if (!name) {
    return `<section class="how-measured"><div class="stage-title">How this is measured</div>
      <p class="how-note">Choose a set of examples above and this will say what will run over them, what will score
        the answers, and where those rows came from.</p></section>`;
  }
  const examples = state.datasetSizes.get(name);
  const repeats = Math.max(1, Number(state.run.repeats) || 1);
  const model = state.settings.evaluation.model_id.trim() || 'the evaluation model';
  const origin = setOrigin(name);
  const source = origin.url
    ? `<a href="${esc(origin.url)}" target="_blank" rel="noreferrer noopener">${esc(origin.label)} ↗</a>`
    : esc(origin.label);
  return `<section class="how-measured">
    <div class="stage-title">How this is measured</div>
    <ol class="how-steps">
      <li><b>Run.</b> The prompt above goes to <strong>${esc(model)}</strong> once for every example in
        <code>${esc(name)}</code>${Number.isFinite(examples) ? ` — ${plural(examples, 'example')}` : ''},
        ${repeats === 1 ? 'once' : `${repeats} times`} each. Only the input changes between runs; the wording is
        sent as it stands.</li>
      <li><b>Grade.</b> Every answer is scored from 0 to 1 by code — a rule you can read, not a model marking a model.
        The same answer always gets the same score. Open prose is judged separately, on
        <a href="#judge" data-global-tab="judge" data-screen="judge">Answer judging</a>, and never enters a
        benchmark number without a human saying so.</li>
      <li><b>Fold.</b> <strong>Quality</strong> is the mean of the one grader that stands for a right answer.
        <strong>Reliability</strong> is the share of correctly shaped answers times stability — how often repeats of
        the same input came back the same, which is 1.000 by definition at one run each. Time, tokens and cost are
        read off the calls themselves.</li>
    </ol>
    <div class="how-block">
      <div class="how-label">The examples it is measured on</div>
      <p class="how-note"><strong>${source}</strong> — ${esc(origin.note)}</p>
    </div>
    <div class="how-block">
      <div class="how-label">What will score the answers</div>
      ${measurementGraders(name)}
    </div>
    <p class="how-note">A number belongs to one prompt, one model and one set: change any of the three and it is a
      guess again. The <a href="#guides/evaluation" data-global-tab="guides" data-screen="guides" data-mode="evaluation">Evaluation guide</a>
      has every grader, where each bundled set comes from, and the five rules a number depends on.</p>
  </section>`;
}

/* The field that decides what every number on the screen is about, grouped the
 * way the library groups the same sets and ordered the way they are worth
 * measuring on. A flat alphabetical list put `agents` at the top — one of the
 * benchmarks this tool tests itself with, and the one class the screen below
 * warns describes the tool rather than your task — above the rows the reader
 * brought themselves. The prefixes are what the grouping already knows, so they
 * are dropped from the labels: the group says what `hf:` was saying. */
const DATASET_GROUPS = [
  ['Your sets', name => typeof datasetIsMine === 'function' && datasetIsMine(name)],
  ['Ready-made datasets by business task', name => name.startsWith('business:')],
  ['Shipped with the tool', () => true]
];

function datasetOptions() {
  const sets = [...state.datasetSizes.entries()];
  return DATASET_GROUPS.map(([label, belongs], index) => {
    const mine = sets.filter(([name]) =>
      belongs(name) && !DATASET_GROUPS.slice(0, index).some(([, earlier]) => earlier(name)));
    if (!mine.length) return '';
    const options = mine.map(([name, size]) => {
      // The whole name stays the value — it is what the server is asked for —
      // while the label drops the prefix the group above it already carries.
      const shown = name.includes(':') ? name.slice(name.indexOf(':') + 1) : name;
      return `<option value="${esc(name)}"${name === state.run.dataset ? ' selected' : ''}>${esc(shown)} — ${size} examples</option>`;
    }).join('');
    return `<optgroup label="${esc(label)}">${options}</optgroup>`;
  }).join('');
}

function runField(name) {
  const options = datasetOptions();
  // The empty row is the opening state and stays in the list afterwards: a set
  // can be un-chosen the same way it was chosen, and nothing runs until one is.
  const placeholder = `<option value=""${state.run.dataset ? '' : ' selected'}>Choose a set of examples…</option>`;
  switch (name) {
    case 'dataset': return `<label for="run-dataset">Measure against<select id="run-dataset" data-run-field="dataset">${placeholder}${options}</select></label>`;
    case 'repeats': return `<label for="run-repeats">Runs per example<input id="run-repeats" type="number" min="1" max="10" value="${esc(state.run.repeats)}" data-run-field="repeats"></label>`;
    case 'rounds': return `<label for="run-rounds">Rounds<input id="run-rounds" type="number" min="1" max="6" value="${esc(state.run.rounds)}" data-run-field="rounds"></label>`;
    case 'backend': return `<label for="run-backend">How to search<select id="run-backend" data-run-field="backend">${state.backendOptions}</select></label>`;
    default: return '';
  }
}

/* --------------------------------------------------------------------------
 * Twenty of your own inputs, no right answers.
 *
 * Everything on this screen is worth more when the rows are yours, and the
 * screen used to open pointed at a set that ships with the tool — one click
 * from a number that describes this tool rather than the reader's work. The
 * gap it was leaving unsaid is that a useful measurement does not need an
 * answer key: whether the shape holds, whether the same input comes back the
 * same, how long it takes and what it costs are all answered by inputs alone.
 *
 * So it is offered here, where the meaningless click was, and only while the
 * selected set is not the reader's own. The rows go in through the same upload
 * the file screen uses, so they are validated and named the same way.
 * -------------------------------------------------------------------------- */
function ownRowsInvitation(tab) {
  if (tab !== 'report') return '';
  const name = state.run.dataset;
  if (name && typeof datasetIsMine === 'function' && datasetIsMine(name)) return '';
  return `<details class="own-rows" data-testid="own-rows">
    <summary><strong>Start with your own inputs — no right answers needed</strong>
      <small>Twenty real lines are enough to measure everything that does not need an answer key.</small></summary>
    <div class="own-rows-body">
      <p class="field-hint">Paste inputs you have actually seen — tickets, emails, documents — one per line. The run
        reports shape, repeatability, time and cost. It cannot report whether an answer is <em>right</em>: that needs
        rows with the right answer in them, which is what
        <a href="#dataset-add" data-global-tab="dataset-add" data-screen="dataset-add" data-mode="upload">Upload your own</a> takes.</p>
      <label for="own-rows-input" class="sr-only">Your inputs, one per line</label>
      <textarea id="own-rows-input" rows="6" placeholder="Card payment failed twice this morning, third attempt went through&#10;Where do I change the billing address on my account?"></textarea>
      <div class="own-rows-actions">
        <button type="button" class="primary" data-action="use-own-rows">Use these as my examples</button>
        <span class="own-rows-status" role="status" aria-live="polite"></span>
      </div>
      <p class="field-hint">They become a set of your own, selected straight away, with runs per example at 3 so
        repeatability has something to compare. Held for this session only — the
        <a href="#dataset-add" data-global-tab="dataset-add" data-screen="dataset-add" data-mode="upload">Add dataset screen</a> can
        keep a set on this machine.</p>
    </div>
  </details>`;
}

// Through the same endpoint a dropped file takes: one JSON object per line,
// validated server-side, named after the "file" it arrived as.
async function useOwnRows(panel) {
  const box = panel.querySelector('#own-rows-input');
  const status = panel.querySelector('.own-rows-status');
  const lines = box.value.split('\n').map(line => line.trim()).filter(Boolean);
  if (!lines.length) {
    status.textContent = 'Nothing to use yet — paste a few inputs first.';
    return;
  }
  const jsonl = lines.map((input, index) => JSON.stringify({id:`row-${index + 1}`, input})).join('\n');
  const form = new FormData();
  form.append('file', new Blob([jsonl], {type:'application/x-ndjson'}), 'my-inputs.jsonl');
  status.textContent = `Registering ${plural(lines.length, 'row')}…`;
  try {
    const response = await fetch('/v1/datasets/upload', {method:'POST', body:form});
    const body = await response.json();
    if (!response.ok) throw new Error(body.detail || 'Upload failed');
    state.run.repeats = 3;
    // Registering the rows hides the block that asked for them — the set is the
    // reader's own now — so what just happened is said on the screen rather than
    // inside the thing that disappeared.
    state.ownRowsNote = `${plural(body.examples, 'row')} of your own are now what this measures, as `
      + `${body.name}, three runs each. Held for this server session only.`;
    await loadDatasets(body.name);
    renderDetailPanel('report');
  } catch (error) {
    status.textContent = error.message;
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
  const note = tab === 'report' && state.ownRowsNote
    ? `<div class="upload-status success">${esc(state.ownRowsNote)}</div>` : '';
  return `<section class="run-setup" data-run-setup="${tab}">
    <p class="run-lead">${esc(setup.lead)}</p>
    ${ownRowsInvitation(tab)}${note}
    <div class="quality-form">${setup.fields.map(runField).join('')}</div>
    <div class="meta estimate" id="${setup.estimate}"></div>
    <div class="form-actions"><button id="${setup.button.id}" class="primary" type="button" data-action="${setup.button.action}" disabled>${esc(setup.button.label)}</button></div>
    <div class="progress" id="progress"></div>
  </section>`;
}

const RUN_ACTIONS = {'bench-btn':() => runBenchmark(), 'compare-btn':() => runComparison(), 'optimize-btn':() => runOptimization()};

function wireRunSetup(panel) {
  panel.querySelector('[data-action="adopt-optimized"]')
    ?.addEventListener('click', event => adoptOptimized(event.currentTarget));
  panel.querySelector('[data-action="download-technique"]')
    ?.addEventListener('click', event => exportTechnique(event.currentTarget, false));
  panel.querySelector('[data-action="save-technique"]')
    ?.addEventListener('click', event => exportTechnique(event.currentTarget, true));
  panel.querySelector('[data-action="use-own-rows"]')?.addEventListener('click', () => useOwnRows(panel));
  panel.querySelectorAll('[data-run-field]').forEach(field => field.addEventListener('change', () => {
    if (field.dataset.runField === 'dataset') state.ownRowsNote = '';
    state.run[field.dataset.runField] = field.value;
    updateEstimates();
    // The bar names the set every number is computed from, so it is rewritten
    // by the control that changes it rather than on the next navigation.
    updateWorkspaceContext();
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
  // Nothing is measured against a set nobody picked, so the three runs are held
  // until one is — for the same reason and in the same place as a missing model.
  const noSet = !state.run.dataset;
  const pickSet = 'Choose a set of examples first — the field above this button.';
  const why = noModel ? missing : noSet ? pickSet : noMethod;
  setAction('select-btn', running || noModel, running ? inFlight : missing);
  setAction('bench-btn', running || noModel || noSet || !state.chosen, running ? inFlight : why);
  setAction('optimize-btn', running || noModel || noSet || !state.chosen, running ? inFlight : why);
  setAction('compare-btn', running || noModel || noSet || state.recs.length < 2,
    running ? inFlight : noModel ? missing : noSet ? pickSet : 'Comparing needs at least two recommended methods.');
  // The prompt can be written, or rewritten, while one of these screens is
  // open, so what the screen says it is working on is redrawn with the buttons
  // that would run it.
  refreshRunSubject();
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
      dataset: state.run.dataset, repeats: Number(state.run.repeats), ...businessCaseRequestFields()
    });
    state.report = await pollJob(job.id, showProgress);
    // This run was of the prompt currently held, so it is the number a release
    // of that prompt can point at — a stronger claim than the optimization that
    // may have produced the wording, because it measured this exact text.
    if (state.report.experiment_id) {
      state.provenance = {experiment_id:state.report.experiment_id, kind:'measurement',
        dataset:state.report.dataset, quality:state.report.scorecard.quality};
    }
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
      prompt: state.program, dataset: state.run.dataset, repeats: Number(state.run.repeats),
      ...businessCaseRequestFields()
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
    // The prompt goes with the request, as it does on the other two screens: it
    // is the baseline, so "improved by 0.09" is a statement about the text on
    // this screen rather than about a compile of the method nobody has seen.
    const job = await api('/v1/optimize', {
      task: await taskProfile(), technique_id: state.chosen, prompt: state.program,
      dataset: state.run.dataset, repeats: Number(state.run.repeats),
      rounds: Number(state.run.rounds), backend: state.run.backend,
      engine_model: engineProfile(), ...businessCaseRequestFields(),
      allow_noisy_objective: state.run.allowNoisyObjective === true
    });
    state.optimization = await pollJob(job.id, showProgress);
    state.tab = 'optimization'; renderDetail();
  } catch (e) { showDetailMessage('optimization', optimizeFailure(e)); }
  finally { busy(false); }
}

/* A search maximises whatever number it is handed. Handed word overlap on rows
 * whose answers already resemble each other, it raises it by drifting towards
 * the wording every row shares — the prompt gets worse while the score goes up.
 * The server refuses that before spending a call, and this is where the refusal
 * turns into something a person can act on: what to give the rows instead, and
 * the one way to proceed anyway, which relabels what comes back. */
// The override, wired once. The refusal is drawn into a panel that redraws
// itself, so the button cannot be bound where it is written.
document.addEventListener('click', event => {
  if (!event.target.closest('[data-action="optimize-anyway"]')) return;
  // Set for this search only. A run that opted out of the refusal is a run
  // whose result is drift, and the next one should have to say so again.
  state.run.allowNoisyObjective = true;
  runOptimization().finally(() => { state.run.allowNoisyObjective = false; });
});

function optimizeFailure(error) {
  if (error.code !== 'unmeasurable_objective') return `<div class="error">${esc(error.message)}</div>`;
  const floor = error.detail?.chance_level;
  return `<div class="error">
    <p><strong>This set has no number worth searching against.</strong>${floor == null ? ''
      : ` An answer written for a different row of it already scores ${Number(floor).toFixed(2)} on word overlap, which is what the search would be raising.`}</p>
    <p>Give the rows requirements a rule can decide and the search has something real to maximise —
      <a href="#dataset-library" data-global-tab="dataset-library" data-screen="dataset-library">Datasets</a> can read them
      off the rows for you.</p>
    <div class="quality-actions">
      <button type="button" class="ghost" data-action="optimize-anyway">Search anyway, and read it as drift</button>
    </div>
  </div>`;
}

// The exporter's own default collides with the next winner from the same recipe,
// so the round is in the name a person is offered before they keep it.
function defaultTechniqueId(o) {
  return `${o.winner.technique_id}.optimized`;
}

async function exportTechnique(button, save) {
  const optimization = state.optimization;
  if (!optimization) return;
  const name = document.getElementById('technique-name')?.value.trim();
  const status = document.querySelector('[data-technique-status]');
  const original = button.textContent;
  button.disabled = true;
  button.textContent = save ? 'Keeping…' : 'Building…';
  try {
    const result = await api('/v1/export/technique', {
      technique: optimization.exported_technique, technique_id: name || null, save
    });
    if (save) {
      state.techniqueNote = `${result.id} is saved and now resolves. ${result.next}`;
      // The catalogue and every method list read from the server, so what was
      // just added has to be re-read rather than assumed.
      await loadTechniqueCatalog();
    } else {
      downloadText(result.filename, result.yaml, 'text/yaml');
      state.techniqueNote = `${result.filename} downloaded. ${result.next}`;
    }
    if (status) { status.className = 'copy-status success'; status.textContent = state.techniqueNote; }
  } catch (e) {
    state.techniqueNote = e.message;
    if (status) { status.className = 'copy-status error-text'; status.textContent = e.message; }
  } finally {
    button.disabled = false;
    button.textContent = original;
  }
}

/* --------------------------------------------------------------------------
 * Adopting the winner. The search never saw the authored prompt — it works from
 * the method in the registry — and its preview was compiled against one dataset
 * row. So the winning instructions are recompiled here against this task, on the
 * server, rather than the preview being copied onto the screen with a benchmark
 * example baked into it.
 * -------------------------------------------------------------------------- */
async function adoptOptimized(button) {
  const optimization = state.optimization;
  if (!optimization) return;
  const original = button.textContent;
  button.disabled = true;
  button.textContent = 'Adopting…';
  state.adoptError = '';
  try {
    const program = await api('/v1/optimize/adopt', {
      task: await taskProfile(),
      technique_id: optimization.winner.technique_id,
      // A prompt search already measured this exact text for this task, so it is
      // copied. A recipe search measured a compile against a benchmark row, so
      // its winner has to be rebuilt against the real material instead.
      technique: optimization.winner_program ? {} : optimization.exported_technique,
      program: optimization.winner_program || null,
      description: $('description').value,
      reusable: state.inputSource === 'reusable',
      engine_model_id: optimization.engine_model_id || optimization.model_id
    });
    state.program = program;
    // The held-out numbers belong to the search, not to this text as compiled
    // for this task — but they are the run that justifies adopting it, and a
    // release registered now should say so rather than say nothing.
    state.provenance = optimization.experiment_id
      ? {experiment_id:optimization.experiment_id, kind:'optimization',
         dataset:optimization.dataset, quality:optimization.winner_validation.quality}
      : null;
    state.tab = 'prompt';
    updateEstimates();
    updateWorkspaceContext();
    renderDetail();
  } catch (e) {
    // Not `showDetailMessage`: that replaces the screen with the error, and the
    // screen is the search — a failed click would cost the reader the table,
    // the history and the winner's text. The error belongs next to the button
    // that produced it.
    state.adoptError = e.message;
    renderDetailPanel('optimization');
  }
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
  // The set is picked in the run setup on this screen, not in the library, which
  // only shows what exists. The caller has already walked the reader there.
  if (!dataset) throw new Error('Choose a set of examples first — the "Measure against" field on the Measurement screen.');

  report('step', 'Writing the prompt…');
  if (!await createPrompt()) throw new Error('Describe the task first, then start again.');
  if (!state.chosen) throw new Error('No method fit this task, so there is nothing to measure.');

  report('step', `Measuring ${techniqueTitle(state.chosen)} on ${plural(state.datasetSizes.get(dataset) || 0, 'example')}…`);
  const benchmark = await api('/v1/benchmark', {
    task: await taskProfile(), technique_id: state.chosen, prompt: state.program,
    dataset, repeats, ...businessCaseRequestFields()
  });
  state.report = await pollJob(benchmark.id, showProgress);

  report('step', `Improving it over ${plural(Number(state.run.rounds), 'round')}…`);
  const optimize = await api('/v1/optimize', {
    task: await taskProfile(), technique_id: state.chosen, prompt: state.program, dataset, repeats,
    rounds: Number(state.run.rounds), backend: state.run.backend, engine_model: engineProfile(),
    ...businessCaseRequestFields()
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
  // The measured floor under the headline metric, when the headline is a
  // comparison against one reference answer. This is the note that stops
  // someone rewriting a working prompt: if answers to other rows already score
  // what this run scored, the number is about the metric, not the prompt.
  if (c.quality_chance_level != null) {
    const margin = c.quality - c.quality_chance_level;
    notes.push(margin <= 0.05
      ? `Answers copied from other rows of this set already score ${c.quality_chance_level.toFixed(2)} here — at or above what this run scored. This metric is not telling your prompt apart from an answer to a different question, so the number is not a verdict on the prompt at all.`
      : `Answers copied from other rows of this set already score ${c.quality_chance_level.toFixed(2)} here, so ${c.quality.toFixed(2)} is ${margin.toFixed(2)} above what wording alone earns. 1.00 is not reachable by anything but a copy of the reference.`);
  }
  const graderNote = graderCaveat(c.quality_grader);
  if (graderNote) notes.push(graderNote);
  // Which of these numbers nobody chose. A row that names its graders said what
  // it wanted measured; a row that did not had them picked from the shape of
  // its answer, and the result reads the same either way unless it is said.
  const inferred = Object.keys(report.inferred_graders || {});
  if (inferred.length) {
    const rows = Math.max(...Object.values(report.inferred_graders));
    notes.push(`${rows} of ${report.examples} examples name no grader of their own, so ${inferred.join(', ')} ${inferred.length === 1 ? 'was' : 'were'} chosen for them from the shape of their answers — not by you. Write "graders" into the rows to make the choice yours.`);
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
  // Nothing could grade correctness: the rows carry no right answer and the task
  // asks for no shape to check against. The run still measured real things —
  // form, repeatability, time, cost — so it is those that stand in the head.
  // A 0.00 in the ring would say every answer was wrong, which is a different
  // and much worse claim than "there was nothing here to be right about".
  const unscored = !c.quality_grader;
  const tone = unscored ? '' : delta == null ? '' : delta > 0 ? ' up' : delta < 0 ? ' down' : '';
  const cautions = verdictCautions(report);
  // 2πr for the ring below; the arc is the score and nothing else.
  const circumference = 273.3;
  const stat = (label, value, note) => `<div class="stat"><dt>${esc(label)}</dt><dd>${esc(value)}<small>${esc(note)}</small></dd></div>`;
  const ring = unscored
    ? `<div class="ring unscored" role="img" aria-label="No grader could score these answers">
        <svg viewBox="0 0 96 96" aria-hidden="true"><circle class="ring-track" cx="48" cy="48" r="43.5"></circle></svg>
        <b>—</b><span>unscored</span>
      </div>`
    // The floor is marked on the ring, not only said underneath it. An arc
    // filled to 0.66 reads as two thirds of the way to right; over a metric
    // that already gives an answer to a different question 0.63, almost all of
    // that arc was never the prompt's to earn. The tick is where that line
    // falls, drawn over the fill so it shows on either side of it.
    : `<div class="ring" role="img" aria-label="Quality ${c.quality.toFixed(3)} out of 1${c.quality_chance_level == null ? '' : `, where an answer written for a different row already scores ${c.quality_chance_level.toFixed(2)}`}">
        <svg viewBox="0 0 96 96" aria-hidden="true">
          <circle class="ring-track" cx="48" cy="48" r="43.5"></circle>
          <circle class="ring-fill" cx="48" cy="48" r="43.5" stroke-dasharray="${circumference}" stroke-dashoffset="${(circumference * (1 - Math.max(0, Math.min(1, c.quality)))).toFixed(1)}"></circle>
          ${c.quality_chance_level == null ? '' : `<circle class="ring-chance" cx="48" cy="48" r="43.5" stroke-dasharray="2 ${circumference}" stroke-dashoffset="${(1 - circumference * Math.max(0, Math.min(1, c.quality_chance_level))).toFixed(1)}"><title>an answer written for a different row scores ${c.quality_chance_level.toFixed(2)}</title></circle>`}
        </svg>
        <b>${c.quality.toFixed(2)}</b><span>quality</span>
      </div>`;
  const line = unscored
    ? `<p class="verdict-line"><strong>Nothing here could score correctness.</strong> These rows carry no right
        answer and the task sets no shape to check against, so what was measured is repeatability, time and cost.</p>
      <p class="verdict-move">Add the right answer to some rows and the same run returns a quality number.</p>`
    // A share of answers and an average score are two different claims, and the
    // second one was being read out as the first. `token_f1` gives an answer
    // partial credit for the words it shares with a reference, so "14 out of
    // every 100 answers were correct" was a pass rate nobody measured — and the
    // one sentence most likely to send a reader off to fix a working prompt.
    : isPassRate(c.quality_grader)
    ? `<p class="verdict-line"><strong>${percent} out of every 100 answers</strong> passed — ${esc(graderMeaning(c.quality_grader))}.</p>
      <p class="verdict-move">${esc(movement)}</p>`
    : `<p class="verdict-line">Answers scored <strong>${c.quality.toFixed(2)} out of 1 on average</strong>, where the score is ${esc(graderMeaning(c.quality_grader))}. That is an average, not a share of answers that were right.</p>
      <p class="verdict-move">${esc(movement)}</p>`;
  const headline = unscored
    ? stat('Same answer twice', c.stability.toFixed(3), report.repeats > 1 ? `over ${plural(report.repeats, 'run')}` : 'raise runs per example')
    : stat('Quality', c.quality.toFixed(3), previous ? `was ${previous.quality.toFixed(3)}` : 'first run');
  return `<section class="verdict${tone}">
    <div class="verdict-head">
      ${ring}
      <div class="verdict-words">
        <span class="section-eyebrow">Result</span>
        ${line}
        <p class="verdict-sub">${esc(techniqueTitle(report.technique_id))} on ${esc(report.model_id)} · ${esc(report.dataset)}</p>
      </div>
    </div>
    <dl class="stats">
      ${headline}
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

function renderExampleCard(report, entry, full, unscored = false) {
  const source = datasetRow(report, entry.id);
  // Nothing graded this run, so a red card would be a verdict nobody reached.
  const tone = unscored ? 'plain' : scoreTone(entry.score);
  const grader = report.scorecard.quality_grader;
  const cut = (value, limit) => esc(asText(value).slice(0, limit));
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
  const noAnswer = unscored
    ? 'none — and with nothing to compare against, nothing scored this'
    : 'none — the graders judge the answer on its own';
  const wanted = source
    ? `<div class="example-field"><dt>Right answer</dt><dd><pre>${source.expected == null || source.expected === '' ? noAnswer : cut(source.expected, 1200)}</pre></dd></div>`
    : '';
  return `<article class="example-card ${tone}">
    <div class="example-head">
      <strong>${esc(entry.id)}</strong>
      ${unscored
        ? '<span class="state idle">not scored</span>'
        : `<span class="state ${tone === 'good' ? 'ok' : tone === 'part' ? 'wait' : 'bad-chip'}">${entry.score.toFixed(2)}${grader ? ` ${esc(grader)}` : ''}</span>`}
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
  // With nothing grading correctness the strip would paint every example red and
  // "where it went wrong" would list rows nothing found wrong. What helps then is
  // reading a few answers as they came back.
  const unscored = !c.quality_grader;
  const rows = [
    ['quality — ' + graderMeaning(c.quality_grader), c.quality, r.declared.quality, 'ratio'],
    // Directly under quality, because it is the row that says where this
    // metric's zero actually is: the score an answer about a different row
    // already earns. Absent for every grader whose zero is at zero.
    ...(c.quality_chance_level == null ? [] : [['chance level — what an unrelated answer scores here', c.quality_chance_level, null, 'ratio']]),
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
  const sample = exampleScores(r).slice(0, 3).map(entry => renderExampleCard(r, entry, false, true)).join('');
  const answers = unscored
    ? `<div class="stage-title">What came back</div>
      <p class="meta">Nothing graded these, so they are a sample to read rather than a list of failures — the fastest
        way to tell whether the shape is right is to look at three of them.</p>
      ${sample}`
    : `<div class="stage-title">Where it went wrong</div>
      ${worst || '<div class="empty">Nothing scored below the top — every example came back right.</div>'}`;
  return `${renderVerdict(r)}
    ${unscored ? '' : renderRunStrip(r)}
    ${answers}
    <div class="stage-title">Every measurement</div>
    <p class="meta">Measured is what just happened on your examples; declared is what the registry claims for ${esc(r.technique_title || r.technique_id)}. Run with the ${esc(r.strategy)} strategy.</p>
    <table><thead><tr><th>Metric</th><th>Measured</th><th>Declared</th></tr></thead><tbody>${rows}</tbody></table>
    <div class="stage-title">Graders</div>
    ${graders
      ? `<table><thead><tr><th>Grader</th><th class="what">What it measures</th><th>Mean</th></tr></thead><tbody>${graders}</tbody></table>`
      : `<div class="empty">No grader could produce a number for these rows: none of them carries a right answer, and
        the task asks for no shape to check. Add <code>expected</code> to some rows, or say in the task that the answer
        must be JSON, and the same run comes back with a score.</div>`}
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

/* The winner has to be able to leave this screen. Until it can, the only thing
 * downstream of a search is a wall of text: Releases registers the prompt on
 * Prompt text, which the search never touched, so a run could be optimized and
 * shipped and the two would have nothing to do with each other.
 *
 * Two cases are refused rather than offered. The baseline winning means the
 * search found nothing better, and "adopting" it would overwrite whatever the
 * engine wrote with a plain compile of the registry method — a downgrade wearing
 * the word improvement. A gain of zero or less on held-out quality is the same
 * answer arrived at by arithmetic.
 */
function renderAdopt(o) {
  const gain = o.winner_validation.quality - o.baseline_validation.quality;
  if (o.winner.id === o.baseline_id) {
    return `<div class="warning">The baseline won: no version the search wrote scored better on the
      held-out split, so there is nothing here to adopt. Your prompt stays as it is.</div>`;
  }
  const adopted = state.program && state.program.artifact_source === 'optimizer';
  const rewrote = Boolean(o.winner_program);
  const numbers = gain > 0
    ? `Held-out quality ${o.baseline_validation.quality.toFixed(3)} → ${o.winner_validation.quality.toFixed(3)}.`
    : 'Held-out quality did not improve, so this is a trade — read the table above before taking it.';
  return `<section class="adopt-winner">
    <h3>Take this wording</h3>
    <p class="prompt-lead">${rewrote
      ? `Puts <strong>${esc(o.winner.id)}</strong> on <a href="#prompt" data-global-tab="prompt" data-screen="prompt">Prompt text</a>, replacing what is there. ${esc(numbers)} The search rewrote your own words, so the text above is what was measured and adopting copies it verbatim.`
      : `Recompiles <strong>${esc(o.winner.id)}</strong> against your task and puts it on <a href="#prompt" data-global-tab="prompt" data-screen="prompt">Prompt text</a>, replacing what is there. ${esc(numbers)} The prompt above ran on one row of ${esc(o.dataset)}; what lands on your screen is the same instructions with your material in its place.`}</p>
    <div class="form-actions">
      <button type="button" class="primary" data-action="adopt-optimized">Adopt optimized prompt</button>
      ${adopted ? '<span class="meta">An optimized prompt is already on the Prompt text screen.</span>' : ''}
    </div>
    ${state.adoptError ? `<div class="error">${esc(state.adoptError)}</div>` : ''}
    ${rewrote ? `<p class="prompt-lead">No technique file to keep here: the winner is a prompt, not a recipe, and a
      file of the untouched recipe would reproduce none of it. Export a runnable client from
      <a href="#prompt" data-global-tab="prompt" data-screen="prompt">Prompt text</a> once you have adopted it.</p>`
      : `${renderTechniqueKeep(o)}`}
  </section>`;
}

function renderTechniqueKeep(o) {
  return `<h3>Or keep it as a method of its own</h3>
    <p class="prompt-lead">The same winner as a technique file. Downloaded, it goes in your own registry; kept here,
      its name resolves, so <code>/v1/run</code> and an exported client execute it instead of the recipe it was tuned
      from. It is never recommended to anyone — a method tuned on ${esc(o.dataset)} says nothing about another
      task.</p>
    <div class="quality-form">
      <label>Name<input id="technique-name" value="${esc(defaultTechniqueId(o))}"></label>
    </div>
    <div class="form-actions">
      <button type="button" class="ghost" data-action="download-technique">Download the file</button>
      <button type="button" class="ghost" data-action="save-technique">Keep it on this server</button>
    </div>
    <div class="copy-status" data-technique-status role="status" aria-live="polite">${state.techniqueNote
      ? esc(state.techniqueNote) : ''}</div>`;
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
    ${stages}
    ${renderAdopt(o)}`;
}
