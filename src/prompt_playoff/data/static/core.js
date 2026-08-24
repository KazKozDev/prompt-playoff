/* --------------------------------------------------------------------------
 * One icon set. Every mark is drawn on the same 24-unit grid with the same
 * stroke, round caps and no fills, so a column of them reads as one family
 * instead of as whatever each font's glyph happened to look like. A section and
 * its screens deliberately share a mark — Datasets and Dataset library.
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
  search:'<circle cx="10.8" cy="10.8" r="6.6"/><path d="m16 16 4.2 4.2"/>',
  menu:'<path d="M4 7h16M4 12h16M4 17h16"/>',
  upload:'<path d="M12 15V4"/><path d="m8 7.5 4-4 4 4"/><path d="M4 16.5v3A1.5 1.5 0 0 0 5.5 21h13a1.5 1.5 0 0 0 1.5-1.5v-3"/>',
  download:'<path d="M12 3v11"/><path d="m8 10.5 4 4 4-4"/><path d="M4 16.5v3A1.5 1.5 0 0 0 5.5 21h13a1.5 1.5 0 0 0 1.5-1.5v-3"/>'
};
const icon = name => `<svg class="i" viewBox="0 0 24 24" aria-hidden="true">${ICONS[name] || ''}</svg>`;
// Which mark belongs to which screen. Only the mobile bar carries marks — the
// rail alongside it carries none, because there the name is the whole row — so
// this is the bar's five destinations and nothing else. It used to list every
// screen, including the ones the merge folded away, which read as a promise
// that some other surface was drawing them.
const screenIcons = {
  prompt:'pencil', 'dataset-library':'rows', results:'clock', ship:'package', guides:'book'
};

const $ = id => document.getElementById(id);
const esc = v => String(v).replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
// A row's right answer is JSON as often as it is a string: an extraction set
// holds an object, a classification set a bare label. `String(value)` renders
// the first as "[object Object]", which is the one thing the reader cannot act
// on — the whole point of showing the row is to see what was expected. Objects
// and arrays are shown as the JSON they already are.
const asText = value => (
  value === null || value === undefined ? ''
    : typeof value === 'object' ? JSON.stringify(value, null, 2)
      : String(value)
);
const plural = (count, word) => `${count} ${word}${Number(count) === 1 ? '' : 's'}`;
const chips = values => values.map(value => `<code>${esc(value)}</code>`).join('');
const state = {
  task:null, recs:[], chosen:null, program:null, tab:'prompt', lastResultTab:'prompt', report:null,
  // One step below a screen: which single thing on it you arrived to look at.
  // {tab, value}, or null for the whole screen. It lives in the address bar as
  // `#screen/thing`, so the step can be walked back out of like any other.
  showing:null,
  // The selector's whole answer, not just the ranking it put first: the Method
  // panel draws the rejections and the warnings out of it as well, so this is
  // what that panel is redrawn from when the page comes back from a reload.
  ranking:null,
  comparison:null, optimization:null, inputSource:'task',
  techniqueCatalog:new Map(), catalogStatus:'loading', catalogError:'', copyPayloads:new Map(),
  datasetSizes:new Map(), datasetFacts:new Map(), hub:null,
  // The business catalogue: the categories of work a model is paid to do, the
  // tasks under each, and the public set that measures a task where one honestly
  // does. Fetched once per visit to the library, and null until then.
  // `catalogGroup` is which category is open — one at a time, because every
  // category's tasks and cases at once is a document, not a screen.
  catalog:null, catalogError:'', catalogGroup:null,
  // Library browsing is deliberately transient: search, scope and sort help
  // find a set in this visit, but are not part of a dataset or run contract.
  catalogBrowse:{query:'', scope:'all', availability:'all', sort:'relevance'},
  // The rows of a set, fetched only when the library is opened on that one set.
  // Name → {status, rows, error}.
  datasetRows:new Map(),
  // Which set has been armed for deletion, and what the last deletion did. Both
  // belong to the screen rather than to a set, because only one row at a time
  // can be asking the question.
  pendingDelete:null, datasetNote:'',
  // What a run is set up with. It used to live in the DOM, which meant the
  // controls had to exist on whatever screen you were on; held here, each
  // screen can render the ones it needs and none of the others.
  // Three runs per example, not one. At one, the verdict the run produces goes
  // on to say that nothing in it separates a real difference from the model
  // answering differently on a second try — so the opening value was the one
  // the scorecard itself refuses to stand behind. Pasting your own inputs
  // already raised it to three; arriving at the screen now does the same.
  run:{dataset:'', repeats:3, rounds:2, backend:''}, backendOptions:'',
  // What the last paste of your own inputs did, said on the screen after the
  // block that asked for them has stepped aside.
  ownRowsNote:'',
  techniqueExamples:new Map(), graderHelp:{},
  // The two orderings the scorecard applies to the grades, as the server
  // reports them: which grader becomes the headline quality, and which ones
  // are contract checks and therefore feed reliability.
  qualityPreference:[], contractGraders:new Set(),
  // What each grader's number must not be read as, and which graders score
  // every answer 0 or 1. Both are served rather than written here, so the
  // warning beside a number is the one the grader itself carries.
  graderCaveats:{}, passRateGraders:new Set(),
  installed:{ engine:{status:'idle', models:[], error:'', url:null}, judge:{status:'idle', models:[], error:'', url:null}, similarity:{status:'idle', models:[], error:'', url:null}, evaluation:{status:'idle', models:[], error:'', url:null} },
  // The recorded run that justifies the prompt currently held: what a release
  // registered from it points back to. Null means the prompt as it stands has
  // no number of its own, and a release of it would say only "somebody typed
  // this". Cleared whenever the prompt is rewritten from scratch.
  provenance:null,
  // Why the last attempt to take an optimization winner failed, shown beside the
  // button rather than in place of the screen it is on.
  adoptError:'',
  // What the last technique export did, kept so the message survives the
  // re-render the export itself triggers.
  techniqueNote:'',
  readinessNotice:null, compileVersion:0, jobs:[], logStatus:'idle', logError:'', logTimer:null,
  openLogs:new Set(), selectedJobId:null, logsInitialized:false, profiles:[], experiments:[], experimentComparison:null,
  // Saved cases organize prompt lineage without making assignment mandatory.
  // Empty string is the deliberate Unassigned choice; the history uses its own
  // sentinel because case ids themselves are opaque strings.
  businessCases:[], businessCasesLoading:true, businessCasesError:'', businessCaseId:'',
  historyCaseId:null, historyPromptId:null, historyDataset:null, historyTechnique:null,
  historyCompareContext:null, historyError:'',
  quality:{projects:[], reviews:[], releases:[], gates:{}, results:{}, error:'', loading:false, loaded:new Set(),
    // The builder form lives here rather than in the DOM: the cost of the
    // settings is quoted before the button is pressed, so a keystroke has to
    // re-render the quote, and a re-render would otherwise wipe the fields.
    build:{name:'robustness-suite', mode:'edge_cases', count:12, llm:false, candidates:4, answers:false, personas:true, session:'', tags:'', filter:'all'}},
  settings:{
    engine:{provider:'ollama', model_id:'', base_url:'', api_key:''},
    // Scores answers against each other. Blank falls back to the engine and
    // never to the model under evaluation — see judgeProfile.
    judge:{provider:'ollama', model_id:'', base_url:'', api_key:''},
    // Turns generated rows into vectors so near-copies can be spotted. Blank is
    // off: the exact-match rule stays the only duplicate rule.
    similarity:{provider:'ollama', model_id:'', base_url:'', api_key:''},
    evaluation:{provider:'ollama', model_id:'llama3.2:3b', base_url:'', api_key:'', model_class:'small', capabilities:['structured_output','system_messages'], input_cost_per_million_usd:'', output_cost_per_million_usd:''}
  }
};

/* --------------------------------------------------------------------------
 * The prompt outlives the tab.
 *
 * The compiled prompt was held in page memory and nowhere else. A reload — or a
 * closed tab, or a crash — took the only copy with it: the screen that writes
 * it came back saying "Nothing here yet", and no other screen could produce the
 * text, because the run history stores a preview and a fingerprint and the
 * release table stores a fingerprint. So the prompt was unopenable at every
 * step of the workflow, including the one step that had just written it.
 *
 * Only what the screens redraw from is written down. The task profile is not:
 * it carries the evaluation model, and that carries an API key, which has no
 * business being on disk. It is re-derived from the description on the next run.
 * -------------------------------------------------------------------------- */
const DRAFT_KEY = 'pp-draft';
const DRAFT_VERSION = 1;

function rememberDraft() {
  const description = $('description')?.value || '';
  if (!state.program && !state.chosen && !description.trim()) return forgetDraft();
  try {
    localStorage.setItem(DRAFT_KEY, JSON.stringify({
      version:DRAFT_VERSION, description, inputSource:state.inputSource, chosen:state.chosen,
      program:state.program, ranking:state.ranking, provenance:state.provenance,
      businessCaseId:state.businessCaseId
    }));
  } catch { /* storage can be denied or full; the page still works */ }
}

function forgetDraft() {
  try { localStorage.removeItem(DRAFT_KEY); } catch { /* nothing to undo */ }
}

// Read back before the first render, so the screens draw the restored prompt
// rather than drawing "nothing yet" and being corrected a frame later.
function restoreDraft() {
  let draft = null;
  try { draft = JSON.parse(localStorage.getItem(DRAFT_KEY) || 'null'); }
  catch { draft = null; }
  if (!draft || draft.version !== DRAFT_VERSION) return;
  if ($('description')) $('description').value = draft.description || '';
  state.inputSource = draft.inputSource === 'reusable' ? 'reusable' : 'task';
  const mode = document.querySelector(`input[name="creation-mode"][value="${state.inputSource}"]`);
  if (mode) mode.checked = true;
  if ($('task-helper')) $('task-helper').innerHTML = CREATION_HELP[state.inputSource];
  state.chosen = draft.chosen || null;
  state.program = draft.program || null;
  state.provenance = draft.provenance || null;
  state.businessCaseId = draft.businessCaseId || '';
  state.ranking = draft.ranking || null;
  state.recs = state.ranking?.recommendations || [];
  if (state.ranking) {
    renderRecommendations(state.ranking);
    if (state.chosen) markChosenTechnique(state.chosen);
  }
}

// What this screen has been narrowed to, or null. Every screen that can be
// narrowed asks this one question rather than reading the address bar itself.
const showingOn = tab => (state.showing && state.showing.tab === tab ? state.showing.value : null);

// One name for one part of a compiled prompt: the map that draws the prompt to
// scale and the screen that highlights a part of it have to agree on what that
// part is called, or clicking a circle would land on nothing.
function promptPartName(program, stageIndex, message) {
  const stage = program.stages[stageIndex] || {};
  const role = String(message.role || 'message');
  return program.stages.length > 1 ? `${stage.stage || `stage ${stageIndex + 1}`} · ${role}` : role;
}

/* A prompt read out as a flat list of messages, each under the name the rest of
 * the app calls that part by. Two screens show a whole prompt — the one
 * measuring it and the one holding the copy a release froze — and neither walks
 * the stages itself, or the same prompt would be drawn two ways on two screens.
 *
 * The three shapes are the three the server's manifest reader knows, and for the
 * same reason: a release freezes whatever payload registered it, and one frozen
 * by an older client or by the API directly is still a prompt somebody has to be
 * able to read. Anything else returns nothing, and the caller says so rather
 * than dressing an unknown object up as a prompt. */
function promptMessages(program) {
  const stages = program?.stages;
  if (Array.isArray(stages) && stages.length) {
    const multi = stages.length > 1;
    return stages.flatMap((stage, stageIndex) => (stage.messages || []).map(message => {
      const role = String(message.role || 'message').toUpperCase();
      return {
        head: multi ? `${stage.stage || `stage ${stageIndex + 1}`} · ${role}` : role,
        content: message.content || '',
        demo: Boolean(message.demo)
      };
    }));
  }
  for (const key of ['text', 'prompt', 'content']) {
    const value = program?.[key];
    if (typeof value === 'string' && value.trim()) return [{head:'PROMPT', content:value, demo:false}];
  }
  const messages = program?.messages;
  if (Array.isArray(messages)) {
    return messages.filter(message => message && typeof message === 'object').map(message => ({
      head: String(message.role || 'message').toUpperCase(),
      content: message.content || '',
      demo: Boolean(message.demo)
    }));
  }
  return [];
}

// The same prompt as plain text, which is what a copy button hands over.
const promptPlainText = program =>
  promptMessages(program).map(part => `${part.head}\n${part.content}`).join('\n\n');

// One message of it, drawn the same way wherever a whole prompt is shown.
const promptPartBlock = part => `<div class="prompt-part">
    <span class="prompt-role">${esc(part.head)}</span>${part.demo ? '<span class="demo-tag">worked example</span>' : ''}
    <pre>${esc(part.content)}</pre>
  </div>`;

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

// The model named on one of the side cards, or null when that card is blank.
// Blank is a real answer here — what to do about it differs per role, and each
// caller answers that for itself rather than being handed a substitute.
const ROLE_LABELS = {engine:'prompt engine', judge:'judge', similarity:'similarity model'};
function roleProfile(role) {
  const setting = state.settings[role];
  const id = setting.model_id.trim();
  if (!id) return null;
  const profile = { provider:setting.provider, model_id:id, local:setting.provider === 'ollama' };
  if (setting.base_url.trim()) profile.base_url = setting.base_url.trim();
  if (setting.api_key) profile.api_key = setting.api_key;
  if (setting.provider === 'custom' && !profile.base_url) throw new Error(`Base URL is required for a custom ${ROLE_LABELS[role]}.`);
  return profile;
}

// Prompt authoring always uses a model. Blank is an explicit UI choice to use
// the target model itself; the authoring endpoint has no deterministic fallback.
function engineProfile() {
  return roleProfile('engine') || modelProfile();
}

/* Who scores answers.
 *
 * This one never falls back to the model under evaluation: a model asked to
 * mark its own answers marks them well, and a verdict bought that way is worth
 * less than no verdict. Blank borrows the engine, which is a different model by
 * intent; blank on both is null, and the judge screen says so rather than
 * quietly handing the whistle to a player.
 */
function judgeProfile() {
  return roleProfile('judge') || roleProfile('engine');
}

/* Which model compares rows with each other, or null.
 *
 * No fallback of any kind: this one writes nothing, so standing another model
 * in for it would not degrade the check, it would answer a different question.
 * Blank means the check does not run, and the builder says so.
 */
function similarityProfile() {
  return roleProfile('similarity');
}

// A method with no body is a real request — DELETE mostly — so it is the method
// that decides how this is sent, not whether a body happened to be passed.
async function api(path, body, method) {
  const verb = method || (body ? 'POST' : 'GET');
  const init = verb === 'GET' ? undefined : body
    ? {method:verb, headers:{'Content-Type':'application/json'}, body:JSON.stringify(body)}
    : {method:verb};
  const res = await fetch(path, init);
  if (!res.ok) {
    const failure = await apiFailure(res);
    // The message is what a person reads; the code is what a screen can act on.
    // A refusal that a screen is allowed to offer to override has to be told
    // apart from a typo in a field, and matching on the wording would break the
    // moment the wording improved.
    const error = new Error(failure.message);
    error.status = res.status;
    error.code = failure.code;
    error.detail = failure.detail;
    throw error;
  }
  return res.json();
}

async function apiFailure(res) {
  const text = (await res.text()).slice(0, 2000);
  let detail = null;
  try { detail = JSON.parse(text).detail ?? null; } catch { /* plain text below */ }
  const message = detail && typeof detail === 'object' && !Array.isArray(detail) && detail.message
    ? detail.message
    : errorText(text, res);
  return {message, code: detail?.code || null, detail};
}

function errorText(text, res) {
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

// For a caller that reads the response itself and only wants the sentence.
async function apiError(res) {
  return errorText((await res.text()).slice(0, 2000), res);
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
    state.backendOptions = options(info.optimizer_backends, info.dspy.installed);
    state.run.backend = state.run.backend || info.optimizer_backends[0] || '';
    if (info.tracing.active && info.tracing.active !== 'none') state.tracing = info.tracing.active;
  } catch {
    // The probe failed, not the backends: keep the same list the server ships
    // and only mark the ones we cannot vouch for, instead of silently
    // collapsing the search down to a single choice.
    state.backendOptions = options(Object.keys(labels), false);
    state.run.backend = state.run.backend || 'native';
  }
  if (typeof refreshRunSetup === 'function') refreshRunSetup();
}

// The full recipes live in one shared catalog. Recommendations remain compact
// and are joined to it by id only when the user inspects a method.
