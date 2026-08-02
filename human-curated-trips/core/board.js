/* The ranked board.
 *
 * One renderer for every sport. It reads only the shape a domain promises —
 * label, weights, dials, picks — and never branches on which sport it is. The
 * single conditional is whether the domain has a real board to link through to
 * (`href`), which is a fact about the pipeline, not about the sport.
 */
Fieldwork.Board = (function () {
  const esc = Fieldwork.Dial.esc;

  function render(d, el) {
    el.sport.textContent = d.label;
    el.weights.innerHTML = 'Weighted first for ' + d.label.toLowerCase() + ': <b>' +
      d.weights.map(esc).join('</b> and <b>') + '</b>. Then flights, beds and chatter.';
    el.count.textContent = d.picks.length + ' places on the board · watched daily';

    /* a live sport links straight through to its real, running board */
    el.live.innerHTML = d.href
      ? `<a class="golive" href="${esc(d.href)}">${esc(d.cta)}` +
        '<svg class="arr" width="19" height="19" aria-hidden="true" style="stroke:currentColor;' +
        'fill:none;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round">' +
        '<use href="#i-arr"/></svg></a>'
      : `<p class="soon">${esc(d.soon || '')}</p>`;

    el.board.innerHTML = d.picks.map((p, i) => `
    <article class="row in${i === 0 ? ' top' : ''}" style="animation-delay:${i * 55}ms">
      <div class="rk">${String(i + 1).padStart(2, '0')}</div>
      <div class="dest"><span class="nm">${esc(p.nm)}</span><span class="cc">${esc(p.cc)}</span></div>
      <div class="win"><span>Best window</span>${esc(p.win)}</div>
      <div class="dials">
        ${p.bars.map((b, j) => `
          <div class="dl${j < 2 ? ' key' : ''}">
            <div class="trk"><div class="fil" data-h="${Math.round(b * 100)}"
              style="transition-delay:${i * 55 + j * 45}ms"></div></div>
            <small>${esc(d.dials[j])}</small>
          </div>`).join('')}
      </div>
      <div class="sc">${p.sc}</div>
      <p class="note"><span class="by">${esc(p.by)}</span>${esc(p.note)}</p>
    </article>`).join('');

    requestAnimationFrame(() => {
      el.board.querySelectorAll('.fil').forEach(f => { f.style.height = f.dataset.h + '%'; });
    });
  }

  return { render };
})();
