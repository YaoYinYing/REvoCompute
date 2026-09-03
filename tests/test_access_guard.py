from __future__ import annotations

from revocompute import access_guard


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.expiries = {}

    def incr(self, key):
        self.values[key] = int(self.values.get(key, 0)) + 1
        return self.values[key]

    def expire(self, key, seconds):
        self.expiries[key] = seconds
        return True

    def ttl(self, key):
        return self.expiries.get(key, -2) if key in self.values else -2

    def setex(self, key, seconds, value):
        self.values[key] = value
        self.expiries[key] = seconds

    def set(self, key, value, *, nx=False, ex=None):
        if nx and key in self.values:
            return False
        self.values[key] = value
        if ex:
            self.expiries[key] = ex
        return True

    def delete(self, *keys):
        for key in keys:
            self.values.pop(key, None)
            self.expiries.pop(key, None)


def test_progressive_thresholds_and_bounded_window(monkeypatch):
    redis = FakeRedis()
    monkeypatch.setattr(access_guard, "get_redis", lambda: redis)
    user, policy = 7, "alphafold3_noncommercial"
    for expected in (1, 2):
        state = access_guard.record_denial(user, policy)
        assert state.denial_count == expected
        assert not state.active
    assert access_guard.record_denial(user, policy).retry_after_seconds == 30
    for _ in range(2):
        state = access_guard.record_denial(user, policy)
    assert state.retry_after_seconds == 300
    for _ in range(3):
        state = access_guard.record_denial(user, policy)
    assert state.retry_after_seconds == 1800
    for _ in range(2):
        state = access_guard.record_denial(user, policy)
    assert state.retry_after_seconds == 3600
    assert access_guard.active_suspension(user, policy).active


def test_blocked_audit_marker_aggregates(monkeypatch):
    redis = FakeRedis()
    monkeypatch.setattr(access_guard, "get_redis", lambda: redis)
    assert access_guard.mark_blocked_event(1, "p")
    assert not access_guard.mark_blocked_event(1, "p")
    access_guard.clear_policy_state(1, "p")
    assert access_guard.mark_blocked_event(1, "p")


def test_redis_failure_falls_back_without_changing_denial_semantics(monkeypatch):
    monkeypatch.setattr(access_guard, "get_redis", lambda: None)
    access_guard.reset_memory_state()
    for _ in range(2):
        assert not access_guard.record_denial(22, "p").active
    assert access_guard.record_denial(22, "p").active
    access_guard.clear_policy_state(22, "p")
    assert not access_guard.active_suspension(22, "p").active
