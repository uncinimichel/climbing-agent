/* Wiring: dial → board, scroll reveals, and the counts in the prose.
 *
 * The sport count is derived from the registry rather than typed into the copy.
 * It was hardcoded as "five" in six different places, which is exactly the kind
 * of thing that goes stale the first time someone adds a sport.
 */
(function () {
  const el = {
    sport: document.getElementById('b-sport'),
    weights: document.getElementById('weights'),
    count: document.getElementById('b-count'),
    live: document.getElementById('b-live'),
    board: document.getElementById('board'),
  };

  /* counts that must never drift from what is actually registered */
  const n = Fieldwork.all().length;
  const word = Fieldwork.Dial.word(n);
  const fill = {
    sports: word,
    Sports: word.replace(/^./, c => c.toUpperCase()),
    sportsNum: String(n),
    live: String(Fieldwork.live().length),
  };
  document.querySelectorAll('[data-fw]').forEach(node => {
    const v = fill[node.dataset.fw];
    if (v !== undefined) node.textContent = v;
  });

  Fieldwork.Dial.build({
    slices: 'slices', pointer: 'ptr', hub: 'hub',
    hubName: 'hub-n', hubStatus: 'hub-s',
    hint: 'dialhint', wrap: 'dialwrap',
    initial: 'climbing',
    onSelect: d => Fieldwork.Board.render(d, el),
  });

  const io = new IntersectionObserver(es => {
    es.forEach(e => {
      if (e.isIntersecting) { e.target.classList.add('on'); io.unobserve(e.target); }
    });
  }, { threshold: .12 });
  document.querySelectorAll('.reveal').forEach(node => io.observe(node));
})();
