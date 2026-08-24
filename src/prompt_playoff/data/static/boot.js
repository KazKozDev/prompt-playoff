wireSmartStart(document.querySelector('.rail-smart-start'), document.querySelector('.rail-smart-status'));
refreshRailDatasetField();

loadTechniqueCatalog();
loadGraderHelp();
loadDatasets();
loadBackends();
loadProfiles();
// Fetched here, not only when the library screen opens: the "Fits your task"
// group on the dataset field needs it from the first prompt anyone writes.
loadBusinessCatalog().then(() => refreshDatasetSuggestions());
// Before the first render, so the screens draw the prompt this browser was
// already holding rather than drawing an empty one and correcting itself.
restoreDraft();
refreshActions();
initializeNavigation();
