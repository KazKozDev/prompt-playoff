async function writeClipboard(text) {
  if (navigator.clipboard && window.isSecureContext) {
    await navigator.clipboard.writeText(text);
    return;
  }
  const fallback = document.createElement('textarea');
  fallback.value = text;
  fallback.setAttribute('readonly', '');
  fallback.style.position = 'fixed';
  fallback.style.opacity = '0';
  document.body.appendChild(fallback);
  fallback.select();
  const copied = document.execCommand('copy');
  fallback.remove();
  if (!copied) throw new Error('Clipboard access was denied');
}

function copyStatusNode(key) {
  const statusKey = key.startsWith('compiled:') ? 'compiled' : key.split(':').slice(0, 2).join(':');
  return [...document.querySelectorAll('[data-copy-status]')].find(node => node.dataset.copyStatus === statusKey);
}

function downloadText(filename, content, type='text/plain') {
  const url = URL.createObjectURL(new Blob([content], {type}));
  const link = document.createElement('a'); link.href = url; link.download = filename;
  document.body.appendChild(link); link.click(); link.remove(); URL.revokeObjectURL(url);
}

// Delegation keeps copy and retry controls functional after recommendation,
// disclosure, tab, and source-toggle rerenders.
document.addEventListener('click', async event => {
  const retry = event.target.closest('.retry-catalog');
  if (retry) {
    retry.disabled = true;
    retry.textContent = 'Loading';
    await loadTechniqueCatalog();
    return;
  }

  // Taking the worked examples back out is a local edit: they are separate
  // messages, so removing them leaves the text the person wrote, unchanged.
  const dropDemos = event.target.closest('[data-action="drop-demos"]');
  if (dropDemos) {
    state.program = {...state.program, stages: state.program.stages.map(stage =>
      ({...stage, messages: (stage.messages || []).filter(message => !message.demo)}))};
    // The numbers were measured with them in, so they no longer describe this.
    state.provenance = null;
    renderDetail();
    return;
  }

  const runtimeExport = event.target.closest('[data-runtime-export]');
  if (runtimeExport) {
    runtimeExport.disabled = true;
    const original = runtimeExport.textContent;
    try {
      const bundle = await api('/v1/export/runtime', {
        task:await taskProfile(), technique_id:state.program.technique_id,
        language:runtimeExport.dataset.runtimeExport
      });
      downloadText(bundle.filename, bundle.content);
      window.setTimeout(() => downloadText(bundle.config_filename, bundle.config, 'application/json'), 150);
      // A technique this server holds rather than one the package ships has to
      // travel with the client, or the export only runs on the machine it was
      // made on. The note in the bundle says what to do with it.
      if (bundle.technique) {
        window.setTimeout(() => downloadText(bundle.technique_filename, bundle.technique, 'text/yaml'), 300);
      }
      runtimeExport.textContent = 'Exported';
    } catch (e) { runtimeExport.textContent = 'Export failed'; runtimeExport.title = e.message; }
    finally { window.setTimeout(() => { runtimeExport.disabled = false; runtimeExport.textContent = original; }, 1800); }
    return;
  }

  const button = event.target.closest('[data-copy-key]');
  if (!button) return;
  const key = button.dataset.copyKey;
  const status = copyStatusNode(key);
  const originalLabel = button.textContent;
  button.disabled = true;
  try {
    if (!state.copyPayloads.has(key)) throw new Error('Copy content is no longer available');
    await writeClipboard(state.copyPayloads.get(key));
    button.textContent = 'Copied';
    if (status) {
      status.className = 'copy-status success';
      status.textContent = 'Copied to clipboard.';
    }
  } catch (e) {
    button.textContent = 'Copy failed';
    if (status) {
      status.className = 'copy-status error-text';
      status.textContent = `Could not copy: ${e.message}`;
    }
  } finally {
    window.setTimeout(() => {
      if (button.isConnected) {
        button.disabled = false;
        button.textContent = originalLabel;
      }
    }, 1600);
  }
});
