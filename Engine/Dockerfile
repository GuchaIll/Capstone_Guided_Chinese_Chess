# ============================================================
# Engine Dockerfile - Rust Chinese Chess Engine
# ============================================================
# Multi-stage build for minimal image size
# Exposes WebSocket on port 8080
# ============================================================

FROM rust:1.85-slim AS builder

WORKDIR /app

# Copy workspace Cargo files first for dependency caching
COPY Cargo.toml Cargo.lock ./
COPY Engine/Cargo.toml Engine/Cargo.toml

# Create stub source so cargo can fetch and cache all dependencies
RUN mkdir -p Engine/src && echo "fn main() {}" > Engine/src/main.rs
# Fetch deps only (ignore compile errors from stub) -- uses locked versions
RUN cargo fetch --locked --manifest-path Engine/Cargo.toml

# Copy real source
COPY Engine/src Engine/src

# Touch to invalidate stub-compiled artifacts, then build for real
RUN touch Engine/src/main.rs && \
    cargo build --release --locked --manifest-path Engine/Cargo.toml

# ---- Runtime stage ----
FROM debian:bookworm-slim AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy binary from builder
COPY --from=builder /app/target/release/Chinese_Chess_Engine .

# Create logs directory
RUN mkdir -p logs

EXPOSE 8080

CMD ["./Chinese_Chess_Engine"]
