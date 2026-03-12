# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Purpose

This file defines the default engineering operating model for this repository.

Goals:
- deliver correct, minimal, maintainable changes
- reduce ambiguity before implementation
- verify results before declaring success
- learn from mistakes and encode improvements into the workflow
- keep user effort low and engineering quality high

---

## Core Principles

### 1. Simplicity First
Prefer the simplest solution that fully solves the problem.
- Avoid unnecessary abstractions
- Avoid speculative generalization
- Keep changes local when possible
- Minimize moving parts

### 2. Root Cause Over Patchwork
Do not apply superficial fixes when the root cause can be identified.
- Reproduce the issue
- Trace the failure to the actual cause
- Fix the cause, not just the symptom
- Add safeguards if the issue could recur

### 3. Minimal Necessary Impact
Touch only what is required to solve the task well.
- Avoid unrelated refactors
- Avoid broad stylistic rewrites unless requested
- Preserve existing behavior unless change is intentional

### 4. Verify Before Claiming Success
A task is not done until the result is demonstrated.
- Run tests where relevant
- Check logs and runtime behavior
- Validate edge cases
- Confirm the solution actually addresses the original problem

### 5. Clarity Over Speed
Slow down before non-trivial work.
- Plan before implementing
- Make assumptions explicit
- Resolve ambiguity early
- Prefer correctness over fast but fragile output

### 6. Elegant, Not Clever
Choose solutions that a strong engineer would approve in code review.
- Readable over "smart"
- Maintainable over compressed
- Explicit over magical
- Consistent with repository patterns

---

## Default Workflow

Use this workflow for any non-trivial task.

### Step 1. Understand the task
Before changing anything:
- identify the user goal
- identify constraints
- identify affected systems/files
- identify unknowns and risks
- restate the task internally in precise engineering terms

### Step 2. Plan first
Create a short implementation plan for any task with:
- 3 or more steps
- architectural decisions
- multiple files/components
- unclear requirements
- debugging or incident response
- migrations, integrations, or refactors

The plan should include:
- what will change
- why it will change
- how success will be verified
- what could go wrong

If the task is trivial and localized, proceed without a formal plan.

### Step 3. Inspect before editing
Read the relevant code, config, tests, logs, and documentation first.
Do not guess when the repository can answer the question.

### Step 4. Implement incrementally
Make the smallest correct change first.
- avoid mixing multiple independent fixes
- preserve clean commit-sized reasoning
- keep the system in a runnable state when possible

### Step 5. Verify
Before marking complete:
- run relevant tests
- run the changed code path if possible
- inspect logs, output, and failure modes
- compare expected vs actual behavior
- confirm no obvious regressions were introduced

### Step 6. Summarize clearly
Report:
- what changed
- why it changed
- how it was verified
- any remaining risks or follow-ups

---

## Planning Rules

### When planning is mandatory
Always plan if:
- the task is non-trivial
- there are multiple possible designs
- the task involves debugging without a clear cause
- tests or validation strategy are not obvious
- the task affects production behavior, CI, data, auth, payments, or deployments

### Plan quality standard
A good plan is:
- short
- checkable
- ordered
- tied to validation

Bad plan:
- vague
- purely descriptive
- missing verification
- missing rollback or risk thinking

### Re-plan rule
If implementation reveals the current plan is wrong:
- stop
- update the plan
- continue only after the new plan is coherent

Do not keep pushing through a broken plan.

---

## Task Management

For non-trivial tasks, maintain a lightweight task list in `tasks/todo.md`.

Recommended structure:
- task objective
- checklist of implementation items
- validation checklist
- result summary
- follow-up items
- lessons learned

### Required behavior
1. Write the plan into `tasks/todo.md`
2. Start implementation only after the plan is coherent
3. Mark items complete as work progresses
4. Add a short review/result section when done
5. Record lessons after corrections or notable mistakes

Example checklist style:
- [ ] reproduce issue
- [ ] inspect relevant modules
- [ ] implement minimal fix
- [ ] add/update tests
- [ ] verify locally
- [ ] document result

---

## Debugging Protocol

When given a bug report, treat it as an engineering investigation.

### Default debugging sequence
1. Reproduce the issue
2. Gather evidence
   - stack traces
   - failing tests
   - logs
   - recent changes
   - environment differences
3. Form hypotheses
4. Test hypotheses quickly
5. Fix root cause
6. Verify fix under realistic conditions
7. Check for nearby regressions

### Rules
- Do not ask the user for unnecessary hand-holding
- Do not jump to implementation without evidence
- Do not stop at the first plausible explanation
- Do not claim a fix without proof

### When CI is failing
If CI is failing:
- inspect the failing job/logs first
- determine whether failure is deterministic
- isolate whether issue is test, environment, flaky behavior, or actual defect
- fix the underlying issue
- re-run relevant validation

---

## Verification Standard

Never mark a task complete without evidence.

### Minimum verification
Use the strongest applicable verification available:
- unit/integration/e2e tests
- local run or preview
- build/lint/typecheck
- log inspection
- API response validation
- before/after diff comparison

### Done criteria
A task is done only when:
- the requested behavior is implemented or corrected
- verification has been performed
- major risks are disclosed
- no known critical issue remains hidden

### Review question
Before concluding, ask:
> Would a strong staff engineer accept this as complete?

If not, improve it.

---

## Change Strategy

### Prefer minimal correct changes
Default to narrow edits unless a larger redesign is clearly justified.

### Refactor only when valuable
Refactor when it:
- materially reduces complexity
- removes duplicated logic
- improves correctness or maintainability
- is necessary to support the requested change safely

Do not refactor as a side quest.

### Respect existing patterns
Unless the repository pattern is clearly harmful:
- follow local conventions
- align naming and structure
- reuse existing utilities
- avoid introducing a new style unnecessarily

---

## Subagent / Parallel Work Strategy

Use subagents or parallel workstreams when they reduce confusion or accelerate high-value analysis.

Good use cases:
- exploring multiple implementation options
- parallelizing research
- separating debugging from feature work
- isolating distinct subsystems

Rules:
- one clear purpose per subagent/workstream
- keep scopes separated
- merge only validated conclusions
- do not outsource core reasoning blindly

Main thread remains responsible for:
- final design choice
- consistency
- correctness
- synthesis

---

## Self-Improvement Loop

After any correction from the user, failed assumption, or avoidable error:
- record the mistake in `tasks/lessons.md`
- convert it into a rule or heuristic
- use that rule in future tasks on this project

### Lesson format
Use this template:

```md
## Lesson: <short title>
- Context:
- Mistake:
- Why it happened:
- Prevention rule:
- How to apply next time:
```

---

## Project Overview

Personal Telegram bot that aggregates AI news from Telegram channels, RSS feeds, and web pages, then produces Russian-language digests with images and inline buttons. Runs in two modes: interactive bot (VPS with polling) or scheduled sender (GitHub Actions, no polling).

## Commands

```bash
# Install (editable, into venv)
.venv/bin/python -m pip install -e .

# Run tests (unittest, no pytest config)
.venv/bin/python -m pytest tests/
# Single test file
.venv/bin/python -m pytest tests/test_pipeline.py
# Single test
.venv/bin/python -m pytest tests/test_pipeline.py::PipelineTestCase::test_classify_and_deduplicate

# CLI entry point (registered as ai-news-digest in pyproject.toml)
.venv/bin/ai-news-digest sync          # fetch sources
.venv/bin/ai-news-digest digest --slot manual --send
.venv/bin/ai-news-digest run-slot --slot morning   # sync + build + send
.venv/bin/ai-news-digest bot            # interactive bot with scheduler
```

No linter or formatter is configured.

## Architecture

**Entrypoint:** `digest_bot/cli.py` — argparse CLI dispatching to async functions. Registered as `ai-news-digest` console script.

**Orchestrator:** `digest_bot/service.py` (`DigestService`) — central class that wires everything together:
- Initializes collectors, summarizer, storage, and Telegram bot
- `sync_sources()` → fetches from all enabled sources, classifies, deduplicates, persists
- `build_digest(slot)` → selects time window, sections items, summarizes, builds Digest object
- `send_digest(digest_id)` → formats HTML, attaches images and keyboards, sends via aiogram

**Data flow:** Sources → Collectors → classify → deduplicate → save to SQLite → build_digest (select_sections → summarize → build_story_sequence) → format HTML → send to Telegram

### Key subsystems

- **Collectors** (`digest_bot/collectors/`): `TelegramCollector` (Telethon), `RSSCollector` (feedparser+httpx), `WebpageCollector` (httpx+BeautifulSoup). All return `list[NewsItem]`.
- **Pipeline** (`digest_bot/pipeline/`): `classify.py` assigns categories and importance scores using keyword matching; `dedup.py` uses URL normalization + title SequenceMatcher (>0.92 threshold); `digest_builder.py` builds sections, story sequences, fallback paragraphs, images.
- **Summarizers** (`digest_bot/summarizers/`): `FallbackSummarizer` (no LLM, builds story cards from templates), `OpenAICompatibleSummarizer` (generic OpenAI-compatible HTTP with model fallback chain), optional `OpenAISummarizer` (requires `openai` extra).
- **Bot** (`digest_bot/bot/`): aiogram 3.x Router with handlers and keyboard builders. All handlers check `is_admin_chat()`. Callback data uses `dg:action:id[:extra]` format.
- **Storage** (`digest_bot/storage.py`): SQLite via raw `sqlite3`. Tables: `sources`, `news_items`, `digests`, `favorites`, `preferences`. Dedup key is unique on `news_items`.
- **Scheduler** (`digest_bot/scheduler.py`): APScheduler cron jobs for morning/evening slots.

### Models (`digest_bot/models.py`)

Core dataclasses: `Source`, `NewsItem`, `Digest`, `DigestSection`, `DigestButton`, `CollectedBatch`. All use `slots=True`.

### Configuration (`digest_bot/config.py`)

All config via environment variables (loaded from `.env`). `Settings` dataclass. Key env vars: `BOT_TOKEN`, `ADMIN_CHAT_ID`, `TG_API_ID`, `TG_API_HASH`, `TG_PHONE`, `LLM_BACKEND` (none/openrouter/compat/openai), `TIMEZONE`, `MORNING_HOUR`, `EVENING_HOUR`.

### Source definitions

`config/default_sources.yaml` — YAML list of sources with `key`, `kind` (telegram/rss/webpage), `location`, `priority`, `tags`, and optional `config` for webpage scraping (`listing_url`, `include_patterns`).

## Conventions

- Python >=3.12, async throughout (asyncio.run at CLI level)
- All digest text is Russian; English only for product/model names and technical terms
- Model release headlines are rendered in ALL CAPS; free offers get "АБСОЛЮТНО БЕСПЛАТНО" suffix
- Category system: models, comparisons, coding, vibe_coding, dev_tools, watchlist, resources, freebies, noise
- Noise filtering removes prompt collections, listicles, courses, and marketing content
- Image selection uses a scoring system (`image_selection.py`) that penalizes SVGs, icons, logos, small images, and rewards OG/cover images
- Tests use `unittest.TestCase` (not pytest fixtures)
- No ORM — raw SQLite with `sqlite3.Row` for dict-like access

---

## Mandatory Quality Bar

Treat the following as top-priority project defects:
- a story link points to the wrong story
- a headline is too generic and fails to explain the news
- words are cut in the middle
- Telegram HTML or text is hard to read
- headlines degrade into noisy Title Case
- the model produces weak Russian phrasing
- an image caption or media link belongs to the wrong story

### Definition of Done for digest-related work

A task affecting the digest is not done until it is demonstrated that:
- each link is attached to the correct story
- text does not cut words in the middle
- headlines read naturally in Russian
- the final digest is visually readable and clean
- Telegram formatting is valid and stable
- tests, checks, and/or manual validation confirm the result
- known risks and limitations are explicitly listed

### Headline rules

Headlines must:
- be simple, clear, short, and informative
- explain the point of the story instead of copying the raw source title
- use normal sentence case, not noisy Title Case
- avoid clickbait, bureaucratic phrasing, and filler words
- preferably contain subject + action + meaning

Do not:
- blindly copy source titles
- produce vague headlines like "AI released a new model" when the company, product, or key capability can be named
- cut a headline in the middle of a word

### Digest text rules

- Keep wording compact but not robotic
- Never break words, HTML tags, or paragraphs during trimming
- Optimize for Telegram mobile readability
- Separate stories clearly with spacing or lightweight visual separators
- If a story has media, the media caption and link must match that exact story

### Summarization / LLM rules

If proposing a model, prompt, or fallback-chain change:
- prioritize free models unless the user explicitly asks for paid ones
- compare at least 3 options by Russian quality, format stability, latency, price, and summarization quality
- do not swap models blindly; test on real project examples
- evaluate not only wording quality, but also structural correctness, generic-headline risk, and instruction following

---

## Confirmation Policy

Before any action with an external side effect, ask for user confirmation.

Confirmation is mandatory before:
- sending the digest to a real Telegram chat or channel
- deleting or overwriting important data
- modifying production secrets, environment variables, deployment, or infrastructure
- publishing or pushing code

No confirmation is required for safe local work such as:
- reading code, logs, tests
- local analysis and dry runs
- preparing patches and writing plans
