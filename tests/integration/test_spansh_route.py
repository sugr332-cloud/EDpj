from __future__ import annotations

from dataclasses import dataclass, field

from app.collectors.spansh_route import plot_route


@dataclass
class FakeResponse:
    status_code: int
    _json: dict

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            import httpx

            raise httpx.HTTPStatusError("error", request=None, response=None)

    def json(self) -> dict:
        return self._json


@dataclass
class FakeRouteClient:
    post_response: FakeResponse
    poll_responses: list[FakeResponse] = field(default_factory=list)
    poll_index: int = 0
    sleeps: list[float] = field(default_factory=list)

    def post(self, url, *, params=None, timeout=None):
        return self.post_response

    def get(self, url, *, timeout=None):
        response = self.poll_responses[self.poll_index]
        self.poll_index = min(self.poll_index + 1, len(self.poll_responses) - 1)
        return response


def _no_sleep(seconds: float) -> None:
    pass


COMPLETED_RESULT = {
    "state": "completed",
    "status": "ok",
    "result": {"total_jumps": 1, "distance": 4.377, "source_system": "Sol", "destination_system": "Alpha Centauri"},
}


class TestPlotRoute:
    def test_successful_route_after_one_queued_poll(self):
        client = FakeRouteClient(
            post_response=FakeResponse(202, {"job": "abc123", "status": "queued"}),
            poll_responses=[FakeResponse(202, {"status": "queued"}), FakeResponse(200, COMPLETED_RESULT)],
        )

        result = plot_route("Sol", "Alpha Centauri", 25.0, client, sleep_fn=_no_sleep)

        assert result == {"total_jumps": 1, "distance_ly": 4.377}

    def test_submit_failure_returns_none(self):
        client = FakeRouteClient(post_response=FakeResponse(400, {}))

        result = plot_route("Nowhere", "Alpha Centauri", 25.0, client, sleep_fn=_no_sleep)

        assert result is None

    def test_missing_job_id_returns_none(self):
        client = FakeRouteClient(post_response=FakeResponse(202, {"status": "queued"}))

        result = plot_route("Sol", "Alpha Centauri", 25.0, client, sleep_fn=_no_sleep)

        assert result is None

    def test_unexpected_status_code_returns_none(self):
        client = FakeRouteClient(
            post_response=FakeResponse(202, {"job": "abc123"}),
            poll_responses=[FakeResponse(500, {})],
        )

        result = plot_route("Sol", "Alpha Centauri", 25.0, client, sleep_fn=_no_sleep)

        assert result is None

    def test_times_out_waiting_for_completion(self):
        client = FakeRouteClient(
            post_response=FakeResponse(202, {"job": "abc123"}),
            poll_responses=[FakeResponse(202, {"status": "queued"})],
        )

        result = plot_route("Sol", "Alpha Centauri", 25.0, client, sleep_fn=_no_sleep, max_polls=3)

        assert result is None

    def test_completed_response_missing_result_returns_none(self):
        client = FakeRouteClient(
            post_response=FakeResponse(202, {"job": "abc123"}),
            poll_responses=[FakeResponse(200, {"state": "completed", "status": "ok"})],
        )

        result = plot_route("Sol", "Alpha Centauri", 25.0, client, sleep_fn=_no_sleep)

        assert result is None

    def test_uses_injected_sleep_function_not_real_time(self):
        sleeps = []
        client = FakeRouteClient(
            post_response=FakeResponse(202, {"job": "abc123"}),
            poll_responses=[FakeResponse(200, COMPLETED_RESULT)],
        )

        plot_route("Sol", "Alpha Centauri", 25.0, client, sleep_fn=lambda s: sleeps.append(s))

        assert sleeps == [1.0]
