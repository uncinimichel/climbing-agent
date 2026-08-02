/* Golf — wind first, then how fast the course drains after rain.
 *
 * The two lead signals are deliberately not "weather is nice". A dry, mild day
 * with 45 km/h gusts is a bad round, and an hour of rain means nothing on links
 * sand and ruins a parkland course for a day. That judgement lives here and in
 * domains/golf/conditions.py — never in core.
 */
Fieldwork.domain({
  key: 'golf',
  label: 'Golf',
  status: 'In curation',
  icon: '<path d="M12 20V3"/><path d="M12 3.5 19 6.5 12 10"/>' +
        '<path d="M7 21h11"/><circle cx="8" cy="18.5" r="1.6"/>',
  weights: ['wind on the exposed holes', 'how fast the course drains'],
  dials: ['Wind', 'Course', 'Fly', 'Beds', 'Buzz'],
  soon: 'Golf is in curation. Iain and Rui are playing each course in its shoulder season before it goes on the board — how a links plays in July tells you nothing about how it plays in April.',
  picks: [
    { nm: 'Algarve', cc: 'Portugal', sc: 91, win: '6–13 Feb', bars: [.78, .88, .84, .80, .62],
      by: 'Rui P. · Algarve',
      note: 'Winter golf that actually plays: 18°C, firm fairways and a tee time you can still book on the day. Avoid half-term — go either side of it.' },
    { nm: 'East Lothian', cc: 'Scotland', sc: 86, win: '11–18 May', bars: [.55, .92, .70, .66, .74],
      by: 'Iain F. · Gullane',
      note: 'Ten links inside twenty minutes, and the wind decides which one you play. Book nothing until the Thursday forecast, then book the sheltered one.' },
    { nm: 'County Down', cc: 'Northern Ireland', sc: 82, win: '1–8 Jun', bars: [.58, .90, .68, .72, .58],
      by: 'Dan K. · Belfast',
      note: 'The best links in these islands, and you can get on it midweek if you ask properly and well ahead. Bring a low ball flight and no ego.' },
    { nm: 'Costa del Sol', cc: 'Spain', sc: 77, win: '20–27 Feb', bars: [.72, .80, .86, .74, .50],
      by: 'Rui P. · Algarve',
      note: 'Reliable rather than thrilling, and everything is a drive from everything else. Worth it in February, when nothing north of the Pyrenees is playable.' }
  ]
});
