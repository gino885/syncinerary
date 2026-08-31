"""The destination's timezone, looked up rather than assumed to be Tokyo."""
from __future__ import annotations

import httpx
import pytest

from syncinerary.harness import run_tool
from syncinerary.tools.timezone import TimezoneLookupInput, make_timezone_tool


async def test_a_coordinate_resolves_to_its_iana_zone():
    def respond(request: httpx.Request) -> httpx.Response:
        assert request.url.params["location"] == "38.7223,-9.1393"
        assert request.url.params["timestamp"]
        return httpx.Response(
            200,
            json={
                "status": "OK",
                "timeZoneId": "Europe/Lisbon",
                "timeZoneName": "Western European Standard Time",
            },
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        result = await run_tool(
            make_timezone_tool(client=client, api_key="test-key"),
            TimezoneLookupInput(lat=38.7223, lng=-9.1393),
        )

    assert result.timezone == "Europe/Lisbon"


async def test_a_coordinate_in_the_ocean_has_no_zone():
    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "ZERO_RESULTS"}, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        result = await run_tool(
            make_timezone_tool(client=client, api_key="test-key"),
            TimezoneLookupInput(lat=0.0, lng=0.0),
        )

    assert result.timezone is None


async def test_a_provider_error_is_not_reported_as_an_unknown_timezone():
    from syncinerary.tools.timezone import TimezoneUnavailable

    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"status": "OVER_QUERY_LIMIT", "errorMessage": "Quota exhausted"},
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        with pytest.raises(TimezoneUnavailable, match="OVER_QUERY_LIMIT"):
            await run_tool(
                make_timezone_tool(client=client, api_key="test-key"),
                TimezoneLookupInput(lat=38.7223, lng=-9.1393),
            )


async def test_the_lookup_requires_a_configured_key():
    with pytest.raises(RuntimeError, match="GOOGLE_MAPS_API_KEY"):
        await run_tool(
            make_timezone_tool(api_key=""),
            TimezoneLookupInput(lat=38.7223, lng=-9.1393),
        )


async def test_the_solver_plans_against_the_trips_own_clock():
    """SolverOptions used to hardcode Asia/Tokyo for every trip."""
    from syncinerary.agents.solver.stage2_route import SolverOptions

    options = SolverOptions(timezone="Europe/Lisbon")

    assert options.timezone == "Europe/Lisbon"


async def test_an_unknown_timezone_is_refused_rather_than_silently_wrong():
    from zoneinfo import ZoneInfoNotFoundError

    from syncinerary.agents.solver.stage2_route import SolverOptions

    with pytest.raises(ZoneInfoNotFoundError):
        SolverOptions(timezone="Mars/Olympus_Mons")
