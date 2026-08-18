document.querySelector('.rail-smart-mark')?.insertAdjacentHTML('afterbegin', icon('sparkle'));
wireSmartStart(document.querySelector('.rail-smart-start'), document.querySelector('.rail-smart-status'));

loadTechniqueCatalog();
loadGraderHelp();
loadDatasets();
loadBackends();
loadProfiles();
refreshActions();
initializeNavigation();
