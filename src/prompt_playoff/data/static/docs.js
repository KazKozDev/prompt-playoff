/* --------------------------------------------------------------------------
 * The contents strip both reading screens carry.
 *
 * Twelve sections and ten thousand pixels is the same problem the technique
 * catalogue has, and the app already answered it there: an index at the top,
 * one line per thing, so a reader can see the whole shape before scrolling and
 * jump to the part they came for. Built from the headings rather than written
 * out in each file, because four documents in two languages is four places for
 * an index to disagree with the page under it.
 * -------------------------------------------------------------------------- */
(() => {
  const main = document.querySelector('main');
  if (!main) return;
  const ru = document.documentElement.lang === 'ru';
  const slug = text => text.toLowerCase().replace(/[^\p{L}\p{N}]+/gu, '-').replace(/^-|-$/g, '');
  const seen = new Set();
  const idFor = head => {
    let id = head.id || slug(head.textContent) || 'section';
    while (seen.has(id)) id += '-2';
    seen.add(id);
    head.id = id;
    return id;
  };

  if (main.classList.contains('page')) {
    // The two-plate guides carry an empty rail; fill it from the article's
    // headings so the list cannot drift from the page. A rail that already
    // has links (Prompt vs Fine-Tuning) is left alone.
    const toc = main.querySelector(':scope > .toc');
    const heads = [...main.querySelectorAll('.content > h2')];
    if (toc && heads.length && !toc.querySelector('a')) {
      heads.forEach((head, index) => {
        const link = document.createElement('a');
        link.href = `#${idFor(head)}`;
        link.textContent = `${index + 1}. ${head.textContent}`;
        toc.append(link);
      });
    }
  } else {
    const heads = [...main.querySelectorAll(':scope > h2')];
    // Two or three sections read fine as they are; an index is for a document
    // long enough that the reader has lost the shape of it.
    if (heads.length >= 5) {
      const links = heads.map(head => {
        const link = document.createElement('a');
        link.href = `#${idFor(head)}`;
        link.textContent = head.textContent;
        return link;
      });
      const nav = document.createElement('nav');
      nav.className = 'doc-index';
      nav.setAttribute('aria-label', ru ? 'Содержание' : 'On this page');
      const title = document.createElement('div');
      title.className = 'doc-index-title';
      title.textContent = ru ? 'На этой странице' : 'On this page';
      const list = document.createElement('div');
      list.className = 'doc-index-links';
      links.forEach(link => list.append(link));
      nav.append(title, list);
      const head = main.querySelector('.doc-head');
      head ? head.after(nav) : main.prepend(nav);
    }
  }

  // Inside the app the frame is drawn at the full height of this document, so
  // it has nothing to scroll and a bare #anchor moves nothing. The page that
  // scrolls is the one holding the frame, and it is same-origin, so the jump is
  // made there — measured from where the frame sits on it.
  document.addEventListener('click', event => {
    const link = event.target.closest('a[href^="#"]');
    if (!link || event.defaultPrevented || event.metaKey || event.ctrlKey || event.shiftKey) return;
    const target = document.getElementById(decodeURIComponent(link.hash.slice(1)));
    if (!target) return;
    event.preventDefault();
    const behavior = matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth';
    const top = target.getBoundingClientRect().top;
    try {
      const frame = window.frameElement;
      if (frame && window.parent !== window) {
        const parentTop = frame.getBoundingClientRect().top + window.parent.scrollY + top - 16;
        window.parent.scrollTo({ top: parentTop, behavior });
        return;
      }
    } catch (error) { /* another origin owns the frame: scroll ourselves instead */ }
    target.scrollIntoView({ behavior, block: 'start' });
  });

  if (document.documentElement.classList.contains('embed')) {
    document.querySelectorAll('a.lang, a.lang-switch').forEach(link => {
      if (link.search.indexOf('embed') === -1) {
        link.search += (link.search ? '&' : '') + 'embed';
      }
    });
  }
})();

/* The guide's own contents rail, when the page is read on its own. Inside the
 * app the parent owns that rail; here the document scrolls, so the spy can
 * live on this window. Same mark as the sidebar: the current section, a gold
 * edge. */
(() => {
  const toc = document.querySelector('main.page .toc');
  if (!toc || document.documentElement.classList.contains('embed')) return;
  const links = [...toc.querySelectorAll('a[href^="#"]')];
  const sections = links.map(link => document.getElementById(decodeURIComponent(link.hash.slice(1)))).filter(Boolean);
  if (!sections.length) return;
  const tick = () => {
    let current = sections[0];
    sections.forEach(section => {
      if (section.getBoundingClientRect().top <= 120) current = section;
    });
    if (!current) current = sections[0];
    links.forEach(link => {
      if (current && link.hash === `#${current.id}`) link.setAttribute('aria-current', 'true');
      else link.removeAttribute('aria-current');
    });
  };
  tick();
  window.addEventListener('scroll', tick, { passive:true });
})();
