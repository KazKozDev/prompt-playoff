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
  const heads = [...main.querySelectorAll(':scope > h2')];
  // Two or three sections read fine as they are; an index is for a document
  // long enough that the reader has lost the shape of it.
  if (heads.length < 5) return;

  const slug = text => text.toLowerCase().replace(/[^\p{L}\p{N}]+/gu, '-').replace(/^-|-$/g, '');
  const seen = new Set();
  const links = heads.map(head => {
    let id = head.id || slug(head.textContent) || 'section';
    while (seen.has(id)) id += '-2';
    seen.add(id);
    head.id = id;
    const link = document.createElement('a');
    link.href = `#${id}`;
    link.textContent = head.textContent;
    return link;
  });

  const ru = document.documentElement.lang === 'ru';
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
})();
