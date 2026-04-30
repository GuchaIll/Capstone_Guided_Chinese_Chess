# Modal Qwen vLLM Setup

This folder now contains a Modal deployment path that makes Qwen available as an OpenAI-compatible backend for `go-coaching`.

Files:

- `modal_qwen_server.py`: deploys a vLLM server on Modal with `/v1/chat/completions`
- `modal_train_lora.py`: runs `train_lora.py` inside Modal on a GPU and commits adapter checkpoints back into the shared Volume
- `sync_modal_volume.sh`: uploads local `finetunning/` assets and optional model weights into a Modal Volume

## 1. Create and populate the Volume

From your local terminal:

```bash
modal volume create guided-chinese-chess-finetuning
./finetunning/sync_modal_volume.sh guided-chinese-chess-finetuning ./finetunning ./path/to/merged_model_or_adapter
```

If you only want to upload the `finetunning/` folder and not model weights yet:

```bash
./finetunning/sync_modal_volume.sh guided-chinese-chess-finetuning ./finetunning
```

By default the script uploads:

- local `./finetunning` to remote `/finetunning`
- optional local weights directory to remote `/models/qwen-xiangqi`

## 2. Train directly on Modal with the shared Volume

After syncing the folder once, you can launch LoRA training remotely:

```bash
modal run finetunning/modal_train_lora.py
```

Quick validation run:

```bash
modal run finetunning/modal_train_lora.py --max-steps 20 --batch-size 1
```

Custom training run:

```bash
modal run finetunning/modal_train_lora.py \
  --model Qwen/Qwen2.5-7B-Instruct \
  --epochs 3 \
  --batch-size 1 \
  --grad-accum 8 \
  --output-dir /vol/finetunning/output/xiangqi-lora
```

By default the trainer uses:

- `/vol/finetunning/data/dataset.train.clean.jsonl`
- `/vol/finetunning/data/dataset.val.clean.jsonl`
- `/vol/finetunning/output/xiangqi-lora`

The remote runner executes your existing [train_lora.py](/Users/guchaill/Coding/Capstone_Guided_Chinese_Chess/finetunning/train_lora.py) inside the mounted Volume, then calls `volume.commit()` so the serving app can read the new adapter.

## 3. Mount the same Volume in your Modal notebook

Use the same named Volume in your notebook so training checkpoints land in the same durable storage the server reads from.

```python
import modal

app = modal.App("guided-chinese-chess-finetune")
volume = modal.Volume.from_name("guided-chinese-chess-finetuning", create_if_missing=True)

@app.function(
    gpu="A100-40GB",
    timeout=60 * 60 * 6,
    volumes={"/vol": volume},
)
def train():
    volume.reload()
    # Write checkpoints somewhere under /vol, for example:
    # /vol/finetunning/output/xiangqi-lora
    #
    # Your existing train_lora.py already supports --output-dir,
    # so point it at a path inside /vol.
    #
    # After the job writes new checkpoints, commit them so serving
    # containers can reload the latest state.
    volume.commit()
```

Suggested paths inside the Volume:

- `/vol/finetunning/data`
- `/vol/finetunning/output/xiangqi-lora`
- `/vol/models/qwen-xiangqi`

If you keep LoRA adapters instead of merged weights, set `MODAL_QWEN_LORA_DIR=/finetunning/output/xiangqi-lora` when deploying the server.

## 4. Deploy the OpenAI-compatible server

```bash
modal deploy finetunning/modal_qwen_server.py
```

Useful deployment env vars:

```bash
export MODAL_QWEN_BASE_MODEL=Qwen/Qwen3-4B-Instruct-2507
export MODAL_QWEN_SERVED_MODEL=xiangqi-coach-qwen
export MODAL_QWEN_MODEL_DIR=/models/qwen-xiangqi
export MODAL_QWEN_LORA_DIR=/finetunning/output/xiangqi-lora
export MODAL_QWEN_GPU=A100-40GB
export MODAL_QWEN_FAST_BOOT=true
export MODAL_QWEN_API_KEY=replace-me-if-you-want-bearer-auth
modal deploy finetunning/modal_qwen_server.py
```

Notes:

- If `/models/qwen-xiangqi` exists in the Volume, the server serves that path directly.
- Otherwise it falls back to `Qwen/Qwen3-4B-Instruct-2507` from Hugging Face.
- If `MODAL_QWEN_LORA_DIR` exists, the server enables LoRA in vLLM and exposes the adapter under the same served model name.

## 5. Point the coach at Modal

Once Modal prints your public endpoint URL, set your local `.ENV`:

```env
LLM_PROVIDER=modal
MODAL_LLM_BASE_URL=https://<workspace>--guided-chinese-chess-qwen-serve.modal.run/v1
MODAL_LLM_MODEL=xiangqi-coach-qwen
MODAL_LLM_API_KEY=replace-me-if-you-enabled-server-auth
LLM_TIMEOUT_SECONDS=45
```

Then rebuild or restart the Go coach container:

```bash
docker compose up -d --build go-coaching client
```

## 6. Quick checks

Health:

```bash
curl https://<workspace>--guided-chinese-chess-qwen-serve.modal.run/health
```

Chat completion:

```bash
curl https://<workspace>--guided-chinese-chess-qwen-serve.modal.run/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer replace-me-if-you-enabled-server-auth" \
  -d '{
    "model": "xiangqi-coach-qwen",
    "messages": [
      {"role": "system", "content": "You are a Xiangqi coach."},
      {"role": "user", "content": "Explain why centralizing the chariot can be useful."}
    ]
  }'
```

## 7. Recommended workflow

1. Sync local data and code with `sync_modal_volume.sh`.
2. Train with `modal run finetunning/modal_train_lora.py` or from a notebook, writing outputs into `/vol/...`.
3. Commit the Volume after training finishes.
4. Redeploy or restart the serving app if you changed config.
5. The serving container reloads the Volume before boot, so newly committed checkpoints become visible to vLLM.
