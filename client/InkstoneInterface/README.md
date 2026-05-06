# Inkstone Interface

Parallel migration client for the Inkstone board refresh.

Goals:
- keep the legacy `client/Interface` app available during migration
- reuse the existing engine, state bridge, and coaching services
- stay software-only for gameplay: no CV turn capture, no physical-board sync
- treat Kibo as deprecated in this lane
- defer voice integration until the board migration is stable

Current local/dev port:
- `3002`

Reference material copied into this client:
- Inkstone image assets in `src/assets/`
- Inkstone UI primitives in `src/components/inkstone/`
- Inkstone audio hook in `src/hooks/useInkSounds.ts`

Operational pages intentionally retained from the integrated client:
- `/agents`
- `/hardware`

This directory is the active migration lane. `inkstone-chess/` remains the design/reference source and can be removed after the UI has been fully ported.
