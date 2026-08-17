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
