/* Cycling — rain risk first, then wind on the exposed sections. */
Fieldwork.domain({
  key: 'cycling',
  label: 'Cycling',
  status: 'In curation',
  icon: '<circle cx="5.5" cy="15" r="3.5"/><circle cx="18.5" cy="15" r="3.5"/>' +
        '<path d="M5.5 15 10 6h5l3.5 9"/><path d="M9 6h5"/>',
  weights: ['rain risk', 'wind on the exposed sections'],
  dials: ['Rain', 'Wind', 'Fly', 'Beds', 'Buzz'],
  soon: 'Cycling is in curation. Ana is riding each route herself before it goes on the board.',
  picks: [
    { nm: 'Girona', cc: 'Spain', sc: 92, win: '20–27 Mar', bars: [.88, .82, .84, .86, .90],
      by: 'Michel U. · London',
      note: 'Gradients, coffee and a train to the airport. Rides start from the front door, which is the whole argument.' },
    { nm: 'Mallorca', cc: 'Spain', sc: 87, win: '6–13 Mar', bars: [.86, .76, .88, .80, .84],
      by: 'Dan K. · Belfast',
      note: 'Sa Calobra is the postcard; the Orient valley is the ride. February to April, then it gets too hot to enjoy.' },
    { nm: 'Dolomites', cc: 'Italy', sc: 83, win: '12–19 Jun', bars: [.74, .70, .66, .72, .78],
      by: 'Michel U. · London',
      note: 'The passes are shut until late May. Once they open, nothing in Europe comes close. Check pass status, not just weather.' },
    { nm: 'Provence', cc: 'France', sc: 78, win: '2–9 May', bars: [.80, .52, .70, .74, .60],
      by: 'Ana L. · Girona',
      note: 'Ventoux is a day, not a week. Build the trip around the Gorges du Verdon and treat the mountain as the finale.' }
  ]
});
