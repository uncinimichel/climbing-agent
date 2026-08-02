/* Windsurfing — hours of usable wind, and how reliably it turns up. */
Fieldwork.domain({
  key: 'windsurfing',
  label: 'Windsurfing',
  short: 'Windsurf',
  status: 'In curation',
  icon: '<path d="M8 21V3"/><path d="M8 4c5 1 9 4 11 8-4 1.5-8 1.5-11 1"/><path d="M5 21h8"/>',
  weights: ['wind hours per day', 'gust consistency'],
  dials: ['Wind', 'Gust', 'Fly', 'Beds', 'Buzz'],
  soon: 'Windsurfing is in curation. Jonas is working through the summer wind records spot by spot.',
  picks: [
    { nm: 'Tarifa', cc: 'Spain', sc: 90, win: '8–15 Jul', bars: [.96, .78, .74, .70, .80],
      by: 'Jonas R. · Tarifa',
      note: 'Levante blows most summer afternoons and it is not gentle. Poniente weeks are the friendly ones — check which one you booked.' },
    { nm: 'Vassiliki', cc: 'Greece', sc: 86, win: '1–8 Aug', bars: [.88, .92, .60, .76, .68],
      by: 'Jonas R. · Tarifa',
      note: 'The most reliable thermal in Europe and the easiest place to learn on. Dead every morning, by design — that is the point.' },
    { nm: 'Pozo Izquierdo', cc: 'Gran Canaria', sc: 81, win: '18–25 Jul', bars: [.98, .58, .72, .66, .62],
      by: 'Jonas R. · Tarifa',
      note: 'Overpowered and unforgiving. Small sails and some experience, or you will spend the week swimming.' },
    { nm: 'Karpathos', cc: 'Greece', sc: 75, win: '22–29 Jun', bars: [.90, .74, .44, .72, .38],
      by: 'Jonas R. · Tarifa',
      note: 'Big wind, small island. The trip works if you are happy sailing and doing very little else.' }
  ]
});
