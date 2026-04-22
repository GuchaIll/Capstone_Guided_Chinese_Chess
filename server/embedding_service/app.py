"""
Embedding Service
=================

Lightweight HTTP service exposing sentence-transformer embeddings.
Used by the Go chess-coach service to embed query text before
querying ChromaDB.

Endpoint:
    POST /embed  {"texts": ["query text"]}  → {"embeddings": [[0.1, ...], ...]}
    GET  /health                             → {"status": "ok"}
"""

from __future__ import annotations

import json
import os
from http.server import HTTPServer, BaseHTTPRequestHandler

from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

_ef = DefaultEmbeddingFunction()
_PORT = int(os.environ.get("EMBEDDING_PORT", "8100"))


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            self._json_response({"status": "ok"})
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path != "/embed":
            self.send_error(404)
            return

        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length)) if length else {}
        texts = body.get("texts", [])

        if not texts:
            self._json_response({"error": "no texts provided"}, status=400)
            return

        embeddings = _ef(texts)
        # Convert numpy arrays to lists
        result = [emb.tolist() if hasattr(emb, "tolist") else list(emb) for emb in embeddings]
        self._json_response({"embeddings": result})

    def _json_response(self, data: dict, status: int = 200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        # Suppress per-request logs; use structured logging if needed
        pass


def main():
    # Warm up the model on startup
    print(f"Loading embedding model...", flush=True)
    _ef(["warmup"])
    print(f"Embedding service ready on port {_PORT}", flush=True)

    server = HTTPServer(("0.0.0.0", _PORT), Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()
