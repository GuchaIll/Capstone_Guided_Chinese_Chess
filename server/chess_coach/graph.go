package chess

import (
	"chess_coach/agents"
	"go_agent_framework/contrib/llm"
	"go_agent_framework/core"
)

// BuildGraph wires the chess-coach pipeline:
//
//	serial(ingest) -> serial(inspection) -> serial(orchestrator)
//	  -> serial(blunder_detection)          [sets blunder_abort=true to short-circuit]
//	  -> parallel(position_analyst, puzzle_curator)
//	  -> serial(coach)                      [slow path: only when coach_trigger is set]
//	  -> serial(guard)                      [scores coach advice; approves or rejects]
//	  -> serial(feedback)
func BuildGraph(tools *core.ToolRegistry, skills *core.SkillRegistry, models llm.Models) *core.Graph {
	return core.NewGraph("chess_coach").
		AddSerial(&agents.IngestAgent{}).
		AddSerial(&agents.InspectionAgent{Tools: tools}).
		AddSerial(&agents.OrchestratorAgent{
			LLM:   models.For(llm.RoleOrchestration),
			Tools: tools,
		}).
		AddSerial(&agents.BlunderDetectionAgent{Tools: tools}).
		AddParallel(
			&agents.PositionAnalystAgent{Tools: tools, Skills: skills, Depth: 5},
			&agents.PuzzleCuratorAgent{Tools: tools, Skills: skills},
		).
		AddSerial(&agents.CoachAgent{
			LLM:    models.For(llm.RoleAnalysis),
			Skills: skills,
			Tools:  tools,
		}).
		AddSerial(&agents.GuardAgent{Tools: tools}).
		AddSerial(&agents.FeedbackAgent{})
}
