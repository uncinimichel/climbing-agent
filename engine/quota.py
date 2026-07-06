"""Quota-safety seams for engine.flights — interfaces only. The real
DynamoDB-backed budget tracking and shared cross-user flight-price cache
(ClimbingAgentQuota / ClimbingAgentFlightCache, per the plan's milestone M3)
are a later milestone; this module only defines the protocol plus the
permissive, no-op implementations the cron driver uses so its behavior is
completely unchanged by this refactor — attach_flights always priced flights
without any budget check or cross-run shared cache before, and it still does.
"""


class QuotaGuard:
    """can_spend(n) gates a SerpApi search before it happens; record_spend(n)
    reports it afterwards. A real implementation (M3) checks a global daily/
    monthly budget; this protocol is what engine.flights.price_top_venues()
    is written against."""

    def can_spend(self, n=1):
        raise NotImplementedError

    def record_spend(self, n=1):
        raise NotImplementedError


class AlwaysAllowQuotaGuard(QuotaGuard):
    """No budget tracking at all — matches today's cron, which has never had
    a quota guard and prices every top-N venue's flights unconditionally."""

    def can_spend(self, n=1):
        return True

    def record_spend(self, n=1):
        pass


class FlightCache:
    """Shared (route, date-combo) -> priced-options cache, checked before
    spending a SerpApi search. A real implementation (M3's
    ClimbingAgentFlightCache) shares results across every user's trips; this
    protocol is what engine.flights.price_top_venues() is written against."""

    def get(self, route_key, dates_key):
        raise NotImplementedError

    def set(self, route_key, dates_key, value):
        raise NotImplementedError


class NullFlightCache(FlightCache):
    """Always a miss, never stores — matches today's cron, which has no
    shared result cache and calls serp_flights() fresh for every venue/
    traveller pair every run (its only reuse is prev_prices, the previous
    run's flights-latest.json, handled separately in price_top_venues)."""

    def get(self, route_key, dates_key):
        return None

    def set(self, route_key, dates_key, value):
        pass
