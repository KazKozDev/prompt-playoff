document.querySelector('.rail-smart-mark')?.insertAdjacentHTML('afterbegin', icon('sparkle'));
wireSmartStart(document.querySelector('.rail-smart-start'), document.querySelector('.rail-smart-status'));

['dataset', 'repeats', 'rounds'].forEach(id => {
  $(id).addEventListener('input', () => { updateEstimates(); updateWorkspaceContext(); });
  $(id).addEventListener('change', () => { updateEstimates(); updateWorkspaceContext(); });
});

loadTechniqueCatalog();
loadGraderHelp();
loadDatasets();
loadBackends();
loadProfiles();
refreshActions();
initializeNavigation();
