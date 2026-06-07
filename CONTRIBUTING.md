# Contributing to VidSumAI

Thanks for your interest in contributing! This document covers everything you need to get the project running locally, run the test suite, and submit a PR.

## Code of Conduct

All participants are expected to follow the [Code of Conduct](CODE_OF_CONDUCT.md). Be respectful and constructive.

## Development Environment

| Tool | Version | Why |
|------|---------|-----|
| Node.js | 18+ | Frontend (Nuxt 3) |
| Python | 3.10+ | Backend (FastAPI) |
| [uv](https://docs.astral.sh/uv/) | latest | Python package manager (replaces pip + venv) |
| ffmpeg | any recent | Merges DASH audio + video streams |
| [Playwright](https://playwright.dev/) | bundled via npm | E2E tests |

`yt-dlp`'s browser impersonation also requires `curl-cffi`, which is installed automatically by `uv sync`.

## First-time Setup

```bash
# 1. Clone
git clone https://github.com/SAX-ops/VidSumAI.git
cd VidSumAI

# 2. Frontend
cd frontend
npm install
cd ..

# 3. Backend
cd backend
uv sync
cd ..
```

## Running Locally

You need **two terminals** — backend on `:8000`, frontend on `:3000`.

```bash
# Terminal 1 — backend
cd backend
uv run python -m uvicorn main:app --host 0.0.0.0 --port 8000

# Terminal 2 — frontend
cd frontend
npx nuxi dev
```

Open <http://localhost:3000>.

For GFW-blocked platforms (YouTube, TikTok, X, Facebook, Instagram), set proxy env vars **before** starting the backend:

```bash
# Windows (PowerShell)
$env:HTTP_PROXY  = "http://127.0.0.1:7890"
$env:HTTPS_PROXY = "http://127.0.0.1:7890"

# macOS / Linux
export HTTP_PROXY=http://127.0.0.1:7890
export HTTPS_PROXY=http://127.0.0.1:7890
```

The backend auto-detects proxy from `HTTP(S)_PROXY` env vars or common ports (7890 / 10809 / 1080). It only routes GFW-blocked sites through the proxy — B站, 抖音, 小红书, 微博 connect directly.

### B站 1080P+ Unlock (Optional)

To download 1080P+ on Bilibili, log in to bilibili.com in Firefox. The backend auto-extracts cookies from `%APPDATA%\Mozilla\Firefox\Profiles\*\cookies.sqlite` and passes them to yt-dlp.

Without login, B站 downloads max out at 480p (visitor mode).

## Running Tests

### Backend unit tests

```bash
cd backend
uv run pytest                    # all
uv run pytest tests/test_ytdlp.py # one file
uv run pytest -k test_parse_url   # by name
```

### Frontend E2E tests (Playwright)

```bash
# Pre-requisites:
#   - Backend running on :8000
#   - Frontend running on :3000
#   - GFW proxy available (for YouTube / TikTok)

cd frontend
PROXY_AVAILABLE=1 npx playwright test --project=chromium    # all
npx playwright test video-preview.spec.ts -g "B站"          # single platform
CI=1 npx playwright test                                      # CI mode (no retries)
```

Tests are integration-only — they hit the real backend, real proxy, and real CDNs. They skip (not fail) when infra is missing. See [`docs/superpowers/specs/2026-06-07-video-preview-e2e-design.md`](docs/superpowers/specs/2026-06-07-video-preview-e2e-design.md) for the design rationale.

## Project Conventions

### Code style

- **Python**: PEP 8, type hints on public APIs, docstrings only when the *why* is non-obvious
- **Vue / TypeScript**: Composition API with `<script setup>`, Tailwind utility classes, no inline `<style>` blocks unless component-scoped CSS is needed

### Commit messages

Use [Conventional Commits](https://www.conventionalcommits.org/) format. The git history already follows this pattern — see `git log` for examples.

```
feat: add batch download UI
fix: prevent audio desync on rapid seek
docs: update API endpoint table
chore: bump yt-dlp to 2026.04.01
test: add e2e for YouTube proxy path
refactor: extract DASH audio detection helper
```

### Branching

- `master` is the release branch — keep it green
- For new work, branch from `master`: `git checkout -b feat/short-name`
- Rebase before opening the PR: `git rebase master`

## Submitting a Pull Request

1. **Open an issue first** for non-trivial changes (new feature, large refactor, platform support). This saves you from writing code that gets rejected.
2. **Keep PRs focused** — one logical change per PR. Multiple unrelated fixes should be separate PRs.
3. **Fill out the PR template** — it's in `.github/PULL_REQUEST_TEMPLATE.md` and renders automatically.
4. **Pass all checks locally**:
   - `cd backend && uv run pytest`
   - `cd frontend && npx nuxi build`
   - For UI changes: run the relevant Playwright test
5. **Push and open the PR**:
   ```bash
   git push origin feat/your-branch
   gh pr create --fill
   ```
6. **Respond to review comments** — push follow-up commits, don't force-push during review.

## Reporting Bugs

Use the [Bug Report](.github/ISSUE_TEMPLATE/bug_report.md) template. Include:

- Exact steps to reproduce
- Your OS, browser, Python / Node versions
- The platform / URL that triggered the bug
- Backend logs and / or browser console errors

## Suggesting Features

Use the [Feature Request](.github/ISSUE_TEMPLATE/feature_request.md) template. Describe the user problem, not just the proposed solution — there may be a better way.

## Questions?

Open a GitHub issue with the `question` label. We don't have a chat server yet.

## License

By contributing, you agree that your contributions will be licensed under the [MIT License](LICENSE).
