package chess

import (
	"go_agent_framework/contrib/llm"
	"go_agent_framework/core"
	"chess_coach/agents"
)

// BuildGraph wires the chess-coach pipeline:
//
//	serial(ingest) -> serial(inspection) -> serial(orchestrator)
//	  -> parallel(position_analyst, blunder_detection)
//	  -> serial(puzzle_curator) [conditional via route flag]
//	  -> serial(coach)
//	  -> serial(visualization)
//	  -> serial(feedback)
func BuildGraph(tools *core.ToolRegistry, skills *core.SkillRegistry, models llm.Models) *core.Graph {
	return core.NewGraph("chess_coach").
		AddSerial(&agents.IngestAgent{}).
		AddSerial(&agents.InspectionAgent{Tools: tools}).
		AddSerial(&agents.OrchestratorAgent{
			LLM:   models.For(llm.RoleOrchestration),
			Tools: tools,
		}).
		AddParallel(
			&agents.PositionAnalystAgent{Tools: tools, Skills: skills, Depth: 20},
			&agents.BlunderDetectionAgent{Tools: tools},
			&agents.GuardAgent{Tools: tools},
		).
		AddSerial(&agents.PuzzleCuratorAgent{Tools: tools, Skills: skills}).
		AddSerial(&agents.CoachAgent{
			LLM:    models.For(llm.RoleAnalysis),
			Skills: skills,
		}).
		AddSerial(&agents.VisualizationAgent{Tools: tools}).
		AddSerial(&agents.FeedbackAgent{})
}
