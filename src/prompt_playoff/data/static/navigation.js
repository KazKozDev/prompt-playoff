// The prompt and the three measurements taken on it: they share the composer
// column, which every other screen hides.
const resultTabs = ['prompt', 'report', 'comparison', 'optimization'];
const platformTabs = ['dataset-builder', 'context-lab', 'judge', 'model-matrix', 'analysis', 'reviews', 'regressions', 'releases', 'production', 'dataset-library'];
const sectionTabs = ['s-prompt', 's-examples', 's-check', 's-ship', 's-reference'];
const detailPanels = ['home', ...sectionTabs, 'prompt', 'report', 'comparison', 'optimization', 'techniques', 'logs', 'history', 'settings', 'help', 'evaluation', 'dataset-hub', ...platformTabs];
const docPages = { help: ['/help', 'Help'], evaluation: ['/benchmarks', 'Evaluation Guide'] };
// One name per screen, written down once. The sidebar link, the heading in the
// context bar and the browser tab all read from here, so a screen can never be
// called three different things on the way to itself. Names in the navigation
// are nouns; the expert term and the question a newcomer would ask both live in
// the third entry, the one line that says what the screen is for. Screens no
// longer carry a heading of their own — the context bar is already showing it.
const screenMeta = {
  prompt:['Prompt', 'Write the prompt'], report:['Prompt', 'Measurement'], comparison:['Prompt', 'Method comparison'], optimization:['Prompt', 'Optimization'],
  'dataset-library':['Examples', 'Example library', 'Every set of examples this server can measure against — the bundled ones, your uploads, and anything imported.'],
  'dataset-hub':['Examples', 'Import from Hugging Face', 'No examples of your own? Find a public dataset whose material resembles your task and import the rows you pick. This is the only thing here that needs an internet connection.'],
  'dataset-builder':['Examples', 'Build examples', 'Generate edge cases and mutations from your task. Nothing becomes benchmark truth before you approve it.'],
  history:['Check', 'Results', 'Every run this server has recorded. Aggregate numbers only — prompts and raw model answers are not stored here.'],
  judge:['Check', 'Side-by-side judging', 'Two answers, one rubric, and the order hidden from the judge. Every decision goes to your approvals.'],
  'model-matrix':['Check', 'Across models', 'Run one prompt and one set of examples across models, to find wording that only works on the model you wrote it for.'],
  'context-lab':['Check', 'Context test', 'The same prompt against different context: full documents, memory, retrieval results, or a compressed version.'],
  analysis:['Check', 'Confidence', 'Is the difference real? Confidence intervals and per-slice scores, so a small noisy sample does not turn into a release decision.'],
  regressions:['Ship', 'Before / after', 'Better or worse? Compare two recorded runs against the quality and the speed you are willing to lose.'],
  reviews:['Ship', 'Your approvals', 'Generated examples, judge decisions, regressions and releases waiting for an explicit yes or no.'],
  releases:['Ship', 'Releases', 'Draft → tested → approved → production, with a rollback that puts the previous prompt back.'],
  production:['Ship', 'Live quality', 'Watch real inputs drift away from what you tested on, inspect agent runs, and try the prompt against injection attempts.'],
  techniques:['Reference', 'Techniques', 'Every method with its own task and a real prompt compiled from the live registry. Open the blueprint only when you need its source blocks.'],
  logs:['Reference', 'Jobs & logs', 'What is running right now, and what every finished run did.'],
  settings:['Reference', 'Models & keys', 'Two models, and they do different jobs. The prompt engine writes the final prompt; the evaluation model runs it and produces every number you see.'],
  evaluation:['Reference', 'Evaluation guide'], help:['Reference', 'Help'],
  home:['Workspace', 'Prompt Playoff', 'Five places, and one button that walks you through all of them. Everything here runs on your machine.'],
  's-prompt':['Prompt', 'Prompt', 'Everything about the prompt itself — writing it, and the measurements taken on it.'],
  's-examples':['Examples', 'Examples', 'The rows every score is computed against — bring your own, import public ones, or generate them. A number only means something when these look like your real inputs.'],
  's-check':['Check', 'Check', 'Different ways of asking the same question: is this prompt actually good, or did it just get lucky?'],
  's-ship':['Ship', 'Ship', 'The gate between a prompt that scores well here and a prompt running in front of real users.'],
  's-reference':['Reference', 'Reference', 'The catalogue, the machinery, and the reading. Nothing here changes your prompt.']
};

// The one action a screen offers about itself lives in the same corner on every
// screen, instead of somewhere inside its body.
const screenActions = {
  history: () => state.experiments.length ? '<a class="export-link" href="/v1/experiments.csv" download="prompt-playoff-history.csv">Download CSV</a>' : '',
  logs: () => '<button type="button" class="ghost log-refresh">Refresh</button>'
};

function screenShell(tab, body) {
  const [, title, lead] = screenMeta[tab] || screenMeta.home;
  const actions = screenActions[tab]?.() || '';
  const gate = modelGatedScreens.has(tab) ? MODEL_GATE : '';
  // The name belongs to the screen, not to the chrome: the bar carries the path
  // you took, the screen carries what it is.
  const head = `<div class="screen-head">
      <div><h1 class="screen-title">${esc(title)}</h1>${lead ? `<p class="screen-lead">${esc(lead)}</p>` : ''}</div>
      ${actions ? `<div class="screen-actions">${actions}</div>` : ''}
    </div>`;
  return `${head}${gate}${body}`;
}
// Appearance. "Auto" clears the attribute so the media query decides; the other
// two override it in both directions. The head script has already applied the
// stored choice — this only keeps the control in step with it.
function applyTheme(choice) {
  if (choice === 'auto') document.documentElement.removeAttribute('data-theme');
  else document.documentElement.setAttribute('data-theme', choice);
  document.querySelectorAll('[data-theme-set]').forEach(button =>
    button.setAttribute('aria-pressed', String(button.dataset.themeSet === choice)));
  try { localStorage.setItem('pp-theme', choice); } catch { /* storage can be denied; the page still works */ }
}

document.querySelectorAll('[data-theme-set]').forEach(button =>
  button.addEventListener('click', () => applyTheme(button.dataset.themeSet)));
applyTheme((() => {
  try { return localStorage.getItem('pp-theme') || 'dark'; } catch { return 'dark'; }
})());

// The sidebar and the mobile bar are static markup; their marks come from the
// one icon set here, so a screen cannot end up with a different symbol in the
// two places it is listed.
document.querySelectorAll('.lifecycle-nav a[data-screen], .bottom-nav a[data-screen]').forEach(link => {
  const mark = screenIcons[link.dataset.screen];
  if (mark) link.insertAdjacentHTML('afterbegin', icon(mark));
});
/* --------------------------------------------------------------------------
 * The rail has two layers. Five sections are always visible, which is what the
 * first visit can hold in its head; the open one lists its screens, which is
 * what the twentieth visit needs — any screen one click away without going
 * through a menu. Only one section opens at a time, so the rail never grows
 * past ten rows, and the open one always follows where you actually are.
 * -------------------------------------------------------------------------- */
const sectionIcons = {prompt:'pencil', examples:'rows', check:'target', ship:'rocket', reference:'book'};
document.querySelectorAll('[data-section-toggle]').forEach(button =>
  button.insertAdjacentHTML('afterbegin', icon(sectionIcons[button.dataset.sectionToggle])));
const sectionOf = screen => screen.startsWith('s-') ? screen.slice(2)
  : [...document.querySelectorAll('.sidebar-group[data-section]')]
      .find(group => group.querySelector(`a[data-screen="${screen}"]`))?.dataset.section || '';

function openSection(section) {
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
  const counts = {
    prompt:'', examples:state.datasetSizes.size || '', check:state.experiments.length || '',
    ship:pending || '', reference:state.techniqueCatalog.size || ''
  };
  document.querySelectorAll('[data-section-count]').forEach(node => {
    const key = node.dataset.sectionCount;
    node.textContent = counts[key] === '' ? '' : String(counts[key]);
    node.classList.toggle('wait', key === 'ship' && Boolean(pending));
  });
}

// The home tiles report state that arrives after the first paint.
function refreshHomeIfVisible() {
  if (state.tab === 'home' || sectionTabs.includes(state.tab)) renderDetailPanel(state.tab);
}

/* --------------------------------------------------------------------------
 * The model is not a setting you visit — it decides every number on every
 * screen. So it is visible in the bar at all times, switchable without leaving
 * the screen you are on, and named again in the corner of the rail. And nothing
 * that needs it pretends it can run without one: the screen says what is
 * missing and links to the one place that fixes it, and the buttons it would
 * have enabled go quiet at the same time.
 * -------------------------------------------------------------------------- */
const modelGatedScreens = new Set(['prompt', 'report', 'comparison', 'optimization', 'judge', 'model-matrix', 'context-lab']);
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
    <div class="model-pop-foot"><button type="button" class="ghost" data-action="open-model-settings">Models &amp; keys…</button></div>`;
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

// One chain, two doors: the rail card and the home tile run the same thing.
function wireSmartStart(button, status) {
  button?.addEventListener('click', async () => {
    const say = (kind, text) => { if (status) { status.textContent = text; status.className = `${status.classList[0]} ${kind}`; } };
    button.disabled = true; button.setAttribute('aria-busy', 'true'); button.textContent = 'Running…';
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

const routeAliases = {selector:'prompt'};
let drawerTrigger = null;
const mobileDrawerQuery = window.matchMedia('(max-width: 900px)');

function normalizedTab(tab) {
  const resolved = routeAliases[tab] || tab;
  return detailPanels.includes(resolved) ? resolved : 'home';
}

function tabFromLocation() {
  return normalizedTab(decodeURIComponent(window.location.hash.slice(1)).split('/').pop() || 'home');
}

function primaryDestination(tab) {
  if (resultTabs.includes(tab)) return 'prompt';
  if (['dataset-library', 'dataset-hub', 'dataset-builder'].includes(tab)) return 'dataset-library';
  if (['history', 'judge', 'model-matrix', 'context-lab', 'analysis'].includes(tab)) return 'history';
  if (['regressions', 'reviews', 'releases', 'production'].includes(tab)) return 'regressions';
  return null;
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
  selectTab(link.dataset.globalTab, {focus:true});
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
    ['s-prompt', 'Prompt', 'Everything about the prompt itself — writing it, and the measurements taken on it.',
      technique ? ['ok', 'Prompt ready'] : ['idle', 'Not written yet']],
    ['s-examples', 'Examples', 'The rows every score is computed against. Bring your own, import public ones, or generate them.',
      state.datasetSizes.size ? ['ok', `${plural(state.datasetSizes.size, 'set')}`] : ['idle', 'Loading…']],
    ['s-check', 'Check', 'Different ways of asking the same question: is this prompt actually good, or did it just get lucky?',
      state.experiments.length ? ['ok', `${plural(state.experiments.length, 'run')} recorded`] : ['idle', 'Nothing measured yet']],
    ['s-ship', 'Ship', 'The gate between a prompt that scores well here and a prompt running in front of real users.',
      pending ? ['wait', `${pending} waiting for you`] : ['idle', 'Nothing waiting']],
    ['s-reference', 'Reference', 'The catalogue, the machinery, and the reading. Nothing here changes your prompt.',
      state.techniqueCatalog.size ? ['idle', `${plural(state.techniqueCatalog.size, 'technique')}`] : ['idle', 'Loading…']]
  ].map(([tab, name, lead, [tone, label]]) => `<a class="tile" href="#${tab}" data-global-tab="${tab}" data-screen="${tab}">
      <span class="tile-top">${icon(sectionIcons[tab.slice(2)] || 'pencil')}<strong>${esc(name)}</strong></span>
      <span class="tile-lead">${esc(lead)}</span>
      <span class="tile-foot"><span class="state ${tone}">${esc(label)}</span></span>
    </a>`).join('');
}

// What a tile says is not what the screen says. A tile is read while scanning
// five of them, so it gets one short line; the screen itself gets the longer
// one, read once you are there. Same source, two lengths.
const tileDesc = {
  prompt:'Describe the job in plain words; a proven technique is picked and the prompt written for you.',
  report:'The scorecard for the prompt as it stands, example by example.',
  comparison:'Every recommended technique scored side by side on the same examples.',
  optimization:'Rewrites the prompt over several rounds and keeps whichever version scores best.',
  'dataset-library':'Every set available to this server — bundled, uploaded, imported, or built here.',
  'dataset-hub':'No examples of your own? Find a public dataset whose material resembles your task.',
  'dataset-builder':'Generate edge cases and mutations. Nothing becomes truth before you approve it.',
  history:'Every run this server has recorded, newest first, with a version-to-version diff.',
  judge:'Two answers, one rubric, order hidden from the judge.',
  'model-matrix':'The same prompt on several models, to catch wording that only works on one.',
  'context-lab':'Same prompt, different context — documents, memory, retrieval, compressed.',
  analysis:'Is the difference real? Confidence intervals and per-slice scores, so noise does not become a decision.',
  regressions:'Better or worse? Two recorded runs against the quality and the speed you are willing to lose.',
  reviews:'Generated examples, judge decisions, regressions and releases needing a yes or no.',
  releases:'Draft → tested → approved → production, with a rollback that restores the previous prompt.',
  production:'Input drift, agent runs, and injection attempts — three checks on what happens in production.',
  techniques:'Every method with its own task and a real prompt compiled from the live registry.',
  logs:'What is running right now, and what every finished run did.',
  settings:'Two models: one writes the prompt, one runs the tests.',
  evaluation:'What the scores mean, and when a number is worth trusting.',
  help:'How the whole thing fits together, start to finish.'
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
      const unreviewed = state.quality.projects.reduce((total, project) =>
        total + project.examples.filter(item => item.status === 'unreviewed').length, 0);
      return unreviewed ? ['wait', `${plural(unreviewed, 'example')} unreviewed`] : ['idle', 'Nothing generated'];
    }
    case 'history': return state.experiments.length ? ['ok', `${plural(state.experiments.length, 'run')}`] : ['idle', 'No runs yet'];
    case 'analysis': return state.report ? ['idle', 'Ready'] : ['wait', 'Needs a run'];
    case 'regressions': return state.experiments.length > 1 ? ['idle', 'Ready'] : ['wait', 'Needs 2 runs'];
    case 'reviews': {
      const pending = state.quality.reviews.filter(item => item.status === 'pending').length;
      return pending ? ['wait', `${pending} waiting for you`] : ['idle', 'Nothing waiting'];
    }
    case 'releases': return state.quality.releases.length ? ['ok', `${plural(state.quality.releases.length, 'release')}`] : ['idle', 'None yet'];
    case 'techniques': return state.techniqueCatalog.size ? ['idle', `${state.techniqueCatalog.size}`] : ['idle', 'Loading…'];
    case 'settings': return [state.settings.evaluation.model_id.trim() ? 'ok' : 'wait', state.settings.evaluation.model_id.trim() || 'No model set'];
    case 'dataset-hub': return ['idle', 'Needs internet'];
    case 'judge': return screenResultState('judge');
    case 'model-matrix': return screenResultState('model-matrix');
    case 'context-lab': return screenResultState('context-lab');
    case 'production': return ['idle', '3 tools'];
    case 'logs': {
      const running = state.jobs.filter(job => job.status === 'running').length;
      return running ? ['wait', `${plural(running, 'job')} running`] : ['idle', 'Idle'];
    }
    case 'evaluation': case 'help': return ['idle', 'Reading'];
    default: return null;
  }
}

function screenTile(tab) {
  const [, name] = screenMeta[tab];
  const lead = tileDesc[tab] || screenMeta[tab][2];
  const chip = screenState(tab);
  return `<a class="tile" href="#${tab}" data-global-tab="${tab}" data-screen="${tab}">
      <span class="tile-top">${icon(screenIcons[tab] || 'pencil')}<strong>${esc(name)}</strong></span>
      <span class="tile-lead">${esc(lead || '')}</span>
      ${chip ? `<span class="tile-foot"><span class="state ${chip[0]}">${esc(chip[1])}</span></span>` : ''}
    </a>`;
}

function renderSection(tab) {
  const section = tab.slice(2);
  const group = document.querySelector(`.sidebar-group[data-section="${section}"]`);
  const screens = group ? [...group.querySelectorAll('.sidebar-links a')].map(link => link.dataset.screen) : [];
  return `<div class="tiles">${screens.map(screenTile).join('')}</div>`;
}

function renderHome() {
  return `<div class="tiles">
      <div class="tile wide smart-tile">
        <span class="smart-mark" aria-hidden="true">${icon('sparkle')}</span>
        <div>
          <strong>Smart run</strong>
          <p>Writes the prompt, measures it on your examples, improves it over a few rounds, and stops at the first step that needs you. Minutes, not seconds.</p>
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
  if (tab === 'report') body = state.report ? renderReport(state.report) : renderBenchmarkPrerequisites();
  if (tab === 'comparison' && state.comparison) body = renderComparison(state.comparison);
  if (tab === 'optimization' && state.optimization) body = renderOptimization(state.optimization);
  if (tab === 'dataset-hub') body = renderDatasetHub();
  if (tab === 'techniques') body = renderTechniqueCatalog();
  if (tab === 'logs') body = renderLogs();
  if (tab === 'history') body = renderHistory();
  if (tab === 'settings') body = renderSettings();
  if (platformTabs.includes(tab)) body = renderPlatformTab(tab);
  if (docPages[tab]) {
    const [src, title] = docPages[tab];
    body = `<iframe class="doc-frame" src="${src}" title="${title}"></iframe>`;
  }
  return body;
}

function renderBenchmarkPrerequisites() {
  const checks = [
    ['Prompt selected', Boolean(state.program)],
    ['Dataset selected', Boolean($('dataset')?.value)],
    ['Model configured', Boolean(state.settings.evaluation.model_id.trim())]
  ];
  return `<section class="benchmark-setup" data-testid="benchmark-prerequisites" aria-labelledby="benchmark-setup-title">
    <span class="section-eyebrow">Ready the run</span>
    <h2 id="benchmark-setup-title">Benchmark setup</h2>
    <p class="meta">Confirm the inputs, then open the measurement controls to run this prompt against representative examples.</p>
    <ul class="setup-checklist">${checks.map(([label, ready]) => `<li class="${ready ? 'ready' : ''}"><span aria-hidden="true"></span>${esc(label)}<small>${ready ? 'Ready' : 'Required'}</small></li>`).join('')}</ul>
    <button type="button" class="primary setup-benchmark" data-action="setup-benchmark" data-testid="setup-benchmark">Set up benchmark</button>
  </section>`;
}

function ensureDetailShell() {
  if ($('detail').querySelector('.detail-panels')) return;
  // No tab strip: a prompt's measurements are screens with names of their own,
  // listed once in the rail and once as tiles on their section. A strip here
  // would be a third place to reach them, under a fourth set of labels.
  const panels = detailPanels.map(key => `<section class="tab-panel" id="screen-panel-${key}" data-tab-panel="${key}" data-screen="${key}" data-testid="screen-${key}" hidden></section>`).join('');
  $('detail').innerHTML = `<div class="detail-panels">${panels}</div>`;
}

function fitDocFrame(frame) {
  const doc = frame.contentDocument;
  if (!doc) { frame.style.height = '80vh'; return; }
  const main = doc.querySelector('main');
  if (main) main.style.margin = '0 auto 8px';
  const resize = () => { frame.style.height = `${doc.documentElement.scrollHeight + 8}px`; };
  resize();
  window.setTimeout(resize, 60);
  if (window.ResizeObserver && doc.body) new ResizeObserver(resize).observe(doc.body);
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
  if (tab === 'settings') {
    hydrateSettingsSecrets();
    ['engine', 'evaluation'].forEach(loadInstalledModels);
    wireProfileControls(panel);
  }
  if (docPages[tab]) {
    const frame = panel.querySelector('.doc-frame');
    if (frame) frame.addEventListener('load', () => fitDocFrame(frame));
  }
  if (tab === 'logs') {
    const refresh = panel.querySelector('.log-refresh');
    if (refresh) refresh.addEventListener('click', () => refreshLogs(true));
    panel.querySelectorAll('.log-job').forEach(item => item.addEventListener('toggle', () => {
      if (item.open) state.openLogs.add(item.dataset.jobId);
      else state.openLogs.delete(item.dataset.jobId);
    }));
  }
  if (tab === 'home' || sectionTabs.includes(tab)) {
    panel.querySelectorAll('[data-global-tab]').forEach(link => link.addEventListener('click', event => {
      event.preventDefault(); selectTab(link.dataset.globalTab, {focus:true});
    }));
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
  if (tab === 'dataset-hub') wireDatasetHub(panel);
  if (tab === 'history') wireHistoryControls(panel);
  if (platformTabs.includes(tab)) wirePlatformTab(tab, panel);
  panel.querySelector('[data-action="setup-benchmark"]')?.addEventListener('click', () => {
    const steps = $('prompt-steps');
    if (!steps) return;
    steps.scrollIntoView({behavior:'smooth', block:'start'});
    window.requestAnimationFrame(() => $('dataset')?.focus({preventScroll:true}));
  });
}

function activateDetailTab() {
  ensureDetailShell();
  if (resultTabs.includes(state.tab)) state.lastResultTab = state.tab;
  // Only the screen you write on keeps the composer beside it. A measurement is
  // something you read, so it gets the full width, like every other screen.
  const globalView = state.tab !== 'prompt';
  $('workspace-layout').classList.toggle('global-view', globalView);
  $('workspace-layout').dataset.screen = state.tab;
  // Recommendations belong to the authored prompt, not to the measurements taken on it.
  $('results').hidden = state.tab !== 'prompt';
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
    const active = isBottom ? tab === primary : tab === state.tab || (tab === 'prompt' && resultTabs.includes(state.tab));
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
  const section = sectionOf(tab);
  if (section) trail.push([`s-${section}`, screenMeta[`s-${section}`][1]]);
  if (!sectionTabs.includes(tab)) trail.push([tab, (screenMeta[tab] || screenMeta.home)[1]]);
  return trail;
}

function renderCrumbs(tab) {
  const trail = crumbTrail(tab);
  const parent = trail.length > 1 ? trail[trail.length - 2][0] : null;
  $('crumbs').innerHTML = trail.slice(0, -1).map(([target, label]) =>
    `<button type="button" data-crumb="${target}">${esc(label)}</button>${icon('chevron')}`).join('');
  const back = $('back-button');
  if (back) { back.hidden = !parent; back.dataset.crumb = parent || ''; if (!back.firstChild) back.innerHTML = icon('chevronLeft'); }
}

function updateWorkspaceContext() {
  const [, title] = screenMeta[state.tab] || screenMeta.home;
  renderCrumbs(state.tab);
  document.title = `${title} · Prompt Playoff`;
  const technique = state.program?.technique_id || state.chosen;
  const prompt = technique ? (state.techniqueCatalog.get(technique)?.title || technique) : 'Draft';
  const dataset = $('dataset')?.value || 'Not selected';
  const model = state.settings.evaluation.model_id.trim() || 'Not set';
  [['context-prompt', prompt], ['context-dataset', dataset], ['context-model', model], ['rail-model-name', model]].forEach(([id, value]) => { const node=$(id); if (node) node.textContent=value; });
  applyModelGate();
  renderSectionCounts();
}

function selectTab(tab, options={}) {
  tab = normalizedTab(tab);
  const targetHash = `#${tab}`;
  if (options.syncUrl !== false && window.location.hash !== targetHash) {
    window.history[options.replace ? 'replaceState' : 'pushState']({screen:tab}, '', targetHash);
  }
  state.tab = tab;
  if (state.logTimer) { window.clearTimeout(state.logTimer); state.logTimer = null; }
  ensureDetailShell();
  const panel = $('detail').querySelector(`[data-tab-panel="${tab}"]`);
  const platformNeedsLoad = platformTabs.includes(tab) && !state.quality.loaded.has(tab);
  if (panel && (panel.dataset.rendered !== 'true' || (tab === 'report' && !state.report))) {
    renderDetailPanel(tab, platformNeedsLoad ? '<div class="empty">Loading…</div>' : detailBody(tab));
  }
  activateDetailTab();
  if (tab === 'logs') refreshLogs();
  if (tab === 'history') refreshHistory();
  if (platformNeedsLoad) refreshPlatformTab(tab);
  if (options.focus) $('main-content')?.focus({preventScroll:true});
}

function initializeNavigation() {
  const requested = decodeURIComponent(window.location.hash.slice(1)).split('/').pop();
  const tab = tabFromLocation();
  if (!requested || normalizedTab(requested) !== requested) {
    window.history.replaceState({screen:tab}, '', `#${tab}`);
  }
  selectTab(tab, {syncUrl:false});
}

window.addEventListener('popstate', () => selectTab(tabFromLocation(), {syncUrl:false}));
window.addEventListener('hashchange', () => {
  const tab = tabFromLocation();
  if (tab !== state.tab) selectTab(tab, {syncUrl:false});
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
  if (!state.jobs.length || manual) state.logStatus = 'loading';
  state.logError = '';
  if (manual || !state.jobs.length) renderDetail();
  try {
    state.jobs = await api('/v1/jobs');
    state.logStatus = 'ready';
    if (!state.logsInitialized && state.jobs.length) {
      state.openLogs.add(state.jobs[0].id);
      state.logsInitialized = true;
    }
  } catch (e) {
    state.logStatus = 'error';
    state.logError = e.message;
  }
  if (state.tab !== 'logs') return;
  if (manual || previous !== JSON.stringify(state.jobs) || previousStatus !== state.logStatus || state.logError) renderDetail();
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
  const toolbar = `<div class="meta log-status">${status}</div>`;
  if (state.logError) return `${toolbar}<div class="error">Could not load logs: ${esc(state.logError)}</div>`;
  if (!state.jobs.length) return `${toolbar}<div class="empty">No benchmark, comparison, or optimization runs yet.</div>`;
  const jobs = state.jobs.map(job => {
    const lines = (job.events || []).map(logEvent);
    if (!lines.length) lines.push(`[${logClock(job.created_at)}] event=queued`);
    return `<details class="log-job" data-job-id="${esc(job.id)}" ${state.openLogs.has(job.id) ? 'open' : ''}>
      <summary><span class="log-status ${esc(job.status)}">${esc(job.status)}</span><span class="log-kind">${esc(job.kind)}</span><span class="log-id">${esc(job.id)}</span><span class="log-time">${esc(logClock(job.created_at))}</span></summary>
      ${job.error ? `<div class="log-error">${esc(job.error)}</div>` : ''}
      <pre class="log-lines">${esc(lines.join('\n'))}</pre>
    </details>`;
  }).join('');
  return toolbar + jobs;
}

async function refreshHistory() {
  try { state.experiments = await api('/v1/experiments'); }
  catch (e) { state.experiments = []; state.experimentComparison = {error:e.message}; }
  if (state.tab === 'history') renderDetailPanel('history');
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

function renderHistory() {
  if (!state.experiments.length) return '<div class="empty">No recorded benchmarks, comparisons, or optimizations yet.</div>';
  // One row per measured variant, numbers unformatted. The server writes the
  // file; the link only names it.
  const options = state.experiments.map(item => `<option value="${esc(item.id)}">${esc(item.created_at)} · ${esc(item.kind)} v${item.version} · ${esc(item.model_id)}</option>`).join('');
  const rows = state.experiments.map(item => { const m = experimentMetric(item); return `<tr><td>v${item.version}</td><td>${esc(historyDate(item.created_at))}</td><td>${esc(item.kind)}</td><td>${esc(item.model_id)}</td><td>${esc(item.dataset)}</td><td>${m ? m.quality.toFixed(3) : '—'}</td><td>${m ? m.mean_latency_seconds.toFixed(2) : '—'}</td><td>${m && m.mean_cost_usd != null ? `$${m.mean_cost_usd.toFixed(6)}` : 'unknown'}</td></tr>`; }).join('');
  return `${historyChart(state.experiments)}
    <div class="quality-form"><label for="history-before">Before<select id="history-before">${options}</select></label><label for="history-after">After<select id="history-after">${options}</select></label></div>
    <div class="form-actions"><button type="button" class="primary history-compare">Compare versions</button></div>
    ${renderExperimentComparison(state.experimentComparison)}
    <p class="table-scroll-hint" id="history-scroll-hint">Scroll the table horizontally to inspect every measurement.</p>
    <div class="table-scroll" role="region" aria-label="Experiment history table" aria-describedby="history-scroll-hint" tabindex="0"><table><thead><tr><th>Version</th><th>Recorded</th><th>Kind</th><th>Model</th><th>Dataset</th><th>Quality</th><th>Latency s</th><th>Mean cost</th></tr></thead><tbody>${rows}</tbody></table></div>`;
}

function wireHistoryControls(panel) {
  const before = panel.querySelector('#history-before'); const after = panel.querySelector('#history-after');
  if (before && state.experiments[1]) before.value = state.experiments[1].id;
  panel.querySelector('.history-compare')?.addEventListener('click', async () => {
    try { state.experimentComparison = await api('/v1/experiments/compare', {before_id:before.value, after_id:after.value}); }
    catch (e) { state.experimentComparison = {error:e.message}; }
    renderDetailPanel('history');
  });
}

// One prompt per screen: the text is the product, so everything around it stays
// quiet. The only accent on this view is the copy button that gets it out.
