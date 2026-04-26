package agents

import (
	"encoding/json"
	"fmt"
	"strings"

	"go_agent_framework/core"
	"go_agent_framework/observability"
)

func toolAvailable(reg *core.ToolRegistry, name string) bool {
	if reg == nil {
		return false
	}
	_, ok := reg.Get(name)
	return ok
}

func retrieveRAGSection(ctx *core.Context, reg *core.ToolRegistry, section, toolName string, payload map[string]interface{}) {
	if !toolAvailable(reg, toolName) {
		return
	}

	args, _ := json.Marshal(payload)
	call := core.ToolCall{
		ID:   fmt.Sprintf("rag_%s_%s", section, toolName),
		Name: toolName,
		Args: args,
	}

	observability.PublishToolCall(ctx.GraphName, ctx.AgentName, ctx.SessionID, call.Name, payload)
	result := reg.ExecuteTool(ctx.StdContext, call)
	if result.Error != "" {
		observability.PublishToolResult(ctx.GraphName, ctx.AgentName, ctx.SessionID, call.Name, "", result.Error)
		return
	}
	observability.PublishToolResult(ctx.GraphName, ctx.AgentName, ctx.SessionID, call.Name, result.Output, "")

	var parsed map[string]interface{}
	if err := json.Unmarshal([]byte(result.Output), &parsed); err != nil {
		return
	}

	text := extractRAGText(parsed)
	if strings.TrimSpace(text) == "" {
		return
	}

	query, _ := parsed["query"].(string)
	storeRAGSection(ctx.State, section, toolName, query, text)
}

func extractRAGText(parsed map[string]interface{}) string {
	if text, _ := parsed["explanation"].(string); strings.TrimSpace(text) != "" {
		return trimRAGText(text, 1200)
	}
	if text, _ := parsed["guidance"].(string); strings.TrimSpace(text) != "" {
		return trimRAGText(text, 1200)
	}
	results, ok := parsed["results"].([]interface{})
	if !ok || len(results) == 0 {
		return ""
	}

	parts := make([]string, 0, len(results))
	seen := map[string]struct{}{}
	for _, item := range results {
		row, ok := item.(map[string]interface{})
		if !ok {
			continue
		}
		content, _ := row["content"].(string)
		if trimmed := normalizeRAGChunk(content); trimmed != "" {
			if _, exists := seen[trimmed]; exists {
				continue
			}
			seen[trimmed] = struct{}{}
			parts = append(parts, trimmed)
			if len(parts) >= 2 {
				break
			}
		}
	}
	return trimRAGText(strings.Join(parts, "\n\n"), 1200)
}

func storeRAGSection(state map[string]interface{}, section, toolName, query, text string) {
	ragContext, _ := state["rag_context"].(map[string]interface{})
	if ragContext == nil {
		ragContext = make(map[string]interface{})
	}
	ragContext[section] = map[string]interface{}{
		"tool":  toolName,
		"query": query,
		"text":  text,
	}
	state["rag_context"] = ragContext

	ragQueries, _ := state["rag_queries"].(map[string]interface{})
	if ragQueries == nil {
		ragQueries = make(map[string]interface{})
	}
	ragQueries[section] = query
	state["rag_queries"] = ragQueries
}

func buildOpeningRAGQuery(state map[string]interface{}, bestMove string) string {
	question, _ := state["question"].(string)
	return strings.TrimSpace(strings.Join(nonEmpty(
		question,
		bestMove,
		"opening principles develop pieces control the center initiative",
	), " "))
}

func buildMiddlegameRAGQuery(state map[string]interface{}, bestMove string) string {
	question, _ := state["question"].(string)
	features := make([]string, 0, 6)
	if hasItems(state["forks"]) {
		features = append(features, "fork")
	}
	if hasItems(state["pins"]) {
		features = append(features, "pin")
	}
	if hasItems(state["hanging_pieces"]) {
		features = append(features, "hanging piece")
	}
	return strings.TrimSpace(strings.Join(nonEmpty(
		question,
		bestMove,
		strings.Join(features, " "),
		"middlegame tactical theme strategy attack defense",
	), " "))
}

func buildEndgameRAGQuery(state map[string]interface{}) string {
	question, _ := state["question"].(string)
	materialInfo := ""
	if material, ok := state["material_info"].(map[string]interface{}); ok {
		if balance, ok := material["material_balance"]; ok {
			materialInfo = fmt.Sprintf("material balance %v", balance)
		}
	}
	return strings.TrimSpace(strings.Join(nonEmpty(
		question,
		materialInfo,
		"endgame principle conversion king activity practical endgame",
	), " "))
}

func nonEmpty(values ...string) []string {
	out := make([]string, 0, len(values))
	for _, value := range values {
		if trimmed := strings.TrimSpace(value); trimmed != "" {
			out = append(out, trimmed)
		}
	}
	return out
}

func hasItems(value interface{}) bool {
	items, ok := value.([]interface{})
	return ok && len(items) > 0
}

func normalizeRAGChunk(text string) string {
	text = strings.TrimSpace(text)
	if text == "" {
		return ""
	}
	return strings.Join(strings.Fields(text), " ")
}

func trimRAGText(text string, maxLen int) string {
	text = strings.TrimSpace(text)
	if maxLen <= 0 || len(text) <= maxLen {
		return text
	}
	cut := text[:maxLen]
	if idx := strings.LastIndex(cut, "\n\n"); idx > maxLen/2 {
		cut = cut[:idx]
	}
	return strings.TrimSpace(cut) + "\n\n[truncated]"
}
