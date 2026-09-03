# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Progressive cooldowns for repeated restricted-runner denials.

Entitlement checks remain the caller's responsibility.  This module only
tracks denial pressure and active temporary suspensions.  Redis is preferred
so all web workers share state; an unavailable Redis server degrades abuse
tracking to per-process memory without ever turning a denial into an allow.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from revocompute.redis_util import get_redis

ABUSE_WINDOW_SECONDS = 60 * 60
# (minimum denial count, suspension duration), kept centralized for review.
ESCALATION_THRESHOLDS: tuple[tuple[int, int], ...] = (
    (10, 60 * 60),
    (8, 30 * 60),
    (5, 5 * 60),
    (3, 30),
)


@dataclass(frozen=True)
class SuspensionState:
    """Current cooldown state after a denial or blocked request."""

    active: bool
    retry_after_seconds: int = 0
    denial_count: int = 0
    newly_suspended: bool = False


_lock = threading.Lock()
_memory_counts: dict[str, tuple[int, float]] = {}
_memory_suspensions: dict[str, float] = {}
_memory_block_markers: dict[str, float] = {}


def _key(user_id: int, policy_id: str, suffix: str) -> str:
    return f"runner-abuse:{user_id}:{policy_id}:{suffix}"


def _ttl(value: int | float | None) -> int:
    try:
        return max(int(value or 0), 0)
    except (TypeError, ValueError):
        return 0


def active_suspension(user_id: int, policy_id: str) -> SuspensionState:
    """Return active suspension state without mutating denial counters."""
    redis_client = get_redis()
    if redis_client is not None:
        try:
            remaining = _ttl(redis_client.ttl(_key(user_id, policy_id, "suspension")))
            return SuspensionState(active=remaining > 0, retry_after_seconds=remaining)
        except Exception:
            pass
    now = time.monotonic()
    key = _key(user_id, policy_id, "suspension")
    with _lock:
        expiry = _memory_suspensions.get(key, 0.0)
        if expiry <= now:
            _memory_suspensions.pop(key, None)
            return SuspensionState(active=False)
        return SuspensionState(active=True, retry_after_seconds=max(int(expiry - now), 1))


def record_denial(user_id: int, policy_id: str) -> SuspensionState:
    """Register one missing-entitlement denial and apply escalation if needed."""
    counter_key = _key(user_id, policy_id, "denials")
    redis_client = get_redis()
    if redis_client is not None:
        try:
            count = int(redis_client.incr(counter_key))
            if count == 1:
                redis_client.expire(counter_key, ABUSE_WINDOW_SECONDS)
            duration = next((seconds for threshold, seconds in ESCALATION_THRESHOLDS if count >= threshold), 0)
            if duration:
                suspension_key = _key(user_id, policy_id, "suspension")
                # Refreshing the TTL at a threshold is intentional: repeated
                # attempts cannot shorten an active suspension.
                current = _ttl(redis_client.ttl(suspension_key))
                if current < duration:
                    redis_client.setex(suspension_key, duration, "1")
                remaining = max(current, duration)
                return SuspensionState(
                    active=True,
                    retry_after_seconds=remaining,
                    denial_count=count,
                    newly_suspended=current == 0,
                )
            return SuspensionState(active=False, denial_count=count)
        except Exception:
            # Fall through to local tracking.  Authorization is never decided
            # from this result; callers still return 403 on a denial.
            pass

    now = time.monotonic()
    with _lock:
        previous_count, started = _memory_counts.get(counter_key, (0, now))
        if now - started >= ABUSE_WINDOW_SECONDS:
            previous_count, started = 0, now
        count = previous_count + 1
        _memory_counts[counter_key] = (count, started)
        duration = next((seconds for threshold, seconds in ESCALATION_THRESHOLDS if count >= threshold), 0)
        if not duration:
            return SuspensionState(active=False, denial_count=count)
        suspension_key = _key(user_id, policy_id, "suspension")
        current_expiry = _memory_suspensions.get(suspension_key, 0.0)
        current = max(int(current_expiry - now), 0)
        if current < duration:
            _memory_suspensions[suspension_key] = now + duration
        return SuspensionState(
            active=True,
            retry_after_seconds=max(current, duration),
            denial_count=count,
            newly_suspended=current == 0,
        )


def mark_blocked_event(user_id: int, policy_id: str) -> bool:
    """Return true once per active suspension window for audit aggregation."""
    key = _key(user_id, policy_id, "blocked-audit")
    redis_client = get_redis()
    if redis_client is not None:
        try:
            if redis_client.set(key, "1", nx=True, ex=ABUSE_WINDOW_SECONDS):
                return True
            return False
        except Exception:
            pass
    now = time.monotonic()
    with _lock:
        expiry = _memory_block_markers.get(key, 0.0)
        if expiry > now:
            return False
        _memory_block_markers[key] = now + ABUSE_WINDOW_SECONDS
        return True


def clear_policy_state(user_id: int, policy_id: str) -> None:
    """Clear denial/cooldown state after full entitlement grant or admin action."""
    redis_client = get_redis()
    if redis_client is not None:
        try:
            redis_client.delete(
                _key(user_id, policy_id, "denials"),
                _key(user_id, policy_id, "suspension"),
                _key(user_id, policy_id, "blocked-audit"),
            )
            return
        except Exception:
            pass
    with _lock:
        for suffix, mapping in (
            ("denials", _memory_counts),
            ("suspension", _memory_suspensions),
            ("blocked-audit", _memory_block_markers),
        ):
            mapping.pop(_key(user_id, policy_id, suffix), None)


def reset_memory_state() -> None:
    """Test helper; production state is held by Redis TTLs."""
    with _lock:
        _memory_counts.clear()
        _memory_suspensions.clear()
        _memory_block_markers.clear()
