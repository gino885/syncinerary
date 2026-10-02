"""Deterministic admission release gate. No provider or model calls.

Run with `python -m syncinerary.eval.discovery`. Expected identities come
from the reported bad cards and the six-city live provider audit.
"""

from __future__ import annotations

import json
from pathlib import Path

from syncinerary.agents.gather.admission import admit_place
from syncinerary.tools.places import PlaceMatch


def evaluate_admission(fixtures: list[dict]) -> dict[str, float | int]:
    admitted = invalid = rejected_valid = 0
    for row in fixtures:
        accepted = admit_place(
            PlaceMatch.model_validate(row["place"]), destination=row["destination"]
        ).accepted
        admitted += accepted
        invalid += accepted and not row["expected_accepted"]
        rejected_valid += not accepted and row["expected_accepted"]
    return {
        "cases": len(fixtures),
        "admitted": admitted,
        "invalid_card_rate": invalid / admitted if admitted else 0.0,
        "false_rejections": rejected_valid,
    }


def main() -> int:
    fixtures = json.loads(Path(__file__).with_name("discovery_regressions.json").read_text())
    report = evaluate_admission(fixtures)
    print(json.dumps(report, indent=2))
    return int(report["invalid_card_rate"] > 0 or report["false_rejections"] > 0)


if __name__ == "__main__":
    raise SystemExit(main())
