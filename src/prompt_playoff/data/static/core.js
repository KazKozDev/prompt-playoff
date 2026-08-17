/* --------------------------------------------------------------------------
 * One icon set. Every mark is drawn on the same 24-unit grid with the same
 * stroke, round caps and no fills, so a column of them reads as one family
 * instead of as whatever each font's glyph happened to look like. A section and
 * its screens deliberately share a mark — Examples and Example library.
 * -------------------------------------------------------------------------- */
const ICONS = {
  pencil:'<path d="M12 20h9"/><path d="M16.4 3.6a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/>',
  rows:'<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 9.5h18M3 15h18"/>',
  rowsAdd:'<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 9.5h18M12 12.2v5.4M9.3 14.9h5.4"/>',
  target:'<circle cx="12" cy="12" r="8.5"/><circle cx="12" cy="12" r="3.2"/>',
  rocket:'<path d="M14.6 4.6c3-3 6.4-2.6 6.4-2.6s.4 3.4-2.6 6.4L11 16l-4-4Z"/><path d="M5 15.5c-1.4 1.4-1.8 5.5-1.8 5.5s4.1-.4 5.5-1.8"/><circle cx="15.3" cy="8.7" r="1.3"/>',
  book:'<path d="M4 19.6V6.2A3.2 3.2 0 0 1 7.2 3H20v13.6H7.2A3.2 3.2 0 0 0 4 19.6Z"/><path d="M4 19.6A1.4 1.4 0 0 0 5.4 21H20"/>',
  gauge:'<path d="M3.5 18a9 9 0 1 1 17 0"/><path d="m12 14 4.2-4.6"/>',
  scale:'<path d="M12 4v16M7 20h10M4.5 8h15"/><path d="M4.5 8 2 14h5ZM19.5 8 17 14h5Z"/>',
  sparkle:'<path d="m12 3 1.8 4.9L18.5 9.7l-4.7 1.8L12 16.4l-1.8-4.9-4.7-1.8 4.7-1.8Z"/><path d="m18.6 15.4.7 1.9 1.9.7-1.9.7-.7 1.9-.7-1.9-1.9-.7 1.9-.7Z"/>',
  clock:'<circle cx="12" cy="12" r="8.5"/><path d="M12 7.2V12l3.2 1.9"/>',
  grid:'<rect x="3" y="3" width="7.5" height="7.5" rx="1.6"/><rect x="13.5" y="3" width="7.5" height="7.5" rx="1.6"/><rect x="3" y="13.5" width="7.5" height="7.5" rx="1.6"/><rect x="13.5" y="13.5" width="7.5" height="7.5" rx="1.6"/>',
  columns:'<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M12 4v16"/>',
  diff:'<path d="M8 4.5v13"/><path d="M4.6 7.9 8 4.5l3.4 3.4"/><path d="M16 19.5v-13"/><path d="M12.6 16.1 16 19.5l3.4-3.4"/>',
  checkCircle:'<circle cx="12" cy="12" r="8.5"/><path d="m8.4 12.2 2.6 2.6 4.6-5.2"/>',
  package:'<path d="M20.5 8.3 12 3.6 3.5 8.3v7.4l8.5 4.7 8.5-4.7Z"/><path d="m3.5 8.3 8.5 4.7 8.5-4.7"/><path d="M12 13v7.4"/>',
  pulse:'<path d="M3 12.5h4L9.5 6l4.5 12 2.4-5.5H21"/>',
  play:'<path d="M8.5 5.4v13.2L19 12Z"/>',
  help:'<circle cx="12" cy="12" r="8.5"/><path d="M9.7 9.4a2.4 2.4 0 1 1 2.9 3.1v1.2"/><path d="M12 17.1h.01"/>',
  sliders:'<path d="M4 7.5h9M19 7.5h1M4 16.5h3M13 16.5h7"/><circle cx="16" cy="7.5" r="2.4"/><circle cx="10" cy="16.5" r="2.4"/>',
  wave:'<path d="M3 9.2c2.4-3 5.4-3 7.8 0s5.4 3 7.8 0"/><path d="M3 15.2c2.4-3 5.4-3 7.8 0s5.4 3 7.8 0"/>',
  link:'<path d="m9.6 14.4 4.8-4.8"/><path d="m11.2 6.6 1.6-1.6a4.3 4.3 0 0 1 6.2 6l-1.7 1.8"/><path d="m12.8 17.4-1.6 1.6a4.3 4.3 0 0 1-6.2-6l1.7-1.8"/>',
  shield:'<path d="M12 3.2 20 6v6.1c0 4.4-3.2 7.5-8 8.7-4.8-1.2-8-4.3-8-8.7V6Z"/><path d="M12 8.8v3.6M12 15.8h.01"/>',
  chevron:'<path d="m9.5 5 7 7-7 7"/>',
  chevronLeft:'<path d="m14.5 5-7 7 7 7"/>',
  menu:'<path d="M4 7h16M4 12h16M4 17h16"/>',
  download:'<path d="M12 3v11"/><path d="m8 10.5 4 4 4-4"/><path d="M4 16.5v3A1.5 1.5 0 0 0 5.5 21h13a1.5 1.5 0 0 0 1.5-1.5v-3"/>'
};
const icon = name => `<svg class="i" viewBox="0 0 24 24" aria-hidden="true">${ICONS[name] || ''}</svg>`;
// Which mark belongs to which screen. The sidebar is static HTML, so the marks
// are put in from here rather than repeated sixteen times in the markup.
const screenIcons = {
  prompt:'pencil', 'dataset-library':'rows', 'dataset-hub':'download', 'dataset-builder':'rowsAdd',
  history:'clock', judge:'scale', 'model-matrix':'grid', 'context-lab':'columns', analysis:'target',
  regressions:'diff', reviews:'checkCircle', releases:'package', production:'pulse',
  techniques:'sparkle', logs:'play', settings:'sliders', evaluation:'book', help:'help'
};

const $ = id => document.getElementById(id);
const esc = v => String(v).replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
const plural = (count, word) => `${count} ${word}${Number(count) === 1 ? '' : 's'}`;
const chips = values => values.map(value => `<code>${esc(value)}</code>`).join('');
const state = {
  task:null, recs:[], chosen:null, program:null, tab:'prompt', lastResultTab:'prompt', report:null,
  comparison:null, optimization:null, inputSource:'task',
  techniqueCatalog:new Map(), catalogStatus:'loading', catalogError:'', copyPayloads:new Map(),
  datasetSizes:new Map(), hub:null,
  techniqueExamples:new Map(), graderHelp:{},
  installed:{ engine:{status:'idle', models:[], error:'', url:null}, evaluation:{status:'idle', models:[], error:'', url:null} },
  readinessNotice:null, compileVersion:0, jobs:[], logStatus:'idle', logError:'', logTimer:null,
  openLogs:new Set(), logsInitialized:false, profiles:[], experiments:[], experimentComparison:null,
  quality:{projects:[], reviews:[], releases:[], results:{}, error:'', loading:false, loaded:new Set()},
  settings:{
    engine:{provider:'ollama', model_id:'', base_url:'', api_key:''},
    evaluation:{provider:'ollama', model_id:'llama3.2:3b', base_url:'', api_key:'', model_class:'small', capabilities:['structured_output','system_messages'], input_cost_per_million_usd:'', output_cost_per_million_usd:''}
  }
};

function modelProfile() {
  const setting = state.settings.evaluation;
  const profile = {
    provider: setting.provider,
    model_id: setting.model_id,
    model_class: setting.model_class,
    local: setting.provider === 'ollama',
    context_window: 8192,
    capabilities: [...setting.capabilities]
  };
  if (setting.base_url.trim()) profile.base_url = setting.base_url.trim();
  if (setting.api_key) profile.api_key = setting.api_key;
  if (setting.input_cost_per_million_usd !== '') profile.input_cost_per_million_usd = Number(setting.input_cost_per_million_usd);
  if (setting.output_cost_per_million_usd !== '') profile.output_cost_per_million_usd = Number(setting.output_cost_per_million_usd);
  if (setting.provider === 'custom' && !profile.base_url) throw new Error('Base URL is required for a custom evaluation provider.');
  return profile;
}

// Prompt authoring always uses a model. Blank is an explicit UI choice to use
// the target model itself; the authoring endpoint has no deterministic fallback.
function engineProfile() {
  const setting = state.settings.engine;
  const id = setting.model_id.trim();
  if (!id) return modelProfile();
  const profile = { provider:setting.provider, model_id:id, local:setting.provider === 'ollama' };
  if (setting.base_url.trim()) profile.base_url = setting.base_url.trim();
  if (setting.api_key) profile.api_key = setting.api_key;
  if (setting.provider === 'custom' && !profile.base_url) throw new Error('Base URL is required for a custom prompt engine.');
  return profile;
}

async function api(path, body, method) {
  const res = await fetch(path, body ? {method:method||'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)} : {});
  if (!res.ok) throw new Error(await apiError(res));
  return res.json();
}

async function apiError(res) {
  const text = (await res.text()).slice(0, 2000);
  if (!text) return `${res.status} ${res.statusText}`.trim();
  try {
    const payload = JSON.parse(text);
    const detail = payload.detail ?? payload.error ?? payload.message;
    if (typeof detail === 'string') return detail;
    if (Array.isArray(detail)) return detail.map(item => item.msg || JSON.stringify(item)).join('; ');
    if (detail != null) return JSON.stringify(detail);
  } catch { /* The server returned plain text; show it as-is. */ }
  return text;
}

async function loadBackends() {
  const labels = {
    'native': 'Built in — rewrite, score, keep the winner',
    'dspy:mipro': 'DSPy MIPROv2 — searches wording and examples together',
    'dspy:gepa': 'DSPy GEPA — grows several prompts and keeps the best trade-offs',
    'dspy:bootstrap': 'DSPy BootstrapFewShot — only picks worked examples'
  };
  const options = (ids, dspyOk) => ids.map(id => {
    const ok = !id.startsWith('dspy:') || dspyOk;
    return `<option value="${esc(id)}"${ok ? '' : ' disabled'}>${esc(labels[id] || id)}${ok ? '' : ' (not installed)'}</option>`;
  }).join('');
  try {
    const info = await api('/v1/integrations');
    $('backend').innerHTML = options(info.optimizer_backends, info.dspy.installed);
    if (info.tracing.active && info.tracing.active !== 'none') {
      $('progress').textContent = `tracing → ${info.tracing.active}`;
    }
  } catch {
    // The probe failed, not the backends: keep the same list the server ships
    // and only mark the ones we cannot vouch for, instead of silently
    // collapsing the search down to a single choice.
    $('backend').innerHTML = options(Object.keys(labels), false);
  }
}

// The full recipes live in one shared catalog. Recommendations remain compact
// and are joined to it by id only when the user inspects a method.
