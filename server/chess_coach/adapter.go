package chess

import (
	"go_agent_framework/core"
	"go_agent_framework/observability"
)

// GraphAdapter implements observability.GraphInfoProvider for the dashboard.
type GraphAdapter struct {
	Graph *core.Graph
}

// GraphInfo builds the dashboard graph structure from the core.Graph steps.
func (a *GraphAdapter) GraphInfo() observability.GraphInfo {
	steps := a.Graph.Steps()
	info := observability.GraphInfo{Name: a.Graph.Name()}

	for _, step := range steps {
		for _, agent := range step.Agents {
			node := observability.NodeInfo{ID: agent.Name()}
			if d, ok := agent.(core.Describable); ok {
				node.Description = d.Description()
				caps := d.Capabilities()
				node.Tools = caps.Tools
				node.Skills = caps.Skills
				node.RAG = caps.RAG
				node.Agents = caps.Agents
				node.Model = caps.Model
			}
			info.Nodes = append(info.Nodes, node)
		}
	}

	for i := 0; i < len(steps)-1; i++ {
		current := steps[i]
		next := steps[i+1]
		parallel := len(current.Agents) > 1 || len(next.Agents) > 1
		for _, src := range current.Agents {
			for _, dst := range next.Agents {
				info.Edges = append(info.Edges, observability.EdgeInfo{
					Source:   src.Name(),
					Target:   dst.Name(),
					Parallel: parallel,
				})
			}
		}
	}

	return info
}
