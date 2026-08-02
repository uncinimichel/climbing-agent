/* Climbing — the one sport whose board is actually running.
   `href` is what makes it live: it links through to the real ranked board that
   domains/climbing/ (the Python domain) rebuilds every morning. */
Fieldwork.domain({
  key: 'climbing',
  label: 'Climbing',
  status: 'Live',
  href: '../index.html',
  cta: 'Climbing is live — open the real board, three winter weekends ranked',
  icon: '<path d="M6 21V6l6-3 6 6v12"/><path d="M6 12h6"/><path d="M12 3v18"/>',
  weights: ['hours of dry rock', 'temperature window'],
  dials: ['Dry', 'Temp', 'Fly', 'Beds', 'Buzz'],
  picks: [
    { nm: 'Kalymnos', cc: 'Greece', sc: 89, win: '10–17 Oct', bars: [.93, .88, .64, .90, .76],
      by: 'Michel U. · London',
      note: "Autumn, not summer. Skip Grande Grotta at midday — that's a queue, not a crag. Ferries thin out after early November." },
    { nm: 'El Chorro', cc: 'Spain', sc: 85, win: '28 Nov–2 Dec', bars: [.88, .82, .78, .72, .55],
      by: 'Dan K. · Belfast',
      note: 'Winter sun that actually delivers. The Makinodromo needs a still day — check the wind, not just the temperature.' },
    { nm: 'Finale Ligure', cc: 'Italy', sc: 80, win: '14–18 Nov', bars: [.79, .85, .58, .80, .48],
      by: 'Michel U. · London',
      note: 'Best value in Europe if you can drive. The classics are polished glass; the newer sectors are where the climbing is.' },
    { nm: 'Costa Blanca', cc: 'Spain', sc: 76, win: '5–9 Dec', bars: [.86, .80, .74, .66, .40],
      by: 'Michel U. · London',
      note: "Reliable, but everything good is forty minutes from everything else. Don't come without a car." }
  ]
});
