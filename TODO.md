# TODO

## Completed before M4

Restored to M3 scope and completed on 2026-08-31.

- [x] Add profile-driven place suggestions, capped per traveler.
- [x] Filter explicit hard dietary conflicts and warn on unknown information.
- [x] Add the solver-driven top-three lodging comparison and group pick flow.

## Follow-ups from M7

The eval harness surfaced these. None blocks the milestone.

- [ ] The `must-go` sabotage does not fail `must_go_placed` on the current
      fixtures, because every shortlist fits the days available, so a pin
      never changes whether a place is scheduled. It shows up instead as a
      meal-coverage regression. A fixture with real capacity pressure would
      make the pin load-bearing and the check direct.
- [ ] `clean_5day_hokkaido` and `weather_storm_day3` both hit the ten-second
      CP-SAT ceiling, so their plans are the best found in that budget rather
      than provably optimal. Worth understanding what makes those two models
      hard before assuming the limit is the right number.
- [ ] `budget_daily` is carried on the `budget_tight` fixture but nothing
      reads it: there is no budget constraint in the solver yet. The fixture
      is ready for it.
