from mcrag.service.ratelimit import RateLimiter


class Clock:
    def __init__(self, t=1_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


def test_a_client_is_limited_per_minute_and_recovers():
    clock = Clock()
    rl = RateLimiter(per_minute=2, daily_cap=100, clock=clock)
    assert rl.check("a") is None and rl.check("a") is None
    assert rl.check("a") == "too many requests"
    assert rl.check("b") is None  # another client is unaffected
    clock.t += 61
    assert rl.check("a") is None


def test_the_daily_cap_applies_across_clients_and_resets_next_day():
    clock = Clock()
    rl = RateLimiter(per_minute=100, daily_cap=2, clock=clock)
    assert rl.check("a") is None and rl.check("b") is None
    assert rl.check("c") == "daily limit reached"
    clock.t += 86400
    assert rl.check("c") is None


def test_a_refused_request_does_not_use_up_the_budget():
    clock = Clock()
    rl = RateLimiter(per_minute=1, daily_cap=2, clock=clock)
    assert rl.check("a") is None
    for _ in range(5):
        assert rl.check("a") == "too many requests"
    assert rl.check("b") is None  # still 1 of 2 left for the day, not 0
