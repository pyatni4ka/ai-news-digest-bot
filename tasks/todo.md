# AI News Digest Bot: stabilization and deploy track

## Task objective
- Turn the current repository into a production-grade Telegram AI digest bot with reliable filtering, stable runtime behavior, clean deployment posture, and a deployable always-on setup.

## Checklist
- [x] Inspect architecture, tests, docs, runtime files, database state, and current git status.
- [x] Run existing tests.
- [x] Run a real `sync` and inspect a real generated digest.
- [ ] Fix false-positive classification that pushes irrelevant stories into the digest.
- [ ] Review and prune/fix default sources with focus on AI relevance and runtime stability.
- [ ] Remove secret/config anti-patterns from repo and container build path.
- [ ] Clean repository hygiene: generated artifacts, tracked media/cache files, helper auth leftovers.
- [ ] Improve bot send flow and digest UX where code/runtime gaps are confirmed.
- [ ] Add regression tests for every critical fixed defect.
- [ ] Re-run tests, sync, digest build, and deployment smoke checks.
- [ ] Prepare primary deployment target and perform real deploy after user confirmation.

## Verification plan
- Run `.venv/bin/python -m pytest -q`.
- Run `.venv/bin/ai-news-digest sync` and confirm source error profile improves.
- Run `.venv/bin/ai-news-digest digest --slot manual` and inspect the saved digest text/payload for relevance, readable Russian, and correct story links.
- Smoke-check Docker/systemd/deploy artifacts after config cleanup.

## Result summary
- In progress.
- Current confirmed issues:
- Secrets/config are mixed into repo/deploy flow.
- Repository tracks generated media/cache artifacts.
- Real sync shows multiple broken or slow sources.
- Real generated digest includes irrelevant gaming/meme stories due to classifier false positives.

## Remaining risks / follow-ups
- External deploy requires user confirmation and target-platform choice.
- Telegram account/session strategy must be finalized before production rollout.
- Some source choices are product-policy decisions, not only engineering fixes.

## Lessons learned
- Pending.
