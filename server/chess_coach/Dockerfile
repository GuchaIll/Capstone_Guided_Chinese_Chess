# ---- Dashboard SPA build stage ----
FROM node:22-alpine AS dashboard

WORKDIR /dashboard
COPY go_agent_framework/dashboard/package.json go_agent_framework/dashboard/package-lock.json ./
RUN npm ci
COPY go_agent_framework/dashboard/ ./
RUN npm run build

# ---- Go build stage ----
FROM golang:1.26-alpine AS builder

RUN apk add --no-cache git

WORKDIR /src

# Copy the framework dependency first (for layer caching).
COPY go_agent_framework/ /src/go_agent_framework/

# Copy the chess_coach module.
COPY chess_coach/ /src/chess_coach/

WORKDIR /src/chess_coach

# Download deps and build.
RUN go mod download
RUN CGO_ENABLED=0 GOOS=linux go build -o /chess-coach ./cmd

# ---- Runtime stage ----
FROM alpine:3.20

RUN apk add --no-cache ca-certificates wget

WORKDIR /app

COPY --from=builder /chess-coach /app/chess-coach
COPY chess_coach/skills/ /app/skills/
COPY --from=dashboard /dashboard/dist/ /app/dashboard/dist/

EXPOSE 8080

ENTRYPOINT ["/app/chess-coach"]
