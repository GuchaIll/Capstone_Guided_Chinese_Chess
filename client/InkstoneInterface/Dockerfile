# ============================================================
# Inkstone Interface Dockerfile - Next.js (App Router) frontend
# ============================================================
# Multi-stage: build with Node, serve via Next.js standalone output.
# Exposes port 3002.
#
# BFF migration note (refs docs/refactoring/refactoring_guide.md C3/C4):
# The browser never sees STATE_BRIDGE_TOKEN any more. It is supplied at
# RUNTIME via the `environment:` section of docker-compose.yml; the
# Next.js server reads it inside route handlers under app/api/* and
# attaches it as an Authorization header on every upstream proxy call.
# Build-time NEXT_PUBLIC_STATE_BRIDGE_TOKEN has been removed.
# ============================================================

FROM node:20-alpine AS builder

WORKDIR /app

# Install dependencies first (layer cache)
COPY package.json package-lock.json* ./
RUN npm ci --ignore-scripts 2>/dev/null || npm install

# Build-time public configuration only — these are inlined into the
# browser bundle and MUST NOT contain secrets.
ARG TTS_PROVIDER=fish_modal
ENV NEXT_PUBLIC_TTS_PROVIDER=$TTS_PROVIDER
ARG TTS_FALLBACK_PROVIDER=browser
ENV NEXT_PUBLIC_TTS_FALLBACK_PROVIDER=$TTS_FALLBACK_PROVIDER
# Optional WS origin override (URL only, no secret) — defaults to
# `${pageProtocol}://${pageHost}:5003` resolved by the browser.
ARG BRIDGE_WS_ORIGIN=
ENV NEXT_PUBLIC_BRIDGE_WS_ORIGIN=$BRIDGE_WS_ORIGIN

COPY . .
RUN npm run build

# ---- Serve stage ----
FROM node:20-alpine AS runtime

WORKDIR /app
ENV NODE_ENV=production
ENV PORT=3002

# Copy the standalone server + its required runtime assets.
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public

EXPOSE 3002

# Required runtime env (set by docker-compose, NOT baked into image):
#   STATE_BRIDGE_TOKEN          shared secret with state-bridge / go-coach
#   STATE_BRIDGE_INTERNAL_URL   e.g. http://state-bridge:5003
#   COACH_INTERNAL_URL          e.g. http://go-coaching:8080
#   BFF_SESSION_SECRET          random 32+ byte string for cookie HMAC
CMD ["node", "server.js"]
