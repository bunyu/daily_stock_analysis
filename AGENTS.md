# AGENTS.md

Default development rules for this repository. The goal is less back-and-forth, less rework, and changes that stay consistent with the project structure.

If this file disagrees with the scripts, workflows or code in the repository, trust what actually runs, and fix the document in the same change so the rules do not drift.

`CLAUDE.md` is a symlink to this file. Read [`HANDOFF.md`](HANDOFF.md) first for the current state of the fork and open items.

## 0. About this fork

- This is a personal fork of `ZhuLinsen/daily_stock_analysis`, used to analyse a Euronext watchlist (Yahoo symbols `.PA` and `.AS`, market code `fr`) every trading day before the Paris open.
- The owner works directly on `main`. When the owner asks for a change, commit and push to `main`; no pull request is needed. Do not commit or push work the owner did not ask for.
- Reports, workflow text and new documentation are in English. Upstream Chinese documents under `docs/` are kept as they are.
- Fork-specific code: `src/services/market_symbol_utils.py` (suffix market `fr`), `src/data/euronext_stocks.py` (names and search keywords), `src/multi_horizon.py` (multi-horizon trend and levels), `.github/workflows/00-daily-analysis.yml` (schedule gate).

## 1. Hard rules

- Respect directory boundaries:
  - Backend logic goes in `src/`, `data_provider/`, `api/`, `bot/`
  - Web frontend in `apps/dsa-web/`
  - Desktop app in `apps/dsa-desktop/`
  - Deployment and pipelines in `scripts/`, `.github/workflows/`, `docker/`
- Do not run `git commit`, `git tag` or `git push` without the owner's request (see section 0 for the standing rule on `main`).
- Commit messages are in English and carry no `Co-Authored-By` line.
- Never hard-code secrets, accounts, paths, model names, ports or environment-specific logic.
- Reuse existing modules, configuration entry points, scripts and tests. Do not add parallel implementations.
- Stability comes before opportunistic improvement. Hold back refactors, abstractions and infrastructure moves the task does not need.
- A new configuration key must be added to `.env.example` and the related documentation in the same change.
- A change to user-visible behaviour, CLI/API behaviour, deployment, notifications or report structure must update the related documentation and `docs/CHANGELOG.md`.
- The `[Unreleased]` section of `docs/CHANGELOG.md` uses a flat format: one line per entry, `- [type] description`, where type is one of `新功能` (feature), `改进` (improvement), `修复` (fix), `文档` (docs), `测试` (tests), `chore`. Do not add `###` headings inside `[Unreleased]`.
- Screenshots and one-off visual evidence are not committed to the repository.
- `README.md` holds positioning, quick start and main entry points only. Module behaviour, configuration detail, troubleshooting and edge cases belong in `docs/*.md`.
- Comments, docstrings and log messages should be clear and consistent with the surrounding file. English is preferred for new code.

## 1.1 Quality bar

- A change is judged by whether it solves a stated problem, keeps the affected surface minimal, keeps existing contracts consistent, and covers the real risk paths. It is not judged by lines added or by looking complete.
- AI-assisted work is fine. Unreviewed, unverified, non-converged AI output is not.
- After feedback, do not patch only the line that was pointed at. Re-check every entry point, configuration, test, document, workflow and user-visible path that shares the same business meaning.
- Do not hide an unclear contract behind a broad fallback, silent degradation, or `return False/None/[]`.
- Do not mock away the layer where the real risk lives.

## 2. AI collaboration assets

- `AGENTS.md` is the single source of truth for AI collaboration rules.
- `CLAUDE.md` must be a symlink to `AGENTS.md`.
- `.github/copilot-instructions.md` and `.github/instructions/*.instructions.md` mirror or extend these rules for GitHub Copilot; `AGENTS.md` wins on conflict.
- Repository skills live in `.claude/skills/`; analysis output goes to `.claude/reviews/` and is local by default.
- The root `SKILL.md` and `docs/openclaw-skill-integration.md` describe product integrations, not collaboration rules.
- After changing any of these assets, run:

```bash
python scripts/check_ai_assets.py
```

## 3. Repository overview

- Purpose: AI stock analysis. Upstream covers A-shares, Hong Kong, US, Japan, Korea and Taiwan; this fork adds Euronext.
- Main flow: fetch data -> technical analysis and news search -> LLM analysis -> report -> notification.
- Entry points:
  - `main.py`: analysis job
  - `server.py`: FastAPI service
  - `apps/dsa-web/`: web frontend
  - `apps/dsa-desktop/`: Electron desktop app
  - `.github/workflows/`: CI, release, daily job
- Responsibilities:
  - `src/core/`: pipeline orchestration
  - `src/services/`: business services
  - `src/repositories/`: data access
  - `src/reports/`: report generation
  - `src/schemas/`: schemas and data structures
  - `data_provider/`: data source adapters and fallback
  - `api/`: FastAPI API
  - `bot/`: bot integrations
  - `scripts/`: local scripts
  - `.github/scripts/`: GitHub automation
  - `tests/`: pytest tests
  - `docs/`: documentation

## 4. Common commands

### Run

```bash
python main.py
python main.py --debug
python main.py --dry-run
python main.py --stocks MC.PA,TTE.PA,ASML.AS
python main.py --market-review
python main.py --schedule
python main.py --serve
python main.py --serve-only
uvicorn server:app --reload --host 0.0.0.0 --port 8000
```

### Backend checks

```bash
pip install -r requirements.txt
pip install flake8 pytest
./scripts/ci_gate.sh
python -m pytest -m "not network"
python -m py_compile <changed_python_files>
```

### Web / Desktop

```bash
cd apps/dsa-web
npm ci
npm run lint
npm run build

cd ../dsa-desktop
npm install
npm run build
```

## 5. Default workflow

1. Classify the task: `fix / feat / refactor / docs / chore / test / review`.
2. Read the existing implementation, configuration, tests, scripts, workflows and documents before editing.
3. Identify the boundary: backend / API / Web / Desktop / workflow / docs / AI assets.
4. Check whether a high-risk area is involved: configuration semantics, API or schema, data source fallback, report structure, authentication, scheduling, release flow, desktop startup.
5. Make the smallest change that serves the task. No unrelated refactors.
6. When documents and code disagree, trust the code and workflows, then decide whether to fix the document.
7. Verify according to the matrix below.
8. Report: what changed, why, what was verified, what was not verified, risks, and how to roll back.

## 6. Verification matrix

### CI

| Check | Source | What it does | Blocking |
| --- | --- | --- | --- |
| `ai-governance` | `.github/workflows/ci.yml` | Validates `AGENTS.md` / `CLAUDE.md` / `.github` instructions / `.claude/skills` | Yes |
| `backend-gate` | `.github/workflows/ci.yml` | Runs `./scripts/ci_gate.sh` | Yes |
| `docker-build` | `.github/workflows/ci.yml` | Docker build and import smoke test | Yes |
| `web-gate` | `.github/workflows/ci.yml` | `npm run lint` and `npm run build` when the frontend changes | Yes, when triggered |
| `network-smoke` | `.github/workflows/network-smoke.yml` | `pytest -m network` and `scripts/test.sh quick` | No |
| `pr-review` | `.github/workflows/pr-review.yml` | Static checks, AI review, labels | No |

### By change surface

- **Python backend** (`main.py`, `src/`, `data_provider/`, `api/`, `bot/`, `tests/`): prefer `./scripts/ci_gate.sh`; at minimum `python -m py_compile <changed_python_files>`. If the change touches API, orchestration, report generation, notifications, data source fallback, authentication or scheduling, state whether that path was covered.
- **Web frontend** (`apps/dsa-web/`): `npm ci && npm run lint && npm run build`.
- **Desktop** (`apps/dsa-desktop/` and build scripts): build the web app, then the desktop app; state what could not be verified on the current platform.
- **API / schema / authentication**: backend checks plus a build of each affected client. State compatibility impact for any field, enum, cookie or session change.
- **Docs and governance files**: no code tests required. Confirm that commands, configuration keys, file names and workflow names match the repository. Run `python scripts/check_ai_assets.py` for AI assets.
- **Workflows / scripts / Docker** (`.github/**`, `scripts/**`, `docker/**`): run the closest local check, say which pipeline is affected, and say what was not run and why.
- **Network or third-party dependencies**: run offline or deterministic checks first; confirm timeout, retry, fallback and degradation paths still hold; say so when no online check was run. Yahoo Finance is not reachable from some sandboxes, so `.PA` data may need a real workflow run to verify.

## 7. Stability guardrails

- **Configuration and entry points**: a change to `.env` semantics, defaults, CLI arguments, startup or scheduling must be assessed for local runs, Docker, GitHub Actions, API, Web and Desktop. New configuration should work when unset and add capability when set.
- **Data sources and fallback**: watch source priority, failure degradation, field normalisation, caching and timeouts. One failing source must not take down the whole analysis.
- **API / Web / Desktop compatibility**: prefer adding fields and keeping old ones.
- **Report / prompt / notification**: check that upstream inputs and downstream consumers still agree. One failing channel must not take down the analysis.
- **Workflow / release / packaging**: assess triggers, artifact paths, permissions and rollback. Automatic tagging is opt-in: only a commit title containing `#patch`, `#minor` or `#major` bumps the version, so never use those markers by accident.
- **Daily schedule**: the daily workflow relies on two UTC crons and the `schedule-gate` job. When changing the time, change both crons and the matching strings in the gate.

## 8. Issue / PR / skill workflow

- Existing skills: `.claude/skills/analyze-issue/SKILL.md`, `.claude/skills/analyze-pr/SKILL.md`, `.claude/skills/fix-issue/SKILL.md`. Use them for issue analysis, PR review and issue fixes, and save output to `.claude/reviews/`.
- Before PR or issue work, sync the baseline with `git fetch --all --prune`, and `git pull --ff-only` when the tree is clean and can fast-forward. Never force a branch switch, stash, reset or overwrite local state.
- Skills must not push, tag or create PRs without the owner's confirmation.
- PR review order: necessity, relevance, title, description completeness, verification evidence, correctness, merge verdict.
- For a `fix`, state the original problem, the root cause, the fix, and the regression risk.
- Merge blockers: correctness or security problems, failing blocking CI, a description that contradicts the diff, no rollback plan, repeated non-converging patches.

## 9. Delivery

- Default delivery note: what changed, why, verification, not verified, risks, rollback.
- For a docs-only task, `Docs only, tests not run` is enough, as long as commands and file names were checked.
- Manual tags must be annotated tags.
