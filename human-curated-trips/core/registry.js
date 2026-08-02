/* The domain registry — the only thing core knows about sports.
 *
 * Each domains/<sport>.js calls Fieldwork.domain({...}) with its own data and
 * copy. Nothing in core/ contains a sport name, a destination or a curator
 * note, so adding a sport is one new file plus one <script> tag, and two people
 * adding two sports never touch the same file.
 *
 * Plain script rather than an ES module on purpose: this page has to open from
 * file:// as a design prototype, and module imports are blocked there.
 */
window.Fieldwork = (function () {
  const order = [];
  const byKey = Object.create(null);

  const REQUIRED = ['key', 'label', 'icon', 'weights', 'dials', 'picks'];

  function domain(spec) {
    for (const f of REQUIRED) {
      if (spec[f] == null) throw new Error(`domain "${spec.key || '?'}" is missing ${f}`);
    }
    if (byKey[spec.key]) throw new Error(`domain already registered: ${spec.key}`);
    if (spec.dials.length !== 5) {
      throw new Error(`domain "${spec.key}": expected 5 dials, got ${spec.dials.length}`);
    }
    // A sport is live only if it has a real board to link through to.
    spec.status = spec.status || (spec.href ? 'Live' : 'In curation');
    byKey[spec.key] = spec;
    order.push(spec.key);
    return spec;
  }

  const get = key => byKey[key];
  const all = () => order.map(k => byKey[k]);
  const live = () => all().filter(d => d.href);

  /* Curators are declared by the domains that employ them, then deduped here —
     so the tally on the page can never drift from the boards above it. */
  function curators() {
    const seen = new Map();
    for (const d of all()) {
      for (const p of d.picks) {
        if (!seen.has(p.by)) seen.set(p.by, { by: p.by, sports: new Set() });
        seen.get(p.by).sports.add(d.label);
      }
    }
    return [...seen.values()];
  }

  return { domain, get, all, live, curators, order };
})();
