"""
Monthly quota manager for Google Places API (New) billing.

Pricing model (as of 2025):
  - Places Text Search (Pro SKU): 5,000 free requests per month
  - Beyond free tier: ~$32 per 1,000 requests ($0.032 per call)

Each page of results (up to 20 places) counts as one API call.
Pagination can yield up to 3 pages (60 results) per zip code search.
"""

from datetime import datetime
from typing import Dict

from lib.database import get_api_usage, increment_api_calls

FREE_LIMIT: int = 5_000
PAID_COST_PER_CALL: float = 0.032  # $32 / 1,000 calls


class QuotaManager:
    """
    Tracks monthly free/paid API usage against the database and enforces limits.

    Usage:
        quota = QuotaManager(db_path, allow_paid=False)
        if quota.can_make_calls(call_count):
            ... make API calls ...
            quota.record_calls(call_count)
    """

    def __init__(
        self,
        db_path: str,
        allow_paid: bool = False,
        max_spend: float = 50.0,
    ) -> None:
        self.db_path = db_path
        self.allow_paid = allow_paid
        self.max_spend = max_spend
        self._sync()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _sync(self) -> None:
        """Refresh the in-memory counters from the database."""
        now = datetime.now()
        self._year = now.year
        self._month = now.month
        usage = get_api_usage(self.db_path, self._year, self._month)
        self._free_used: int = usage["free_calls"]
        self._paid_used: int = usage["paid_calls"]

    def _maybe_roll_month(self) -> None:
        """Re-sync if the calendar month has changed (long-running processes)."""
        now = datetime.now()
        if now.year != self._year or now.month != self._month:
            self._sync()

    # ------------------------------------------------------------------
    # Public properties
    # ------------------------------------------------------------------

    @property
    def free_used(self) -> int:
        self._maybe_roll_month()
        return self._free_used

    @property
    def paid_used(self) -> int:
        self._maybe_roll_month()
        return self._paid_used

    @property
    def free_remaining(self) -> int:
        return max(0, FREE_LIMIT - self.free_used)

    @property
    def estimated_cost(self) -> float:
        return self.paid_used * PAID_COST_PER_CALL

    @property
    def spend_remaining(self) -> float:
        return max(0.0, self.max_spend - self.estimated_cost)

    # ------------------------------------------------------------------
    # Core quota logic
    # ------------------------------------------------------------------

    def can_make_calls(self, count: int = 1) -> bool:
        """
        Return True if `count` more API calls are allowed under current limits.

        Free tier is consumed first; paid tier is only allowed when
        --allow-paid is set and the dollar spend cap has not been reached.
        """
        self._maybe_roll_month()
        if self.free_remaining >= count:
            return True
        if not self.allow_paid:
            return False
        # Check if the remaining calls would exceed the spend cap
        paid_calls_needed = count - self.free_remaining
        projected_cost = self.estimated_cost + paid_calls_needed * PAID_COST_PER_CALL
        return projected_cost <= self.max_spend

    def record_calls(self, count: int) -> None:
        """
        Persist `count` API calls to the database, allocating to free tier
        first and overflow to paid tier.
        """
        self._maybe_roll_month()
        free_available = self.free_remaining
        free_now = min(count, free_available)
        paid_now = max(0, count - free_now)

        increment_api_calls(
            self.db_path,
            self._year,
            self._month,
            free_count=free_now,
            paid_count=paid_now,
        )
        self._sync()

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def get_stats(self) -> Dict:
        """Return a snapshot of current quota state."""
        self._maybe_roll_month()
        return {
            "year":            self._year,
            "month":           self._month,
            "free_used":       self._free_used,
            "free_limit":      FREE_LIMIT,
            "free_remaining":  self.free_remaining,
            "paid_used":       self._paid_used,
            "estimated_cost":  self.estimated_cost,
            "allow_paid":      self.allow_paid,
            "max_spend":       self.max_spend if self.allow_paid else None,
            "spend_remaining": self.spend_remaining if self.allow_paid else None,
        }
