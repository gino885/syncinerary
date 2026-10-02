# Gino Chen: resume review and proposed improvements

## Follow-up changes applied

The current PDF now includes the approved headline and uses OpenTelemetry in the Syncinerary bullet. The owner confirmed that Google's 2 MB figure is the upload buffer size, Garmin's 32% covers all IT support tickets, and NCCUPass has 2,000+ registered students. Those scopes are explicit in the revised bullets. WellNest now names GPT-4o mini. The entire PDF was rebuilt with embedded fonts; its complete text matches the source in pypdf, pdfplumber, and Poppler extraction checks. It remains one page and retains all five hyperlinks.

The remaining degree-name and skills proposals below have not been applied. The original review below is retained as a record of the first revision.

Reviewed September 15, 2026. Target: applied AI / LLM engineering, with backend engineering as a supporting strength.

## What was updated

Only the Syncinerary description and bullets were changed in the accompanying PDF. Its project heading, dates, and every other section retain their original text and positions. The separate project description was folded into the first bullet to keep three readable bullets on one page. The original PDF in Downloads was preserved.

### Updated Syncinerary bullets

- Built a **LangGraph travel agent** for social discovery and human-approved replanning; moved discovery to **checkpointed PostgreSQL workers**, completing a live **16-card run after client disconnect**.
- Improved worst-case **meal coverage from 62.5% to 100%** across 12 storm-scenario test runs by modeling meal availability in a **two-stage OR-Tools CP-SAT solver**, with LLMs excluded from feasibility decisions.
- Hardened LLM tool calls with **Pydantic validation, repair, loop detection, and cost caps**; added **OpenTelemetry/Phoenix** traces and **10-scenario deterministic CI evaluations** to detect constraint regressions.

These show what you built, how it works, and a concrete result. They cover stateful agents, durable execution, tool validation, human approval, optimization, observability, and evaluation. Current [Anthropic Applied AI requirements](https://job-boards.greenhouse.io/anthropic/jobs/5057647008) emphasize agent development, evaluation, Python/TypeScript, and production implementation. [Snorkel's Applied AI role](https://job-boards.greenhouse.io/snorkelai/jobs/5709067004) also calls for RAG, typed Python services, LangGraph, and evaluation. These postings inform the skills emphasis; their seniority requirements are not a claim about your eligibility.

### Evidence and limits

| Resume claim | Evidence reviewed | Scope |
|---|---|---|
| LangGraph, social discovery, checkpointed workers | `syncinerary/agents/graph.py`, `syncinerary/workers/gather.py`, `syncinerary/api/routers/gather.py`, gather recovery tests | Includes current local implementation, some of which is uncommitted. No claim of a public production launch. |
| Human-approved replanning | `tests/test_m6_replan_gate.py` and the rescue implementation | Approval activates the proposal; rejection keeps the prior version active. |
| 16-card run after client disconnect | `DISCOVERY_IMPLEMENTATION_NOTES.md`, validation and rollout evidence | One recorded live two-day Tokyo run with Google, Brave, and Anthropic. Not a load test or broad reliability rate. |
| 62.5% to 100% worst-case meal coverage | `EVAL_FIXTURE_CONVERGENCE.md`, section 6; commit `81f0d2e` | Minimum coverage across a 12-seed storm fixture experiment. Historical recorded result, not a production business metric or a fresh rerun here. |
| Reliability and tracing | `syncinerary/harness/`, `syncinerary/obs/`, related tests | Implementation inspected; tracing was not successfully exercised in this review. |
| 10-scenario deterministic CI evaluation | Ten fixture files, `syncinerary/eval/cases.py`, `scorers.py`, and `.github/workflows/ci.yml` | CI gates feasibility, harness health, and fixture quality floors. A prior-commit comparison requires stored baseline results. |

The old wording, “10-scenario DeepEval eval harness in CI,” was replaced because the default CI path makes no model calls and uses custom deterministic scoring. DeepEval is listed as an optional dependency; that alone does not establish that DeepEval judges the CI suite.

I ran the separate discovery admission check during this review: **14 cases, 0 invalid-card rate, 0 false rejections**. The command exited successfully. Trace export failed with `localhost:4317 ... Operation not permitted`. I did not rerun the full backend suite, live discovery, or the historical solver experiment. The recorded “786 backend tests passed” result was not added to the resume as a fresh verification claim.

The final PDF was rendered and visually checked. A character-position comparison verified that text outside the edited region was unchanged. Obsolete Syncinerary text was removed from the PDF content stream rather than covered with a white rectangle.

## Proposed changes elsewhere, not applied

### 1. Fix three credibility and document issues first

**PDF text extraction.** The original looks readable, but common extraction tools return corrupted words such as `So#ware`, `MulZ-Agent`, and `PydanZc`. This can impair keyword extraction. The new Syncinerary bullets extract correctly; the original sections still carry their original encoding. Proposal: re-export the entire resume from its editable source, or rebuild it with correctly embedded fonts, after you approve the other edits. A readable visual preview alone does not prove clean text extraction.

**Cornell degree name.** Your resume says “Master of Science in Computer Information Systems.” Cornell's [official catalog](https://catalog.cornell.edu/programs/information-systems-ms/) names the program **Information Systems (MS)**. Proposal, subject to your enrollment record: **Master of Science in Information Systems**. Add your concentration or the Technion dual degree only if it matches your actual program. Keep graduation date and GPA tied to your records.

**WellNest model and dates.** The project ends in December 2024 but claims a fine-tuned `o4-mini` model. OpenAI [released o4-mini on April 16, 2025](https://openai.com/index/introducing-o3-and-o4-mini/). The timeline therefore needs an explanation or correction. Confirm the actual model, whether training occurred, and whether the project continued after the listed end date. Prompt customization and RAG are not fine-tuning. Do not silently replace the model name with a guess.

### 2. Headline

Proposed:

> Software Engineer | AI Agents & Backend Systems | Cornell Tech

This makes the AI direction visible while preserving software engineering as your professional identity. Keep Education near the top for student and new-graduate applications. A separate multi-line summary is unnecessary on this already full page.

### 3. Technical skills

Proposed four-line grouping:

- **Languages:** Python, Java, Kotlin, TypeScript, SQL
- **AI Systems:** LangGraph, Tool Calling, Structured Outputs, RAG, ChromaDB, LLM Evaluation, OpenTelemetry, Arize Phoenix
- **Backend & Data:** FastAPI, Pydantic, Spring Boot/WebFlux, PostgreSQL, MySQL, Redis, REST, gRPC
- **Infrastructure & Testing:** Docker, AWS, Azure, GitHub Actions, pytest, JUnit, Grafana

Add SQL only if you are comfortable being tested on it. AWS/Azure are already in your resume; keep them only if you can describe hands-on deployment work. This grouping is a proposed priority order, not a claim that all listed skills were independently verified.

For general software roles, retain React, SwiftUI, and Android in a compact additional line or swap them for less relevant AI tools. For applied AI roles, prioritize demonstrated agents, retrieval, evaluation, and backend work over HTML/CSS, JIRA, Agile, Postman, Maven, and “OOP.”

Keep PyTorch/CUDA only if you can explain a concrete training or GPU workload. Keep DeepEval only if you have actually built or run evaluations with it. A dependency declaration is insufficient. Do not add MCP, fine-tuning, Kubernetes, or model-serving expertise without evidence.

### 4. Google internship

This is already a strong section. Preserve its security and systems engineering evidence. Proposed wording:

- Closed all identified authentication-bypass vulnerabilities in the upload path by replacing a legacy proxy with authenticated gRPC calls from Kotlin services.
- Eliminated out-of-memory failures during large log uploads by streaming compressed archives with Kotlin Coroutine Flow and backpressure.
- Separated Wi-Fi diagnostics from a shared connectivity workflow by implementing user consent, Android WorkManager scheduling, and opt-in health telemetry.
- Migrated a legacy integration to the official partner API with zero downtime using feature-flagged rollout and instant rollback.

**Metric clarification:** the existing “constant 2 MB peak heap” claim may mean the upload buffer, incremental pipeline memory, or the entire process heap. Restore the number using the precise measured scope. If it was the buffer, use “bounded the upload buffer to 2 MB.” If it was measured additional heap, say that. These are different claims.

If you know the number of vulnerabilities, upload sizes, upload volume, or measured rollout traffic, those would strengthen the relevant bullet. No new figures were inferred. “Zero downtime” remains a claim from your resume, not something independently verified here.

### 5. Garmin internship

Lead with the enterprise RAG result. Proposed wording:

- Built a RAG chatbot backend with Spring WebFlux and streaming responses, automatically resolving 32% of IT support tickets for an organization of 1,500 employees.
- Reduced package-origin verification from 8 steps to 3 by integrating an image-recognition API and Jaro-Winkler matching across 10,000+ package-origin records.
- Automated migration of 20 years of review data with Python and HTML parsing; implemented JWT authentication and role-based access control for supporting REST APIs.

The first bullet retains the existing reported result. Confirm whether 32% means all support tickets, eligible ticket categories, or chatbot-handled queries, and specify the scope if narrower. “For an organization of 1,500 employees” avoids implying 1,500 active chatbot users.

Confirm what the “10,000” count measures before using “records”: packages processed, product identifiers, or origin records. Expand the internal acronym COO if it is essential. For the third bullet, “supporting” assumes those APIs belonged to the migration system; if these were separate projects, retain separate claims or prioritize the more relevant one.

### 6. NCCUPass

The section repeats the 2,000-user figure, and the description says registrations while the bullet implies usage. Proposed wording:

- Built and containerized a FastAPI campus assistant with MySQL and Redis, supporting 2,000+ registered students.
- Reduced search API latency by 34% through Redis caching; implemented BM25 retrieval with jieba tokenization and monitored P99 latency in Grafana.

Use “registered” unless you have active-user data. The second bullet keeps the latency reduction separate from P99 monitoring because the original does not establish that the 34% improvement was specifically at P99. If available, add the measured before/after latency and test conditions.

### 7. WellNest

Keep the competition result and retrieval/classification work. Proposed wording while the model detail is unresolved:

- Placed 3rd among 16 teams in the NCCU Graduation Project Competition with an AI mental-health companion combining conversational NLP and emotion classification.
- Built a streaming chatbot with Spring WebFlux, Server-Sent Events, and the OpenAI API; integrated ChromaDB retrieval and BERT/XGBoost emotion classification.

This proposal intentionally omits the unsupported model/training detail pending confirmation. If fine-tuning was performed, a stronger replacement would name the actual model, dataset size, evaluation metric, and improvement over a baseline. Do not imply clinical effectiveness from a competition placement or classifier score.

## Guidance consulted

I read the [Tailored Resume Generator skill](https://raw.githubusercontent.com/ComposioHQ/awesome-claude-skills/master/tailored-resume-generator/SKILL.md) and the [Resume Builder bullet-writing guide](https://raw.githubusercontent.com/dabydat/resume-builder-skill/master/skill/references/bullet-writing-guide.md). Their useful principles here are relevance to the role, action-led bullets, concrete technical context, and substantiated results. I cross-checked those with [MIT's guidance on writing about skills](https://capd.mit.edu/resources/resumes-writing-about-your-skills/). Generic rules about mandatory section order, summary length, or inserting metrics were not treated as reasons to invent facts or rewrite unapproved sections.

Best next revision: correct the degree/model details, clarify the Google and Garmin metrics, then apply the approved wording and regenerate the whole PDF with clean text encoding.
