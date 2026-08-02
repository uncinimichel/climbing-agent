/* The sport dial.
 *
 * Geometry is derived from however many domains are registered — the wedge
 * angle was hardcoded to 72° (five sports) and is now 360/n, so adding golf
 * re-cuts the dial rather than breaking it.
 */
Fieldwork.Dial = (function () {
  const NS = 'http://www.w3.org/2000/svg';
  /* one source of truth for the dial's geometry */
  const C = 200, R_OUT = 176, R_IN = 96, GAP = 2.4, POP = 10;
  const R_MID = (R_OUT + R_IN) / 2;   // wedge centroid ring
  const ICO = 28, ICO_DY = -13, LAB_DY = 17;

  const esc = s => String(s).replace(/[&<>"]/g, c =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const pt = (r, a) => {
    const t = (a - 90) * Math.PI / 180;
    return [C + r * Math.cos(t), C + r * Math.sin(t)];
  };
  const f = n => Math.round(n * 100) / 100;

  const WORDS = ['zero', 'one', 'two', 'three', 'four', 'five',
                 'six', 'seven', 'eight', 'nine', 'ten'];
  const word = n => WORDS[n] || String(n);

  /* Each domain ships its own 24×24 icon; they become <symbol>s in one sprite. */
  function sprite(domains) {
    const svg = document.createElementNS(NS, 'svg');
    svg.setAttribute('width', '0');
    svg.setAttribute('height', '0');
    svg.setAttribute('aria-hidden', 'true');
    svg.style.position = 'absolute';
    svg.innerHTML = domains.map(d =>
      `<symbol id="i-${d.key}" viewBox="0 0 24 24">${d.icon}</symbol>`).join('') +
      '<symbol id="i-arr" viewBox="0 0 24 24"><path d="M5 12h13"/><path d="m12 6 6 6-6 6"/></symbol>';
    document.body.appendChild(svg);
  }

  function build(opts) {
    const domains = Fieldwork.all();
    const keys = domains.map(d => d.key);
    const step = 360 / domains.length;
    const slices = document.getElementById(opts.slices);
    const ptr = document.getElementById(opts.pointer);
    const hub = document.getElementById(opts.hub);
    const hubN = document.getElementById(opts.hubName);
    const hubS = document.getElementById(opts.hubStatus);
    const hint = document.getElementById(opts.hint);
    const wrapEl = document.getElementById(opts.wrap);

    sprite(domains);

    domains.forEach((d, i) => {
      const mid = i * step;
      const a1 = mid - step / 2 + GAP / 2, a2 = mid + step / 2 - GAP / 2;
      const [x1, y1] = pt(R_OUT, a1), [x2, y2] = pt(R_OUT, a2);
      const [x3, y3] = pt(R_IN, a2), [x4, y4] = pt(R_IN, a1);
      /* icon and label stack vertically in SCREEN space, from the wedge centroid,
         so the order reads the same on every wedge — radial placement flips it. */
      const [cx, cy] = pt(R_MID, mid);
      const [dx, dy] = [Math.sin(mid * Math.PI / 180) * POP,
                        -Math.cos(mid * Math.PI / 180) * POP];

      const g = document.createElementNS(NS, 'g');
      g.setAttribute('class', 'sl');
      g.setAttribute('role', 'tab');
      g.setAttribute('tabindex', d.key === opts.initial ? '0' : '-1');
      g.setAttribute('aria-label', `${d.label} — ${d.status}`);
      g.dataset.k = d.key;
      g.style.setProperty('--dx', f(dx) + 'px');
      g.style.setProperty('--dy', f(dy) + 'px');
      g.innerHTML =
        `<path class="wedge" d="M${f(x1)} ${f(y1)} A${R_OUT} ${R_OUT} 0 0 1 ${f(x2)} ${f(y2)} ` +
        `L${f(x3)} ${f(y3)} A${R_IN} ${R_IN} 0 0 0 ${f(x4)} ${f(y4)} Z"/>` +
        `<use class="ico" href="#i-${d.key}" x="${f(cx - ICO / 2)}" y="${f(cy + ICO_DY - ICO / 2)}" ` +
        `width="${ICO}" height="${ICO}"/>` +
        `<text class="lab" x="${f(cx)}" y="${f(cy + LAB_DY)}" text-anchor="middle">` +
        `${esc(d.short || d.label)}</text>`;
      slices.appendChild(g);
    });

    const tabs = [...slices.querySelectorAll('.sl')];
    let current = opts.initial;
    let timer = null, paused = false;
    const still = matchMedia('(prefers-reduced-motion: reduce)').matches;

    function setHint(auto) {
      hint.innerHTML = auto
        ? `<span class="auto">●</span> Cycling through all ${word(domains.length)}. ` +
          '<b>Click a wedge</b> to take over.'
        : `${word(domains.length).replace(/^./, c => c.toUpperCase())} sports, one method. ` +
          '<b>Click a wedge</b> to load its board.';
    }

    function select(key, focus) {
      current = key;
      const i = keys.indexOf(key), d = Fieldwork.get(key);
      tabs.forEach(t => {
        const on = t.dataset.k === key;
        t.classList.toggle('on', on);
        t.setAttribute('aria-selected', on ? 'true' : 'false');
        t.setAttribute('tabindex', on ? '0' : '-1');
        if (on && focus) t.focus();
      });
      ptr.style.transform = `rotate(${i * step}deg)`;
      hubN.textContent = d.label;
      hubS.textContent = d.status;
      hubS.classList.toggle('live', d.status === 'Live');
      hub.classList.remove('flip'); void hub.offsetWidth; hub.classList.add('flip');
      opts.onSelect(d);
    }

    function stopAuto() {
      if (timer) clearInterval(timer);
      timer = null;
      setHint(false);
    }
    function startAuto() {
      if (still) { setHint(false); return; }
      setHint(true);
      timer = setInterval(() => {
        if (!paused) select(keys[(keys.indexOf(current) + 1) % keys.length]);
      }, 4200);
    }

    tabs.forEach(t => t.addEventListener('click', () => { stopAuto(); select(t.dataset.k); }));
    slices.addEventListener('keydown', e => {
      const i = keys.indexOf(current);
      let n = null;
      if (e.key === 'ArrowRight' || e.key === 'ArrowDown') n = (i + 1) % keys.length;
      if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') n = (i - 1 + keys.length) % keys.length;
      if (e.key === 'Home') n = 0;
      if (e.key === 'End') n = keys.length - 1;
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); stopAuto(); return; }
      if (n !== null) { e.preventDefault(); stopAuto(); select(keys[n], true); }
    });

    wrapEl.addEventListener('pointerenter', () => { paused = true; });
    wrapEl.addEventListener('pointerleave', () => { paused = false; });

    select(opts.initial);
    startAuto();
    return { select, stopAuto };
  }

  return { build, esc, word };
})();
