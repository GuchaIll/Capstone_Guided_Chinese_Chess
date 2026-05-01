# Fish Speech Voice Cloning

This plan is intentionally **voice-cloning only**. We are not fine-tuning for now.

That matches Fish Audio's current guidance well:
- Fish Audio S2 supports rapid voice cloning from short reference audio, typically 10-30 seconds.
- Fish's official fine-tune docs warn that fine-tuning an RL-trained model can degrade quality.
- Fish's server docs expose a self-hosted HTTP API, which is a good fit for Modal deployment.

Primary sources:
- [Fish Speech overview](https://github.com/fishaudio/fish-speech/blob/main/docs/en/index.md)
- [Fish inference](https://speech.fish.audio/inference/)
- [Fish server](https://speech.fish.audio/server/)
- [Fish installation](https://speech.fish.audio/install/)

## Model choice

Use `s2-pro` as the base inference model.

Recommended env:

```env
FISH_TTS_MODEL=s2-pro
FISH_TTS_API_URL=https://your-modal-endpoint.modal.run
FISH_TTS_API_KEY=
FISH_TTS_TIMEOUT_SECONDS=45
```

## Local reference-audio workflow

The repository now includes a lightweight prep flow under `tts/`:

- `tts/prepare_voice_cloning.py`
  - scans `tts/data`
  - creates missing transcript and style sidecars
  - writes `tts/voice_clone_manifest.json`
- `tts/build_voice_clone_bundle.py`
  - collects ready clips for one voice
  - builds `tts/out/<voice-id>_reference_bundle.json`
- `tts/scripts/prepare_voice_cloning.sh`
  - bootstrap command for annotation files
- `tts/scripts/build_voice_clone_bundle.sh`
  - one-command bundle build for a chosen voice

Run the bootstrap:

```bash
tts/scripts/prepare_voice_cloning.sh
```

Build a bundle for the current `chopper` clips:

```bash
tts/scripts/build_voice_clone_bundle.sh chopper
```

## How to annotate transcripts and style

Each audio clip should have two sidecars next to it:

- `.lab`
  - exact transcript of what is spoken
  - plain text only
  - no markup, no stage directions, no metadata
- `.style.txt`
  - your human annotation for delivery and performance
  - used by our workflow as metadata
  - not part of Fish's required `.lab` format

### Transcript rules

Put the literal spoken words in the `.lab` file.

Good:

```text
Move the horse to f3 and prepare to castle on the next turn.
```

Bad:

```text
[calm tone] Move the horse to f3 and prepare to castle on the next turn.
```

Bad:

```text
Speaker: calm, tactical, medium pace
Move the horse to f3 and prepare to castle on the next turn.
```

### Style rules

Put style guidance in the `.style.txt` file instead:

```text
mood: calm, confident
pace: medium
energy: restrained
delivery: tactical coach, slightly playful
notes: avoid shouting, keep phrasing smooth and deliberate
```

### File examples

For `tts/data/chopper_v1/chopper_v1.m4a`, annotate:

- `tts/data/chopper_v1/chopper_v1.lab`
- `tts/data/chopper_v1/chopper_v1.style.txt`

For `tts/data/chopper_v3/chopper_v3.m4a`, annotate:

- `tts/data/chopper_v3/chopper_v3.lab`
- `tts/data/chopper_v3/chopper_v3.style.txt`

## Why separate transcript and style

This split keeps the data clean:

- Fish expects the transcript separately from the reference audio.
- Transcript text should mirror the spoken content as closely as possible.
- Style notes are still useful for selecting the best reference clips and building prompt metadata, but they should not pollute the transcript.

## What the bundle is for

`tts/out/<voice-id>_reference_bundle.json` is the handoff artifact for the next stage.

It contains:
- selected audio clip paths
- their transcripts
- parsed style notes
- a combined `prompt_text`
- a combined `style_summary`

That bundle gives us one consistent reference package to feed into the Modal-hosted Fish TTS service.

## Modal deployment shape

For Modal, keep the deployment simple:

1. Deploy a self-hosted Fish S2 server.
2. Keep `s2-pro` fixed at server startup.
3. Pass reference audio plus transcript per generation request.
4. Keep app-level provider switching outside Modal.

Recommended split:

- Modal app: Fish server only
- Your app backend: proxy/auth/retries/cache
- Frontend: provider switch between browser TTS and Fish TTS

This repository now includes the first scaffold for that split:

- `tts/modal_serve_fish.py`
  - Modal-hosted `/health` and `/tts`
  - accepts bundled reference audio from Kibo
  - runs the Fish cloning pipeline on GPU
  - starts from Fish Audio's official Docker image to avoid editable-install dependency resolver failures during Modal builds
- `tts/scripts/deploy_modal_fish.sh`
  - deploy helper for the Modal app
- `server/chess_coach/cmd/fish_tts.go`
  - Go proxy endpoint at `/dashboard/tts`
  - reads `FISH_TTS_REFERENCE_BUNDLE`
  - forwards the request to Modal
- `client/Interface/src/services/speech/SpeechService.ts`
  - env-driven provider switch between browser speech and Fish Modal

### Deploy flow

Deploy the Modal app:

```bash
tts/scripts/deploy_modal_fish.sh
```

Then point the Go coaching service at it:

```env
FISH_TTS_API_URL=https://<workspace>--guided-chinese-chess-fish-serve.modal.run
FISH_TTS_API_KEY=
FISH_TTS_MODEL=s2-pro
FISH_TTS_REFERENCE_BUNDLE=/app/tts/out/chopper_reference_bundle.json
FISH_TTS_TIMEOUT_SECONDS=90
```

For the frontend, switch providers with:

```env
NEXT_PUBLIC_TTS_PROVIDER=fish_modal
NEXT_PUBLIC_TTS_FALLBACK_PROVIDER=browser
```

Modal docs that matter here:
- [Web endpoints](https://modal.com/docs/guide/webhooks)
- [Container lifecycle hooks](https://modal.com/docs/guide/lifecycle-functions)
- [GPU acceleration](https://modal.com/docs/guide/gpu)
- [Volumes](https://modal.com/docs/guide/volumes)
- [Secrets](https://modal.com/docs/guide/secrets)

## Integration direction

When you wire this into the product, keep browser speech as the default fallback.

Recommended provider setup:

```env
NEXT_PUBLIC_TTS_PROVIDER=browser
NEXT_PUBLIC_TTS_FALLBACK_PROVIDER=browser
TTS_PROVIDER=browser
FISH_TTS_MODEL=s2-pro
```

Then later:

```env
NEXT_PUBLIC_TTS_PROVIDER=fish_modal
TTS_PROVIDER=fish_modal
```

The important part is that `FISH_TTS_MODEL` stays server-side and can be changed in `.env` without touching the client bundle.
