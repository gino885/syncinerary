# AGENTS.md

Instructions for coding agents working in this repo (Codex reads this file
automatically; it is the counterpart to `CLAUDE.md`).

## 1. Read the spec first

**`CLAUDE.md` at the repo root is the canonical build brief. Read all of it
before writing code.** This file does not restate it. What follows is only the
operational knowledge that is not in the spec: how to run things, and the
traps that have already cost time.

Section references below (`§2`, `§7`, `§16`) point into `CLAUDE.md`.

If something in the spec is ambiguous, **stop and ask the user.** Do not
infer behavior. That rule is in `CLAUDE.md` §0 and it is meant literally: the
project owner would rather answer a question than review a guess.

## 2. Environment

Python 3.12 (not 3.13: the venv is pinned). No system python3.12 exists on
this machine; `uv` fetches one.

```bash
uv venv --python 3.12
uv pip install -e '.[dev]'
```

Every command below assumes `.venv/bin/...`, not a global interpreter.

Infrastructure runs in Docker. **Start it before running the test suite** or
94 of the 153 tests silently skip:

```bash
docker compose up -d          # postgres+pgvector, redis, phoenix
.venv/bin/alembic upgrade head
```

Services: Postgres 5432, Redis 6379, Phoenix UI 6006 (OTLP ingress 4317).

Run everything:

```bash
.venv/bin/python -m pytest tests/ -q
.venv/bin/ruff check syncinerary tests
```

Both must be clean before a commit.

### Secrets

`.env` is gitignored; `.env.example` is the template. Two keys matter:

| Key | Used by | State as of this writing |
|---|---|---|
| `ANTHROPIC_API_KEY` | `agents/explain.py` | **Placeholder `sk-ant-...`, returns 401** |
| `GOOGLE_MAPS_API_KEY` | `tools/transit/` (M1-7, unwritten) | **Empty** |

Do not paper over a missing key with a mock that ships. Ask the user for the
key; if they decline, agree on an explicit fallback and label it.

## 3. Non-obvious traps

These have all bitten already. Each one is commented at its site too.

### Alembic autogenerate is wrong three ways

`alembic revision --autogenerate` produces a revision that does not run. After
generating, hand-edit:

1. Add `import pgvector.sqlalchemy`. Autogenerate emits
   `pgvector.sqlalchemy.vector.VECTOR(dim=1536)` without the import →
   `NameError`.
2. Add `op.execute("CREATE EXTENSION IF NOT EXISTS vector")` at the top of
   `upgrade()`. Otherwise the revision only works where
   `docker/postgres-init.sql` happened to run.
3. Add explicit `DROP TYPE` for every native enum in `downgrade()`. Postgres
   creates enum types as a side effect of `CREATE TABLE` but does **not** drop
   them on `DROP TABLE`, so a downgrade orphans them and the next upgrade
   dies on "type already exists".

Verify a new revision with the full round trip, not just the upgrade:

```bash
.venv/bin/alembic upgrade head && .venv/bin/alembic downgrade base && .venv/bin/alembic upgrade head
```

### env.py hides the LangGraph checkpointer tables

`store/migrations/env.py` has an `include_object` filter excluding
`checkpoints`, `checkpoint_blobs`, `checkpoint_writes`,
`checkpoint_migrations`. Those are owned by `langgraph-checkpoint-postgres`
and created by its own `setup()`. **Do not remove the filter**, because autogenerate
would emit `DROP TABLE` for all four.

That package speaks **psycopg3**; the store layer speaks **asyncpg**. Two
pools against one database is intentional, not a mistake to clean up.

### Repositories: the two-dump trick

`store/repositories/base.py` dumps a pydantic model twice. Fields listed in
`jsonb_fields` use `mode="json"` (so nested models and UUIDs inside JSONB
become JSON scalars); everything else uses `mode="python"` (so SQLAlchemy
gets real `UUID`, `datetime`, enum objects). One mode for both breaks in one
direction or the other. `column_aliases` maps domain field → column where the
names differ (`profile` → `profile_json`).

### Test session rollback, and nodes that open their own session

`tests/conftest.py` wraps each test in a transaction and rolls it back.
Repository code flushes, never commits, so nothing leaks.

LangGraph nodes call `session_scope()` themselves (no session threaded
through graph state). Tests therefore **monkeypatch the module's
`session_scope`** to yield the fixture session. Copy `_use_test_session` from
any existing node test.

### The LLM request surface is narrower than you remember

`SYNC_LLM_MODEL` defaults to `claude-opus-4-7` (§16). On that model these
return **HTTP 400**, not a warning:

- `temperature`, `top_p`, `top_k`: removed. Steer with the prompt only.
- `thinking: {"type": "enabled", "budget_tokens": N}`: removed. Use
  `output_config: {"effort": ...}`.
- A trailing assistant message (prefill) is rejected. Use
  `output_config.format` or a system instruction.

Also check `stop_reason == "refusal"` **before** indexing `response.content`:
a declined request is HTTP 200 with an empty content list.

`tests/test_m1_explain.py` asserts all of this against a stub client. If you
change the request shape, those tests are the guard.

### Smaller ones

- Project version is `0.1.0+m1`. `0.1.0-M1` is not PEP 440 valid and makes
  `pip install -e .` fail outright.
- Ruff excludes `syncinerary/store/migrations/versions/`: those are rendered
  from alembic's template and reformatting them just churns.
- `CONSTRAINT` is a Postgres reserved word, so §7's `constraint` table is
  named **`trip_constraint`**. The domain class is still `Constraint`.
- Trip `days` counts both end dates: 21→25 May is 5 days.

## 4. Rules that are enforced by tests

Breaking these fails the suite, not just review.

- **No LLM SDK import in `agents/aggregate.py`, `agents/shortlist.py`,
  `agents/solver/`, `harness/`** (§2). Tests parse the module AST and assert
  the import roots. A grep is not enough, because those modules' docstrings discuss
  LLMs at length precisely because they must not import one.
- **Nodes return a partial dict and never mutate the input state** (§14).
  In-place mutation breaks checkpointer serialization, which the swipe
  interrupt depends on. Each node test asserts the input state is unchanged.
- **`itinerary_version` and `itinerary_node` are append-only** (§7).
  `ItineraryNodeRepository` deliberately exposes no update method. The only
  mutation on a version is `set_status`, which is lifecycle, not content.
- **Every §7 table has a repository.** A test enumerates
  `Base.metadata.tables` against the repository classes and fails on a gap.
- **Determinism where it is claimed.** Gather pool, aggregate ranking, and
  shortlist selection each have a test asserting identical output across
  runs, because F2 replay (§12.3) compares them across commits.

## 5. Working conventions

- **One milestone per branch** (`m1-vertical-slice`), one PR at the end.
- **Small commits**, prefixed `M1-3:`, `M1-7a:` so they map onto the
  `CLAUDE.md` §13 step list. Not 500-line commits.
- **Commit messages explain the non-obvious decision**, per §14. If a choice
  had a defensible alternative, say why this one won. No em dashes anywhere
  in prose, comments, or commit messages (§14).
- **Every acceptance criterion needs a passing test** before a feature is
  "done" (§14).
- **When blocked on an external dependency** (Docker, alembic, a third-party
  API), paste the actual log to the user and stop. Do not invent a
  workaround. This is an explicit instruction from the project owner.
- **Report faithfully.** If something is untested against reality, say so.
  `M1-8` is committed with its request shape unverified against the live API,
  and the commit message says exactly that.

## 6. Where things live

Layout follows `CLAUDE.md` §6, with `solver/` and `delegate/` under
`agents/`. Two orientation notes:

- `store/tables.py` is SQLAlchemy (persistence shape); `domain/models.py` is
  pydantic (graph + API shape). Repositories own the translation. **Nothing
  outside `store/` imports `tables.py`**, and the API layer never touches
  SQLAlchemy (§14).
- `api/schemas.py` is separate from `domain/models.py` on purpose: the client
  must not set a trip's uuid, and the swipe card does not need `enrichment`.
  Pinning the wire format means a domain change cannot silently alter what
  the iOS app decodes.

## 7. Current state

See **`HANDOFF.md`** for where the work stopped, what is blocked, and the
remaining M1 steps in order. Delete that file when M1 merges; this one stays.
