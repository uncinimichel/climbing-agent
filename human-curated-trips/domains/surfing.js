/* Surfing — swell size and period first, then what the wind does to it. */
Fieldwork.domain({
  key: 'surfing',
  label: 'Surfing',
  status: 'In curation',
  icon: '<path d="M2 16c3.5 0 3.5-3 7-3s3.5 3 7 3 3.5-3 6-3"/>' +
        '<path d="M2 20c3.5 0 3.5-2 7-2s3.5 2 7 2 3.5-2 6-2"/>' +
        '<path d="M9 12c1-5 4-8 8-9-1 4-1 7-2 9"/>',
  weights: ['swell size & period', 'wind direction'],
  dials: ['Swell', 'Wind', 'Fly', 'Beds', 'Buzz'],
  soon: 'Surfing is in curation. Sofia and Dan are still checking these four against a full season before the board opens.',
  picks: [
    { nm: 'Ericeira', cc: 'Portugal', sc: 88, win: '3–10 Oct', bars: [.90, .84, .76, .82, .72],
      by: 'Sofia M. · Ericeira',
      note: 'Six breaks in ten minutes of driving, so a bad wind direction never kills the day. Ribeira d’Ilhas when it’s big.' },
    { nm: 'Hossegor', cc: 'France', sc: 82, win: '12–16 Sep', bars: [.94, .62, .70, .68, .66],
      by: 'Sofia M. · Ericeira',
      note: 'September: the swell is back and the crowds have gone. The banks move after every storm — ask at the shop each morning.' },
    { nm: 'Lanzarote', cc: 'Spain', sc: 78, win: '16–23 Jan', bars: [.82, .55, .80, .74, .50],
      by: 'Jonas R. · Tarifa',
      note: 'Waves all winter, wind that can ruin a week. Stay north — the south is a different island entirely.' },
    { nm: 'Bundoran', cc: 'Ireland', sc: 71, win: '24–28 Oct', bars: [.85, .60, .72, .78, .30],
      by: 'Dan K. · Belfast',
      note: 'Cold, empty, genuinely world class. You need a 5/4, a hood, and a tolerance for horizontal rain.' }
  ]
});
