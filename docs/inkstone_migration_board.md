# Inkstone Migration Board

## Decisions

- New migration lane: `client/InkstoneInterface`
- Legacy UI stays available at `http://localhost:3000`
- Inkstone migration client runs at `http://localhost:3002`
- `/agents` and `/hardware` stay functionally the same as the current integrated client
- Inkstone remains a reference source for now and will be removed after migration
- New client is software-only for gameplay: no CV capture, no physical-board sync
- Voice controls move to backlog and are not part of the initial migration
- Kibo is deprecated for the new client: no trigger calls, no viewer dependency in the new lane

## Extracted Inkstone Reference Assets

Copied into `client/InkstoneInterface`:

- `src/assets/brush-stroke.png`
- `src/assets/fisherman-bg.jpg`
- `src/assets/hero-mountains.jpg`
- `src/components/inkstone/BrushHeading.tsx`
- `src/components/inkstone/InkReveal.tsx`
- `src/hooks/useInkSounds.ts`

Reference-only upstream source files still living in `inkstone-chess/`:

- `src/pages/LandingPage.tsx`
- `src/pages/XiangqiGame.tsx`
- `src/index.css`
- `src/lib/xiangqiRules.ts`

## Sprint 0: Parallel Lane Setup

Goal: start migration without risking the deprecated UI.

- `INK-S0-01` Create `client/InkstoneInterface` from the integrated client baseline.
  - Done when the directory builds independently and does not replace `client/Interface`.
- `INK-S0-02` Move the new lane to port `3002`.
  - Done when local dev and Docker can expose the new client on `3002`.
- `INK-S0-03` Keep `/agents` and `/hardware` unchanged in behavior.
  - Done when those routes are still reachable in the new client.
- `INK-S0-04` Disable hardware-only gameplay flows in the new lane.
  - Done when End Turn no longer depends on CV capture or physical-board verification.
- `INK-S0-05` Deprecate Kibo in the new lane.
  - Done when no Kibo trigger calls are emitted from the new client.
- `INK-S0-06` Defer voice integration.
  - Done when voice UI is removed from the new lane and captured in backlog instead.

## Sprint 1: Inkstone Design System Port

Goal: transplant Inkstone visual language onto the engine-backed client shell.

- `INK-S1-01` Port Inkstone typography, colors, and motion tokens into `client/InkstoneInterface`.
  - Done when shared board and shell styling no longer depends on legacy UI styles alone.
- `INK-S1-02` Introduce a reusable Inkstone shell for the main page.
  - Done when header, background treatment, and section framing match the new direction.
- `INK-S1-03` Bring in Inkstone primitives where safe.
  - Done when `BrushHeading`, `InkReveal`, and ink-themed assets are available for real screens.
- `INK-S1-04` Preserve chat and operational navigation while restyling.
  - Done when `/`, `/agents`, and `/hardware` still function during visual migration.

## Sprint 2: Board Migration

Goal: replace board presentation while keeping the current backend contracts.

- `INK-S2-01` Build a new `InkstoneBoard` presentation component in the new client.
  - Done when board visuals no longer depend on the legacy `ChessBoard` presentation.
- `INK-S2-02` Keep engine-backed move staging and turn flow.
  - Done when pending moves, legal targets, AI moves, and game-over states still come from the current bridge/engine stack.
- `INK-S2-03` Remove browser-only rules as production truth.
  - Done when no live move validation depends on `inkstone-chess/src/lib/xiangqiRules.ts`.
- `INK-S2-04` Preserve coaching-assisted move commentary.
  - Done when board events still feed the existing coaching service for advice generation.

## Sprint 3: Advice Experience and Product Parity

Goal: make the new client feature-complete for software-only play.

- `INK-S3-01` Restyle `ChatPanel` for Inkstone while keeping the current coaching backend.
  - Done when move commentary and free-form advice remain functional.
- `INK-S3-02` Audit `/agents` and `/hardware` for visual regressions only.
  - Done when those routes keep their current behavior and link structure.
- `INK-S3-03` Remove legacy board-specific UI copy that still references physical mirroring.
  - Done when player-facing messaging is software-only and no longer mentions camera or board resync.
- `INK-S3-04` Add a visible “migration lane” label or beta marker.
  - Done when testers can distinguish the new UI from the deprecated one.

## Sprint 4: Hardening and Cutover Prep

Goal: make the new lane safe enough to replace the old one later.

- `INK-S4-01` Add regression tests for engine-backed board behavior.
  - Done when tests cover move staging, AI turn handling, and chat wiring.
- `INK-S4-02` Add route-level smoke tests for `/`, `/agents`, and `/hardware`.
  - Done when the new client can be validated without manual full-stack browsing.
- `INK-S4-03` Remove remaining Kibo-only and hardware-only assumptions from copy, config, and docs.
  - Done when the new client is clearly software-first.
- `INK-S4-04` Plan final cutover and `inkstone-chess/` removal.
  - Done when the old prototype is no longer needed as a live reference.

## Backlog

- `INK-BL-01` Voice controls integration using the coaching/TTS stack
- `INK-BL-02` Inkstone landing page replacement for the current home screen
- `INK-BL-03` Dedicated mobile polish for the new board layout
- `INK-BL-04` Remove deprecated Kibo service from compose after old UI retirement
- `INK-BL-05` Replace legacy board marker styling with Inkstone-native overlays
