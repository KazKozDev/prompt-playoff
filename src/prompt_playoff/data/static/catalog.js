async function loadTechniqueCatalog() {
  state.catalogStatus = 'loading';
  state.catalogError = '';
  refreshMethodBodies();
  try {
    const [techniques, examples] = await Promise.all([
      api('/v1/techniques'),
      api('/v1/techniques/examples')
    ]);
    state.techniqueCatalog = new Map(techniques.map(item => [item.id, item]));
    state.techniqueExamples = new Map(examples.map(item => [item.technique_id, item]));
    state.catalogStatus = 'ready';
  } catch (e) {
    state.techniqueCatalog = new Map();
    state.techniqueExamples = new Map();
    state.catalogStatus = 'error';
    state.catalogError = e.message;
  }
  refreshMethodBodies();
  if (state.tab === 'techniques') renderDetailPanel('techniques');
  refreshHomeIfVisible();
}

// A grader name means nothing to someone reading their first report, so every
// number is labelled with what it measured. The wording is the server's, shared
// with the CLI, so the two cannot describe the same number differently.
async function loadGraderHelp() {
  try {
    const capabilities = await api('/v1/capabilities');
    state.graderHelp = capabilities.grader_help || {};
  } catch (e) {
    state.graderHelp = {};
  }
  if (state.report) renderDetail();
}

function graderMeaning(name) {
  return name ? (state.graderHelp[name] || name) : 'no grader could score this data';
}

function refreshMethodBodies() {
  document.querySelectorAll('.method-body[data-technique]').forEach(node => {
    node.innerHTML = renderMethodBody(node.dataset.technique);
  });
}

function methodDisclosure(id, catalogView=false) {
  return `<details class="method${catalogView ? ' technique-blueprint' : ''}">
    <summary>${catalogView ? 'Reusable method blueprint' : 'View method blueprint'}</summary>
    <div class="method-body" data-technique="${esc(id)}">${renderMethodBody(id)}</div>
  </details>`;
}

function registerCopy(key, value) {
  state.copyPayloads.set(key, String(value == null ? '' : value));
  return key;
}

function copyButton(key, label, accessibleLabel) {
  return `<button type="button" class="copy-btn" data-copy-key="${esc(key)}" aria-label="${esc(accessibleLabel)}">${esc(label)}</button>`;
}

function renderMethodBody(id) {
  if (state.catalogStatus === 'loading') {
    return '<div class="empty">Loading full method…</div>';
  }
  if (state.catalogStatus === 'error') {
    return `<div class="method-error"><span>Could not load the method catalog: ${esc(state.catalogError)}</span><button type="button" class="retry-catalog">Retry</button></div>`;
  }
  const technique = state.techniqueCatalog.get(id);
  if (!technique) {
    return '<div class="method-error"><span>This technique is missing from the method catalog.</span><button type="button" class="retry-catalog">Reload catalog</button></div>';
  }

  const recipe = technique.recipe || {};
  const blocks = recipe.blocks || [];
  const prefix = `method:${id}`;
  const rawParts = [`SYSTEM\n${recipe.system || ''}`];
  blocks.forEach(block => rawParts.push(`${block.title || block.name || 'BLOCK'} [${block.name || 'unnamed'}; when: ${block.when || 'always'}]\n${block.body || ''}`));
  const fullKey = registerCopy(`${prefix}:all`, rawParts.join('\n\n'));
  const systemKey = registerCopy(`${prefix}:system`, recipe.system || '');
  const templates = `<div class="template-toolbar">
      <span class="template-label">System template</span>
      ${copyButton(systemKey, 'Copy system', `Copy raw system template for ${technique.title}`)}
    </div>
    <pre>${esc(recipe.system || 'none')}</pre>
    ${blocks.map((block, index) => {
      const key = registerCopy(`${prefix}:block:${index}`, block.body || '');
      return `<div class="template-toolbar">
        <span class="template-label">${esc(block.title || 'Untitled block')} · ${esc(block.name || 'unnamed')} · when: ${esc(block.when || 'always')}</span>
        ${copyButton(key, 'Copy block', `Copy raw ${block.title || block.name || 'prompt'} block`)}
      </div><pre>${esc(block.body || '')}</pre>`;
    }).join('')}`;
  const instructionItems = (recipe.instructions || []).length
    ? `<ul class="instruction-list">${recipe.instructions.map(item => `<li>${esc(item)}</li>`).join('')}</ul>`
    : '<p>none</p>';
  const blockIndex = blocks.length
    ? `<div class="block-index">${blocks.map(block => `<div class="block-index-item">
        <strong>${esc(block.title || 'Untitled block')}</strong>
        <code>${esc(block.name || 'unnamed')}</code>
        <span class="condition">when: ${esc(block.when || 'always')}</span>
      </div>`).join('')}</div>`
    : '<p>none</p>';
  const validators = (recipe.validators || []).length
    ? `<ul class="instruction-list">${recipe.validators.map(item => `<li><code>${esc(item)}</code></li>`).join('')}</ul>`
    : '<p>none</p>';
  const execution = technique.execution || {};
  const executionStages = (execution.stages || []).length ? ` · ${execution.stages.length} declared stage(s)` : '';

  return `<section class="method-section">
      <div class="eyebrow">Method blueprint</div>
      <h3>How the method works</h3>
      <p>${esc(technique.description)}</p>
      <div class="method-meta"><code>strategy: ${esc(execution.strategy || 'single')}</code><code>minimum calls: ${esc(technique.min_calls)}</code>${executionStages ? `<code>${esc(executionStages.slice(3))}</code>` : ''}</div>
    </section>
    <section class="method-section">
      <div class="template-toolbar"><div><div class="eyebrow">Reusable recipe</div><h3>Method template</h3></div>${copyButton(fullKey, 'Copy full template', `Copy full raw method template for ${technique.title}`)}</div>
      <p>Placeholders are intentionally unresolved here. They are filled only when this method is compiled for an input.</p>
      ${templates}
      <div class="copy-status" data-copy-status="${esc(prefix)}" role="status" aria-live="polite"></div>
    </section>
    <section class="method-section">
      <div class="eyebrow">Recipe logic</div>
      <h3>Instructions and conditions</h3>
      ${instructionItems}
      ${blockIndex}
    </section>
    <section class="method-section">
      <div class="eyebrow">Guardrails</div>
      <h3>Validation and fallback</h3>
      ${validators}
      <p><strong>Fallback:</strong> ${esc(recipe.fallback || 'none')}</p>
    </section>`;
}

function renderCompiledExample(example) {
  if (!example) return '<div class="method-error">No compiled example is registered for this technique.</div>';
  const program = example.program;
  const stages = (program.stages || []).map((stage, index) => {
    const system = (stage.messages || []).find(message => message.role === 'system')?.content || '';
    const user = (stage.messages || []).find(message => message.role === 'user')?.content || '';
    const key = `catalog-example:${example.technique_id}:${index}`;
    registerCopy(key, `SYSTEM\n${system}\n\nUSER\n${user}`);
    return `<section class="compiled-example-stage">
      <div class="template-toolbar"><div><span class="compiled-example-stage-order">Stage ${index + 1} of ${program.stages.length}</span><div class="compiled-example-stage-title">${esc(stage.stage)}</div></div>${copyButton(key, 'Copy stage', `Copy compiled example stage ${stage.stage}`)}</div>
      <span class="compiled-example-role">SYSTEM</span><pre tabindex="0">${esc(system)}</pre>
      <span class="compiled-example-role">USER</span><pre tabindex="0">${esc(user)}</pre>
      ${(stage.deferred_placeholders || []).length ? `<div class="compiled-example-schema">Runtime placeholders: ${esc(stage.deferred_placeholders.map(name => `{${name}}`).join(', '))}</div>` : ''}
    </section>`;
  }).join('');
  return `<div class="technique-example">
      <div class="technique-example-label">Example · ${esc(example.task_type)}</div>
      <div class="technique-example-key">Task</div><p>${esc(example.user_input)}</p>
      <div class="technique-example-key">Why this one</div><p>${esc(example.why_this_example)}</p>
      <details class="technique-prompt">
        <summary>Compiled prompt <span class="technique-prompt-summary-meta">${esc(plural(program.stages.length, 'stage'))} · ${esc(plural(program.expected_calls, 'call'))} · ${esc(program.strategy)}</span></summary>
        <div class="compiled-example">${stages}${program.response_schema ? `<div class="compiled-example-schema">A native JSON Schema is attached to the compiled call.</div>` : ''}</div>
      </details>
    </div>`;
}

// A registry can be swapped for an external one, so the url here is not
// necessarily ours. Only http(s) becomes a link; anything else is shown as text
// rather than handed to the browser as a scheme.
function paperLink(url, label) {
  const safe = /^https?:\/\//i.test(String(url || ''));
  return safe
    ? `<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${label}</a>`
    : label;
}

function techniqueSource(source) {
  if (!source || !source.paper) {
    // Saying nothing would read as an oversight. These are patterns built here,
    // and the registry already grades them heuristic for exactly that reason.
    return `<div class="technique-source none">No published source — an engineering pattern built for this registry, and graded <code>heuristic</code> because of it.</div>`;
  }
  const arxiv = /arxiv\.org\/abs\/([\w.\/-]+)/i.exec(String(source.url || ''));
  const credit = [source.authors, source.year].filter(Boolean).map(esc).join(', ');
  const label = esc(source.paper) + (credit ? ` <span class="technique-source-credit">— ${credit}</span>` : '');
  const badge = arxiv ? `<span class="technique-source-id">arXiv:${esc(arxiv[1])}</span>` : '';
  return `<div class="technique-source">${badge}${paperLink(source.url, label)}${
    source.note ? `<span class="technique-source-note">${esc(source.note)}</span>` : ''
  }</div>`;
}

function renderTechniqueCatalog() {
  if (state.catalogStatus === 'loading') return '<div class="empty">Loading all techniques…</div>';
  if (state.catalogStatus === 'error') return `<div class="method-error"><span>Could not load the technique catalog: ${esc(state.catalogError)}</span><button type="button" class="retry-catalog">Retry</button></div>`;
  // Sixty-one methods is a catalogue you read, not one you scan. Arriving from
  // the section map means arriving with a kind of task in hand, and then the
  // catalogue is only the methods that are strong at it.
  const only = showingOn('techniques');
  const techniques = [...state.techniqueCatalog.values()]
    .filter(technique => !only || (technique.strong_tasks || []).includes(only))
    .sort((a, b) => a.title.localeCompare(b.title));
  if (!techniques.length) return `<div class="empty">No technique in the registry is strong at ${esc(only)}.</div>`;
  const anchorFor = id => `technique-${String(id).replace(/[^a-zA-Z0-9_-]/g, '-')}`;
  const grouped = new Map();
  techniques.forEach(technique => {
    const family = technique.family || 'Other';
    if (!grouped.has(family)) grouped.set(family, []);
    grouped.get(family).push(technique);
  });
  const index = [...grouped.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([family, items]) => `
    <div class="technique-index-group">
      <div class="technique-index-family">${esc(family)}</div>
      <div class="technique-index-links">${items.map(item => `<a href="#${esc(anchorFor(item.id))}">${esc(item.title)}</a>`).join('')}</div>
    </div>`).join('');
  const articles = techniques.map(technique => {
    const example = state.techniqueExamples.get(technique.id);
    const strategy = technique.execution?.strategy || 'single';
    return `<article class="technique-card" id="${esc(anchorFor(technique.id))}">
      <div class="technique-family">${esc(technique.family)}</div>
      <h3>${esc(technique.title)}</h3>
      <div class="technique-id">${esc(technique.id)}</div>
      <p class="technique-description">${esc(technique.description)}</p>
      <dl class="technique-facts">
        <dt>Best for</dt><dd>${chips((technique.strong_tasks || []).length ? technique.strong_tasks : ['general tasks'])}</dd>
        <dt>Strategy</dt><dd>${chips([strategy, `minimum ${plural(technique.min_calls, 'call')}`])}</dd>
      </dl>
      ${renderCompiledExample(example)}
      ${techniqueSource(technique.source)}
      ${methodDisclosure(technique.id, true)}
      <a class="technique-index-return" href="#technique-index">Back to technique index</a>
    </article>`;
  }).join('');
  return `<div class="techniques-shell">
    <div class="techniques-intro"><div class="meta">${only
      ? `${plural(techniques.length, 'technique')} strong at ${esc(only)}, of ${state.techniqueCatalog.size} in the live registry`
      : `${techniques.length} techniques in the live registry`}</div></div>
    <nav class="technique-index" id="technique-index" aria-labelledby="technique-index-title">
      <h3 id="technique-index-title">Technique index</h3>
      ${index}
    </nav>
    <div class="technique-catalog">${articles}</div>
  </div>`;
}

// ---- step 1: recommend -----------------------------------------------------
