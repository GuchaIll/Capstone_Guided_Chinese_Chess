# ============================================================
# Client Dockerfile - Next.js (App Router) frontend
# ============================================================
# Multi-stage: build with Node, serve via Next.js standalone output.
# Exposes port 3000.
# ============================================================

FROM node:20-alpine AS builder

WORKDIR /app

# Install dependencies first (layer cache)
COPY package.json package-lock.json* ./
RUN npm ci --ignore-scripts 2>/dev/null || npm install

# Build-time configuration baked into the bundle. Next inlines env vars
# prefixed with NEXT_PUBLIC_ at `next build` time, so they must be
# present in the environment for that step. Override via
# `docker compose build --build-arg STATE_BRIDGE_TOKEN=…`.
ARG STATE_BRIDGE_TOKEN=integration-bridge-token
ENV NEXT_PUBLIC_STATE_BRIDGE_TOKEN=$STATE_BRIDGE_TOKEN
# In the compose network the bridge isn't reachable from the browser as
# state-bridge:5003, so the bundle still hits ${origin}/bridge by
# default and Next's rewrite layer proxies HTTP into the cluster. The
# rewrite target is a build-time env (rewrites runs server-side).
ARG STATE_BRIDGE_INTERNAL_URL=http://state-bridge:5003
ENV NEXT_PUBLIC_STATE_BRIDGE_INTERNAL_URL=$STATE_BRIDGE_INTERNAL_URL
ARG COACHING_INTERNAL_URL=http://coaching:5000
ENV NEXT_PUBLIC_COACHING_INTERNAL_URL=$COACHING_INTERNAL_URL
ARG DASHBOARD_INTERNAL_URL=http://go-coaching:8080
ENV NEXT_PUBLIC_DASHBOARD_INTERNAL_URL=$DASHBOARD_INTERNAL_URL

COPY . .
RUN npm run build

# ---- Serve stage ----
FROM node:20-alpine AS runtime

WORKDIR /app
ENV NODE_ENV=production

# Copy the standalone server + its required runtime assets.
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public

EXPOSE 3000

CMD ["node", "server.js"]
