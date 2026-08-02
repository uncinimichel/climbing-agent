"""The domain registry — discovery only, deliberately not a behavioural contract.

An earlier draft of this file was a fat `Sport` Protocol: every domain had to
supply day_score, climo_score, signals, fit, composite weights. That was a
mistake, and the reason is worth writing down so it does not get re-invented:

  A shared behavioural interface makes every domain a stakeholder in every
  other domain's changes. Give climbing a sixth dial and the protocol grows a
  method; now ski and golf must answer a question nobody asked them. Worse, no
  single person — or agent — can hold one sport in their head any more, because
  the shape of their code is decided somewhere else.

So a domain owes core nothing except a name. Ranking, curves, dials, weights and
rendering are entirely its own business, and two sports that happen to score
rain the same way are expected to say so twice. That duplication is the price of
being able to work on golf without reading a line of climbing — and it is worth
paying.

What core DOES provide is infrastructure a domain would otherwise re-implement
badly: weather providers and payload parsing, tides, flights, stays, caching,
HTTP with retry/redaction, the trip context. Fetching is a solved problem;
judging is the product.
"""
from dataclasses import dataclass, field

_REGISTRY: dict[str, "Domain"] = {}


@dataclass(frozen=True)
class Domain:
    """A sport's entry in the registry. Data only — nothing here is called."""
    key: str                       # stable slug + package name: domains/<key>/
    label: str                     # human name for the UI
    status: str = "in curation"    # "live" | "in curation" | free text
    blurb: str = ""                # one line: what this domain ranks, and on what
    owns: tuple = field(default_factory=tuple)   # the modules that are its own


def register(domain):
    """Record a domain. Called from domains/<key>/__init__.py, so importing the
    package is all it takes to make the sport discoverable."""
    if domain.key in _REGISTRY and _REGISTRY[domain.key] != domain:
        raise ValueError(f"domain key already registered: {domain.key!r}")
    _REGISTRY[domain.key] = domain
    return domain


def get(key):
    """The registered Domain for `key`, importing its package on demand so
    callers never have to know the import order."""
    if key not in _REGISTRY:
        try:
            __import__(f"domains.{key}")
        except ImportError as e:
            raise KeyError(f"no domain package for {key!r}") from e
    if key not in _REGISTRY:
        raise KeyError(f"domains.{key} did not register a domain named {key!r}")
    return _REGISTRY[key]


def registered():
    """Every domain registered so far, in registration order."""
    return dict(_REGISTRY)
