wireSmartStart(document.querySelector('.rail-smart-start'), document.querySelector('.rail-smart-status'));

loadTechniqueCatalog();
loadGraderHelp();
loadDatasets();
loadBackends();
loadProfiles();
// Before the first render, so the screens draw the prompt this browser was
// already holding rather than drawing an empty one and correcting itself.
restoreDraft();
refreshActions();
initializeNavigation();
