// The same three steps the buttons run, callable in sequence: Smart run is the
// existing engine driven from one place, not a second implementation of it.
async function createPrompt() {
  const description = $('description').value;
  if (!description.trim()) {
    $('task-error').textContent = 'Enter the task you want the model to do.';
    $('description').focus();
    return false;
  }
  const btn = $('select-btn'); btn.disabled = true;
  $('task-error').textContent = '';
  btn.textContent = 'Creating your prompt…';
  btn.setAttribute('aria-busy', 'true');
  $('results').innerHTML = '<div class="empty">Choosing a method that fits your task…</div>';
  showDetailMessage('prompt', `<div class="empty">${state.inputSource === 'task' ? 'Creating a ready prompt for your task…' : 'Creating a reusable template…'}</div>`);
  try {
    const data = await api('/v1/recommend', { description, model: modelProfile(), engine_model: engineProfile() });
    state.recs = data.recommendations;
    // API responses deliberately redact credentials. Reattach the current
    // evaluation profile only in page memory before caching the normalized task.
    state.task = {...data.task, model:modelProfile()};
    state.report = state.comparison = state.optimization = null;
    state.readinessNotice = null;
    renderRecommendations(data);
    if (data.recommendations.length) await chooseReadyTechnique(data.recommendations);
  } catch (e) {
    $('results').innerHTML = `<div class="error">${esc(e.message)}</div>`;
    showDetailMessage('prompt', '<div class="empty">Your prompt could not be created yet.</div>');
    throw e;
  } finally {
    btn.disabled = false;
    btn.textContent = 'Create my prompt';
    btn.removeAttribute('aria-busy');
  }
  return Boolean(state.chosen);
}

$('select-btn').addEventListener('click', createPrompt);

// The selector scores every eligible technique and explains every rejection;
// showing only the top three threw the second half of that away.
function renderRejected(rejected, open) {
  if (!rejected || !rejected.length) return '';
  const items = rejected.map(item => `
    <div class="rejected-item">
      <div><strong>${esc(item.title)}</strong> <span class="meta">${esc(item.technique_id)}</span></div>
      <ul>${item.reasons.map(r => `<li>${esc(r)}</li>`).join('')}</ul>
      ${methodDisclosure(item.technique_id)}
    </div>`).join('');
  return `<details class="rejected"${open ? ' open' : ''}>
    <summary>${rejected.length} technique${rejected.length === 1 ? '' : 's'} ruled out by your constraints</summary>
    ${items}
  </details>`;
}

function renderRecommendations(data) {
  if (!data.recommendations.length) {
    $('results').innerHTML =
      '<div class="empty">No technique satisfies the hard constraints.</div>'
      + renderRejected(data.rejected, true);
    showDetailMessage('prompt', '<div class="empty">No prompt could be created with the current constraints.</div>');
    return;
  }
  const techniqueCard = (item, i, recommended) => {
    const technique = state.techniqueCatalog.get(item.technique_id);
    const explanation = technique?.description || item.reasons[0] || 'This method matches the task and constraints you described.';
    return `<article class="result${recommended ? ' recommended-result' : ''}" data-technique="${esc(item.technique_id)}">
      ${recommended ? '<div class="recommended-label" id="top-method-label">Recommended method · rank #1</div>' : ''}
      <div class="topline">
        <div>
          ${recommended ? '' : `<div class="rank">#${i + 1}</div>`}
          <h2>${esc(item.title)}</h2>
          <div class="meta">${esc(item.technique_id)} · ${esc(item.family)}</div>
        </div>
      </div>
      <p class="method-explanation">${esc(explanation)}</p>
      <details class="evidence">
        <summary>Technical evidence · score ${Math.round(item.score * 100)}/100 · confidence ${Math.round(item.confidence * 100)}%</summary>
        <div class="meta">Evidence source: <span class="pill ${item.evidence_source === 'measured' ? 'measured' : 'prior'}">${item.evidence_source === 'measured' ? 'measured' : 'prior only'}</span></div>
        <ul>${item.reasons.map(r => `<li>${esc(r)}</li>`).join('')}</ul>
      </details>
      ${methodDisclosure(item.technique_id)}
      <button class="ghost use-btn" type="button" data-technique="${esc(item.technique_id)}">${recommended ? 'Create with recommended technique' : 'Create with this technique'}</button>
    </article>`;
  };
  const [recommended, ...alternatives] = data.recommendations;
  const primary = techniqueCard(recommended, 0, true);
  const otherMethods = alternatives.length ? `<details class="other-methods" open>
    <summary>Alternative techniques — choose one (${alternatives.length})</summary>
    ${alternatives.map((item, i) => techniqueCard(item, i + 1, false)).join('')}
  </details>` : '';
  const warnings = data.warnings.map(w => `<div class="warning">${esc(w)}</div>`).join('');
  $('results').innerHTML = '<div id="readiness-notice"></div>' + primary + otherMethods + warnings + renderRejected(data.rejected, false);
  document.querySelectorAll('.use-btn').forEach(b => b.addEventListener('click', () => {
    state.readinessNotice = null;
    renderReadinessNotice();
    chooseTechnique(b.dataset.technique);
  }));
  refreshActions();
}

// ---- step 2: validate the method, then have the engine author the prompt ---
function needsMissingExamples(p) {
  return (p.notes || []).some(note => {
    const text = String(note);
    return /(demonstration|exemplar|example block)/i.test(text)
      && /(none|no\s|not supplied|missing|absent|empty|without|pass exemplars)/i.test(text);
  });
}

async function compileTechnique(id, inputSource = state.inputSource) {
  const program = await api('/v1/author', {
    task: await taskProfile(),
    description: $('description').value,
    reusable: inputSource === 'reusable',
    response_schema: null,
    technique_id: id,
    variables: {},
    engine_model: engineProfile()
  });
  return { program, inputSource };
}

async function inspectTechnique(id, inputSource = state.inputSource) {
  const userInput = inputSource === 'reusable' ? '{input}' : $('description').value;
  return api('/v1/compile', {
    task: await taskProfile(), user_input: userInput, response_schema: null,
    technique_id: id, variables: {}
  });
}

async function chooseReadyTechnique(recommendations) {
  let topCompiled = null;
  for (let index = 0; index < recommendations.length; index += 1) {
    const item = recommendations[index];
    try {
      const scaffold = await inspectTechnique(item.technique_id);
      if (!needsMissingExamples(scaffold)) {
        if (index > 0) {
          state.readinessNotice = {
            chosenTitle:item.title,
            topTitle:recommendations[0].title
          };
        }
        await chooseTechnique(item.technique_id, true);
        renderReadinessNotice();
        return;
      }
    } catch {
      // Try the next ranked recommendation. A final normal compile below will
      // still surface an actionable API error if none can be prepared.
    }
  }
  await chooseTechnique(recommendations[0].technique_id, true);
  renderReadinessNotice();
}

function renderReadinessNotice() {
  const node = $('readiness-notice');
  const label = $('top-method-label');
  if (!node) return;
  if (!state.readinessNotice) {
    node.innerHTML = '';
    if (label) label.textContent = 'Recommended method · rank #1';
    return;
  }
  if (label) label.textContent = 'Top-ranked method · kept as rank #1';
  node.innerHTML = `<div class="warning readiness-notice"><strong>Ready prompt:</strong> ${esc(state.readinessNotice.chosenTitle)} was used automatically. ${esc(state.readinessNotice.topTitle)} remains #1 by ranking evidence, but its prompt requires demonstrations or exemplars that were not supplied.</div>`;
}

async function chooseTechnique(id, focusReady = false) {
  const compileVersion = ++state.compileVersion;
  state.chosen = id;
  document.querySelectorAll('.result').forEach(el => el.classList.toggle('selected', el.dataset.technique === id));
  document.querySelectorAll('.use-btn').forEach(button => {
    const current = button.dataset.technique === id;
    button.disabled = current;
    button.setAttribute('aria-current', current ? 'true' : 'false');
  });
  refreshActions();
  showDetailMessage('prompt', '<div class="empty">The engine is writing your prompt from the selected method…</div>');
  try {
    const compiled = await compileTechnique(id);
    if (compileVersion !== state.compileVersion) return;
    state.program = compiled.program;
    state.tab = 'prompt';
    updateEstimates();
    updateWorkspaceContext();
    renderDetail();
    if (focusReady) {
      const ready = $('ready-title');
      if (ready) {
        ready.scrollIntoView({ block:'start' });
        ready.focus({ preventScroll:true });
      }
    }
  } catch (e) {
    if (compileVersion !== state.compileVersion) return;
    showDetailMessage('prompt', `<div class="error">${esc(e.message)}</div>`);
  }
}

// The ranking response carries the exact profile it was computed against, so
// compile / benchmark / optimize all run on identical inputs. Evaluation
// settings are handled by the delegated Settings listeners below because that
// tab is rerendered on every visit.
$('description').addEventListener('input', () => {
  state.task = null;
  if ($('description').value.trim()) $('task-error').textContent = '';
});

document.querySelectorAll('input[name="creation-mode"]').forEach(input => {
  input.addEventListener('change', () => {
    if (!input.checked || state.inputSource === input.value) return;
    state.inputSource = input.value;
    $('task-helper').innerHTML = input.value === 'task'
      ? 'We will include your exact words in the finished prompt.'
      : 'The finished template will keep <code>{input}</code> for you to replace each time.';
    ++state.compileVersion;
    if (state.chosen) chooseTechnique(state.chosen);
  });
});

async function taskProfile() {
  if (!state.task) {
    const data = await api('/v1/recommend', { description: $('description').value, model: modelProfile(), engine_model: engineProfile() });
    state.task = {...data.task, model:modelProfile()};
  }
  // Always use the live in-memory profile so benchmark/compare/optimize keep
  // credentials that are intentionally excluded from serialized API responses.
  return {...state.task, model:modelProfile()};
}
