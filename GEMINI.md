# GEMINI.md

## Role and language

You are working on the **AI/news-digest-bot** project.

Mandatory rules:
- **Always communicate with the user in Russian unless the user explicitly asks for another language.**
- Be direct and honest. Do not pretend something was verified if it was not.
- Prefer solutions that remain maintainable over time.
- Optimize for correctness, readability, and long-term stability.

## Output format for this user

When you provide anything the user may want to copy:
- present it in a fenced code block;
- provide complete commands, configs, prompts, patches, or file contents;
- do not force the user to reconstruct missing parts manually.

Examples of things that must be copyable:
- shell commands;
- config files;
- prompts;
- JSON/YAML;
- Markdown files;
- code snippets.

## Project objective

Improve **AI/news-digest-bot** as an engineering system, not just as text output.

Project priorities:
1. Pipeline correctness and stability.
2. Digest quality in Telegram.
3. Reliable link-to-story binding.
4. Strong Russian headlines without noisy Title Case.
5. No mid-word truncation or broken HTML fragments.
6. Verified changes with low regression risk.
7. New features only after the key digest defects are fixed.

## Default working mode

For any non-trivial task:
- first inspect the code, config, tests, logs, docs, and current architecture;
- do not invent facts when the repository, logs, tests, or official documentation can answer the question;
- if the task involves 3+ steps, architectural decisions, integrations, CI/CD, production risk, unclear debugging, or refactoring, write a plan first;
- if the plan becomes invalid because of new evidence, stop and re-plan before continuing;
- make the smallest correct change that fully solves the problem;
- verify after each meaningful change instead of assuming success.

For research tasks:
- first gather **3–5 best options**;
- then provide a short comparison with pros, cons, risks, and a recommendation.

If one approach fails:
- try **1–2 reasonable alternatives** before stopping.

## Source priority

Use sources in this order:
1. Official documentation.
2. Primary sources: specifications, GitHub repositories, README files, issues, changelogs, API docs.
3. The current project’s code and tests.
4. Logs, CI, and real execution artifacts.
5. Secondary sources only if primary sources are insufficient.

## Extensions and tool routing

Use active extension-provided tools when they are relevant, but do not assume they are always available.

Tool priority:
1. Use **Context7** first for library/framework documentation, version-specific APIs, and canonical usage patterns.
2. Use **Exa code context** if Context7 is unavailable or insufficient.
3. Use **Exa web search** for current information, release checks, pricing, and ecosystem research.
4. Use **Chrome DevTools** for browser-side debugging, DOM inspection, console errors, network issues, and real UI verification.
5. Use **Google Workspace** only when the task actually requires Calendar, Gmail, Docs, Sheets, Slides, or Chat, and ask for confirmation before any write action.
6. Use **security tools** only for explicit security reviews, vulnerability scans, or dependency audits.

Rules:
- Never pretend an extension or MCP server is available if it is inactive or disconnected.
- If a preferred tool is unavailable, say so explicitly and use the next safe fallback.
- Do not use GEMINI.md to manage installation, enabling, disabling, or updating extensions. That belongs to CLI/environment configuration.

## Confirmation policy

Before any action with an external side effect, ask for user confirmation.

Confirmation is mandatory before:
- form submission;
- purchases;
- publication;
- account sign-in;
- money-related actions;
- sending emails, chat messages, or calendar events;
- sending the digest to a real Telegram chat or channel;
- deleting or overwriting important data;
- modifying production secrets, environment variables, deployment, or infrastructure.

No confirmation is required for safe local work such as:
- reading code;
- reading logs;
- running tests;
- local analysis;
- preparing patches;
- dry runs;
- writing a plan.

## Mandatory quality bar for AI/news-digest-bot

Treat the following as top-priority project defects:
- a story link points to the wrong story;
- a headline is too generic and fails to explain the news;
- words are cut in the middle;
- Telegram HTML or text is hard to read;
- headlines degrade into noisy Title Case;
- the model produces weak Russian phrasing;
- an image caption or media link belongs to the wrong story.

### Definition of Done for digest-related work

A task affecting the digest is not done until it is demonstrated that:
- each link is attached to the correct story;
- text does not cut words in the middle;
- headlines read naturally in Russian;
- the final digest is visually readable and clean;
- Telegram formatting is valid and stable;
- tests, checks, and/or manual validation confirm the result;
- known risks and limitations are explicitly listed.

### Headline rules

Headlines must:
- be **simple, clear, short, and informative**;
- explain the point of the story instead of copying the raw source title;
- use **normal sentence case**, not noisy Title Case;
- avoid clickbait, bureaucratic phrasing, and filler words;
- preferably contain subject + action + meaning.

Do not:
- blindly copy source titles;
- produce vague headlines like “AI released a new model” when the company, product, or key capability can be named;
- cut a headline in the middle of a word.

### Digest text rules

- Keep wording compact but not robotic.
- Never break words, HTML tags, or paragraphs during trimming.
- Optimize for Telegram mobile readability.
- Separate stories clearly with spacing or lightweight visual separators.
- If a story has media, the media caption and link must match that exact story.

### Summarization / LLM rules

If proposing a model, prompt, or fallback-chain change:
- prioritize **free** models unless the user explicitly asks for paid ones;
- compare at least 3 options by Russian quality, format stability, latency, price, and summarization quality;
- do not swap models blindly; test on real project examples;
- evaluate not only wording quality, but also structural correctness, generic-headline risk, and instruction following.

## Planning and tracking

For non-trivial tasks, maintain a lightweight tracker in `tasks/todo.md`.

Minimum structure:
- task objective;
- checklist of steps;
- verification plan;
- result summary;
- remaining risks / follow-ups;
- lessons learned.

After a user correction or your own avoidable mistake:
- update `tasks/lessons.md`;
- record not just the mistake, but the rule that should prevent it next time.

Lesson template:

```md
## Lesson: <short title>
- Context:
- Mistake:
- Why it happened:
- Prevention rule:
- How to apply next time:
```