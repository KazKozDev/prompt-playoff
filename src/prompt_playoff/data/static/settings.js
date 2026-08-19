const providerLabels = {
  ollama:'Ollama', openai:'OpenAI', anthropic:'Anthropic', openrouter:'OpenRouter',
  together:'Together', groq:'Groq', fireworks:'Fireworks', deepseek:'DeepSeek',
  custom:'Custom OpenAI-compatible'
};

function providerOptions(selected) {
  return Object.entries(providerLabels).map(([value, label]) =>
    `<option value="${value}"${selected === value ? ' selected' : ''}>${label}</option>`
  ).join('');
}

function checkedCapabilities(setting) {
  const choices = [
    ['structured_output', 'Structured output'], ['tool_calling', 'Tool calling'],
    ['reasoning_control', 'Reasoning control'], ['system_messages', 'System messages']
  ];
  return choices.map(([value, label]) => `<label><input type="checkbox" data-settings-role="evaluation" data-capability="${value}"${setting.capabilities.includes(value) ? ' checked' : ''}> ${label}</label>`).join('');
}

function safeSettingsSummary(role) {
  const setting = state.settings[role];
  if (role === 'engine' && !setting.model_id.trim()) {
    const evaluation = state.settings.evaluation;
    return `${providerLabels[evaluation.provider]} · Use evaluation model (${evaluation.model_id.trim() || 'Not set'})`;
  }
  // A blank card stands for whoever covers for it, named — "blank" on its own
  // reads as "off", and this one is never off, it is delegated.
  if (role === 'judge' && !setting.model_id.trim()) {
    const engine = state.settings.engine.model_id.trim();
    return engine
      ? `${providerLabels[state.settings.engine.provider]} · Use prompt engine (${engine})`
      : 'No judge and no prompt engine';
  }
  return `${providerLabels[setting.provider]} · ${setting.model_id.trim() || 'Not set'}`;
}

// What a blank field means, per card. Only the judge's blank has a rule behind
// it worth stating twice, so only it is spelled out at length.
const roleHints = {
  engine: '<p class="field-hint">Leave blank to use the evaluation model for prompt authoring too.</p>',
  judge: '<p class="field-hint">Leave blank to borrow the prompt engine. Never the evaluation model: a model marking its own answers marks them generously, and pairwise verdicts are the easiest place for that to go unnoticed.</p>',
  similarity: '<p class="field-hint">An embedding model — <code>bge-m3</code>, <code>nomic-embed-text</code> — not a chat model. It writes nothing, so it cannot invent a row, and pinning it keeps the verdict repeatable. Blank leaves exact text matches as the only duplicate rule.</p>'
};

function settingsCard(role, title, eyebrow, description) {
  const setting = state.settings[role];
  const prefix = `settings-${role}`;
  const custom = setting.provider === 'custom';
  const modelPlaceholder = {engine:'Use evaluation model', judge:'Use prompt engine', similarity:'Off — exact matches only'}[role] || 'llama3.2:3b';
  return `<section class="settings-card" aria-labelledby="${prefix}-title">
    <div class="settings-role">${eyebrow}</div>
    <h3 id="${prefix}-title">${title}</h3>
    <p class="settings-description">${description}</p>
    <label for="${prefix}-provider">Provider</label>
    <select id="${prefix}-provider" data-settings-role="${role}" data-field="provider">${providerOptions(setting.provider)}</select>
    <label for="${prefix}-model">Model ID</label>
    <input id="${prefix}-model" data-settings-role="${role}" data-field="model_id" value="${esc(setting.model_id)}" placeholder="${modelPlaceholder}" spellcheck="false"${role === 'evaluation' ? ' required' : ''}${setting.provider === 'ollama' ? ` list="${prefix}-installed"` : ''}>
    ${setting.provider === 'ollama' ? `<datalist id="${prefix}-installed">${installedOptions(role)}</datalist><p class="field-hint" data-installed-hint="${role}">${esc(installedHint(role))}</p>` : ''}
    ${roleHints[role] || ''}
    <label for="${prefix}-base-url">Base URL</label>
    <input id="${prefix}-base-url" data-settings-role="${role}" data-field="base_url" value="${esc(setting.base_url)}" placeholder="Provider default" spellcheck="false"${custom ? ' required' : ''} aria-describedby="${prefix}-url-hint">
    <p class="field-hint" id="${prefix}-url-hint">${custom ? 'Required for a custom OpenAI-compatible provider.' : 'Optional. Leave blank to use the provider default.'}</p>
    <label for="${prefix}-api-key">API key</label>
    <input id="${prefix}-api-key" type="password" data-settings-role="${role}" data-field="api_key" value="" autocomplete="off" spellcheck="false" placeholder="Uses environment key when blank">
    ${role === 'evaluation' ? `<div class="row"><div><label for="${prefix}-class">Model class</label><select id="${prefix}-class" data-settings-role="evaluation" data-field="model_class">${['small','medium','large','reasoning'].map(value => `<option${setting.model_class === value ? ' selected' : ''}>${value}</option>`).join('')}</select></div></div>
      <div class="row"><div><label for="${prefix}-input-price">Input $ / 1M tokens</label><input id="${prefix}-input-price" type="number" min="0" step="0.001" data-settings-role="evaluation" data-field="input_cost_per_million_usd" value="${esc(setting.input_cost_per_million_usd)}" placeholder="Unknown"></div><div><label for="${prefix}-output-price">Output $ / 1M tokens</label><input id="${prefix}-output-price" type="number" min="0" step="0.001" data-settings-role="evaluation" data-field="output_cost_per_million_usd" value="${esc(setting.output_cost_per_million_usd)}" placeholder="Unknown"></div></div>
      <p class="field-hint">Prices are explicit because provider tariffs change. Blank means cost is unknown, never zero.</p>
      <label>Declared capabilities</label><div class="checks">${checkedCapabilities(setting)}</div>` : ''}
    <div class="settings-summary"><span><strong>Active</strong> · <code data-settings-summary="${role}">${esc(safeSettingsSummary(role))}</code></span><span class="key-status${setting.api_key ? ' set' : ''}" data-key-status="${role}">${setting.api_key ? 'API key set' : 'No page key'}</span></div>
  </section>`;
}

// What Ollama actually has, asked of the server rather than typed from memory.
// A model id is only wrong at the first call of a benchmark, which is after the
// run has been set up and paid for.
// Cached per role: the two cards can point at different machines, and a list
// fetched for one of them is not an answer about the other.
async function loadInstalledModels(role) {
  const setting = state.settings[role];
  const installed = state.installed[role];
  const url = setting.base_url.trim();
  if (setting.provider !== 'ollama') return;
  // Also the loop guard: this ends in a re-render, which asks again.
  if (installed.url === url && installed.status !== 'idle') return;
  Object.assign(installed, { status: 'loading', url, error: '' });
  refreshInstalledHints();
  try {
    const query = url ? `?base_url=${encodeURIComponent(url)}` : '';
    installed.models = await api(`/v1/providers/ollama/models${query}`);
    installed.status = 'ready';
  } catch (e) {
    installed.models = [];
    installed.status = 'error';
    installed.error = e.message;
  }
  refreshInstalledHints();
}

function installedOptions(role) {
  return state.installed[role].models.map(item => {
    // A cloud model's entry is a few hundred bytes of manifest, not weights, so
    // anything that would render as "0.0 GB" is a stub and says nothing.
    const gigabytes = item.size_bytes / 1e9;
    const facts = [item.parameter_size, gigabytes >= 0.05 ? `${gigabytes.toFixed(1)} GB` : '']
      .filter(Boolean).join(' · ');
    // The label sits beside the value in the dropdown, so it carries only what
    // the value does not already say.
    return `<option value="${esc(item.model_id)}"${facts ? ` label="${esc(facts)}"` : ''}>`;
  }).join('');
}

function installedHint(role) {
  const { status, models, error } = state.installed[role];
  if (status === 'loading') return 'Asking Ollama which models it has…';
  if (status === 'error') return error;
  if (status === 'ready') return models.length
    ? `${models.length} models on this Ollama — start typing to pick one, or write any id.`
    : 'This Ollama has no models yet. Pull one with `ollama pull llama3.2:3b`.';
  return '';
}

function refreshInstalledHints() {
  document.querySelectorAll('[data-installed-hint]').forEach(node => {
    node.textContent = installedHint(node.dataset.installedHint);
  });
  ['engine', 'judge', 'similarity', 'evaluation'].forEach(role => {
    const list = document.getElementById(`settings-${role}-installed`);
    if (list) list.innerHTML = installedOptions(role);
  });
}

function renderSettings() {
  const profileOptions = state.profiles.map(item => `<option value="${esc(item.id)}">${esc(item.name)} · ${esc(item.profile.provider)}/${esc(item.profile.model_id)}</option>`).join('');
  // Three roles, three cards, in the order the work happens: something writes
  // the prompt, something runs it, something marks the answers. Keeping the
  // third one implicit is what let the model under test mark its own paper.
  return `<div class="settings-grid">
      ${settingsCard('engine', 'Prompt engine', 'Writes the prompt', 'Authors the final prompt from the selected technique, and writes generated dataset rows. It can be a stronger model than the one under evaluation.')}
      ${settingsCard('evaluation', 'Evaluation model', 'Runs the tests', 'Executes prompts and provides the measurements used by benchmark, comparison, and optimization.')}
      ${settingsCard('judge', 'Judge model', 'Marks the answers', 'Decides pairwise comparisons and rubric scores. Keep it out of the family being measured, or the verdict flatters its own lineage.')}
      ${settingsCard('similarity', 'Similarity model', 'Compares the rows', 'Turns generated rows into vectors, so the builder can see rows that are one sentence reworded and say how varied a set really is.')}
    </div>
    <section class="settings-card" style="margin-top:18px">
      <div class="settings-role">Reusable connections</div><h3>Saved evaluation profiles</h3>
      <p class="settings-description">Save endpoint, model, capabilities, and prices. API keys are never written to disk.</p>
      <label for="profile-name">Profile name</label><input id="profile-name" placeholder="Production model">
      <div class="form-actions"><button type="button" class="ghost profile-save">Save current</button><button type="button" class="ghost provider-check">Check connection</button></div>
      <label for="profile-select">Saved profiles</label><select id="profile-select"><option value="">Choose a profile</option>${profileOptions}</select>
      <div class="form-actions"><button type="button" class="ghost profile-load">Load selected</button><button type="button" class="ghost profile-delete">Delete selected</button></div>
      <div class="upload-status" data-profile-status role="status" aria-live="polite"></div>
    </section>
    <aside class="settings-security"><strong>API key safety:</strong> keys stay only in this page's current in-memory state. They are never saved to local or session storage, and are sent only to the local Prompt Playoff backend when it makes provider calls.</aside>`;
}

async function loadProfiles() {
  try { state.profiles = await api('/v1/model-profiles'); }
  catch { state.profiles = []; }
}

function savedProfileSetting(item) {
  const p = item.profile;
  return {provider:p.provider, model_id:p.model_id, base_url:p.base_url || '', api_key:'', model_class:p.model_class, capabilities:p.capabilities || [], input_cost_per_million_usd:p.input_cost_per_million_usd ?? '', output_cost_per_million_usd:p.output_cost_per_million_usd ?? ''};
}

function hydrateSettingsSecrets() {
  ['engine', 'judge', 'similarity', 'evaluation'].forEach(role => {
    const input = document.querySelector(`[data-settings-role="${role}"][data-field="api_key"]`);
    if (input) input.value = state.settings[role].api_key;
  });
}

function refreshSettingsIndicators(role) {
  const setting = state.settings[role];
  const summary = document.querySelector(`[data-settings-summary="${role}"]`);
  const keyStatus = document.querySelector(`[data-key-status="${role}"]`);
  const baseUrl = document.querySelector(`[data-settings-role="${role}"][data-field="base_url"]`);
  const urlHint = document.getElementById(`settings-${role}-url-hint`);
  if (summary) summary.textContent = safeSettingsSummary(role);
  if (keyStatus) {
    keyStatus.textContent = setting.api_key ? 'API key set' : 'No page key';
    keyStatus.classList.toggle('set', Boolean(setting.api_key));
  }
  if (baseUrl) baseUrl.required = setting.provider === 'custom';
  if (urlHint) urlHint.textContent = setting.provider === 'custom'
    ? 'Required for a custom OpenAI-compatible provider.'
    : 'Optional. Leave blank to use the provider default.';
}

function updateSetting(event) {
  const target = event.target.closest('[data-settings-role]');
  if (!target) return;
  const discreteControl = target.tagName === 'SELECT' || target.type === 'checkbox';
  if ((event.type === 'input' && discreteControl) || (event.type === 'change' && !discreteControl)) return;
  const role = target.dataset.settingsRole;
  const setting = state.settings[role];
  if (target.dataset.capability) {
    const capabilities = new Set(setting.capabilities);
    if (target.checked) capabilities.add(target.dataset.capability);
    else capabilities.delete(target.dataset.capability);
    setting.capabilities = [...capabilities];
  } else if (target.dataset.field) {
    setting[target.dataset.field] = target.value;
  }
  if (role === 'evaluation') state.task = null;
  else if (role === 'engine') {
    ++state.compileVersion;
    state.program = null;
    state.provenance = null;
  }
  refreshSettingsIndicators(role);
  updateWorkspaceContext();
  // A blank card's summary names the model standing in for it, so changing that
  // model is a change to the blank card's line too.
  if (role === 'evaluation' && !state.settings.engine.model_id.trim()) refreshSettingsIndicators('engine');
  if (role !== 'judge' && !state.settings.judge.model_id.trim()) refreshSettingsIndicators('judge');
  // Switching provider changes which fields exist, so the card is rebuilt; the
  // rebuild is also what asks the new provider for its models.
  if (target.dataset.field === 'provider') renderDetailPanel('settings');
}

document.addEventListener('input', updateSetting);
document.addEventListener('change', updateSetting);
// A base URL is asked about once the user has finished typing it, not per keystroke.
document.addEventListener('change', event => {
  const field = event.target.closest('[data-settings-role][data-field="base_url"]');
  if (field) loadInstalledModels(field.dataset.settingsRole);
});
