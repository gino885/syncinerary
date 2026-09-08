# M7j: Provider fallback for transit lookups

## The problem this is actually solving

A missing arc in the Stage 2 routing circuit does not mean "this leg is slow".
It means "these two places cannot be on the same day". M7g already found that
out the hard way: one Sapporo day was handed five places, every one of its
twenty pairs came back unroutable from the single configured provider, and the
day shipped with one stop and 645 spare minutes. The fix then was to estimate
city-scale pairs instead of dropping them, and that fix stays.

What the fix did not address is why the arcs went missing. Today
`make_transit_client()` picks exactly one provider from `SYNC_TRANSIT_PROVIDER`
and there is nothing behind it. A coverage gap, an HTTP 500, or an exhausted
quota all collapse to the same outcome: the solver falls straight through to a
distance estimate, or, past 30 km, to no arc at all. `provider_failed` is being
treated as `physically_unroutable`.

This work puts a chain behind the primary provider so an estimate is the last
resort rather than the second one, without coupling the solver to any country.

## What exists today (verified, not assumed)

| Question | Answer in this repo |
|---|---|
| Provider in use | Google **Routes API** `computeRouteMatrix` (`tools/transit/google_routes.py`), `travelMode: TRANSIT`. Not Directions, not Distance Matrix |
| Second provider | `tools/transit/transitous.py` exists but is an either/or prototype switch, not a fallback |
| Matrix requests built | `GoogleRoutesClient.prefetch_pairwise`, one matrix call per day, cached per directed leg in Redis |
| Abstraction | `TransitProvider` Protocol in `stage2_route.py` (`prefetch_pairwise` only); `make_transit_client()` in `tools/transit/provider.py` |
| Credentials | `settings.google_maps_api_key`, `settings.sync_transit_provider`. No HERE config anywhere |
| Departure time | `PairwiseTransitRequest.departure_at` (tz-aware, day_start on the trip date) plus `departure_window` string `YYYY-MM-DD-HHMM`, which is also the cache bucket |
| `_estimated_leg` | `stage2_route.py:316`, called from the arc loop at `stage2_route.py:531` when a pair is absent from the matrix |
| Provenance / UI label | `TransitDuration.provider` is folded into `transit_from_prev_mode` as `f"{mode}_{provider}"`, e.g. `transit_transitous`, and that string is persisted and sent to iOS. `TransitLegView` shows `approx.` for a `_estimated` suffix |

Two things fall out of that table:

1. There is already a normalized result type (`TransitDuration` /
   `TransitUnavailable` / `TransitMatrix`). No new parallel leg model is needed,
   only a `routing_status` field so an estimate is distinguishable from a route.
2. The provider name is already leaking to the client as `transit_transitous`.
   That has to stop before a second real provider makes it `transit_here`.

## Design

### Resolution order

```
Google Routes  ->  HERE Transit  ->  regional providers (registry, empty by default)
               ->  conservative city-scale estimate  ->  unroutable
```

Each step is only asked about the arcs the previous step left unresolved.

### Provider outcomes

Providers already report per-pair no-route through `TransitMatrix.unavailable`
and whole-request failures through typed exceptions. The chain needs to tell
those apart, so the existing exception trees get a shared base:

```
TransitProviderError            (new, in tools/transit/errors.py)
  RoutesError / TransitousError / HereError
```

with a `kind` of `no_route | provider_error | unsupported | rate_limited`.
Every one of them means "ask the next provider"; they differ only in what the
counters record. A provider with no credentials is never built, so an
unconfigured HERE is not an error at all.

### Only missing arcs go to the fallback

`PairwiseTransitRequest` gains `required_pairs: list[tuple[int, int]] | None`.
`None` keeps today's meaning (every directed transit pair). The resolver sends
the primary a full request, subtracts what came back, and builds the second
request over **only the locations still involved**, with `required_pairs` naming
the directed arcs. One matrix call for the primary, one bounded set of arcs for
the secondary. Walking-cutoff pairs are excluded from "unresolved" because the
clients deliberately never route them.

HERE has no transit matrix endpoint, so its adapter is one call per arc, run
with bounded concurrency and a hard arc cap. That is affordable precisely
because it only ever sees the leftovers.

### Estimation and the hard ceiling

`_estimated_leg`'s body moves to `tools/transit/estimate.py` as
`estimated_transit_leg()`, unchanged in behavior: walking pace under
`NEARBY_WALKING_KM`, `ESTIMATED_TRANSIT_OVERHEAD_MIN + distance /
ESTIMATED_TRANSIT_KMH` up to `ESTIMATED_TRANSIT_MAX_KM`, `None` beyond it.
The resolver applies it after every provider has been asked; `solve_day` keeps
calling it too, because matrices built elsewhere (the eval provider, tests)
never pass through the resolver and must still not lose their arcs.

### Provenance without provider names in the UI

- `TransitDuration.routing_status` (`routed` | `estimated`) and `provider`
  (`google` | `here` | `transitous` | `estimated`) carry the internal facts.
- `transit_from_prev_mode` becomes `transit` / `walking` / `transit_estimated`
  / `walking_estimated`. No provider name crosses the API boundary.
- `ScheduledStop.transit_from_prev_provider` keeps the provenance in-process
  for logs, counters and eval. It is deliberately not a new DB column yet.

### Instrumentation

`TransitResolutionStats` counts, per resolution: `transit.<role>.routed`,
`transit.<role>.no_route`, `transit.<role>.error`, `transit.estimated`,
`transit.unroutable`, where role is `primary` / `secondary` / `regional`.
Written as span attributes on a `transit.resolve` span and one INFO log line.
No new observability dependency.

### Regional providers stay out of the core

`tools/transit/registry.py` holds a `TransitRegion(country, city)` keyed
registry that is empty by default. `make_transit_client(region=...)` appends
whatever it returns after the global chain. Nothing in the solver or the
resolver names a country.

## Files

| File | Change |
|---|---|
| `tools/transit/errors.py` | new: `TransitProviderError`, `TransitFailureKind` |
| `tools/transit/estimate.py` | new: shared conservative estimate |
| `tools/transit/here.py` | new: HERE Transit v8 adapter, optional on credentials |
| `tools/transit/resolver.py` | new: `FallbackTransitResolver`, `TransitResolutionStats` |
| `tools/transit/registry.py` | new: empty regional registry |
| `tools/transit/models.py` | `routing_status`, `required_pairs` |
| `tools/transit/google_routes.py` | honor `required_pairs`, set `provider="google"`, re-base errors |
| `tools/transit/transitous.py` | honor `required_pairs`, re-base errors |
| `tools/transit/provider.py` | build the chain instead of one client |
| `config/transit.py`, `config/__init__.py` | HERE endpoint/limits, `here_api_key`, `sync_transit_fallback_providers` |
| `agents/solver/stage2_route.py` | normalized mode label, provenance field, delegate the estimate |
| `ios/...` | contract fixture + preview string only |

## Not in scope

CP-SAT, Stage 1 clustering, the food-per-day ceiling, fatigue, GTFS/OTP, and
any Japan-specific branch in the solver.
