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
        return `<div class="prompt-msg">
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
  if (p.completed != null) $('progress').textContent = `${p.completed}/${p.total} runs — ${p.example_id || ''}`;
  else if (p.phase) $('progress').textContent = `${p.phase} · round ${p.round || '-'} · ${p.candidate || p.generated + ' candidates'}`;
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
  const button = $(id);
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
  $('chosen').innerHTML = state.chosen
    ? `Ready to measure <strong>${esc(techniqueTitle(state.chosen))}</strong>.`
    : 'Create a prompt first, then pick a method — both steps below measure the method you picked.';
  updateEstimates();
}

function busy(on) {
  refreshActions(on);
  if (!on) $('progress').textContent = '';
}

$('bench-btn').addEventListener('click', async () => {
  busy(true);
  try {
    const job = await api('/v1/benchmark', {
      task: await taskProfile(), technique_id: state.chosen,
      dataset: $('dataset').value, repeats: Number($('repeats').value)
    });
    state.report = await pollJob(job.id, showProgress);
    state.tab = 'report'; renderDetail();
  } catch (e) { showDetailMessage('report', `<div class="error">${esc(e.message)}</div>`); }
  finally { busy(false); }
});

$('compare-btn').addEventListener('click', async () => {
  busy(true);
  try {
    const job = await api('/v1/compare', {
      task: await taskProfile(), technique_ids: state.recs.map(r => r.technique_id),
      dataset: $('dataset').value, repeats: Number($('repeats').value)
    });
    const result = await pollJob(job.id, showProgress);
    state.comparison = result.comparison;
    state.tab = 'comparison'; renderDetail();
  } catch (e) { showDetailMessage('comparison', `<div class="error">${esc(e.message)}</div>`); }
  finally { busy(false); }
});

$('optimize-btn').addEventListener('click', async () => {
  busy(true);
  try {
    const job = await api('/v1/optimize', {
      task: await taskProfile(), technique_id: state.chosen,
      dataset: $('dataset').value, repeats: Number($('repeats').value),
      rounds: Number($('rounds').value), backend: $('backend').value,
      engine_model: engineProfile()
    });
    state.optimization = await pollJob(job.id, showProgress);
    state.tab = 'optimization'; renderDetail();
  } catch (e) { showDetailMessage('optimization', `<div class="error">${esc(e.message)}</div>`); }
  finally { busy(false); }
});

/* --------------------------------------------------------------------------
 * Smart run. The three steps a person has to find and press in order — write,
 * measure, improve — driven from one button, through the same endpoints the
 * three buttons use. It stops at the first step that fails and says which one,
 * because a chain that hides where it broke is worse than three buttons.
 * -------------------------------------------------------------------------- */
async function smartRun(report) {
  const dataset = $('dataset').value;
  const repeats = Number($('repeats').value);
  if (!dataset) throw new Error('Choose a set of examples first — Examples › Example library.');

  report('step', 'Writing the prompt…');
  if (!await createPrompt()) throw new Error('Describe the task first, then start again.');
  if (!state.chosen) throw new Error('No method fit this task, so there is nothing to measure.');

  report('step', `Measuring ${techniqueTitle(state.chosen)} on ${plural(state.datasetSizes.get(dataset) || 0, 'example')}…`);
  const benchmark = await api('/v1/benchmark', {task: await taskProfile(), technique_id: state.chosen, dataset, repeats});
  state.report = await pollJob(benchmark.id, showProgress);

  report('step', `Improving it over ${plural(Number($('rounds').value), 'round')}…`);
  const optimize = await api('/v1/optimize', {
    task: await taskProfile(), technique_id: state.chosen, dataset, repeats,
    rounds: Number($('rounds').value), backend: $('backend').value, engine_model: engineProfile()
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
  return notes;
}

function renderVerdict(report) {
  const c = report.scorecard;
  const percent = Math.round(c.quality * 100);
  const previous = previousMeasurement(report);
  const delta = previous ? c.quality - previous.quality : null;
  const points = delta == null ? null : Math.round(Math.abs(delta) * 100);
  const movement = delta == null ? ''
    : points === 0 ? ` Unchanged against v${previous.version} on the same examples.`
    : delta > 0 ? ` That is ${plural(points, 'point')} better than v${previous.version} on the same examples.`
    : ` That is ${plural(points, 'point')} worse than v${previous.version} on the same examples.`;
  const tone = delta == null ? '' : delta > 0 ? ' up' : delta < 0 ? ' down' : '';
  const cautions = verdictCautions(report);
  return `<section class="verdict${tone}">
    <span class="section-eyebrow">Result</span>
    <p class="verdict-line"><strong>${percent} out of every 100 answers</strong> were judged correct by ${esc(graderMeaning(c.quality_grader))}.${esc(movement)}</p>
    <p class="verdict-sub">${esc(techniqueTitle(report.technique_id))} on ${esc(report.model_id)} · ${esc(report.dataset)} · ${report.examples} × ${report.repeats} · ${c.mean_latency_seconds.toFixed(2)} s per answer${c.mean_cost_usd == null ? '' : ` · $${c.mean_cost_usd.toFixed(6)} per answer`}</p>
    ${cautions.length ? `<ul class="verdict-cautions">${cautions.map(note => `<li>${esc(note)}</li>`).join('')}</ul>` : ''}
  </section>`;
}

function renderReport(r) {
  const c = r.scorecard;
  const rows = [
    ['quality — ' + graderMeaning(c.quality_grader), c.quality, r.declared.quality],
    ['reliability', c.reliability, r.declared.reliability],
    ['contract pass rate', c.contract_pass_rate, null],
    ['stability across repeats', c.stability, null],
    ['mean latency (s)', c.mean_latency_seconds, null],
    ['p95 latency (s)', c.p95_latency_seconds, null],
    ['mean tokens', c.mean_total_tokens, null],
    ['mean cost (USD)', c.mean_cost_usd, null],
    ['total cost (USD)', c.total_cost_usd, null],
    ['mean calls', c.mean_calls, null],
    ['failures', c.failures, null]
  ].map(([label, measured, declared]) => `<tr><td>${esc(label)}</td><td>${measured == null ? 'unknown' : Number(measured).toFixed(6)}</td><td>${declared == null ? '—' : Number(declared).toFixed(3)}</td></tr>`).join('');
  const graders = Object.entries(c.grades).map(([k, v]) => `<tr><td>${esc(k)}${k === c.quality_grader ? ' <span class="pill">headline</span>' : ''}</td><td class="what">${esc(graderMeaning(k))}</td><td>${v.toFixed(3)}</td></tr>`).join('');
  const worst = [...r.runs].sort((a, b) => Math.min(...Object.values(a.grades), 1) - Math.min(...Object.values(b.grades), 1)).slice(0, 3)
    .map(run => `<div class="meta"><strong>${esc(run.example_id)}</strong> ${esc(JSON.stringify(run.grades))} ${esc(run.error || run.schema_errors.join('; '))}</div><pre>${esc(run.output.slice(0, 400))}</pre>`).join('');
  return `${renderVerdict(r)}
    <div class="stage-title">every measurement</div>
    <div class="meta">${esc(r.strategy)} strategy</div>
    <table><thead><tr><th>Metric</th><th>Measured</th><th>Declared</th></tr></thead><tbody>${rows}</tbody></table>
    <div class="stage-title">graders</div>
    <table><thead><tr><th>Grader</th><th class="what">What it measures</th><th>Mean</th></tr></thead><tbody>${graders}</tbody></table>
    ${r.prior != null ? `<div class="warning">Registry prior was ${r.prior.toFixed(2)}; measured quality is ${c.quality.toFixed(2)}. Ranking now uses the measured value.</div>` : ''}
    <div class="stage-title">weakest examples</div>${worst}`;
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
