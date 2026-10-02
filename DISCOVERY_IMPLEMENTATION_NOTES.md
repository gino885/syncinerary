# Discovery implementation notes

The job record in Postgres is the queue. A separate worker holds a session advisory lock on a dedicated connection, with short transactions for status writes. This avoids a database/broker dual write and prevents a slow worker's heartbeat from expiring into duplicate ownership. The existing Redis infrastructure remains available for chat. Graph recovery stops at the swipe interrupt.

The initial states are additive (`draft`, `gathering`), preserving the existing later states and existing trips. Legacy synchronous gather is rejected for new preparation states.

RedNote guides use permitted public index text. Full note bodies are unavailable through the current approved source. A missing excerpt is missing evidence; no extraction claim is made about unseen text. Guide verification shares the trip budget with adaptive discovery.

## Preparation room design

Audience: a trip leader and the invited travelers. Job: see who and what is ready, contribute links and preferences, then deliberately begin discovery.

Reuse existing light/dark tokens: Paper #F0EFE9 / #16181C, Ink #1D2B4F / #E9E7DF, plus Faded and Rule from the asset catalog. Use system body text for member and link rows, the existing display role only for the navigation title, and monospaced digits for counts. A simple grouped list puts actual names, contributions and dates first. The signature is the contributor attribution next to each saved post. The leader's start control is the only prominent action.

Critique: an introductory hero and readiness percentage would repeat existing decorative loading surfaces and imply a readiness formula that does not exist. Remove both. Show named members and their actual preference state. Keep the source explanation in the start confirmation where it informs a decision. Progress shows actual phase and city, without a fabricated percentage.

## Validation and rollout evidence

The read-only shadow audit queried 102 live Google Places results across Tokyo, Kamakura, Atami, Sapporo, Seoul, and Paris. It caught missing supported types, including `art_museum`, `city_park`, `sculpture`, `landmark`, and `amusement_center`. Those types now have regression coverage. The final audit admitted 100 results and rejected a generic government-office listing and a tour-service listing. An office's separate visitor attraction can still qualify through its supported type; a government office alone is deliberately insufficient. No existing deck was changed by this audit.

The allowlist was checked against Google's [current place-type reference](https://developers.google.com/maps/documentation/places/web-service/place-types). Job recovery follows the existing [LangGraph checkpoint model](https://docs.langchain.com/oss/python/langgraph/persistence).

Run `.venv/bin/python -m syncinerary.eval.discovery` for the admission release gate. Its 14 labeled cases require both a zero invalid-card rate and zero false rejections. This is a regression metric, not a claim that provider metadata proves every real-world result is correct.

The existing ten deterministic itinerary fixtures pass, including the 30-minute solver changes. The deliberate fatigue-cap break still fails the harness. The database migration passed upgrade, downgrade to base, and upgrade in a disposable database. Existing trips and candidates were preserved.

Links added after a run starts are marked as deferred and excluded from its snapshot. A new-version refresh workflow remains a separate future action; repeated starts intentionally return the original completed run. Guide bodies remain limited to public index evidence, so a guide with no traceable named places contributes no cards. No unseen post content is inferred.

A live two-day Tokyo run with Traditional Chinese output completed with 16 cards. Creating its draft took 0.87 seconds; starting its persistent run took 0.045 seconds. Two start requests returned the same run. The initiating HTTP client was closed before worker execution, and a new observer saw completion. The disposable database was removed after the test. This exercises live Google, Brave, and Anthropic calls; it does not claim all multi-city combinations have been tested end to end.

The iOS API contract and gather lifecycle executables pass, and the simulator build succeeds. Isolated preview data was used to inspect the preparation room in Traditional Chinese, light mode, and enlarged accessibility text in dark mode. The progress screen renders the server phase and city.

Final verification: 786 backend tests passed, Ruff and whitespace checks passed, both Swift test executables passed, and the final simulator build succeeded. The local API was restarted with the new endpoints and the separate discovery worker was started alongside it. Worker startup and API health were checked.
