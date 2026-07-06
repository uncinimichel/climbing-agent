"""Shared HTTP fetch + secret-redaction helpers used by weather.py, flights.py
and stays.py — moved verbatim from update_report.py's module-level `_get`/
`_redact`, just parameterized on an optional secret instead of reading the
SERPAPI_KEY global."""
import json
import time
import urllib.error
import urllib.request

USER_AGENT = "climbing-agent/1.0 (github.com/uncinimichel/climbing-agent)"


def redact(s, secret=None):
    """Strip `secret` (e.g. the SerpApi key) out of any string before it
    reaches a log or exception — a key can ride in a query string, so raw
    urllib error text would otherwise leak it."""
    s = str(s)
    return s.replace(secret, "***") if secret else s


def get_json(url, retries=4, redact_secret=None):
    """GET JSON with retries — APIs rate-limit bursts; never silently lose a
    sample. Client errors (4xx: bad key/params) are NOT retried — retrying
    can't fix them and just burns time × venues. Errors are re-raised with the
    secret redacted. A real User-Agent is required by some providers (Overpass
    406s on Python's default)."""
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=45) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            last = e
            if 400 <= e.code < 500:
                break
        except Exception as e:
            last = e
        if attempt < retries - 1:
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"GET {redact(url, redact_secret)} failed: {redact(last, redact_secret)}")
