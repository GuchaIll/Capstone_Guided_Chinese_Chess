# Agent's "Long-Term Memory": The AGENT.md file serves as a meta-guide, loaded by default. It instructs the agent on how to behave, what coding standards to follow, and how to interpret and utilize the rest of the .agent directory.

## Project Context
This is the agent orchestration system for the Guided Chinese Chess (Xiangqi)
Capstone project. It sits between the React frontend and the Rust game engine,
providing intelligent coaching through a multi-agent architecture.

## Coding Standards
- Python 3.10+ with type hints on all function signatures
- Use `from __future__ import annotations` for forward references
- All agents inherit from `AgentBase` and implement `async handle()`
- All inter-agent communication goes through the Orchestrator
- Use `AgentResponse` for all agent outputs (never raw dicts/strings)
- Agent methods must be async-compatible (use `async def`)
- Use structured logging via `self.logger` (never print())
- Error handling: agents must never crash; use `safe_handle()` wrapper

## Directory Structure
- `/agents` - Agent implementations (one file per agent)
- `/services` - Orchestrator and SessionState
- `/tools` - External integrations (EngineClient, RAGRetriever, LLMClient)
- `/LLM` - LLM registry and prompt templates
- `/Inference` - RAG + LLM inference pipeline
- `/tests` - pytest test files
- `/spec` - Requirements, design, and task breakdown
- `/wiki` - Domain knowledge and architecture documentation

## Key Interfaces
- `AgentBase.handle(state, **kwargs) -> AgentResponse`
- `Orchestrator.process_input(user_input) -> AgentResponse`
- `EngineClient.send_move(move_str) -> dict`
- `RAGRetriever.retrieve(query, collection, top_k) -> list[dict]`
- `LLMClient.generate(prompt) -> str`

## Testing
- Run tests: `cd server && python -m pytest agent_orchestration/tests/ -v`
- All agents must be testable without external dependencies (mock everything)
