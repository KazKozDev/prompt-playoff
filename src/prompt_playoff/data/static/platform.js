// Product lifecycle screens. They share the existing visual language and API
// helper, but keep their state and event wiring out of the selector workflow.

const q = state.quality;
const statusCard = (label, value, tone='') => `<div class="quality-stat ${tone}"><span>${esc(label)}</span><strong>${esc(value)}</strong></div>`;
const qualityError = () => q.error ? `<div class="error">${esc(q.error)}</div>` : '';
const screenResult = screen => q.results[screen] || null;
const setScreenResult = (screen, value) => { q.results[screen] = value; };
const prerequisite = (message, target, label) => `<div class="prerequisite" role="note"><p>${esc(message)}</p><button type="button" class="ghost" data-prereq-target="${esc(target)}" data-action="resolve-prerequisite">${esc(label)}</button></div>`;

function renderDatasetBuilder() {
  const current = screenResult('dataset-builder');
  const outcome = current?.kind === 'dataset' ? `<div class="quality-result">${esc(current.message)}</div>` : '';
  const projects = q.projects.map(project => {
    const approved = project.examples.filter(item => item.status === 'approved').length;
    const held = project.examples.filter(item => item.split === 'held-out').length;
    const rows = project.examples.slice(0, 8).map(item => `<tr><td><input type="checkbox" data-example-id="${esc(item.example.id)}"></td><td>${esc(item.example.id)}</td><td>${esc(item.mutation || 'baseline')}</td><td><span class="status-chip ${esc(item.status)}">${esc(item.status)}</span></td><td>${esc(item.split)}</td><td>${esc(item.example.input.slice(0, 100))}</td></tr>`).join('');
    return `<details class="quality-project" data-project-id="${esc(project.id)}"><summary>${esc(project.name)} · ${project.examples.length} examples · ${approved} approved · ${held} held-out</summary>
      <div class="quality-actions"><button class="ghost dataset-review" data-action="review-examples">Mark reviewed</button><button class="ghost dataset-approve" data-action="approve-examples">Approve selected</button><button class="dataset-publish" data-action="publish-dataset" ${approved ? '' : 'disabled'}>Publish benchmark dataset</button></div>
      <div class="table-scroll"><table><thead><tr><th></th><th>ID</th><th>Mutation</th><th>Status</th><th>Split</th><th>Input</th></tr></thead><tbody>${rows}</tbody></table></div>
    </details>`;
  }).join('');
  return `${qualityError()}${outcome}<div class="quality-form"><label>Name<input id="builder-name" value="robustness-suite"></label><label>Mode<select id="builder-mode"><option value="edge_cases">Generate edge cases</option><option value="description">From description</option><option value="expand">Expand examples</option><option value="traces">Production traces</option></select></label><label>Examples<input id="builder-count" type="number" min="2" max="100" value="12"></label><label class="mode-option"><input id="builder-llm" type="checkbox"><span><strong>Draft seeds with the prompt engine</strong><small>Model outputs stay unreviewed; the default generator is deterministic.</small></span></label><label>Trace session (optional)<input id="builder-trace-session" placeholder="Langfuse session ID"></label><label>Trace tags (optional)<input id="builder-trace-tags" placeholder="production, support"></label><label class="wide">Task description<textarea id="builder-description" placeholder="Describe real inputs, output contract, and risky cases.">${esc($('description')?.value || '')}</textarea></label><button class="builder-create" data-action="create-dataset-project" data-testid="builder-create">Generate review set</button></div>
    <div class="stage-title">Projects</div>${projects || '<div class="empty">No generated datasets yet.</div>'}`;
}

function renderJudge() {
  const current = screenResult('judge');
  const result = current?.kind === 'judge' ? `<div class="quality-result">${statusCard('Winner', current.winner)}${statusCard('Human gate', 'Pending review', 'warning')}<p>${esc(current.rationale)}</p></div>` : '';
  return `${qualityError()}
    <div class="quality-form"><label class="wide">Input<textarea id="judge-input"></textarea></label><label>Answer A<textarea id="judge-a"></textarea></label><label>Answer B<textarea id="judge-b"></textarea></label><label class="wide">Rubric, one criterion per line<textarea id="judge-rubric">Correctness\nCompleteness\nFollows the requested format</textarea></label><button class="judge-run" data-action="run-blind-judge">Run blind judge</button></div>${result}`;
}

function renderReviews() {
  const cards = q.reviews.map(item => `<article class="review-card" data-review-id="${esc(item.id)}"><div><span class="status-chip ${esc(item.status)}">${esc(item.status)}</span> <span class="meta">${esc(item.kind)} · ${esc(item.created_at)}</span></div><h3>${esc(item.title)}</h3><pre>${esc(JSON.stringify(item.payload, null, 2).slice(0, 1800))}</pre>${item.status === 'pending' ? '<div class="quality-actions"><button class="review-approve" data-action="approve-review">Approve</button><button class="ghost review-reject" data-action="reject-review">Reject</button></div>' : ''}</article>`).join('');
  return `${qualityError()}${cards || '<div class="empty">Review queue is empty.</div>'}`;
}

function experimentOptions() {
  return state.experiments.map(item => `<option value="${esc(item.id)}">v${item.version} · ${esc(item.model_id)} · ${esc(item.dataset)}</option>`).join('');
}

function renderRegressions() {
  const current = screenResult('regressions');
  const result = current?.kind === 'regression' ? `<div class="quality-result">${statusCard('Gate', current.status, current.status === 'passed' ? 'passed' : 'failed')}<pre>${esc(JSON.stringify(current.active, null, 2))}</pre>${current.status === 'failed' ? '<div class="quality-actions"><button class="reg-rerun">Rerun candidate</button><button class="ghost reg-accept">Accept new baseline</button></div>' : ''}</div>` : '';
  const gate = state.experiments.length < 2 ? prerequisite('Record at least two benchmark experiments before analyzing a regression.', 'prompt', 'Open Prompt Studio') : '';
  return `${qualityError()}${gate}<div class="quality-form"><label>Baseline<select id="reg-before">${experimentOptions()}</select></label><label>Candidate<select id="reg-after">${experimentOptions()}</select></label><label>Quality tolerance<input id="reg-quality" type="number" step="0.01" min="0" value="0.01"></label><label>Latency tolerance, seconds<input id="reg-latency" type="number" step="0.1" min="0" value="0.1"></label><button class="reg-run" data-action="analyze-regression" ${state.experiments.length < 2 ? 'disabled' : ''}>Analyze regression</button></div>${result}`;
}

function renderAnalysis() {
  const current = screenResult('analysis');
  const result = current?.kind === 'analysis' ? `<div class="quality-result">${statusCard('Delta', current.delta)}${statusCard('Decision', current.direction, current.significant ? 'passed' : 'warning')}<pre>${esc(JSON.stringify(current, null, 2))}</pre></div>` : '';
  const slices = current?.kind === 'slices' ? `<div class="table-scroll"><table><thead><tr><th>Slice</th><th>Quality</th><th>Runs</th><th>Failures</th></tr></thead><tbody>${current.rows.map(row => `<tr><td>${esc(row.slice)}</td><td>${Number(row.quality).toFixed(3)}</td><td>${row.runs}</td><td>${row.failures}</td></tr>`).join('')}</tbody></table></div>` : '';
  const sliceGate = state.report ? '' : prerequisite('Slice analysis needs a completed benchmark; confidence comparison can run now.', 'prompt', 'Run a benchmark');
  return `${qualityError()}${sliceGate}<div class="quality-form"><label>Baseline scores<textarea id="stats-before" placeholder="0.80, 0.75, 0.90"></textarea></label><label>Candidate scores<textarea id="stats-after" placeholder="0.84, 0.82, 0.91"></textarea></label><button class="stats-run">Compare confidence</button><button class="ghost slices-run" ${state.report ? '' : 'disabled'}>Analyze last benchmark by tags</button></div>${result}${slices}`;
}

function baseBenchmarkPayload() {
  if (!state.chosen || !$('dataset')?.value) throw new Error('Create a prompt and choose a benchmark dataset first.');
  return {technique_id:state.chosen, dataset:$('dataset').value, repeats:Number($('repeats').value || 1)};
}

function renderModelMatrix() {
  const current = screenResult('model-matrix');
  const result = current?.kind === 'matrix' ? `<div class="quality-result">${statusCard('Winner model', current.winner_model)}<div class="table-scroll"><table><thead><tr><th>Model</th><th>Quality</th><th>Latency</th><th>Cost</th></tr></thead><tbody>${current.reports.map(item => `<tr><td>${esc(item.model_id)}</td><td>${item.scorecard.quality.toFixed(3)}</td><td>${item.scorecard.mean_latency_seconds.toFixed(2)}</td><td>${item.scorecard.mean_cost_usd == null ? 'unknown' : item.scorecard.mean_cost_usd.toFixed(6)}</td></tr>`).join('')}</tbody></table></div></div>` : '';
  const gate = state.chosen ? '' : prerequisite('Create and choose a prompt before comparing models.', 'prompt', 'Create a prompt');
  return `${qualityError()}${gate}<label>Model IDs, one per line<textarea id="matrix-models" placeholder="llama3.2:3b\nqwen3:8b"></textarea></label><button class="matrix-run" data-action="run-model-matrix" ${state.chosen ? '' : 'disabled'}>Run matrix</button>${result}`;
}

function renderContextLab() {
  const current = screenResult('context-lab');
  const result = current?.kind === 'context' ? `<div class="quality-result">${statusCard('Best context', current.winner_context)}<pre>${esc(JSON.stringify(current.reports.map(item => ({context:item.context, quality:item.report.scorecard.quality})), null, 2))}</pre></div>` : '';
  const gate = state.chosen ? '' : prerequisite('Create a prompt before comparing context variants.', 'prompt', 'Create a prompt');
  return `${qualityError()}${gate}<div class="quality-form"><label>Variant A name<input id="ctx-a-name" value="full"></label><label>Variant B name<input id="ctx-b-name" value="compressed"></label><label>Context A<textarea id="ctx-a"></textarea></label><label>Context B<textarea id="ctx-b"></textarea></label><button class="context-run" data-action="compare-contexts" ${state.chosen ? '' : 'disabled'}>Compare contexts</button></div>${result}`;
}

function renderReleases() {
  const rows = q.releases.map(item => `<tr data-release-id="${esc(item.id)}"><td>${esc(item.name)} v${item.version}</td><td><span class="status-chip ${esc(item.status)}">${esc(item.status)}</span></td><td>${esc(item.technique_id)}</td><td><code>${esc(item.prompt_hash.slice(0, 10))}</code></td><td><div class="quality-actions">${item.status === 'draft' ? '<button data-release-action="test">Test</button>' : ''}${item.status === 'tested' ? '<button data-release-action="approve">Approve</button>' : ''}${item.status === 'approved' ? '<button data-release-action="release">Release</button>' : ''}${item.status === 'production' ? '<button data-release-action="rollback">Rollback</button><button class="ghost" data-release-action="deprecate">Deprecate</button>' : ''}</div></td></tr>`).join('');
  const gate = state.program ? '' : prerequisite('Author a prompt before registering a release.', 'prompt', 'Author a prompt');
  return `${qualityError()}${gate}<div class="quality-form"><label>Release name<input id="release-name" value="production-prompt"></label><button class="release-create" data-action="create-release" ${state.program ? '' : 'disabled'}>Register current prompt</button></div><div class="table-scroll"><table><thead><tr><th>Release</th><th>Status</th><th>Technique</th><th>Hash</th><th>Action</th></tr></thead><tbody>${rows}</tbody></table></div>`;
}

function renderProduction() {
  const current = screenResult('production');
  const result = current?.kind === 'production' ? `<div class="quality-result"><pre>${esc(JSON.stringify(current.value, null, 2))}</pre></div>` : '';
  return `${qualityError()}<div class="quality-form"><label>Baseline inputs, one per line<textarea id="drift-before"></textarea></label><label>Current inputs, one per line<textarea id="drift-after"></textarea></label><button class="drift-run">Detect drift</button><label class="wide">Agent trajectory JSON<textarea id="trajectory-json" placeholder='[{"tool":"search","success":true},{"tool":"browser","success":false,"recovered":true}]'></textarea></label><label>Required tools, comma separated<input id="trajectory-tools" placeholder="search, browser"></label><button class="ghost trajectory-run">Evaluate trajectory</button><label class="wide">Input for security suite<textarea id="security-input"></textarea></label><button class="ghost security-run">${state.chosen ? 'Run security evaluation' : 'Generate security cases'}</button></div>${result}`;
}

function renderDatasetLibrary() {
  const rows = [...state.datasetSizes.entries()].map(([name, count]) => `<tr><td>${esc(name)}</td><td>${count}</td><td>${name.startsWith('builder:') ? 'Reviewed builder dataset' : name.startsWith('hf:') ? 'Hugging Face' : name.startsWith('uploaded:') ? 'Session upload' : 'Bundled'}</td></tr>`).join('');
  return `<div class="table-scroll"><table><thead><tr><th>Name</th><th>Examples</th><th>Source</th></tr></thead><tbody>${rows}</tbody></table></div>`;
}

function renderPlatformTab(tab) {
  return ({'dataset-builder':renderDatasetBuilder,'judge':renderJudge,'reviews':renderReviews,'regressions':renderRegressions,'analysis':renderAnalysis,'model-matrix':renderModelMatrix,'context-lab':renderContextLab,'releases':renderReleases,'production':renderProduction,'dataset-library':renderDatasetLibrary}[tab] || (() => '<div class="empty">Unknown screen.</div>'))();
}

async function refreshPlatformTab(tab) {
  try {
    if (tab === 'dataset-builder') q.projects = await api('/v1/dataset-projects');
    if (tab === 'reviews') q.reviews = await api('/v1/reviews');
    if (tab === 'releases') q.releases = await api('/v1/releases');
    if (tab === 'regressions' && !state.experiments.length) state.experiments = await api('/v1/experiments');
    if (tab === 'dataset-library') await loadDatasets();
    q.error = '';
  } catch (error) { q.error = error.message; }
  q.loaded.add(tab);
  if (state.tab === tab) renderDetailPanel(tab);
}

function values(text) { return text.split(/[\s,;]+/).filter(Boolean).map(Number).filter(Number.isFinite); }

function wirePlatformTab(tab, panel) {
  panel.querySelectorAll('[data-prereq-target]').forEach(button => button.addEventListener('click', () => selectTab(button.dataset.prereqTarget, {focus:true})));
  panel.querySelector('.builder-create')?.addEventListener('click', async () => qualityAction(tab, async () => { const body={name:panel.querySelector('#builder-name').value, description:panel.querySelector('#builder-description').value, mode:panel.querySelector('#builder-mode').value, count:Number(panel.querySelector('#builder-count').value), trace_session_id:panel.querySelector('#builder-trace-session').value || null, trace_tags:panel.querySelector('#builder-trace-tags').value.split(',').map(x=>x.trim()).filter(Boolean)}; if (panel.querySelector('#builder-llm').checked) body.generator_model=engineProfile(); const project=await api('/v1/dataset-projects', body); setScreenResult(tab, {kind:'dataset', message:`Generated ${project.examples.length} unreviewed examples.`}); }));
  panel.querySelectorAll('.quality-project').forEach(project => {
    const ids = () => [...project.querySelectorAll('[data-example-id]:checked')].map(item => item.dataset.exampleId);
    const review = action => qualityAction(tab, async () => api(`/v1/dataset-projects/${project.dataset.projectId}/review`, {example_ids:ids(), action}));
    project.querySelector('.dataset-review')?.addEventListener('click', () => review('review'));
    project.querySelector('.dataset-approve')?.addEventListener('click', () => review('approve'));
    project.querySelector('.dataset-publish')?.addEventListener('click', () => qualityAction(tab, async () => { const result=await api(`/v1/dataset-projects/${project.dataset.projectId}/publish`, {}); setScreenResult(tab, {kind:'dataset', message:`Published ${result.name} with ${result.examples} approved examples.`}); }));
  });
  panel.querySelector('.judge-run')?.addEventListener('click', () => qualityAction(tab, async () => { const result = await api('/v1/evaluate/pairwise', {input:panel.querySelector('#judge-input').value, answer_a:panel.querySelector('#judge-a').value, answer_b:panel.querySelector('#judge-b').value, rubric:panel.querySelector('#judge-rubric').value.split('\n').filter(Boolean), judge_model:modelProfile()}); setScreenResult(tab, {kind:'judge', ...result}); }));
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
