// The prompt and the three measurements taken on it: they share the composer
// column, which every other screen hides.
const resultTabs = ['prompt', 'report', 'comparison', 'optimization'];
const platformTabs = ['dataset-add', 'dataset-library', 'results', 'test-lab', 'ship', 'judge', 'reviews'];
const sectionTabs = ['s-prompt', 's-examples', 's-check', 's-ship', 's-reference'];
// Screens whose body is already several surfaces beside one another: the panel
// they sit in carries no plate of its own, or the parts would read as one.
const unplatedScreens = new Set(['dataset-add', 'dataset-library', 'results', 'test-lab', 'ship', 'guides',
  'techniques', 'judge', 'reviews', 'logs']);
const detailPanels = ['home', ...sectionTabs, 'prompt', 'report', 'comparison', 'optimization',
  'techniques', 'logs', 'settings', 'guides', ...platformTabs];
const GUIDE_TOC = {
  en: { label:'On this page', title:'Contents', items:[
    ['#split','1. The core distinction'], ['#test','2. A simple test'], ['#prompt','3. When prompting wins'],
    ['#finetune','4. When fine-tuning wins'], ['#knowledge','5. Knowledge vs behavior'], ['#signals','6. Five strong signals'],
    ['#badidea','7. When not to fine-tune'], ['#longcontext','8. Long-context ICL'], ['#ladder','9. Production ladder'],
    ['#formula','10. Decision formula'], ['#references','References']
  ]},
  ru: { label:'На этой странице', title:'Содержание', items:[
    ['#split','1. Главное различие'], ['#test','2. Простой тест'], ['#prompt','3. Когда промптинг выигрывает'],
    ['#finetune','4. Когда файн-тюнинг выигрывает'], ['#knowledge','5. Знания vs поведение'], ['#signals','6. Пять сильных сигналов'],
    ['#badidea','7. Когда не надо файн-тюнить'], ['#longcontext','8. Long-context ICL'], ['#ladder','9. Продакшен-лестница'],
    ['#formula','10. Формула решения'], ['#references','Ссылки']
  ]}
};
// One name per screen, written down once. The sidebar link, the heading in the
// context bar and the browser tab all read from here, so a screen can never be
// called three different things on the way to itself. Names in the navigation
// are nouns; the expert term and the question a newcomer would ask both live in
// the third entry, the one line that says what the screen is for. Screens no
// longer carry a heading of their own — the context bar is already showing it.
const screenMeta = {
  prompt:['Prompt Studio', 'Prompt text'], report:['Prompt Studio', 'Measurement'], comparison:['Prompt Studio', 'Technique comparison'], optimization:['Prompt Studio', 'Optimization'],
  'dataset-library':['Datasets', 'Dataset library', 'All the example sets on this server: ready-made ones grouped by the kind of work, then the sets you brought yourself. This is where you pick what a score will be computed against.'],
  'dataset-add':['Datasets', 'Add dataset', 'Upload your own rows, import a public set, or generate examples for the gaps you still need to test.'],
  'dataset-builder':['Datasets', 'Build datasets', 'Generate example rows from your task description, or around the ones the last run got wrong. Use it when you have nothing of your own and nothing to import. You approve every row before it counts.'],
  'dataset-bundled':['Datasets', 'Shipped with the tool', 'The benchmark sets that ship inside the package. They are what the tool tests itself with, so use them to try the workflow out — a good score here describes the tool, not your prompt.'],
  history:['Evaluation', 'Results', 'Every run this server has finished, newest first, with the numbers it produced. Come here to compare two versions or export the history. Prompts and raw answers are not stored.'],
  results:['Evaluation', 'Results', 'Read the run history, compare versions, check whether a difference is larger than the noise in the examples, and gate a new run against the last one.'],
  judge:['Evaluation', 'Answer judging', 'Have a model mark answers against a rubric without knowing which is which — a whole run against its reference answers, or one pair by hand. Use it for work no grader can score, like tone or clarity. A judged number never becomes a benchmark score or a CI gate: every verdict goes to Reviews for a person to confirm.'],
  'model-matrix':['Evaluation', 'Model matrix', 'Run the same prompt and the same examples on several models. It tells you whether the prompt works anywhere else, or only on the model you wrote it for.'],
  'context-lab':['Evaluation', 'Context lab', 'Run the same prompt with different context in front of it — a document, a summary, retrieval results. It tells you whether the extra text is worth the tokens it costs.'],
  analysis:['Evaluation', 'Significance', 'Check whether a difference between two runs is real or just noise. Paste the per-example scores and you get a confidence interval, plus the score broken down by tag.'],
  'test-lab':['Evaluation', 'Test lab', 'Challenge the same prompt by changing one condition at a time: the model that runs it or the context placed in front of it.'],
  regressions:['Evaluation', 'Regressions', 'Compare two recorded runs and fail the newer one if quality dropped, or latency rose, by more than you allow. Run it before shipping a change.'],
  // Releases were taken out of this queue and must stay out of the sentence
  // that describes it: the screen's own panel explains at length that they do
  // not land here, and the lead above it went on promising they would.
  reviews:['Production', 'Reviews', 'The queue of decisions a model asked a person to make: generated rows, judge verdicts and breached gates. Nothing in it proceeds until you answer. Registering a release does not land here.'],
  releases:['Production', 'Releases', 'A register of prompt versions, moved by hand from draft to tested, approved and production. Use it to freeze the exact text you shipped, and to roll back to the previous one.'],
  ship:['Production', 'Ship', 'Freeze a prompt against the run that measured it, export the manifest and the check block your repository enforces, and spot-check what production is really sending.'],
  // Named for what it does rather than for what the word "monitoring" promises:
  // nothing here is connected to live traffic. Each of the three checks works on
  // material you paste in, and the screen says so before it offers a box.
  production:['Production', 'Spot checks', 'Three checks you run by hand on text you paste in: whether real inputs still look like your examples, whether an agent called the tools it should, and whether the prompt holds when the input attacks it. It does not watch live traffic.'],
  techniques:['Docs', 'Techniques', 'The catalogue of every method in the registry, each with a real prompt compiled for a task that suits it. Read it to see what the selector chose from, or to pick a method yourself.'],
  logs:['System', 'Jobs & logs', 'What is running right now and what each finished job did, step by step. Come here when a run is slow or failed. The numbers those runs produced are in Evaluation → Results.'],
  settings:['System', 'Models & keys', 'Where you set the three models and their keys. The prompt engine writes prompts and generated rows, the evaluation model runs them and produces every number you see, and the judge compares two answers — it must never be the model being judged.'],
  'llm-or-not':['Docs', 'Do you need an LLM?', 'Eight solution classes, from a regular expression to a person, and the checks that decide which one a task needs. The question before the prompt.'],
  evaluation:['Docs', 'Evaluation guide'], help:['Docs', 'User Guide'], 'prompt-vs-finetuning':['Docs', 'Prompt vs Fine-Tuning', 'When to fine-tune a model — and when prompting is enough. A research-backed guide to choosing between prompting, few-shot ICL, RAG, fine-tuning, distillation, and tools/agents.'],
  guides:['Docs', 'Guides', 'Read the end-to-end workflow, the evaluation contract, and the two decision boundaries: whether the task needs a model at all, and whether it needs fine-tuning.'],
  home:['Workspace', 'Prompt Playoff', 'Five sections, in the order a prompt goes through them, and one button that runs the whole path for you. Everything here runs on your machine.'],
  's-prompt':['Prompt Studio', 'Prompt Studio', 'The prompt itself and everything measured on it: one run over your examples, the techniques scored side by side, and the search for better wording. Start here.'],
  's-examples':['Datasets', 'Datasets', 'The example rows every score is computed against. Bring your own, import public ones, or generate them — a score describes your task only if these look like your real inputs.'],
  's-check':['Evaluation', 'Evaluation', 'Ways to test whether a number holds up: on other models, with other context, against another answer, or against statistics. Use this before you trust a result. One plain measurement lives in Prompt Studio.'],
  's-ship':['Production', 'Production', 'How a prompt measured here becomes something outside here: frozen against the run behind it, exported as files your repository holds and CI enforces, and spot-checked against what production is really sending.'],
  's-reference':['Docs', 'Docs', 'Guides, evaluation methodology, and architectural decisions. Everything you need to understand prompt engineering and model trade-offs.']
};

function displayMeta(tab) {
  if (tab === 'results' && screenModes[tab] === 'regressions') return screenMeta.regressions;
  return screenMeta[tab] || screenMeta.home;
}

// The one action a screen offers about itself lives in the same corner on every
// screen, instead of somewhere inside its body.
const screenActions = {
  // The file the server writes is the whole history, so when the screen is
  // showing one set the link says which of the two it is about to hand over.
  results: () => state.experiments.length
    ? '<a class="export-link" href="/v1/experiments.csv" download="prompt-playoff-history.csv">Download all runs CSV</a>'
    : '',
  logs: () => '<button type="button" class="ghost log-refresh">Refresh</button>'
};

/* A screen narrowed to one thing has to say so, in one place, on every screen
 * that can be narrowed — otherwise a table showing three of eleven runs is
 * simply a table that lost eight runs. The band says what is being shown and
 * carries the way back out; the verb differs because a prompt cannot be
 * filtered down to one of its own messages without lying about what a prompt
 * is, so there the part is picked out instead of the rest being removed. */
const showingVerbs = {prompt:'Highlighting'};

function showingBand(tab) {
  const value = showingOn(tab);
  if (!value) return '';
  return `<div class="showing-band" data-testid="showing-band">
      <span>${esc(showingVerbs[tab] || 'Showing')} <b>${esc(value)}</b></span>
      <button type="button" class="ghost" data-action="show-everything">Show everything</button>
    </div>`;
}

function screenShell(tab, body) {
  const [, title, lead] = displayMeta(tab);
  const actions = screenActions[tab]?.() || '';
  const gate = modelGatedScreens.has(tab) ? MODEL_GATE : '';
  // The name belongs to the screen, not to the chrome: the bar carries the path
  // you took, the screen carries what it is.
  const head = `<div class="screen-head">
      <div><h1 class="screen-title">${esc(title)}</h1>${lead ? `<p class="screen-lead">${esc(lead)}</p>` : ''}</div>
      ${actions ? `<div class="screen-actions">${actions}</div>` : ''}
    </div>`;
  const setup = typeof renderRunSetup === 'function' ? renderRunSetup(tab) : '';
  // The prompt these screens work on is not part of the screen: it is the third
  // zone of the workspace, held in the left column where the composer that
  // wrote it stands. So one place to look for the prompt, on all four screens
  // of this section.
  return `${head}${gate}${showingBand(tab)}${setup}${body}`;
}

/* One compact mode rail teaches the consolidated information architecture on
 * every parent screen. The panels stay mounted, so text entered into a form and
 * client-side results survive a mode switch. */
const MODE_SPECS = {
  'dataset-library': {
    label:'Library mode', default:'library', modes:[
      ['library', 'Library', 'Browse every set available for your own measurements.'],
      ['built-in', 'Built-in benchmarks', 'Inspect the fixed reference benchmarks shipped with this tool.']
    ]
  },
  'dataset-add': {
    label:'Dataset source', default:'upload', modes:[
      ['upload', 'Upload file', 'Your own rows are the closest measure of your task.'],
      ['hugging-face', 'Hugging Face', 'Import public rows; this mode needs an internet connection.'],
      ['generate', 'Generate', 'Create candidate rows from your task and approve each one before use.']
    ]
  },
  results: {
    label:'Results mode', default:'history', modes:[
      ['history', 'Run history', 'Filter, compare, inspect, and export recorded runs.'],
      ['significance', 'Significance', 'Test whether a measured difference is larger than sampling noise.'],
      ['regressions', 'Regression gate', 'Compare two recorded runs against explicit quality and latency tolerances.']
    ]
  },
  'test-lab': {
    label:'Test lab mode', default:'models', modes:[
      ['models', 'Models', 'Run the same prompt and examples across several models.'],
      ['context', 'Context', 'Run the same prompt with different context in front of it.']
    ]
  },
  ship: {
    label:'Ship mode', default:'releases', modes:[
      ['releases', 'Releases', 'Freeze a prompt against the run that measured it, and export it to your repository.'],
      ['spot-checks', 'Spot checks', 'Run the three by-hand checks on text you paste in.']
    ]
  },
  guides: {
    label:'Guide', default:'user', modes:[
      ['user', 'User guide', 'Follow the complete Prompt Playoff workflow from prompt to release.'],
      ['evaluation', 'Evaluation', 'See where every number comes from and when to trust it.'],
      ['llm-or-not', 'Do you need an LLM?', 'Pick the lowest solution class that solves the task, from a rule to a person.'],
      ['fine-tuning', 'Prompt vs Fine-Tuning', 'Choose prompting, retrieval, fine-tuning, distillation, or agents.']
    ]
  }
};
const screenModes = Object.fromEntries(Object.entries(MODE_SPECS).map(([tab, spec]) => [tab, spec.default]));

const modeSpec = (tab, mode) => MODE_SPECS[tab]?.modes.find(item => item[0] === mode);
const normalizedMode = (tab, mode) => modeSpec(tab, mode) ? mode : MODE_SPECS[tab]?.default;

function parentForLegacyTab(tab) {
  return ({
    'dataset-builder':'dataset-add', 'dataset-bundled':'dataset-library', history:'results', analysis:'results',
    regressions:'results', 'model-matrix':'test-lab', 'context-lab':'test-lab',
    releases:'ship', 'release-center':'ship', production:'ship',
    help:'guides', evaluation:'guides', 'prompt-vs-finetuning':'guides', 'llm-or-not':'guides'
  })[tab] || tab;
}

function legacyMode(tab) {
  return ({
    'dataset-upload':'upload', 'dataset-hub':'hugging-face', 'dataset-builder':'generate',
    'dataset-bundled':'built-in', history:'history', analysis:'significance', regressions:'regressions',
    'model-matrix':'models', 'context-lab':'context',
    releases:'releases', 'release-center':'releases', production:'spot-checks',
    help:'user', evaluation:'evaluation', 'prompt-vs-finetuning':'fine-tuning', 'llm-or-not':'llm-or-not'
  })[tab] || null;
}

function canonicalModePath(tab, mode, showing=null) {
  const omitDefault = tab === 'dataset-library' || tab === 'dataset-add';
  const segment = omitDefault && mode === MODE_SPECS[tab].default ? '' : `/${mode}`;
  return `#${tab}${segment}${showing ? `/${encodeURIComponent(showing)}` : ''}`;
}

function renderModeRail(tab, bodies) {
  const spec = MODE_SPECS[tab];
  const selected = normalizedMode(tab, screenModes[tab]);
  const buttons = spec.modes.map(([mode, label]) => `<button type="button" class="mode-rail-option"
      id="${tab}-mode-${mode}" role="tab" aria-selected="${mode === selected}"
      aria-controls="${tab}-panel-${mode}" tabindex="${mode === selected ? '0' : '-1'}"
      data-mode-tab="${tab}" data-mode="${mode}">${esc(label)}</button>`).join('');
  const panels = spec.modes.map(([mode]) => `<section class="mode-panel" id="${tab}-panel-${mode}"
      role="tabpanel" aria-labelledby="${tab}-mode-${mode}" data-mode-panel="${mode}"${mode === selected ? '' : ' hidden'}>
      ${bodies[mode] || ''}</section>`).join('');
  return `<div class="mode-rail">
      <div class="mode-rail-intro"><strong>${esc(spec.label)}</strong><span data-mode-note>${esc(modeSpec(tab, selected)[2])}</span></div>
      <div class="mode-rail-switch" role="tablist" aria-label="${esc(spec.label)}">${buttons}</div>
    </div>${panels}`;
}

function renderGuideMode(mode) {
  const pages = {
    user:['/help', 'User Guide'], evaluation:['/evaluation', 'Evaluation Guide'],
    'llm-or-not':['/llm-or-not', 'Do you need an LLM?'],
    'fine-tuning':['/prompt-vs-finetuning', 'Prompt vs Fine-Tuning']
  };
  const [src, title] = pages[mode];
  const toc = mode === 'fine-tuning' ? renderGuideToc('en')
    : '<nav class="toc guide-toc" data-guide-toc aria-label="On this page"><strong>Contents</strong></nav>';
  return `<div class="guide-split">${toc}<iframe class="doc-frame" src="${src}?embed" title="${title}"></iframe></div>`;
}

function renderConsolidatedScreen(tab) {
  if (tab === 'dataset-library') return renderModeRail(tab, {library:renderDatasetLibrary(), 'built-in':renderDatasetBundled()});
  if (tab === 'dataset-add') return renderModeRail(tab, {upload:renderDatasetUpload(), 'hugging-face':renderDatasetHub(), generate:renderDatasetBuilder()});
  if (tab === 'results') return renderModeRail(tab, {history:renderHistory(), significance:renderAnalysis(), regressions:renderRegressions()});
  if (tab === 'test-lab') return renderModeRail(tab, {models:renderModelMatrix(), context:renderContextLab()});
  if (tab === 'ship') return renderModeRail(tab, {releases:renderReleases(), 'spot-checks':renderProduction()});
  if (tab === 'guides') return renderModeRail(tab, {
    user:renderGuideMode('user'), evaluation:renderGuideMode('evaluation'),
    'llm-or-not':renderGuideMode('llm-or-not'), 'fine-tuning':renderGuideMode('fine-tuning')
  });
  return '<div class="empty">Unknown screen.</div>';
}

function applyMode(tab, panel, mode) {
  if (!MODE_SPECS[tab] || !panel) return;
  mode = normalizedMode(tab, mode);
  screenModes[tab] = mode;
  panel.querySelectorAll('[data-mode-tab]').forEach(button => {
    const selected = button.dataset.mode === mode;
    button.setAttribute('aria-selected', String(selected));
    button.tabIndex = selected ? 0 : -1;
  });
  panel.querySelectorAll('[data-mode-panel]').forEach(modePanel => { modePanel.hidden = modePanel.dataset.modePanel !== mode; });
  const note = panel.querySelector('[data-mode-note]');
  if (note) note.textContent = modeSpec(tab, mode)[2];
  const [, title, lead] = displayMeta(tab);
  const screenTitle = panel.querySelector('.screen-title');
  const screenLead = panel.querySelector('.screen-lead');
  if (screenTitle) screenTitle.textContent = title;
  if (screenLead && lead) screenLead.textContent = lead;
  if (tab === 'guides') {
    const active = panel.querySelector(`[data-mode-panel="${mode}"]`);
    const frame = active?.querySelector('.doc-frame');
    if (frame?.contentDocument?.body) wireGuideToc(active, frame);
  }
}

function wireConsolidatedScreen(tab, panel) {
  if (!MODE_SPECS[tab]) return;
  const buttons = [...panel.querySelectorAll('[data-mode-tab]')];
  // The first platform pass can intentionally be only a loading placeholder;
  // its async refresh will replace it with the mounted mode panels.
  if (!buttons.length) return;
  const choose = button => selectTab(tab, {mode:button.dataset.mode, focusMode:true});
  buttons.forEach((button, index) => {
    button.addEventListener('click', () => choose(button));
    button.addEventListener('keydown', event => {
      let next = null;
      if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') next = (index - 1 + buttons.length) % buttons.length;
      if (event.key === 'ArrowRight' || event.key === 'ArrowDown') next = (index + 1) % buttons.length;
      if (event.key === 'Home') next = 0;
      if (event.key === 'End') next = buttons.length - 1;
      if (next == null) return;
      event.preventDefault(); choose(buttons[next]);
    });
  });
  if (tab === 'dataset-library') {
    wirePlatformTab('dataset-library', panel.querySelector('[data-mode-panel="library"]'));
    wirePlatformTab('dataset-bundled', panel.querySelector('[data-mode-panel="built-in"]'));
  }
  if (tab === 'dataset-add') {
    wireDatasetUpload(panel.querySelector('[data-mode-panel="upload"]'));
    wireDatasetHub(panel.querySelector('[data-mode-panel="hugging-face"]'));
    wirePlatformTab('dataset-builder', panel.querySelector('[data-mode-panel="generate"]'));
  }
  if (tab === 'results') {
    wireHistoryControls(panel.querySelector('[data-mode-panel="history"]'));
    wirePlatformTab('analysis', panel.querySelector('[data-mode-panel="significance"]'));
    wirePlatformTab('regressions', panel.querySelector('[data-mode-panel="regressions"]'));
  }
  if (tab === 'test-lab') {
    wirePlatformTab('model-matrix', panel.querySelector('[data-mode-panel="models"]'));
    wirePlatformTab('context-lab', panel.querySelector('[data-mode-panel="context"]'));
  }
  if (tab === 'ship') {
    wirePlatformTab('releases', panel.querySelector('[data-mode-panel="releases"]'));
    wirePlatformTab('production', panel.querySelector('[data-mode-panel="spot-checks"]'));
  }
  if (tab === 'guides') panel.querySelectorAll('.doc-frame').forEach(frame => frame.addEventListener('load', () => {
    fitDocFrame(frame); wireGuideToc(frame.closest('.mode-panel'), frame);
  }));
  applyMode(tab, panel, screenModes[tab]);
}

document.addEventListener('click', event => {
  if (event.target.closest('[data-action="show-everything"]')) selectTab(state.tab, {focus:true});
});
// Appearance. "Auto" clears the attribute so the media query decides; the other
// two override it in both directions. The head script has already applied the
// stored choice — this only keeps the control in step with it.
function currentTheme() {
  try { return localStorage.getItem('pp-theme') || 'dark'; } catch { return 'dark'; }
}

function applyThemeTo(root, choice) {
  if (!root) return;
  if (choice === 'auto') root.removeAttribute('data-theme');
  else root.setAttribute('data-theme', choice);
}

function applyTheme(choice) {
  applyThemeTo(document.documentElement, choice);
  document.querySelectorAll('[data-theme-set]').forEach(button =>
    button.setAttribute('aria-pressed', String(button.dataset.themeSet === choice)));
  try { localStorage.setItem('pp-theme', choice); } catch { /* storage can be denied; the page still works */ }
  // Reading screens live in frames. Without this they keep the colour they
  // loaded with, so Light → Dark left a grey sheet sitting on the panel.
  document.querySelectorAll('.doc-frame').forEach(frame => {
    try { applyThemeTo(frame.contentDocument?.documentElement, choice); } catch { /* frame not ready */ }
  });
}

document.querySelectorAll('[data-theme-set]').forEach(button =>
  button.addEventListener('click', () => applyTheme(button.dataset.themeSet)));
applyTheme(currentTheme());

// The mobile bar is static markup; its marks come from the one icon set here.
// The rail alongside it carries none: there the name is the whole row.
document.querySelectorAll('.bottom-nav a[data-screen]').forEach(link => {
  const mark = screenIcons[link.dataset.screen];
  if (mark) link.insertAdjacentHTML('afterbegin', icon(mark));
});
/* --------------------------------------------------------------------------
 * The rail has two layers. Five sections are always visible, which is what the
 * first visit can hold in its head; the open one lists its screens, which is
 * what the twentieth visit needs — any screen one click away without going
 * through a menu. Only one section opens at a time, so the rail never grows
 * past ten rows, and the open one always follows where you actually are.
 *
 * The rail names the five and nothing more, and so does everything that stands
 * for a section elsewhere. The drawings that used to sit on the home tile and
 * on the section's own screen went when the flat visual language did: both call
 * sites had been painted out in CSS long before this, so the pictures were
 * being fetched on every visit to Home and never shown once.
 * -------------------------------------------------------------------------- */
/* Which section a screen belongs to. It is read off the rail, so the rail and
 * the path can never disagree. Two screens sit outside the five: Models & keys
 * and Jobs & logs live in the rail's foot, because their door is the model in
 * the corner rather than a step in the life of a prompt. They answer `system`,
 * which is a real answer and not a blank one — a blank was being read as "close
 * every section", so arriving at Models & keys used to collapse the whole rail
 * on the way in. */
const sectionOf = screen => screen.startsWith('s-') ? screen.slice(2)
  : [...document.querySelectorAll('.sidebar-group[data-section]')]
      .find(group => group.querySelector(`a[data-screen="${screen}"]`))?.dataset.section
  || (document.querySelector(`.sidebar-system a[data-screen="${screen}"]`) ? 'system' : '');

function openSection(section) {
  // A section with no group of its own — `system`, or nothing at all — is not
  // an instruction to close the five. The rail stays as the reader left it.
  if (!document.querySelector(`.sidebar-group[data-section="${section}"]`)) return;
  document.querySelectorAll('.sidebar-group[data-section]').forEach(group => {
    const open = group.dataset.section === section;
    group.classList.toggle('open', open);
    group.querySelector('[data-section-toggle]')?.setAttribute('aria-expanded', String(open));
    // A collapsed section is zero pixels tall, so its links leave the tab order
    // too — otherwise the keyboard walks through invisible rows.
    group.querySelectorAll('.sidebar-links a').forEach(link => {
      if (open) link.removeAttribute('tabindex'); else link.setAttribute('tabindex', '-1');
    });
  });
}

document.querySelectorAll('[data-section-toggle]').forEach(button => button.addEventListener('click', () => {
  closeDrawer(false);
  selectTab(`s-${button.dataset.sectionToggle}`, {focus:true});
}));

// A count that needs a person is the only thing in the rail allowed a colour.
function renderSectionCounts() {
  const pending = state.quality.reviews.filter(item => item.status === 'pending').length;
  const running = state.jobs.filter(job => job.status === 'running').length;
  const counts = {
    prompt:'', examples:state.datasetSizes.size || '',
    check:state.experiments.length || '', ship:pending || '', reference:state.techniqueCatalog.size || ''
  };
  document.querySelectorAll('[data-section-count]').forEach(node => {
    const key = node.dataset.sectionCount;
    node.textContent = counts[key] === '' ? '' : String(counts[key]);
    node.classList.toggle('wait', key === 'ship' && Boolean(pending));
  });
  document.querySelectorAll('[data-system-count]').forEach(node => {
    const key = node.dataset.systemCount;
    if (key === 'logs') {
      node.textContent = running ? String(running) : '';
      node.classList.toggle('wait', Boolean(running));
    }
  });
}

// The home tiles report state that arrives after the first paint.
function refreshHomeIfVisible() {
  if (state.tab === 'home' || sectionTabs.includes(state.tab)) renderDetailPanel(state.tab);
}

/* A section screen now says how much of its own material exists, and two of the
 * three lists behind that were only ever fetched when their own screen opened —
 * so a section screen would have drawn an empty map over a server that is not
 * empty. It asks for what it is about to show, once per session, and redraws
 * itself when the answers land. */
const SECTION_FACTS = {
  check: [['experiments', '/v1/experiments', list => { state.experiments = list; }]],
  ship: [
    ['reviews', '/v1/reviews', list => { state.quality.reviews = list; }],
    ['releases', '/v1/releases', list => { state.quality.releases = list; }]
  ]
};
const askedFor = new Set();

async function loadSectionFacts(section) {
  const missing = (SECTION_FACTS[section] || []).filter(([key]) => !askedFor.has(key));
  if (!missing.length) return;
  missing.forEach(([key]) => askedFor.add(key));
  await Promise.all(missing.map(async ([, path, apply]) => {
    // A section screen is not the place to report a failed fetch: the map stays
    // as it was, and the screen that owns the list says so properly.
    try { apply(await api(path)); } catch { /* the map simply stays empty */ }
  }));
  refreshHomeIfVisible();
  renderSectionCounts();
}

/* --------------------------------------------------------------------------
 * The model is not a setting you visit — it decides every number on every
 * screen. So it is visible in the bar at all times, switchable without leaving
 * the screen you are on, and named again in the corner of the rail. And nothing
 * that needs it pretends it can run without one: the screen says what is
 * missing and links to the one place that fixes it, and the buttons it would
 * have enabled go quiet at the same time.
 * -------------------------------------------------------------------------- */
const modelGatedScreens = new Set(['prompt', 'report', 'comparison', 'optimization', 'judge', 'test-lab']);
const MODEL_GATE = '<div class="gate" data-model-gate hidden>No model is set, so nothing on this screen can run yet.<button type="button" class="ghost" data-action="open-model-settings">Models &amp; keys</button></div>';

function modelIsSet() { return Boolean(state.settings.evaluation.model_id.trim()); }

function applyModelGate() {
  const ready = modelIsSet();
  document.querySelectorAll('[data-model-gate]').forEach(band => { band.hidden = ready; });
  document.querySelectorAll('[data-needs-model]').forEach(button => { if (!ready) button.disabled = true; });
}

function renderModelMenu() {
  const installed = state.installed.evaluation.models || [];
  const current = state.settings.evaluation.model_id.trim();
  const items = installed.slice(0, 8).map(item => `<button type="button" role="menuitem" class="model-option" data-model-id="${esc(item.model_id)}" aria-current="${item.model_id === current}">${esc(item.model_id)}</button>`).join('');
  return `<span class="model-pop-label">Runs the tests</span>
    ${items || '<span class="model-pop-empty">No installed models found on this provider.</span>'}
    <div class="model-pop-foot"><button type="button" class="ghost" data-action="open-model-settings">Models &amp; keys</button></div>`;
}

function toggleModelMenu(open) {
  const pop = $('model-pop'); const chip = $('model-chip');
  if (!pop || !chip) return;
  if (open) {
    pop.innerHTML = renderModelMenu();
    // The installed list is fetched when the settings screen renders, which may
    // never have happened. Ask for it here and redraw when it lands.
    Promise.resolve(loadInstalledModels('evaluation')).then(() => {
      if (!pop.hidden) pop.innerHTML = renderModelMenu();
    });
  }
  pop.hidden = !open;
  chip.setAttribute('aria-expanded', String(open));
}

document.addEventListener('click', event => {
  if (event.target.closest('[data-action="open-model-settings"]')) {
    toggleModelMenu(false);
    selectTab('settings', {focus:true});
    return;
  }
  const option = event.target.closest('.model-option');
  if (option) {
    state.settings.evaluation.model_id = option.dataset.modelId;
    toggleModelMenu(false);
    if (state.tab === 'settings') renderDetailPanel('settings');
    updateWorkspaceContext();
    refreshActions();
    return;
  }
  if (event.target.closest('#model-chip')) { toggleModelMenu($('model-pop')?.hidden); return; }
  if (!event.target.closest('#model-pop')) toggleModelMenu(false);
});
document.addEventListener('keydown', event => { if (event.key === 'Escape') toggleModelMenu(false); });
// The ceiling floats until there is something under it to separate from.
document.addEventListener('scroll', () => {
  document.querySelector('.context-bar')?.classList.toggle('stuck', window.scrollY > 4);
}, {passive:true});

// Where you were, not where you are: the current screen is already lit in the
// section below, and two highlights for one place read as two places.

document.addEventListener('click', event => {
  const crumb = event.target.closest('[data-crumb]');
  if (crumb && crumb.dataset.crumb) selectTab(crumb.dataset.crumb, {focus:true});
});

/* One chain, two doors: the rail card and the home tile run the same thing.
 *
 * Both doors can be pressed from anywhere, and the chain reads two things that
 * live on particular screens — the task, out of the composer, and the set of
 * examples, out of the run setup. So a refusal here has to be a refusal you can
 * act on: the button goes to the screen carrying the missing field before it
 * says what is missing, rather than naming a field that is not on screen.
 */
function wireSmartStart(button, status) {
  button?.addEventListener('click', async () => {
    // The home tile's own line goes off screen the moment the run navigates
    // away from home. The rail card is on screen throughout, so every word is
    // said there too and the run is never running silently.
    const rail = document.querySelector('.rail-smart-status');
    const say = (kind, text) => {
      [status, status === rail ? null : rail].forEach(node => {
        if (node) { node.textContent = text; node.className = `${node.classList[0]} ${kind}`; }
      });
    };
    // Both inputs, in the order the work needs them: there is nothing to
    // measure a set of examples against until the task exists. The task was
    // not checked at all, which only stayed invisible while the field arrived
    // with an example already written into it.
    if (!($('description')?.value || '').trim()) {
      selectTab('prompt', {focus:true});
      $('description')?.focus();
      say('error-text', 'Describe the task first — the field is on this screen, then start again.');
      return;
    }
    if (!state.run.dataset) {
      selectTab('report', {focus:true});
      say('error-text', 'Choose a set of examples first — the field is on this screen, then start again.');
      return;
    }
    if (state.tab !== 'prompt') selectTab('prompt');
    button.disabled = true; button.setAttribute('aria-busy', 'true'); button.textContent = 'Running';
    try {
      await smartRun(say);
      say('done', 'Done — opening the improved prompt.');
      selectTab('optimization', {focus:true});
    } catch (error) {
      say('error-text', error.message);
    } finally {
      button.disabled = false; button.removeAttribute('aria-busy'); button.textContent = 'Start';
      refreshActions();
    }
  });
}

const routeAliases = {
  selector:'prompt', 'dataset-upload':'dataset-add', 'dataset-hub':'dataset-add',
  'dataset-builder':'dataset-add', 'dataset-bundled':'dataset-library', history:'results', analysis:'results',
  regressions:'results', 'model-matrix':'test-lab', 'context-lab':'test-lab',
  releases:'ship', 'release-center':'ship', production:'ship',
  help:'guides', evaluation:'guides', 'prompt-vs-finetuning':'guides', 'llm-or-not':'guides'
};
let drawerTrigger = null;
const mobileDrawerQuery = window.matchMedia('(max-width: 900px)');

function normalizedTab(tab) {
  const resolved = routeAliases[tab] || tab;
  return detailPanels.includes(resolved) ? resolved : 'home';
}

/* The address is `#screen` or `#screen/thing`: the second segment is the one
 * thing on that screen you came to look at. Anything else in the hash — a
 * technique anchor, say — is a position on the page and not a route at all,
 * which `known` is what tells the listeners apart. */
/* Two of the old addresses cannot be resolved from their first segment alone.
 * `#release-center` split in half: its versions became Ship, its regression gate
 * became a mode of Results, where the runs it compares already live. So the
 * whole path is looked up before the head is, or a bookmarked gate would open
 * the register instead — the same screen name, the wrong screen. */
const legacyPaths = {
  'release-center/versions':['ship', 'releases'],
  'release-center/regressions':['results', 'regressions'],
  'production/drift':['ship', 'spot-checks']
};

function routeFromLocation() {
  const raw = decodeURIComponent(window.location.hash.slice(1));
  const [head, ...rest] = raw.split('/');
  const paired = legacyPaths[`${head}/${rest[0]}`];
  if (paired) {
    const [tab, mode] = paired;
    return {tab, showing:rest.slice(1).join('/') || null, mode, legacy:true, known:true};
  }
  const tab = normalizedTab(head || 'home');
  const spec = MODE_SPECS[tab];
  const aliasMode = legacyMode(head);
  const explicitMode = spec && modeSpec(tab, rest[0]) ? rest[0] : null;
  const mode = spec ? normalizedMode(tab, aliasMode || explicitMode) : null;
  const consumed = explicitMode ? 1 : 0;
  const showing = spec ? rest.slice(consumed).join('/') : rest.join('/');
  return {
    tab,
    showing: showing || null,
    mode,
    legacy: Boolean(head && routeAliases[head]),
    known: !head || detailPanels.includes(routeAliases[head] || head)
  };
}

/* Which of the mobile bar's five is lit. It used to be four hand-written lists,
 * which meant a screen missing from all of them lit nothing at all, and the bar
 * stopped answering "where am I" on exactly the screens a reader is most likely
 * to be lost on. It is one question, so it is asked once: which section is this
 * screen in, and which destination stands for that section.
 *
 * `system` deliberately has no entry. Models & keys and Jobs & logs are under
 * none of the five, and lighting one of them would mark a destination as the
 * current page when tapping it goes somewhere else. The bar goes quiet there
 * and the rail's own foot, which is in the drawer beside it, says where you
 * are instead. */
const sectionDestinations = {
  prompt:'prompt', examples:'dataset-library', check:'results', ship:'ship', reference:'guides'
};

function primaryDestination(tab) {
  return sectionDestinations[sectionOf(tab)] || null;
}

function setSidebarInteractive(interactive) {
  const sidebar = $('app-sidebar');
  if (!sidebar) return;
  sidebar.inert = !interactive;
  if (interactive) sidebar.removeAttribute('aria-hidden');
  else sidebar.setAttribute('aria-hidden', 'true');
  // `inert` is the primary control. Explicit tab stops keep the drawer safe in
  // older embedded browsers that expose the property without enforcing it.
  sidebar.querySelectorAll('a[href]').forEach(link => {
    if (interactive) link.removeAttribute('tabindex');
    else link.setAttribute('tabindex', '-1');
  });
}

function syncDrawerAccessibility() {
  const isMobile = mobileDrawerQuery.matches;
  const isOpen = isMobile && document.body.classList.contains('drawer-open');
  if (!isMobile) document.body.classList.remove('drawer-open');
  document.querySelector('.app-main').inert = isOpen;
  setSidebarInteractive(!isMobile || isOpen);
  document.querySelector('[data-testid="drawer-toggle"]')?.setAttribute('aria-expanded', String(isOpen));
}

function openDrawer(trigger) {
  drawerTrigger = trigger || document.activeElement;
  setSidebarInteractive(true);
  document.body.classList.add('drawer-open');
  document.querySelector('.app-main').inert = true;
  document.querySelector('[data-testid="drawer-toggle"]')?.setAttribute('aria-expanded', 'true');
  document.querySelector('#app-sidebar a')?.focus();
}

function closeDrawer(restoreFocus=true) {
  if (!document.body.classList.contains('drawer-open')) return;
  document.body.classList.remove('drawer-open');
  document.querySelector('.app-main').inert = false;
  document.querySelector('[data-testid="drawer-toggle"]')?.setAttribute('aria-expanded', 'false');
  if (restoreFocus && drawerTrigger?.isConnected) drawerTrigger.focus();
  else if ($('app-sidebar')?.contains(document.activeElement)) $('main-content')?.focus({preventScroll:true});
  setSidebarInteractive(!mobileDrawerQuery.matches);
}

if (mobileDrawerQuery.addEventListener) mobileDrawerQuery.addEventListener('change', syncDrawerAccessibility);
else mobileDrawerQuery.addListener(syncDrawerAccessibility);
syncDrawerAccessibility();

document.querySelector('[data-action="open-drawer"]')?.addEventListener('click', event => openDrawer(event.currentTarget));
document.querySelector('[data-action="close-drawer"]')?.addEventListener('click', () => closeDrawer());
document.addEventListener('keydown', event => {
  if (!document.body.classList.contains('drawer-open')) return;
  if (event.key === 'Escape') { event.preventDefault(); closeDrawer(); return; }
  if (event.key !== 'Tab') return;
  const items = [...document.querySelectorAll('#app-sidebar a[href]')].filter(item => item.offsetParent !== null);
  if (!items.length) return;
  const first = items[0]; const last = items[items.length - 1];
  if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
  else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
});

document.querySelectorAll('[data-global-tab]').forEach(link => link.addEventListener('click', event => {
  event.preventDefault();
  closeDrawer(false);
  selectTab(link.dataset.globalTab, {focus:true, focusMode:Boolean(link.dataset.mode), showing:link.dataset.showing, mode:link.dataset.mode});
}));

/* --------------------------------------------------------------------------
 * Home. Five tiles, one per section, each carrying the one fact that decides
 * whether you need to go there — and above them the single button that walks
 * the whole lifecycle for someone who does not yet know it has five parts.
 * -------------------------------------------------------------------------- */
function sectionTiles() {
  const pending = state.quality.reviews.filter(item => item.status === 'pending').length;
  const technique = state.program?.technique_id || state.chosen;
  return [
    ['s-prompt', 'Prompt Studio', 'Write the prompt, measure it on your examples, compare techniques, and search for better wording. Start here.',
      technique ? ['ok', 'Prompt ready'] : ['idle', 'Not written yet']],
    ['s-examples', 'Datasets', 'The rows every score is computed against. Bring your own, import public ones, or generate them.',
      state.datasetSizes.size ? ['ok', `${plural(state.datasetSizes.size, 'set')}`] : ['idle', 'Loading…']],
    ['s-check', 'Evaluation', 'Test whether a good score holds up — on other models, with other context, or against statistics.',
      state.experiments.length ? ['ok', `${plural(state.experiments.length, 'run')} recorded`] : ['idle', 'Nothing measured yet']],
    ['s-ship', 'Production', 'Freeze the version you ship, export it to your repository, and answer what is waiting for you.',
      pending ? ['wait', `${pending} waiting for you`] : ['idle', 'Nothing waiting']],
    ['s-reference', 'Docs', 'Evaluation methodology, fine-tuning trade-offs, and guides to understanding every score.',
      ['idle', `${MODE_SPECS.guides.modes.length} guides`]]
  ].map(([tab, name, lead, [tone, label]]) => `<a class="tile" href="#${tab}" data-global-tab="${tab}" data-screen="${tab}">
      <span class="tile-top"><strong>${esc(name)}</strong></span>
      <span class="tile-lead">${esc(lead)}</span>
      <span class="tile-foot"><span class="state ${tone}">${esc(label)}</span></span>
    </a>`).join('');
}

// What a tile says is not what the screen says. A tile is read while scanning
// five of them, so it gets one short line; the screen itself gets the longer
// one, read once you are there. Same source, two lengths.
const tileDesc = {
  prompt:'Describe the job in plain words. A method with a track record is picked and the prompt written for you.',
  report:'Run the prompt on your examples and see what it scored, example by example.',
  comparison:'Score every recommended method on the same examples, so the ranking is measured and not assumed.',
  optimization:'Rewrite the prompt over several rounds and keep whichever version scores best.',
  'dataset-library':'All example sets on this server: ready-made ones by kind of work, then your own.',
  'dataset-add':'Upload your own rows, import a public set, or generate cases to review.',
  'dataset-builder':'Generate rows from your task, or around what the last run got wrong. You approve every one.',
  'dataset-bundled':'The benchmarks inside the package, for trying the workflow out rather than judging your prompt.',
  history:'Every finished run, newest first, with a version-to-version diff and a CSV export.',
  results:'Run history and statistical significance in one results workspace.',
  judge:'Have a model mark a whole run against its reference answers, blind, for work no grader can score.',
  'model-matrix':'Run the same prompt on several models, to see whether it works anywhere but yours.',
  'context-lab':'Run the same prompt with different context, to see whether the extra text pays for its tokens.',
  analysis:'Check whether a difference between two runs is real or just noise, before acting on it.',
  'test-lab':'Challenge the prompt across models or with different context.',
  regressions:'Compare two runs and fail the new one if it got worse or slower than you allow.',
  reviews:'Everything waiting for your yes or no: generated rows, judge verdicts, breached gates.',
  releases:'Freeze the exact prompt you shipped, move it from draft to production, roll back when needed.',
  ship:'Freeze a prompt against the run that measured it, export it to your repository, and spot-check real inputs.',
  production:'Three checks you run by hand on pasted text: input drift, agent tool calls, injection attempts.',
  techniques:'The catalogue of methods, each with a real prompt compiled from the live registry.',
  logs:'What is running right now, and what each finished job did, step by step.',
  settings:'Set the three models and keys: one writes prompts, one runs them, one compares answers.',
  evaluation:'Where every number comes from, and when it is worth trusting.',
  help:'How the whole thing fits together, start to finish.',
  'prompt-vs-finetuning':'When to fine-tune a model — and when prompting is enough. A research-backed guide to choosing between prompting, few-shot ICL, RAG, fine-tuning, distillation, and tools/agents.',
  'llm-or-not':'Which of eight solution classes the task needs, from a rule to a person, and what a rung too high costs.',
  guides:'The user guide, the evaluation contract, and the two decision guides: whether to use a model, and whether to fine-tune one.'
};

/* A section screen is where "where am I" is answered, so its tiles carry state
 * rather than a separate list of steps saying the same thing beside them. */
// Screens whose only state is "has this been run here yet".
function screenResultState(tab) {
  return state.quality.results[tab] ? ['ok', 'Run'] : ['idle', 'Not run'];
}

function screenState(tab) {
  const runQuality = report => report ? report.scorecard.quality.toFixed(2) : null;
  switch (tab) {
    case 'prompt': return state.chosen ? ['ok', 'Written'] : ['idle', 'Not written yet'];
    case 'report': return state.report ? ['ok', `Quality ${runQuality(state.report)}`] : ['idle', 'Not measured'];
    case 'comparison': return state.comparison ? ['ok', `${plural(state.comparison.entries.length, 'method')}`] : ['idle', 'Not compared'];
    case 'optimization': return state.optimization ? ['ok', 'Improved'] : ['idle', 'Not optimized'];
    case 'dataset-library': return state.datasetSizes.size ? ['ok', `${plural(state.datasetSizes.size, 'set')}`] : ['idle', 'Loading…'];
    case 'dataset-builder': {
      // Flagged rows outrank merely unreviewed ones: a rule already objected to
      // those, so they are the part of the queue that is actually urgent.
      const rows = state.quality.projects.flatMap(project => project.examples);
      const flagged = rows.filter(item => item.checks?.length).length;
      if (flagged) return ['wait', `${plural(flagged, 'row')} flagged`];
      const unreviewed = rows.filter(item => item.status === 'unreviewed').length;
      return unreviewed ? ['wait', `${plural(unreviewed, 'example')} unreviewed`] : ['idle', 'Nothing generated'];
    }
    case 'history': case 'results': return state.experiments.length ? ['ok', `${plural(state.experiments.length, 'run')}`] : ['idle', 'No runs yet'];
    case 'analysis': return state.report ? ['idle', 'Ready'] : ['wait', 'Needs a run'];
    case 'regressions': return state.experiments.length > 1 ? ['idle', 'Ready'] : ['wait', 'Needs 2 runs'];
    case 'reviews': {
      const pending = state.quality.reviews.filter(item => item.status === 'pending').length;
      return pending ? ['wait', `${pending} waiting for you`] : ['idle', 'Nothing waiting'];
    }
    case 'releases': case 'ship': return state.quality.releases.length ? ['ok', `${plural(state.quality.releases.length, 'release')}`] : ['idle', 'None yet'];
    case 'techniques': return state.techniqueCatalog.size ? ['idle', `${state.techniqueCatalog.size}`] : ['idle', 'Loading…'];
    case 'settings': return [state.settings.evaluation.model_id.trim() ? 'ok' : 'wait', state.settings.evaluation.model_id.trim() || 'No model set'];
    case 'dataset-add': {
      const mine = [...state.datasetSizes.keys()].filter(name => name.startsWith('uploaded:')).length;
      return mine ? ['ok', `${plural(mine, 'set')} of yours`] : ['idle', '2 sources'];
    }
    case 'dataset-bundled': {
      const bundled = [...state.datasetSizes.keys()].filter(name => !name.includes(':')).length;
      // Same rule as the screen itself: a prefix means it came from somewhere.
      return bundled ? ['idle', `${plural(bundled, 'benchmark')}`] : ['idle', 'Loading…'];
    }
    case 'judge': return screenResultState('judge');
    case 'model-matrix': case 'test-lab': return screenResultState('model-matrix');
    case 'context-lab': return screenResultState('context-lab');
    case 'production': return ['idle', '3 checks'];
    case 'logs': {
      const running = state.jobs.filter(job => job.status === 'running').length;
      return running ? ['wait', `${plural(running, 'job')} running`] : ['idle', 'Idle'];
    }
    case 'evaluation': case 'help': case 'prompt-vs-finetuning': case 'llm-or-not': case 'guides': return ['idle', 'Reading'];
    default: return null;
  }
}

const screenActionLabels = {
  prompt:'Open Editor', report:'Measure Now', comparison:'Compare', optimization:'Optimize',
  'dataset-library':'Browse Sets', 'dataset-add':'Add', 'dataset-builder':'Generate', 'dataset-bundled':'Browse',
  history:'View Results', results:'View Results', judge:'Run Judge', 'model-matrix':'Matrix', 'context-lab':'Test Context', 'test-lab':'Open Lab', analysis:'Analyze',
  regressions:'Check Diff', reviews:'Review', releases:'Manage', ship:'Ship it', production:'Run a check',
  techniques:'Browse', guides:'Read Guides', logs:'View Logs', evaluation:'Read Guide', help:'Learn More', 'prompt-vs-finetuning':'Read Guide', 'llm-or-not':'Read Guide', settings:'Set Models'
};


function renderSectionTile(entry) {
  const {tab, mode:requestedMode, label} = typeof entry === 'string' ? {tab:entry} : entry;
  const [, defaultName] = screenMeta[tab] || ['', tab];
  const name = label || defaultName;
  const contentKey = tab === 'results' && requestedMode === 'regressions' ? 'regressions' : tab;
  const lead = tileDesc[contentKey] || screenMeta[contentKey]?.[2] || '';
  const actionLabel = screenActionLabels[contentKey] || 'Learn More';
  const mode = requestedMode || MODE_SPECS[tab]?.default;
  const href = mode ? canonicalModePath(tab, mode) : `#${tab}`;

  return `<a class="section-tile-card" href="${href}" data-global-tab="${tab}" data-screen="${tab}"${mode ? ` data-mode="${mode}"` : ''}>
    <div class="section-tile-info">
      <strong>${esc(name)}</strong>
      <p>${esc(lead)}</p>
    </div>
    <div class="section-tile-action">
      <span class="section-tile-btn">${esc(actionLabel)}</span>
    </div>
  </a>`;
}

/* --------------------------------------------------------------------------
 * The third part of a section screen. The drawing says which section this is
 * and the list says what you can do here; neither says how much of it there
 * already is. So: the section's own stock, drawn to scale — one circle per
 * thing, its area the size of that thing — and under it the single next move,
 * which is the one line a section screen can answer that a list of links
 * cannot. Sizes are read at a glance and compared without arithmetic, which is
 * the whole reason a disk map is a map and not a table.
 * -------------------------------------------------------------------------- */
const compactNumber = value => value >= 10000
  ? `${(value / 1000).toFixed(value >= 100000 ? 0 : 1).replace(/\.0$/, '')}k`
  : String(value);

// Group a list into {label, value} pairs, largest first.
function tally(items, keyOf) {
  const counts = new Map();
  items.forEach(item => {
    const key = keyOf(item);
    counts.set(key, (counts.get(key) || 0) + 1);
  });
  return [...counts.entries()].map(([label, value]) => ({label, value}));
}

// What each section is holding, in its own unit. `empty` is what to say when it
// is holding nothing yet — the map is then the shape of the work not yet done.
const sectionStock = {
  prompt() {
    const program = state.program;
    if (!program) return {
      title:'What the prompt is made of', legend:'One circle per message, sized by how long it is.', unit:'chars', tab:'prompt', items:[],
      caption: '', empty:'Nothing written yet. Once the prompt exists, every part of it is drawn here to scale.'
    };
    const items = [];
    (program?.stages || []).forEach((stage, index) => stage.messages.forEach(message => items.push({
      label: promptPartName(program, index, message),
      value: message.content.length
    })));
    const characters = items.reduce((total, item) => total + item.value, 0);
    return {
      title:'What the prompt is made of', legend:'One circle per message, sized by how long it is.', unit:'chars', tab:'prompt', items,
      caption: characters ? `${compactNumber(characters)} characters ≈ ${compactNumber(Math.round(characters / 4))} tokens` : '',
      empty:'Nothing written yet. Once the prompt exists, every part of it is drawn here to scale.'
    };
  },
  examples() {
    const items = [...state.datasetSizes.entries()]
      .map(([label, value]) => ({label, value: Number(value) || 0}))
      .filter(item => item.value > 0);
    const rows = items.reduce((total, item) => total + item.value, 0);
    return {
      title:'What you can measure against', legend:'One circle per set, sized by how many rows it has.', unit:'rows', tab:'dataset-library', items,
      caption: items.length ? `${plural(items.length, 'set')} · ${compactNumber(rows)} rows` : '',
      empty:'No examples on this server yet. Upload your own rows, or import a public set.'
    };
  },
  check() {
    const items = tally(state.experiments, record => record.dataset || 'unnamed');
    return {
      title:'Where you have measured', legend:'One circle per set you ran on, sized by how many runs it holds.', unit:'runs', tab:'results', items,
      caption: state.experiments.length
        ? `${plural(state.experiments.length, 'run')} over ${plural(items.length, 'set')}`
        : '',
      empty:'Nothing measured yet. Every recorded run lands here, sized by how often you ran on that set.'
    };
  },
  ship() {
    const pending = state.quality.reviews.filter(item => item.status === 'pending').length;
    const items = tally(state.quality.releases, release => release.status);
    // The one circle that is not a release: it opens the approvals screen on
    // what is still unanswered, which is a different screen entirely.
    if (pending) items.push({label:'waiting for you', value:pending, tone:'wait', tab:'reviews', showing:'pending'});
    return {
      title:'What is in flight', legend:'One circle per stage, sized by how many releases sit in it.', unit:'', tab:'ship', items,
      caption: state.quality.releases.length
        ? `${plural(state.quality.releases.length, 'release')}${pending ? ` · ${pending} waiting` : ''}`
        : (pending ? `${pending} waiting for you` : ''),
      empty:'Nothing in flight. Releases and anything waiting for your yes or no are drawn here.'
    };
  },
  reference() {
    return sectionStock.catalogue();
  },
  catalogue() {
    // Not by family: there are nearly as many families as techniques, and a map
    // of sixty circles of one is a list with extra steps. What the catalogue is
    // strong at is both coarse enough to draw and the thing you came to ask.
    const strengths = [...state.techniqueCatalog.values()]
      .flatMap(technique => technique.strong_tasks || []);
    // Drawn with the underscore taken out, opened with the name the catalogue
    // itself uses on every card.
    const items = tally(strengths, task => String(task))
      .map(item => ({...item, showing:item.label, label:item.label.replace(/_/g, ' ')}));
    return {
      title:'What the catalogue is strong at',
      legend:'One circle per kind of task, sized by how many techniques suit it. A technique can suit several.',
      unit:'', tab:'techniques', items,
      caption: state.techniqueCatalog.size
        ? `${state.techniqueCatalog.size} techniques · ${items.length} kinds of task`
        : '',
      empty:'The catalogue has not loaded.'
    };
  }
};

// The one move that follows from where this section actually stands. It is
// allowed to point out of the section — the next thing to do after writing a
// prompt is to measure it, and pretending otherwise would be a menu, not advice.
const sectionNextStep = {
  prompt() {
    if (!state.program && !state.chosen) return ['prompt', 'Write the prompt', 'Describe the task in plain words; the technique is picked for you.'];
    if (!state.report) return ['report', 'Measure it', 'One run over your examples, and the first scorecard.'];
    if (!state.comparison) return ['comparison', 'Compare the methods', 'Every recommended technique, scored on the same examples.'];
    return ['optimization', 'Search for better wording', 'A few rounds of rewriting; the best-scoring version is kept.'];
  },
  examples() {
    const rows = state.quality.projects.flatMap(project => project.examples);
    const flagged = rows.filter(item => item.checks?.length).length;
    if (flagged) return ['dataset-add', `Settle ${plural(flagged, 'flagged row')}`, 'A rule objected to these without needing a model; they are the only rows that need you.', null, 'generate'];
    const unreviewed = rows.filter(item => item.status === 'unreviewed').length;
    if (unreviewed) return ['dataset-add', `Approve ${plural(unreviewed, 'example')}`, 'Generated rows are not benchmark truth until you say so.', null, 'generate'];
    if (![...state.datasetSizes.keys()].some(name => name.startsWith('uploaded:'))) {
      return ['dataset-add', 'Add your own rows', 'A score speaks loudest about examples from your own traffic.'];
    }
    // With a run behind you, the useful next rows are not the awkward ones in
    // general — they are the ones this prompt has already been caught on.
    if (state.report) return ['dataset-add', 'Build from what it got wrong', 'Seed a new set from the rows the last run did not score full marks on.', null, 'generate'];
    return ['dataset-add', 'Build the edge cases', 'Generate the awkward rows your uploads do not cover.', null, 'generate'];
  },
  check() {
    if (!state.experiments.length) return ['report', 'Take the first measurement', 'Nothing here can compare runs until one exists.'];
    if (state.experiments.length === 1) return ['test-lab', 'Try it on another model', 'Wording that only works on one model shows up here first.', null, 'models'];
    return ['results', 'Ask whether it is real', 'Confidence intervals, so a noisy sample does not become a release.', null, 'significance'];
  },
  ship() {
    const pending = state.quality.reviews.filter(item => item.status === 'pending').length;
    // Advice lands where the circle for the same thing lands: on the unanswered
    // ones, not on the whole history of decisions.
    if (pending) return ['reviews', `Clear ${pending} waiting`, 'A generated row or a verdict is waiting for a person to read it.', 'pending'];
    if (!state.quality.releases.length) return ['ship', 'Register a release', 'A named, hashed version is what a rollback puts back.', null, 'releases'];
    if (state.quality.releases.some(release => release.status === 'production')) {
      return ['ship', 'Check for drift', 'Paste the inputs you have seen since, and see how far they have moved from the ones you tested on.', null, 'spot-checks'];
    }
    return ['ship', 'Export the manifest', 'The release becomes two files your repository holds and CI enforces.', null, 'releases'];
  },
  reference() {
    return ['techniques', 'Browse techniques catalogue', 'Explore prompt methods with live compiled examples.'];
  }
};

/* Circle packing, the small way: the biggest circle lands in the middle and
 * each next one takes the first free spot on a widening spiral. No randomness,
 * so the same numbers always produce the same map — a layout that reshuffled on
 * every render would read as something having changed. */
function packCircles(sizes) {
  const radii = sizes.map(size => Math.sqrt(size));
  const gap = Math.max(...radii) * 0.04;
  const placed = [];
  const clearOf = (x, y, radius, ignore) => placed.every((circle, index) =>
    index === ignore || Math.hypot(circle.x - x, circle.y - y) >= circle.r + radius + gap);
  radii.forEach(radius => {
    if (!placed.length) { placed.push({x:0, y:0, r:radius}); return; }
    const step = Math.max(radius * 0.4, gap);
    let spot = null;
    for (let ring = 1; ring <= 300 && !spot; ring += 1) {
      const distance = ring * step;
      const points = Math.max(10, Math.round((2 * Math.PI * distance) / step));
      for (let index = 0; index < points; index += 1) {
        // The half-turn offset keeps successive rings from lining their seats up.
        const angle = ((index / points) + ring * 0.5) * Math.PI * 2;
        const x = Math.cos(angle) * distance;
        const y = Math.sin(angle) * distance;
        if (clearOf(x, y, radius)) { spot = {x, y, r:radius}; break; }
      }
    }
    placed.push(spot || {x:0, y:0, r:radius});
  });
  // The spiral finds a free spot, not the nearest one, so the cluster comes out
  // with holes in it. Let every circle fall toward the middle until something
  // stops it: a few passes turn a ring of circles into a cluster.
  for (let pass = 0; pass < 60; pass += 1) {
    let settled = true;
    placed.forEach((circle, index) => {
      const distance = Math.hypot(circle.x, circle.y);
      if (!index || distance < 1e-4) return;
      const step = Math.min(distance, Math.max(circle.r * 0.06, gap));
      const x = circle.x - (circle.x / distance) * step;
      const y = circle.y - (circle.y / distance) * step;
      if (clearOf(x, y, circle.r, index)) { circle.x = x; circle.y = y; settled = false; }
    });
    if (settled) break;
  }
  // Fit the whole cluster to a unit square, so the drawing fills its box
  // whatever the numbers were.
  const left = Math.min(...placed.map(c => c.x - c.r));
  const right = Math.max(...placed.map(c => c.x + c.r));
  const top = Math.min(...placed.map(c => c.y - c.r));
  const bottom = Math.max(...placed.map(c => c.y + c.r));
  const scale = 1 / Math.max(right - left, bottom - top, 1e-6);
  const offsetX = (1 - (right - left) * scale) / 2;
  const offsetY = (1 - (bottom - top) * scale) / 2;
  return placed.map(circle => ({
    x: (circle.x - left) * scale + offsetX,
    y: (circle.y - top) * scale + offsetY,
    r: circle.r * scale
  }));
}

// Seven circles is as many as stay readable; everything past that is true but
// unreadable, so it is added up into one and named as what it is.
function stockBubbles(items) {
  const sorted = [...items].sort((a, b) => b.value - a.value);
  const shown = sorted.slice(0, 7);
  const rest = sorted.slice(7);
  if (rest.length) {
    shown.push({label:`${rest.length} more`, value:rest.reduce((total, item) => total + item.value, 0), tone:'rest'});
  }
  return shown;
}

function renderSectionMap(section) {
  const stock = sectionStock[section]?.();
  if (!stock) return '';
  const [nextTab, nextLabel, nextHint, nextShowing, nextMode] = sectionNextStep[section]();
  const bubbles = stockBubbles(stock.items);
  const packed = packCircles(bubbles.map(item => item.value));
  // The tally of everything that did not fit can outweigh any single thing in
  // the section, and colouring that one as the leader would point at the one
  // bubble you cannot open.
  const largest = Math.max(...bubbles.filter(item => item.tone !== 'rest').map(item => item.value), 0);
  // The packing fills its square edge to edge; the drawing keeps a margin, so
  // the outermost rim is drawn rather than clipped by the panel.
  const inset = 0.92;
  const margin = (1 - inset) / 2;
  const plot = bubbles.length
    ? `<div class="map-plot">${bubbles.map((item, index) => {
        const circle = packed[index];
        const diameter = circle.r * 2 * inset * 100;
        // A name only goes inside a circle wide enough to hold some of it —
        // shortened to fit, as a disk map does. Below that the number stands
        // alone, and below that the circle is its tooltip and nothing else.
        const room = diameter > 19 ? 'full' : diameter > 10 ? 'value' : 'bare';
        const tone = item.tone || (item.value === largest ? 'lead' : '');
        // A circle stands for one thing, so it opens the screen on that thing
        // rather than on the screen's front page. The tally of the ones too
        // small to draw stands for no single thing, and opens the screen whole.
        const target = item.tab || stock.tab;
        const showing = item.tone === 'rest' ? null : (item.showing ?? item.label);
        const targetMode = item.mode || MODE_SPECS[target]?.default;
        // Spoken aloud and hovered over, so the number is exact and the unit
        // agrees with it: one run, not 1 runs.
        const reading = `${item.label} — ${stock.unit
          ? plural(item.value, stock.unit.replace(/s$/, ''))
          : compactNumber(item.value)}`;
        return `<a class="map-bubble ${tone} ${room}" href="${targetMode ? canonicalModePath(target, targetMode, showing) : `#${target}${showing ? `/${encodeURIComponent(showing)}` : ''}`}"
          data-global-tab="${target}" data-screen="${target}"${targetMode ? ` data-mode="${targetMode}"` : ''}${showing ? ` data-showing="${esc(showing)}"` : ''}
          style="left:${((margin + circle.x * inset) * 100).toFixed(2)}%;top:${((margin + circle.y * inset) * 100).toFixed(2)}%;width:${diameter.toFixed(2)}%"
          title="${esc(reading)}"><span class="sr-only">${esc(reading)}</span>
          <span class="map-bubble-text" aria-hidden="true"><b>${esc(compactNumber(item.value))}</b><i>${esc(item.label)}</i></span></a>`;
      }).join('')}</div>`
    : `<div class="map-plot empty-plot"><p>${esc(stock.empty)}</p></div>`;

  return `<aside class="section-map" aria-label="${esc(stock.title)}">
      <div class="map-head">
        <strong>${esc(stock.title)}</strong>
        ${stock.caption ? `<span class="map-caption">${esc(stock.caption)}</span>` : ''}
      </div>
      ${plot}
      ${bubbles.length ? `<p class="map-legend">${esc(stock.legend)}</p>` : ''}
      <a class="map-next" href="${nextMode ? canonicalModePath(nextTab, nextMode, nextShowing) : `#${nextTab}${nextShowing ? `/${encodeURIComponent(nextShowing)}` : ''}`}"
        data-global-tab="${nextTab}" data-screen="${nextTab}"${nextMode ? ` data-mode="${esc(nextMode)}"` : ''}${nextShowing ? ` data-showing="${esc(nextShowing)}"` : ''}>
        <span class="map-next-kicker">Next step</span>
        <strong>${esc(nextLabel)}</strong>
        <small>${esc(nextHint)}</small>
      </a>
    </aside>`;
}

function renderSection(tab) {
  const section = tab.slice(2);
  const group = document.querySelector(`.sidebar-group[data-section="${section}"]`);
  // The rail's rows, and nothing else: a section screen claims to list what is
  // under it, so the two lists have to be the same list.
  const screens = group ? [...group.querySelectorAll('.sidebar-links a')].map(link => ({
    tab:link.dataset.screen,
    mode:link.dataset.mode || null,
    label:link.textContent.trim()
  })) : [];
  return `<div class="section-showcase">
      <div class="section-tiles-stack">${screens.map(renderSectionTile).join('')}</div>
      ${renderSectionMap(section)}
    </div>`;
}

/* The two things Smart run consumes, said before it is pressed rather than
 * after. Neither of them is on this screen — the task is written in the
 * composer and the set is chosen on the screens that run something — so the
 * tile states what the button is holding. A control whose inputs live
 * elsewhere either shows them or refuses as a surprise. */
function smartRunHolds() {
  const task = ($('description')?.value || '').trim();
  return [
    task ? ['ok', 'Task written'] : ['wait', 'No task yet'],
    state.run.dataset ? ['ok', state.run.dataset] : ['wait', 'No examples chosen']
  ];
}

function renderHome() {
  return `<div class="tiles">
      <div class="tile wide smart-tile">
        <div>
          <strong>Smart run</strong>
          <p>Writes the prompt, measures it on your examples, improves it over a few rounds, and stops at the first step that needs you. Minutes, not seconds.</p>
          <span class="tile-foot">${smartRunHolds().map(([tone, label]) =>
            `<span class="state ${tone}">${esc(label)}</span>`).join('')}</span>
        </div>
        <button type="button" class="primary smart-start" data-testid="smart-run">Start</button>
      </div>
      <p class="smart-status" role="status" aria-live="polite"></p>
      ${sectionTiles()}
    </div>`;
}

function detailBody(tab) {
  let body = '<div class="empty">Nothing here yet.</div>';
  if (tab === 'home') body = renderHome();
  if (sectionTabs.includes(tab)) body = renderSection(tab);
  if (tab === 'prompt' && state.program) body = renderProgram(state.program);
  if (tab === 'report' && state.report) body = renderReport(state.report);
  if (tab === 'comparison' && state.comparison) body = renderComparison(state.comparison);
  if (tab === 'optimization' && state.optimization) body = renderOptimization(state.optimization);
  if (tab === 'techniques') body = renderTechniqueCatalog();
  if (tab === 'logs') body = renderLogs();
  if (tab === 'settings') body = renderSettings();
  if (MODE_SPECS[tab]) body = renderConsolidatedScreen(tab);
  else if (platformTabs.includes(tab)) body = renderPlatformTab(tab);
  return body;
}

function ensureDetailShell() {
  if ($('detail').querySelector('.detail-panels')) return;
  // No tab strip: a prompt's measurements are screens with names of their own,
  // listed once in the rail and once as tiles on their section. A strip here
  // would be a third place to reach them, under a fourth set of labels.
  const panels = detailPanels.map(key => `<section class="tab-panel" id="screen-panel-${key}" data-tab-panel="${key}" data-screen="${key}" data-testid="screen-${key}" hidden></section>`).join('');
  $('detail').innerHTML = `<div class="detail-panels">${panels}</div>`;
}

function renderGuideToc(lang) {
  const spec = GUIDE_TOC[lang] || GUIDE_TOC.en;
  const links = spec.items.map(([href, text]) => `<a href="${href}">${esc(text)}</a>`).join('');
  return `<nav class="toc guide-toc" aria-label="${esc(spec.label)}" data-guide-toc><strong>${esc(spec.title)}</strong>${links}</nav>`;
}

function fillGuideToc(nav, lang) {
  const spec = GUIDE_TOC[lang] || GUIDE_TOC.en;
  nav.setAttribute('aria-label', spec.label);
  nav.innerHTML = `<strong>${esc(spec.title)}</strong>${spec.items.map(([href, text]) => `<a href="${href}">${esc(text)}</a>`).join('')}`;
}

function markGuideToc(nav, id) {
  nav.querySelectorAll('a').forEach(link => {
    if (link.hash === `#${id}`) link.setAttribute('aria-current', 'true');
    else link.removeAttribute('aria-current');
  });
}

function spyGuideToc(frame, nav) {
  const tick = () => {
    const doc = frame.contentDocument;
    if (!doc || !nav.isConnected) return;
    const frameTop = frame.getBoundingClientRect().top;
    let current = null;
    nav.querySelectorAll('a[href^="#"]').forEach(link => {
      const target = doc.getElementById(decodeURIComponent(link.hash.slice(1)));
      if (target && frameTop + target.getBoundingClientRect().top <= 120) current = link.hash.slice(1);
    });
    if (!current) {
      const first = nav.querySelector('a[href^="#"]');
      current = first && first.hash.slice(1);
    }
    if (current) markGuideToc(nav, current);
  };
  if (spyGuideToc.tick) window.removeEventListener('scroll', spyGuideToc.tick);
  spyGuideToc.tick = tick;
  window.addEventListener('scroll', tick, { passive:true });
  tick();
}

function wireGuideToc(panel, frame) {
  const nav = panel.querySelector('[data-guide-toc]');
  const doc = frame.contentDocument;
  if (!nav || !doc) return;
  const apply = () => {
    const inner = doc.querySelector('main.page > .toc');
    if (inner && inner.querySelector('a')) {
      nav.innerHTML = inner.innerHTML;
      const label = inner.getAttribute('aria-label');
      if (label) nav.setAttribute('aria-label', label);
      return true;
    }
    return false;
  };
  if (!apply()) [60, 250, 800].forEach(delay => setTimeout(() => { if (nav.isConnected) apply(); }, delay));
  nav.onclick = event => {
    const link = event.target.closest('a[href^="#"]');
    if (!link) return;
    event.preventDefault();
    const target = frame.contentDocument.getElementById(decodeURIComponent(link.hash.slice(1)));
    if (!target) return;
    const behavior = matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth';
    const top = frame.getBoundingClientRect().top + window.scrollY + target.getBoundingClientRect().top - 16;
    window.scrollTo({ top, behavior });
  };
  spyGuideToc(frame, nav);
}

function fitDocFrame(frame) {
  const doc = frame.contentDocument;
  if (!doc) { frame.style.height = '80vh'; return; }
  applyThemeTo(doc.documentElement, currentTheme());
  const main = doc.querySelector('main');
  if (main) main.style.margin = '0 auto 8px';
  // The height has to be taken once the document has actually laid out. The
  // load event fires before its own stylesheet has finished, so the first
  // measurement came back a fraction of the real height and the frame scrolled
  // inside itself — which is exactly what the wheel handler below assumes never
  // happens. Measure again as fonts and styles settle, and keep watching the
  // element that actually grows.
  const resize = () => {
    const height = Math.max(doc.documentElement.scrollHeight, doc.body?.scrollHeight || 0);
    if (height > 0) frame.style.height = `${height + 8}px`;
  };
  resize();
  [60, 250, 800].forEach(delay => window.setTimeout(resize, delay));
  doc.fonts?.ready.then(resize).catch(() => {});
  if (window.ResizeObserver) new ResizeObserver(resize).observe(doc.documentElement);
  // The frame is as tall as its content, so it never scrolls itself: pass the wheel on to the page.
  doc.addEventListener('wheel', event => {
    if (Math.abs(event.deltaX) > Math.abs(event.deltaY)) return;
    window.scrollBy(0, event.deltaY);
    event.preventDefault();
  }, { passive:false });
}

function renderDetailPanel(tab, body=detailBody(tab)) {
  ensureDetailShell();
  const panel = $('detail').querySelector(`[data-tab-panel="${tab}"]`);
  if (!panel) return;
  panel.innerHTML = screenShell(tab, body);
  panel.dataset.rendered = 'true';
  panel.dataset.showing = showingOn(tab) || '';
  if (tab === 'settings') {
    hydrateSettingsSecrets();
    ['engine', 'judge', 'similarity', 'evaluation'].forEach(loadInstalledModels);
    wireProfileControls(panel);
  }
  if (tab === 'logs') {
    const refreshBtn = panel.querySelector('.log-refresh');
    if (refreshBtn) refreshBtn.addEventListener('click', () => refreshLogs(true));
    panel.querySelectorAll('.log-job-card').forEach(card => {
      card.addEventListener('click', () => {
        const jobId = card.dataset.jobId;
        if (jobId && state.selectedJobId !== jobId) {
          state.selectedJobId = jobId;
          renderDetail();
        }
      });
    });
  }
  // Any link a screen draws to another screen is wired the same way, wherever
  // it is: the map's circles, the home tiles, and a run's example blocks all go
  // through one handler rather than each screen inventing its own.
  panel.querySelectorAll('[data-global-tab]').forEach(link => link.addEventListener('click', event => {
    event.preventDefault(); selectTab(link.dataset.globalTab, {focus:true, focusMode:Boolean(link.dataset.mode), showing:link.dataset.showing, mode:link.dataset.mode});
  }));
  if (sectionTabs.includes(tab)) loadSectionFacts(tab.slice(2));
  if (tab === 'dataset-library' && showingOn(tab)) loadDatasetRows(showingOn(tab));
  // A run records what the model answered, never what it was asked — that lives
  // in the set it ran on. The measurement screen fetches the set so every
  // answer it shows, opened or not, has the question back beside it.
  if (tab === 'report' && state.report) loadDatasetRows(state.report.dataset);
  // A screen that marks one part rather than filtering to it has to bring that
  // part to the reader, or the mark is somewhere below the fold. The panel is
  // still hidden at this point — it is shown a step later — and a hidden
  // element cannot be scrolled to, so this waits for the frame it appears in.
  const picked = panel.querySelector('[data-picked="true"]');
  if (picked) {
    const still = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    window.requestAnimationFrame(() => picked.scrollIntoView({block:'center', behavior: still ? 'auto' : 'smooth'}));
  }
  if (tab === 'home') {
    wireSmartStart(panel.querySelector('.smart-start'), panel.querySelector('.smart-status'));
  }
  if (tab === 'report' && state.report && !state.experiments.length) {
    // The verdict reads this run against the last recorded one, and the history
    // is only fetched when its own screen opens — so ask for it here too.
    api('/v1/experiments').then(list => {
      state.experiments = list;
      if (state.tab === 'report' && list.length) renderDetailPanel('report');
    }).catch(() => { /* the verdict simply omits the comparison line */ });
  }
  // Platform screens finish loading after the shell has already decided what to
  // show, so the bands they render must be judged again once they are here.
  applyModelGate();
  if (RUN_SETUP[tab]) wireRunSetup(panel);
  if (MODE_SPECS[tab]) wireConsolidatedScreen(tab, panel);
  else if (platformTabs.includes(tab)) wirePlatformTab(tab, panel);
  const pendingFocus = state.pendingModeFocus;
  if (pendingFocus?.tab === tab) {
    const target = panel.querySelector(`[data-mode-tab="${tab}"][data-mode="${pendingFocus.mode}"]`);
    if (target) { target.focus({preventScroll:true}); state.pendingModeFocus = null; }
  }
}

function activateDetailTab() {
  ensureDetailShell();
  if (resultTabs.includes(state.tab)) state.lastResultTab = state.tab;
  // Only the screen you write on keeps the composer beside it. A measurement is
  // something you read, so it gets the full width, like every other screen.
  // The left column is the prompt's: the composer on the screen that writes it,
  // the prompt itself on the three that run it. Every other screen has nothing
  // to put there and takes the full width.
  const runs = typeof RUN_SETUP === 'object' && Boolean(RUN_SETUP[state.tab]);
  const globalView = state.tab !== 'prompt' && !runs;
  $('workspace-layout').classList.toggle('global-view', globalView);
  const aside = $('run-aside');
  const composer = $('composer-panel');
  if (aside) {
    aside.hidden = !runs;
    if (runs) aside.innerHTML = renderRunSubject(state.tab);
  }
  if (composer) composer.hidden = state.tab !== 'prompt';
  $('workspace-layout').dataset.screen = state.tab;
  // Recommendations belong to the authored prompt, not to the measurements taken on it.
  $('results').hidden = state.tab !== 'prompt';
  // A section screen is three things — its name, the drawing that stands for
  // it, and the screens under it — and each stands on a surface of its own.
  // The screen's own panel would put all three on one, so it steps aside. The
  // screens that run something are built the same way, for the same reason.
  // Upload is the same shape: a name, what the file has to be, and the control
  // that takes it, side by side rather than stacked on one plate.
  $('detail').classList.toggle('unplated', sectionTabs.includes(state.tab) || unplatedScreens.has(state.tab));
  $('detail').querySelectorAll('[data-tab-panel]').forEach(panel => {
    panel.hidden = panel.dataset.tabPanel !== state.tab;
  });
  renderHeaderActions();
  updateWorkspaceContext();
  openSection(sectionOf(state.tab));
}

function renderDetail() {
  renderDetailPanel(state.tab);
  activateDetailTab();
  // Every path that changes the prompt ends in a render, so this is the one
  // place the draft has to be written down from.
  rememberDraft();
}

function showDetailMessage(tab, body) {
  state.tab = tab;
  renderDetailPanel(tab, body);
  activateDetailTab();
}

function renderHeaderActions() {
  const primary = primaryDestination(state.tab);
  document.querySelectorAll('[data-global-tab]').forEach(link => {
    const tab = normalizedTab(link.dataset.globalTab);
    const isBottom = link.closest('.bottom-nav');
    const modeMatches = !link.dataset.mode || screenModes[tab] === link.dataset.mode;
    const active = isBottom
      ? tab === primary
      : (tab === state.tab && modeMatches) || (tab === 'prompt' && resultTabs.includes(state.tab));
    link.classList.toggle('active', active);
    if (active) link.setAttribute('aria-current', 'page');
    else link.removeAttribute('aria-current');
  });
}

/* Where you are, as a path rather than a label: home → section → screen. The
 * back button walks it one step up, which is the move a tile screen creates. */
function crumbTrail(tab) {
  const trail = [['home', 'Prompt Playoff']];
  if (tab === 'home') return trail;
  // A section is a step of the path only when it has a screen of its own to
  // land on; `system` names the rail's foot, which is not somewhere you go.
  const section = sectionOf(tab);
  if (sectionTabs.includes(`s-${section}`)) trail.push([`s-${section}`, screenMeta[`s-${section}`][1]]);
  if (!sectionTabs.includes(tab)) trail.push([tab, displayMeta(tab)[1]]);
  // The thing you opened the screen on is a step of the path like any other, so
  // the screen it sits on becomes something you can click back to, and the back
  // button widens the screen instead of leaving it.
  const value = showingOn(tab);
  if (value) trail.push([tab, value]);
  return trail;
}

function renderCrumbs(tab) {
  const trail = crumbTrail(tab);
  const parent = trail.length > 1 ? trail[trail.length - 2][0] : null;
  // Where you have been, not where you are: the last step of the path is the
  // screen you are looking at, which names itself. So the marks go between the
  // steps and never after the last one — an arrow pointing at nothing read as a
  // path that had lost its end.
  $('crumbs').innerHTML = trail.slice(0, -1).map(([target, label], index) =>
    `${index ? icon('chevron') : ''}<button type="button" data-crumb="${target}">${esc(label)}</button>`).join('');
  const back = $('back-button');
  if (back) { back.hidden = !parent; back.dataset.crumb = parent || ''; if (!back.firstChild) back.innerHTML = icon('chevronLeft'); }
}

function updateWorkspaceContext() {
  const [, title] = displayMeta(state.tab);
  const value = showingOn(state.tab);
  renderCrumbs(state.tab);
  document.title = `${value ? `${value} · ` : ''}${title} · Prompt Playoff`;
  const technique = state.program?.technique_id || state.chosen;
  const prompt = technique ? (state.techniqueCatalog.get(technique)?.title || technique) : 'Draft';
  const dataset = state.run.dataset || 'Not selected';
  const model = state.settings.evaluation.model_id.trim() || 'Not set';
  const businessCase = typeof activeBusinessCase === 'function' ? activeBusinessCase() : null;
  const caseName = businessCase?.name || 'Unassigned';
  [['context-case', caseName], ['context-prompt', prompt], ['context-dataset', dataset], ['context-model', model], ['rail-model-name', model]].forEach(([id, value]) => { const node=$(id); if (node) node.textContent=value; });
  const caseLink = document.querySelector('[data-testid="context-case-link"]');
  if (caseLink) {
    caseLink.title = businessCase ? `Open results for ${caseName}` : 'This prompt is not assigned to a business case';
    caseLink.setAttribute('aria-label', caseLink.title);
  }
  // The chip is labelled Prompt and the value beside it is the name of a method,
  // which read as the method being the prompt. It is not: it is which method the
  // prompt was written with, and that is what the chip now says in full.
  const promptChip = document.querySelector('[data-testid="context-prompt-link"]');
  if (promptChip) {
    promptChip.title = technique
      ? `The prompt on this workbench, written with the ${prompt} method`
      : 'No prompt has been written yet';
    promptChip.setAttribute('aria-label', promptChip.title);
  }
  // The dataset named in the bar opens the library on that set, the same door
  // the circle for it opens on the section screen.
  const datasetLink = $('context-dataset-link');
  if (datasetLink) {
    const chosen = state.run.dataset;
    datasetLink.dataset.showing = chosen || '';
    datasetLink.href = `#dataset-library${chosen ? `/${encodeURIComponent(chosen)}` : ''}`;
  }
  // The comparing screens hold every row on them to one set of examples, and
  // name that set before the run starts. It is chosen on the screens that
  // measure and can arrive after they have been drawn, so the line is rewritten
  // here rather than left saying nothing is selected.
  if (typeof runAgainst === 'function') {
    document.querySelectorAll('.run-against').forEach(node => { node.innerHTML = runAgainst(node.dataset.lead); });
  }
  applyModelGate();
  renderSectionCounts();
}

function selectTab(tab, options={}) {
  const requestedTab = tab;
  tab = normalizedTab(tab);
  const mode = MODE_SPECS[tab]
    ? normalizedMode(tab, options.mode || legacyMode(requestedTab) || screenModes[tab])
    : null;
  if (mode) screenModes[tab] = mode;
  // Arriving anywhere without naming a thing means the whole screen: a
  // narrowing never outlives the click that asked for it.
  // A narrowing is a statement about something that exists. A measurement is
  // held in this page and nowhere else, so a link to one example of one, opened
  // in a fresh session, has nothing to point at — better to drop the name than
  // to print it over an empty screen.
  const nothingToShow = tab === 'report' && !state.report;
  const showing = (options.showing && !nothingToShow) ? options.showing : null;
  const arrived = state.tab !== tab && options.syncUrl !== false;
  state.showing = showing ? {tab, value:showing} : null;
  const targetHash = mode ? canonicalModePath(tab, mode, showing) : `#${tab}${showing ? `/${encodeURIComponent(showing)}` : ''}`;
  if (options.syncUrl !== false && window.location.hash !== targetHash) {
    window.history[options.replace ? 'replaceState' : 'pushState']({screen:tab, showing}, '', targetHash);
  }
  state.tab = tab;
  if (state.logTimer) { window.clearTimeout(state.logTimer); state.logTimer = null; }
  ensureDetailShell();
  const panel = $('detail').querySelector(`[data-tab-panel="${tab}"]`);
  const platformNeedsLoad = platformTabs.includes(tab) && !state.quality.loaded.has(tab);
  // A screen is drawn once and then left alone — half of them hold something
  // half-typed. What it was narrowed to is part of that drawing, so a screen is
  // drawn again when, and only when, that has changed under it.
  const restated = panel && (panel.dataset.showing || '') !== (showing || '');
  // Home and the five section screens are the exception: they report what
  // exists rather than hold anything, and arriving at one to read counts that
  // stopped being true two screens ago is worse than drawing it again.
  const reports = tab === 'home' || sectionTabs.includes(tab);
  if (panel && (panel.dataset.rendered !== 'true' || restated || reports || (tab === 'report' && !state.report))) {
    renderDetailPanel(tab, platformNeedsLoad ? '<div class="empty">Loading…</div>' : detailBody(tab));
  }
  activateDetailTab();
  if (mode) applyMode(tab, panel, mode);
  // A new screen starts at its own beginning. Without this you land halfway
  // down it, at whatever height the screen you left happened to be scrolled to
  // — and the deeper the path gets, the further from the top that is. Going
  // back is left alone: the browser restores where you were reading. A screen
  // that has a part to point at overrides this a frame later.
  if (arrived) window.scrollTo({top:0, behavior:'auto'});
  if (tab === 'logs') refreshLogs();
  if (tab === 'results') refreshHistory();
  if (platformNeedsLoad) refreshPlatformTab(tab);
  if (options.focusMode && mode) {
    const target = panel?.querySelector(`[data-mode-tab="${tab}"][data-mode="${mode}"]`);
    if (target) target.focus({preventScroll:true});
    else state.pendingModeFocus = {tab, mode};
  } else if (options.focus) $('main-content')?.focus({preventScroll:true});
}

function initializeNavigation() {
  const route = routeFromLocation();
  if (!route.known) window.history.replaceState({screen:route.tab}, '', `#${route.tab}`);
  selectTab(route.tab, {syncUrl:route.legacy, replace:route.legacy, showing:route.showing, mode:route.mode, focusMode:route.legacy});
}

/* A hash that names no screen is a position on the current one — the technique
 * index links to its own cards that way. Reading it as a route sent the reader
 * back to the front of the app, which is what both listeners guard against. */
window.addEventListener('popstate', () => {
  const route = routeFromLocation();
  if (!route.known) return;
  selectTab(route.tab, {syncUrl:route.legacy, replace:route.legacy, showing:route.showing, mode:route.mode, focusMode:route.legacy});
});
window.addEventListener('hashchange', () => {
  const route = routeFromLocation();
  if (!route.known) return;
  if (route.legacy || route.tab !== state.tab || route.showing !== showingOn(route.tab) || (route.mode && route.mode !== screenModes[route.tab])) {
    selectTab(route.tab, {syncUrl:route.legacy, replace:route.legacy, showing:route.showing, mode:route.mode, focusMode:route.legacy});
  }
});

function wireProfileControls(panel) {
  const status = panel.querySelector('[data-profile-status]');
  panel.querySelector('.profile-save')?.addEventListener('click', async () => {
    try {
      const name = panel.querySelector('#profile-name').value.trim();
      if (!name) throw new Error('Enter a profile name.');
      await api('/v1/model-profiles', {name, profile:modelProfile()});
      await loadProfiles(); renderDetailPanel('settings');
    } catch (e) { status.textContent = e.message; }
  });
  panel.querySelector('.profile-load')?.addEventListener('click', () => {
    const item = state.profiles.find(p => p.id === panel.querySelector('#profile-select').value);
    if (!item) { status.textContent = 'Choose a saved profile.'; return; }
    state.settings.evaluation = savedProfileSetting(item); state.task = null; renderDetailPanel('settings');
  });
  panel.querySelector('.profile-delete')?.addEventListener('click', async () => {
    const id = panel.querySelector('#profile-select').value;
    if (!id) { status.textContent = 'Choose a saved profile.'; return; }
    await api(`/v1/model-profiles/${encodeURIComponent(id)}`, {}, 'DELETE');
    await loadProfiles(); renderDetailPanel('settings');
  });
  panel.querySelector('.provider-check')?.addEventListener('click', async event => {
    event.currentTarget.disabled = true; status.textContent = 'Checking endpoint, credentials, and model…';
    try { const result = await api('/v1/providers/check', modelProfile()); status.textContent = `Connected in ${result.latency_seconds.toFixed(2)}s · ${result.detail}`; }
    catch (e) { status.textContent = e.message; }
    finally { event.currentTarget.disabled = false; }
  });
}

async function refreshLogs(manual=false) {
  if (state.tab !== 'logs') return;
  if (manual && state.logTimer) { window.clearTimeout(state.logTimer); state.logTimer = null; }
  const previous = JSON.stringify(state.jobs);
  const previousStatus = state.logStatus;
  const previousSelected = state.selectedJobId;
  if (!state.jobs.length || manual) state.logStatus = 'loading';
  state.logError = '';
  if (manual || !state.jobs.length) renderDetail();
  try {
    state.jobs = await api('/v1/jobs');
    state.logStatus = 'ready';
    renderSectionCounts();
    if (!state.selectedJobId && state.jobs.length) {
      state.selectedJobId = state.jobs[0].id;
    }
  } catch (e) {
    state.logStatus = 'error';
    state.logError = e.message;
  }
  if (state.tab !== 'logs') return;
  if (manual || previous !== JSON.stringify(state.jobs) || previousStatus !== state.logStatus || previousSelected !== state.selectedJobId || state.logError) renderDetail();
  state.logTimer = window.setTimeout(() => refreshLogs(), 1000);
}

function logClock(value) {
  if (!value) return '—';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleTimeString([], {hour:'2-digit', minute:'2-digit', second:'2-digit'});
}

function logEvent(event) {
  const at = logClock(event.at);
  const fields = Object.entries(event)
    .filter(([key, value]) => key !== 'at' && value != null && value !== '')
    .map(([key, value]) => `${key}=${typeof value === 'object' ? JSON.stringify(value) : value}`);
  return `[${at}] ${fields.join(' · ') || 'progress update'}`;
}

function renderLogs() {
  const status = state.logStatus === 'loading' ? 'Refreshing…' : 'Updates automatically every second';
  if (state.logError) {
    return `<div class="log-toolbar"><div class="meta log-status-text">${status}</div><button type="button" class="ghost log-refresh">Refresh</button></div><div class="error">Could not load logs: ${esc(state.logError)}</div>`;
  }
  if (!state.jobs.length) {
    return `<div class="log-toolbar"><div class="meta log-status-text">${status}</div><button type="button" class="ghost log-refresh">Refresh</button></div><div class="empty">No benchmark, comparison, or optimization runs yet.</div>`;
  }

  if (!state.selectedJobId || !state.jobs.some(j => j.id === state.selectedJobId)) {
    state.selectedJobId = state.jobs[0].id;
  }
  const activeJob = state.jobs.find(j => j.id === state.selectedJobId) || state.jobs[0];

  const jobItems = state.jobs.map(job => {
    const isActive = job.id === activeJob.id;
    return `<button type="button" class="log-job-card ${isActive ? 'active' : ''}" data-job-id="${esc(job.id)}">
      <div class="log-job-card-top">
        <span class="log-status ${esc(job.status)}">${esc(job.status)}</span>
        <span class="log-kind">${esc(job.kind)}</span>
      </div>
      <div class="log-job-card-bottom">
        <code class="log-id">${esc(job.id)}</code>
        <span class="log-time">${esc(logClock(job.created_at))}</span>
      </div>
    </button>`;
  }).join('');

  const lines = (activeJob.events || []).map(logEvent);
  if (!lines.length) lines.push(`[${logClock(activeJob.created_at)}] event=queued`);
  const logText = lines.join('\n');
  const copyKey = `log-${activeJob.id}`;
  if (state.copyPayloads) {
    state.copyPayloads.set(copyKey, logText);
  }

  const detailHtml = `
    <div class="log-detail-header">
      <div class="log-detail-meta">
        <span class="log-status ${esc(activeJob.status)}">${esc(activeJob.status)}</span>
        <span class="log-kind">${esc(activeJob.kind)}</span>
        <code class="log-id">${esc(activeJob.id)}</code>
        <span class="log-time">Started ${esc(logClock(activeJob.created_at))}</span>
      </div>
      <div class="log-detail-actions">
        ${typeof copyButton === 'function' ? copyButton(copyKey, 'Copy logs', `Copy logs for job ${activeJob.id}`) : ''}
      </div>
    </div>
    <div class="copy-status" data-copy-status="${esc(copyKey)}" role="status" aria-live="polite"></div>
    ${activeJob.error ? `<div class="log-error">${esc(activeJob.error)}</div>` : ''}
    <div class="log-viewer">
      <pre class="log-lines">${esc(logText)}</pre>
    </div>
  `;

  return `
    <div class="screen-split logs-split">
      <aside class="logs-sidebar">
        <div class="logs-sidebar-head">
          <h3>Jobs (${state.jobs.length})</h3>
          <button type="button" class="ghost log-refresh">Refresh</button>
        </div>
        <div class="meta log-status-text">${status}</div>
        <div class="logs-job-list">
          ${jobItems}
        </div>
      </aside>
      <section class="logs-detail-panel">
        ${detailHtml}
      </section>
    </div>
  `;
}

async function refreshHistory() {
  state.historyError = '';
  try { state.experiments = await api('/v1/experiments'); }
  catch (e) { state.experiments = []; state.historyError = e.message; }
  if (state.tab === 'results') renderDetailPanel('results');
}

function experimentMetric(record) {
  return record.metrics[record.winner] || Object.values(record.metrics)[0] || null;
}

function historyChart(records) {
  const points = records.slice().reverse().map((record, index, all) => {
    const metric = experimentMetric(record); const value = metric ? metric.quality : 0;
    const x = all.length === 1 ? 300 : 36 + index * 528 / (all.length - 1);
    const y = 120 - Math.max(0, Math.min(1, value)) * 90;
    return {x, y, value, version:record.version};
  });
  if (!points.length) return '';
  return `<svg class="history-chart" viewBox="0 0 600 140" role="img" aria-label="Quality history">
    <polyline points="${points.map(p => `${p.x},${p.y}`).join(' ')}"></polyline>
    ${points.map(p => `<circle cx="${p.x}" cy="${p.y}" r="5"><title>v${p.version}: ${p.value.toFixed(3)}</title></circle>`).join('')}
    <text x="10" y="18">quality 1.0</text><text x="10" y="132">0.0</text>
  </svg>`;
}

function historyDate(value) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString([], {month:'short', day:'2-digit', hour:'2-digit', minute:'2-digit'});
}

function renderExperimentComparison(result) {
  if (!result) return '';
  if (result.error) return `<div class="error">${esc(result.error)}</div>`;
  const rows = result.deltas.map(item => `<tr><td>${esc(item.metric)}</td><td>${item.before == null ? 'unknown' : Number(item.before).toFixed(5)}</td><td>${item.after == null ? 'unknown' : Number(item.after).toFixed(5)}</td><td class="delta ${item.degraded === false ? 'up' : item.degraded === true ? 'down' : ''}">${item.delta == null ? '—' : `${item.delta > 0 ? '+' : ''}${Number(item.delta).toFixed(5)}`}</td></tr>`).join('');
  return `<div class="stage-title">Version comparison · ${esc(result.technique_id)}</div><div class="table-scroll" role="region" aria-label="Version comparison table" tabindex="0"><table><thead><tr><th>Metric</th><th>Before</th><th>After</th><th>Delta</th></tr></thead><tbody>${rows}</tbody></table></div>`;
}

const UNASSIGNED_CASE_ID = '__unassigned__';

function historyCaseKey(record) {
  return record.business_case_id == null || record.business_case_id === ''
    ? UNASSIGNED_CASE_ID : String(record.business_case_id);
}

function historyPromptKey(record) {
  return String(record.prompt_id || record.technique_id || record.technique_ids?.join('+') || record.winner || 'legacy-prompt');
}

function historyPromptName(record) {
  const legacyId = record.technique_id || record.technique_ids?.join(' + ') || record.winner;
  const id = record.prompt_id || legacyId || 'Legacy prompt';
  const title = record.technique_id ? techniqueTitle(record.technique_id) : id;
  return title === id ? String(id) : `${title} · ${id}`;
}

function portfolioCases(records) {
  const rowsByCase = new Map();
  records.forEach(record => {
    const key = historyCaseKey(record);
    if (!rowsByCase.has(key)) rowsByCase.set(key, []);
    rowsByCase.get(key).push(record);
  });
  const cases = state.businessCases.map(item => ({
    id:String(item.id), name:item.name, description:item.description || '', records:rowsByCase.get(String(item.id)) || []
  }));
  rowsByCase.forEach((caseRecords, id) => {
    if (id === UNASSIGNED_CASE_ID || cases.some(item => item.id === id)) return;
    cases.push({id, name:caseRecords[0]?.business_case_name || 'Unknown case', description:'', records:caseRecords});
  });
  cases.sort((a, b) => {
    const aDate = a.records[0]?.created_at || ''; const bDate = b.records[0]?.created_at || '';
    return bDate.localeCompare(aDate) || a.name.localeCompare(b.name);
  });
  cases.push({id:UNASSIGNED_CASE_ID, name:'Unassigned', description:'Legacy and deliberately unassigned runs', records:rowsByCase.get(UNASSIGNED_CASE_ID) || []});
  return cases;
}

function latestQuality(records) {
  const metric = records.length ? experimentMetric(records[0]) : null;
  return metric ? Number(metric.quality).toFixed(3) : '—';
}

function historyPromptGroups(records) {
  const groups = new Map();
  records.forEach(record => {
    const key = historyPromptKey(record);
    if (!groups.has(key)) groups.set(key, {id:key, name:historyPromptName(record), records:[]});
    groups.get(key).records.push(record);
  });
  return [...groups.values()];
}

// A pair is comparable only when the server has the same measured series on
// both records. Optimization records often contain `baseline` and a search
// winner while benchmark records contain the authored technique, so sharing a
// prompt family alone is not enough to offer a working comparison.
function historyComparisonSeries(records) {
  const byTechnique = new Map();
  records.forEach(record => Object.keys(record.metrics || {}).forEach(technique => {
    if (!byTechnique.has(technique)) byTechnique.set(technique, []);
    byTechnique.get(technique).push(record);
  }));
  return [...byTechnique.entries()]
    .filter(([, items]) => items.length > 1)
    .map(([id, items]) => ({id, records:items}));
}

function renderHistory() {
  // A route may point at one dataset or run, but it still lands inside the
  // portfolio that owns it rather than replacing the portfolio with a flat list.
  const only = showingOn('results');
  const pointed = only ? state.experiments.find(item => item.id === only) : null;
  const visibleRecords = only
    ? state.experiments.filter(item => item.dataset === only || item.id === only)
    : state.experiments;
  if (only && !visibleRecords.length) {
    return `<div class="empty">No run recorded under ${esc(only)}. Records live in this server's history
      file; one registered before the file was cleared cannot be shown.</div>`;
  }
  const records = only ? visibleRecords : state.experiments;
  const cases = portfolioCases(records);
  const validCaseIds = new Set(cases.map(item => item.id));
  if (pointed) state.historyCaseId = historyCaseKey(pointed);
  if (!state.historyCaseId || !validCaseIds.has(state.historyCaseId)) {
    // A named case that has runs, then any group that has runs, and only then
    // an empty one. The middle step is what was missing: one empty business
    // case on the server was enough to open this screen on it, so the body said
    // "No runs yet" directly under a summary counting every run there is — all
    // of them one row below, under Unassigned. A screen that lands on nothing
    // while it is reporting fifty-three of something is answering a question
    // nobody asked.
    state.historyCaseId = cases.find(item => item.id !== UNASSIGNED_CASE_ID && item.records.length)?.id
      || cases.find(item => item.records.length)?.id
      || cases.find(item => item.id !== UNASSIGNED_CASE_ID)?.id || UNASSIGNED_CASE_ID;
  }
  const selectedCase = cases.find(item => item.id === state.historyCaseId) || cases[cases.length - 1];
  const prompts = historyPromptGroups(selectedCase.records);
  if (pointed) state.historyPromptId = historyPromptKey(pointed);
  if (!prompts.some(item => item.id === state.historyPromptId)) state.historyPromptId = prompts[0]?.id || null;
  const selectedPrompt = prompts.find(item => item.id === state.historyPromptId) || null;
  const datasets = selectedPrompt ? [...new Set(selectedPrompt.records.map(item => item.dataset))] : [];
  if (pointed) state.historyDataset = pointed.dataset;
  if (!datasets.includes(state.historyDataset)) state.historyDataset = datasets[0] || null;
  const datasetRecords = selectedPrompt?.records.filter(item => item.dataset === state.historyDataset) || [];
  const compareSeries = historyComparisonSeries(datasetRecords);
  if (!compareSeries.some(item => item.id === state.historyTechnique)) state.historyTechnique = compareSeries[0]?.id || null;
  const selectedSeries = compareSeries.find(item => item.id === state.historyTechnique) || null;
  const comparableRecords = selectedSeries?.records || [];
  const latest = datasetRecords[0] || selectedPrompt?.records[0] || null;
  const versions = new Set(state.experiments.map(item => `${historyCaseKey(item)}:${historyPromptKey(item)}:${item.prompt_version ?? item.version}`));
  const datasetCount = new Set(state.experiments.map(item => item.dataset)).size;
  const summary = `<dl class="portfolio-summary" aria-label="Portfolio summary">
    <!-- Named for what it counts. "Cases: 1" over a list of two rows read as a
         list that had lost one; the second row is Unassigned, which is where
         runs go when no case was named and therefore not a case. -->
    <div><dt>Business cases</dt><dd>${cases.filter(item => item.id !== UNASSIGNED_CASE_ID).length}</dd></div>
    <div><dt>Prompt versions</dt><dd>${versions.size}</dd></div>
    <div><dt>Datasets</dt><dd>${datasetCount}</dd></div>
    <div><dt>Runs</dt><dd>${state.experiments.length}</dd></div>
  </dl>`;
  const caseList = cases.map(item => `<button type="button" class="portfolio-case-row${item.id === UNASSIGNED_CASE_ID ? ' unassigned' : ''}" data-history-case="${esc(item.id)}" aria-current="${item.id === selectedCase.id ? 'true' : 'false'}">
    <span><strong>${esc(item.name)}</strong><small>${item.records.length ? `Latest ${latestQuality(item.records)}` : 'No runs yet'}</small></span>
    <span class="case-health"><b>${item.records.length}</b><small>${item.records.length ? historyDate(item.records[0].created_at) : '—'}</small></span>
  </button>`).join('');
  const promptList = prompts.map(item => {
    const versionCount = new Set(item.records.map(record => record.prompt_version ?? record.version)).size;
    return `<button type="button" class="portfolio-prompt-row" data-history-prompt="${esc(item.id)}" aria-current="${item.id === state.historyPromptId ? 'true' : 'false'}">
      <strong>${esc(item.name)}</strong><small>${plural(versionCount, 'version')} · ${plural(item.records.length, 'run')}</small>
    </button>`;
  }).join('');
  const datasetList = datasets.map(name => {
    const count = selectedPrompt.records.filter(item => item.dataset === name).length;
    return `<button type="button" class="portfolio-dataset-row" data-history-dataset="${esc(name)}" aria-current="${name === state.historyDataset ? 'true' : 'false'}"><span>${esc(name)}</span><small>${count}</small></button>`;
  }).join('');
  const seriesOptions = compareSeries.map(item => `<option value="${esc(item.id)}"${item.id === state.historyTechnique ? ' selected' : ''}>${esc(techniqueTitle(item.id))} · ${esc(item.id)}</option>`).join('');
  const options = comparableRecords.map(item => `<option value="${esc(item.id)}">prompt v${esc(item.prompt_version ?? item.version)} · ${esc(historyDate(item.created_at))} · ${esc(item.model_id)}</option>`).join('');
  const runRows = datasetRecords.map(item => { const m = experimentMetric(item); return `<tr${pointed?.id === item.id ? ' class="pointed-run"' : ''}><td><code>v${esc(item.prompt_version ?? item.version)}</code></td><td>${esc(historyDate(item.created_at))}</td><td>${esc(item.kind)}</td><td>${esc(item.model_id)}</td><td>${m ? Number(m.quality).toFixed(3) : '—'}</td><td>${m ? Number(m.mean_latency_seconds).toFixed(2) : '—'}</td><td>${m && m.mean_cost_usd != null ? `$${Number(m.mean_cost_usd).toFixed(6)}` : 'unknown'}</td></tr>`; }).join('');
  const compareKey = selectedCase && selectedPrompt && state.historyDataset
    ? `${selectedCase.id}:${selectedPrompt.id}:${state.historyDataset}:${state.historyTechnique || ''}` : '';
  const comparison = state.historyCompareContext === compareKey ? renderExperimentComparison(state.experimentComparison) : '';
  const detail = selectedPrompt ? `<nav class="portfolio-lineage" aria-label="Selected result lineage">
      <span>${esc(selectedCase.name)}</span><b>/</b><span>${esc(selectedPrompt.name)} <em>v${esc(latest?.prompt_version ?? latest?.version ?? '—')}</em></span><b>/</b><span>${esc(state.historyDataset)}</span><b>/</b><span>${latest ? `run ${esc(historyDate(latest.created_at))}` : 'no run'}</span>
    </nav>
    <div class="portfolio-depth">
      <nav class="portfolio-dataset-list" aria-label="Datasets for selected prompt"><div class="portfolio-rail-label">Datasets</div>${datasetList}</nav>
      <section class="portfolio-runs" aria-label="Runs for ${esc(state.historyDataset)}">
        <div class="portfolio-section-head"><div><span class="eyebrow">Measured on</span><h3>${esc(state.historyDataset)}</h3></div><span class="meta">${plural(datasetRecords.length, 'compatible run')}</span></div>
        ${historyChart(datasetRecords)}
        ${selectedSeries ? `<div class="quality-form portfolio-compare">
          <label class="wide" for="history-technique">Measured series<select id="history-technique">${seriesOptions}</select></label>
          <label for="history-before">Before<select id="history-before">${options}</select></label>
          <label for="history-after">After<select id="history-after">${options}</select></label>
          <button type="button" class="primary history-compare">Compare versions</button>
          <div class="meta compare-status wide" role="status" aria-live="polite"></div>
        </div>` : `<p class="meta portfolio-compare-note">No two runs share the same measured series yet. Run another version on this dataset to compare it here.</p>`}
        ${comparison}
        <p class="table-scroll-hint" id="history-scroll-hint">Scroll horizontally to inspect every measurement.</p>
        <div class="table-scroll" role="region" aria-label="Compatible experiment runs" aria-describedby="history-scroll-hint" tabindex="0"><table><thead><tr><th>Prompt</th><th>Recorded</th><th>Kind</th><th>Model</th><th>Quality</th><th>Latency s</th><th>Mean cost</th></tr></thead><tbody>${runRows}</tbody></table></div>
      </section>
    </div>` : `<div class="empty">${selectedCase.id === UNASSIGNED_CASE_ID ? 'No unassigned runs.' : 'No runs yet. Assign a prompt to this case in Prompt Studio, then measure it.'}</div>`;
  const status = state.historyError
    ? `<div class="error portfolio-status">Run history could not be loaded: ${esc(state.historyError)}</div>`
    : state.businessCasesError
      ? `<div class="warning portfolio-status">Saved cases could not be loaded. Recorded runs remain available: ${esc(state.businessCasesError)}</div>`
      : state.businessCasesLoading ? '<div class="meta portfolio-status">Loading saved business cases…</div>' : '';
  return `${status}${summary}<div class="portfolio-workspace">
    <aside class="portfolio-cases" aria-label="Business cases"><div class="portfolio-rail-label">Business cases</div>${caseList}</aside>
    <section class="portfolio-case-detail"><header class="portfolio-case-head"><div><span class="eyebrow">Selected case</span><h2>${esc(selectedCase.name)}</h2><p>${esc(selectedCase.description || 'Prompt runs grouped by version and dataset.')}</p></div></header>
      <div class="portfolio-prompt-layout"><nav class="portfolio-prompt-list" aria-label="Prompts in ${esc(selectedCase.name)}"><div class="portfolio-rail-label">Prompts</div>${promptList || '<p class="meta">No prompts measured</p>'}</nav><div class="portfolio-prompt-detail">${detail}</div></div>
    </section>
  </div>`;
}

function wireHistoryControls(panel) {
  panel.querySelectorAll('[data-history-case]').forEach(button => button.addEventListener('click', () => {
    state.historyCaseId = button.dataset.historyCase; state.historyPromptId = null; state.historyDataset = null; state.historyTechnique = null;
    state.experimentComparison = null; state.historyCompareContext = null; renderDetailPanel('results');
  }));
  panel.querySelectorAll('[data-history-prompt]').forEach(button => button.addEventListener('click', () => {
    state.historyPromptId = button.dataset.historyPrompt; state.historyDataset = null; state.historyTechnique = null;
    state.experimentComparison = null; state.historyCompareContext = null; renderDetailPanel('results');
  }));
  panel.querySelectorAll('[data-history-dataset]').forEach(button => button.addEventListener('click', () => {
    state.historyDataset = button.dataset.historyDataset; state.historyTechnique = null;
    state.experimentComparison = null; state.historyCompareContext = null; renderDetailPanel('results');
  }));
  panel.querySelector('#history-technique')?.addEventListener('change', event => {
    state.historyTechnique = event.currentTarget.value;
    state.experimentComparison = null; state.historyCompareContext = null; renderDetailPanel('results');
  });
  const before = panel.querySelector('#history-before'); const after = panel.querySelector('#history-after');
  if (before && before.options.length > 1) before.selectedIndex = 1;
  const compareButton = panel.querySelector('.history-compare');
  const compareStatus = panel.querySelector('.compare-status');
  const syncComparisonButton = () => {
    if (!compareButton || !before || !after) return;
    const same = before.value === after.value;
    compareButton.disabled = same;
    if (same && compareStatus) compareStatus.textContent = 'Choose two different runs.';
    else if (compareStatus && !compareStatus.textContent.startsWith('Compar')) compareStatus.textContent = '';
  };
  before?.addEventListener('change', syncComparisonButton);
  after?.addEventListener('change', syncComparisonButton);
  syncComparisonButton();
  compareButton?.addEventListener('click', async () => {
    const context = `${state.historyCaseId}:${state.historyPromptId}:${state.historyDataset}:${state.historyTechnique || ''}`;
    compareButton.disabled = true;
    if (compareStatus) compareStatus.textContent = 'Comparing these two recorded runs…';
    try {
      state.experimentComparison = await api('/v1/experiments/compare', {
        before_id:before.value, after_id:after.value, technique_id:state.historyTechnique
      });
    }
    catch (e) { state.experimentComparison = {error:`Comparison failed: ${e.message}`}; }
    state.historyCompareContext = context;
    renderDetailPanel('results');
  });
}

// One prompt per screen: the text is the product, so everything around it stays
// quiet. The only accent on this view is the copy button that gets it out.
