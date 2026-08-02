/* Ski — resorts, ranked on snow depth and lift status first. */
Fieldwork.domain({
  key: 'ski',
  label: 'Ski',
  status: 'Opening Nov',
  icon: '<path d="M4 20h16"/><path d="M7 20 15 4"/><path d="M12 20 20 4"/><path d="M9.5 12h7"/>',
  weights: ['snow depth', 'lift status'],
  dials: ['Snow', 'Lifts', 'Fly', 'Beds', 'Buzz'],
  soon: 'Ski opens in November. All four are written up — Elin is re-checking the lift and snow records before they go live.',
  picks: [
    { nm: 'Sainte-Foy', cc: 'France', sc: 91, win: '6–10 Feb', bars: [.95, .80, .72, .86, .58],
      by: 'Elin H. · Chamonix',
      note: "One lift, no queue, and the north face holds powder for days after Val d'Isère is tracked out. Go midweek or not at all." },
    { nm: 'Andermatt', cc: 'Switzerland', sc: 84, win: '20–24 Jan', bars: [.92, .88, .61, .34, .70],
      by: 'Elin H. · Chamonix',
      note: 'The best snow record in the Alps and the worst bed prices. Only book it when the forecast is already good.' },
    { nm: 'Bansko', cc: 'Bulgaria', sc: 79, win: '13–17 Jan', bars: [.68, .55, .90, .96, .44],
      by: 'Elin H. · Chamonix',
      note: "The cheapest week you'll ever ski. The gondola queue is real — first lift, or write the morning off." },
    { nm: 'Kaprun', cc: 'Austria', sc: 74, win: '27 Nov–1 Dec', bars: [.80, .75, .66, .62, .40],
      by: 'Elin H. · Chamonix',
      note: "Glacier, so it's open when nothing else is. Flat, though. Bring a plan for day three." }
  ]
});
