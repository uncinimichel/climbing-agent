"""Shared headless-browser fetch helper (Playwright/Chromium) for sources
whose Cloudflare bot-protection blocks plain HTTP clients — theCrag hard-
blocks, UKC 403s with a JS "Just a moment" challenge even with a realistic
browser User-Agent (verified live 2026-07-06). Scraping these two is done
with Michel's direct permission from both site owners — see the decision log
in knowledge/roadmap/ingestion-plan.md.

BrowserSession keeps one Chromium instance alive across many fetches (a fresh
launch per page is ~1-2s overhead — wasteful over a day-long crawl).
"""
from __future__ import annotations

from playwright.sync_api import sync_playwright

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


class BrowserSession:
    def __enter__(self) -> "BrowserSession":
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=True)
        return self

    def __exit__(self, *exc) -> None:
        self._browser.close()
        self._pw.stop()

    def fetch(self, url: str, wait_ms: int = 5000, timeout_ms: int = 30000) -> str:
        """Rendered HTML after the page settles. wait_ms is a fixed settle
        delay rather than `wait_until="networkidle"` — UKC/theCrag keep
        background requests (ads, analytics) alive indefinitely, which makes
        networkidle time out."""
        page = self._browser.new_page(user_agent=USER_AGENT)
        try:
            page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
            page.wait_for_timeout(wait_ms)
            return page.content()
        finally:
            page.close()
