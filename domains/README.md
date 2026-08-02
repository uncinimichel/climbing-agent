# domains/ — one folder per sport

Each folder is a **bounded context**: everything that encodes a judgement about
one sport, and nothing else. The point is that a person — or an agent — can be
handed `domains/golf/` and be productive without reading a line of climbing.

## The two rules

**1. `core/` is infrastructure. Domains own all judgement.**

| Goes in `core/` | Goes in `domains/<sport>/` |
|---|---|
| fetching weather, tides, flights, stays, chatter | what "a good day" means |
| parsing provider payloads into per-date records | scoring curves and thresholds |
| HTTP retry, redaction, caching, geo maths | which dials the UI shows |
| the trip context (dates, travellers) | how weather/travel/fit trade off |
| the domain registry | rendering, venue data, tie-breaks |

The test: if answering the question needs the word *climbing* (or *golf*, or
*ski*), it is not core. Fetching is a solved problem; judging is the product.

**2. A domain never imports another domain.**

Two sports that score rain the same way are expected to say so twice. That
duplication is deliberate — it is what lets golf's curves change without anyone
re-checking climbing, and what keeps parallel work on different sports from
colliding in a shared file.

There is no base class and no behavioural interface to implement. A domain
registers a name (`core.sport.Domain`) so the site can list it, and is otherwise
free to be shaped however that sport actually works.

## What's here

| Domain | Status | Owns |
|---|---|---|
| `climbing/` | live | conditions, weights, climbs, venues, scoring, render, site_index, driver |
| `ski/` | opening Nov | conditions — blocked on resort feeds for base depth + lift status |
| `golf/` | in curation | conditions, weights — needs a curated course list |

## Adding a sport

1. `domains/<key>/__init__.py` — register a `Domain(key=..., label=..., status=...)`.
2. `domains/<key>/conditions.py` — your curves. Start from the physical signals
   `core.weather.metrics.forecast_metrics(payload, active_hours)` gives you, and
   decide what they mean for your sport. Do not copy another domain's thresholds
   because they look close.
3. Add the sport to the front page: `human-curated-trips/domains/<key>.js`.

Only step 3 touches a shared file, and it is a data file.
