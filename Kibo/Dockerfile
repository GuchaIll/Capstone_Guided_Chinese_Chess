# ============================================================
# Kibo Agent Viewer - Dockerfile
# ============================================================
# Multi-stage: build with Node, serve with nginx
# Exposes port 3001
# ============================================================

FROM node:20-alpine AS builder

WORKDIR /app

# Install dependencies first (layer cache)
COPY package.json package-lock.json* ./
RUN npm ci --ignore-scripts 2>/dev/null || npm install

# Bridge auth is enforced on /ws/kibo, so bake the token into the Vite
# bundle for browser WebSocket handshakes.
ARG STATE_BRIDGE_TOKEN=integration-bridge-token
ENV VITE_STATE_BRIDGE_TOKEN=$STATE_BRIDGE_TOKEN

# Copy source and build
COPY . .
RUN npm run build

# ---- Serve stage ----
FROM nginx:alpine AS runtime

# Copy custom nginx config
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Copy built assets
COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 3001

CMD ["nginx", "-g", "daemon off;"]
