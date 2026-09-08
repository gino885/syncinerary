"""One failure vocabulary shared by every transit provider adapter.

A provider that could not answer has not proved the journey impossible. The
fallback chain needs to tell "no service between these two points" apart from
"the API returned 500", not because it treats them differently (both mean ask
the next provider) but because the counters that measure provider coverage
are worthless if the two are merged.
"""
from __future__ import annotations

from enum import Enum


class TransitFailureKind(str, Enum):
    """Why one provider did not produce a route."""

    #: The provider answered and said no route exists.
    NO_ROUTE = "no_route"
    #: The request failed technically: HTTP error, malformed payload, timeout.
    PROVIDER_ERROR = "provider_error"
    #: The provider cannot serve this request at all: missing credentials,
    #: unsupported region or mode, request beyond its bounded size.
    UNSUPPORTED = "unsupported"
    #: Quota exhausted or the provider asked us to slow down. Retryable later.
    RATE_LIMITED = "rate_limited"


class TransitProviderError(RuntimeError):
    """Base class for a failure the fallback chain can recover from.

    Every adapter's own error tree inherits from this so the resolver can
    catch one type and still record which kind of failure it was.
    """

    kind: TransitFailureKind = TransitFailureKind.PROVIDER_ERROR


__all__ = ["TransitFailureKind", "TransitProviderError"]
