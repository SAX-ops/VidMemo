# Design Specs & Implementation Plans

This directory contains the technical design documents and step-by-step implementation plans used during VidSumAI's development. It's the internal record of *how* the system was built and *why* those decisions were made.

## Audience

This is the technical counterpart to [`../PRD.md`](../PRD.md).

- **PRD** — *what* the product does, who it's for, what's in scope
- **Here** — *how* it's built, what tradeoffs were considered, what the edge cases are

## Specifications

Design documents — capture architectural decisions, data flow, and constraints *before* implementation.

| Date | Spec | Status |
|------|------|--------|
| 2026-04-25 | [VidSumAI Design](./specs/2026-04-25-vidsumai-design.md) | ✅ Implemented — core architecture, MoSCoW scope, API contract, data models |
| 2026-06-07 | [Video Preview E2E Test Design](./specs/2026-06-07-video-preview-e2e-design.md) | ✅ Implemented — Playwright test strategy, skip logic, pass criteria |

## Implementation Plans

Step-by-step feature plans — what to change, in what order, with edge case analysis.

| Date | Plan | Status |
|------|------|--------|
| 2026-04-25 | [MVP Implementation Plan](./plans/2026-04-25-vidsumai-mvp.md) | ✅ Done — initial 9-platform support |
| 2026-04-26 | [Preview + Download Feature](./plans/2026-04-26-preview-download-feature.md) | ✅ Done — VideoPreview.vue, DASH audio sync, quality selector |
| 2026-06-07 | [Video Preview E2E Plan](./plans/2026-06-07-video-preview-e2e.md) | ✅ Done — Playwright e2e for B站, YouTube, TikTok |

## For Contributors

If you're picking up a new feature:

1. Read the relevant **spec** to understand the design intent
2. Skim the **plan** to see what was done before
3. Open an issue to discuss the new approach — don't write code first
4. Use the [writing-plans skill](https://github.com/SuperClaude-Org/superpowers) (or your team's equivalent) to plan implementation
5. Submit a PR with a clear link back to the discussion issue

If you're trying to understand *why* a particular decision was made, the design specs are the source of truth.
