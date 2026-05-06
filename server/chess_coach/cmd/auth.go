package main

import (
	"crypto/subtle"
	"net/http"
	"os"
	"strings"
)

// requireBearer is a constant-time bearer-token middleware for the
// chess-coach HTTP surface.
//
// Defense in depth — in production the service is reached only via the
// Next.js BFF (client/InkstoneInterface), which holds STATE_BRIDGE_TOKEN
// server-side. This middleware ensures that even if compose accidentally
// re-publishes port 5002 to the host, anonymous requests still 401.
//
// Auth contract mirrors server/state_bridge/app.py:
//   - paths in `allowExact` or with a prefix in `allowPrefix` skip the
//     check (typically /health and dashboard static assets)
//   - everything else requires `Authorization: Bearer <token>` or
//     `?token=<token>` (for SSE / dashboard clients that cannot set
//     headers)
//
// The token is read from STATE_BRIDGE_TOKEN. If that env var is unset
// the middleware fails closed with HTTP 503 — silently allowing
// requests is never the right move.
func requireBearer(next http.Handler, allowExact map[string]bool, allowPrefix []string) http.Handler {
	token := strings.TrimSpace(os.Getenv("STATE_BRIDGE_TOKEN"))
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if isPublicPath(r.URL.Path, allowExact, allowPrefix) {
			next.ServeHTTP(w, r)
			return
		}
		if token == "" {
			http.Error(w, "coach misconfigured: STATE_BRIDGE_TOKEN unset", http.StatusServiceUnavailable)
			return
		}
		presented := extractBearer(r.Header.Get("Authorization"))
		if presented == "" {
			presented = r.URL.Query().Get("token")
		}
		if subtle.ConstantTimeCompare([]byte(presented), []byte(token)) != 1 {
			http.Error(w, "unauthorized", http.StatusUnauthorized)
			return
		}
		next.ServeHTTP(w, r)
	})
}

func isPublicPath(path string, allowExact map[string]bool, allowPrefix []string) bool {
	if allowExact[path] {
		return true
	}
	for _, prefix := range allowPrefix {
		if strings.HasPrefix(path, prefix) {
			return true
		}
	}
	return false
}

func extractBearer(header string) string {
	const prefix = "Bearer "
	if len(header) <= len(prefix) {
		return ""
	}
	if !strings.EqualFold(header[:len(prefix)], prefix) {
		return ""
	}
	return strings.TrimSpace(header[len(prefix):])
}
