# Purple Core V1 Implementation Plan

This plan turns the current redesign direction into a first implementation scope.

It builds on:

- [track-core-plan.md](/Users/enxiangqiu/Desktop/car-bench-agentbeats-main/docs/plans/2026-03-29-track-core-plan.md)
- [purple-agent-design.md](/Users/enxiangqiu/Desktop/car-bench-agentbeats-main/docs/plans/2026-03-29-purple-agent-design.md)
- [car_bench_agent.py](/Users/enxiangqiu/Desktop/car-bench-agentbeats-main/src/purple_car_bench_agent/car_bench_agent.py)

## Goal

Replace the current direct LLM loop with a controlled single-agent core that is:

- benchmark-agnostic at the core layer
- testable first on CAR-bench
- compatible with a future OSWorld bridge

The first version should improve execution discipline, not maximize benchmark coverage.

## Architectural Decision

Use:

- one shared single-agent core
- one CAR bridge as the first environment bridge

Do not use:

- full multi-agent orchestration
- benchmark-specific domain executors in core
- prompt-only patching as the main strategy

The first version should implement one closed loop:

`bridge -> normalizer -> state -> planner -> validator -> execute -> state update -> recovery`

## V1 Modules

### 1. Observation Normalizer

Responsibility:

- convert environment-specific input into one internal observation frame

Initial output fields:

- `goal_text`
- `available_affordances`
- `feedback`
- `facts_delta`
- `constraints`
- `raw_user_text`

V1 rule:

- no planning
- no policy decisions
- no benchmark-solving heuristics

### 2. Session State

Responsibility:

- hold structured working memory per context

Initial fields:

- `message_history`
- `available_affordances`
- `observed_facts`
- `inferred_facts`
- `unknowns`
- `active_goal`
- `pending_confirmation`
- `last_plan`
- `last_result`
- `boundary_mode`

V1 rule:

- only short-horizon working state
- no long-term memory or retrieval system

### 3. Planner

Responsibility:

- produce a high-level next-step proposal

Allowed step types:

- `inspect`
- `clarify`
- `act`
- `stop`

Planner output should include:

- `objective`
- `current_step_type`
- `reason`
- `missing_information`
- `candidate_action`
- `expected_effect`

V1 rule:

- the planner may use the LLM
- the planner must not emit unchecked environment-native actions as final output

### 4. Validator

Responsibility:

- gate every executable step before dispatch

Checks included in V1:

- enough evidence to act
- prerequisite read required or not
- confirmation required or not
- action shape is legal
- capability boundary violated or not
- minimal formatting constraints for user-facing output

Validator output should be one of:

- `approved`
- `blocked_needs_read`
- `blocked_needs_clarification`
- `blocked_needs_confirmation`
- `blocked_boundary`
- `blocked_invalid_action`

### 5. Recovery

Responsibility:

- choose the next move after blocked validation or bad execution feedback

Failure classes in V1:

- `missing_evidence`
- `invalid_action`
- `env_rejection`
- `ambiguous_goal`
- `unsupported_capability`
- `no_progress`

Allowed recovery decisions:

- `re_read`
- `clarify`
- `retry_corrected`
- `replan`
- `stop_cleanly`

## What V1 Explicitly Does Not Include

These are out of scope for the first implementation:

- multi-agent planner/executor/reviewer architecture
- long-term memory or retrieval memory
- CAR-specific climate executor
- CAR-specific navigation state machine
- email-specific executor
- OSWorld bridge implementation
- standalone postcondition-checker module
- learning loop from benchmark traces

These can be added later if the core skeleton proves stable.

## Phase Plan

### Phase 1. Define Shared Types

Create a new shared package, for example:

- `src/purple_core/`

Define typed data models for:

- `ObservationFrame`
- `SessionState`
- `PlanProposal`
- `ValidationResult`
- `RecoveryDecision`

Acceptance:

- no environment-specific fields leak into core abstractions unless marked as generic

### Phase 2. Extract CAR Bridge

Refactor the CAR agent so environment parsing and output serialization are isolated.

The CAR bridge should handle:

- parsing `System:` and `User:` text
- ingesting tool schemas
- ingesting tool results
- serializing validated CAR actions back to tool calls

Acceptance:

- the main CAR executor no longer directly mixes parsing, planning, validation, and response generation in one function

### Phase 3. Add Planner Contract

Introduce a planner step that consumes:

- current `SessionState`
- latest `ObservationFrame`

And emits:

- one `PlanProposal`

Acceptance:

- the planner only produces `inspect / clarify / act / stop`
- no direct unchecked tool calls leave the planner

### Phase 4. Add Validator Gate

Place validator logic between planning and execution.

Start with the highest-value rules:

- prerequisite-read gate
- confirmation gate
- boundary stop gate
- basic action-shape validation

Acceptance:

- blocked actions never reach execution
- blocked outcomes produce structured reasons

### Phase 5. Add Recovery Loop

When validation blocks or execution feedback shows failure, choose one bounded next action.

Acceptance:

- the agent can stop cleanly instead of drifting
- the agent can convert common failures into a re-read, clarification, or replan

### Phase 6. CAR Smoke Validation

Run a small targeted CAR suite instead of full benchmark immediately.

Suggested first check:

- a few `base` tasks
- a few `hallucination` tasks
- a few `disambiguation` tasks

Metrics to watch first:

- `r_tool_subset`
- `r_policy`
- `r_actions_intermediate`
- `r_actions_final`
- `r_user_end_conversation`

Acceptance:

- the new loop runs end to end
- at least some failures move from uncontrolled tool/policy errors into explicit block/recovery behavior

## Code Organization Recommendation

Suggested first layout:

- `src/purple_core/models.py`
- `src/purple_core/observation_normalizer.py`
- `src/purple_core/session_state.py`
- `src/purple_core/planner.py`
- `src/purple_core/validator.py`
- `src/purple_core/recovery.py`
- `src/purple_car_bench_agent/car_bridge.py`

Keep:

- [`car_bench_agent.py`](/Users/enxiangqiu/Desktop/car-bench-agentbeats-main/src/purple_car_bench_agent/car_bench_agent.py)

As the A2A-facing orchestrator for now.

## Success Criteria For V1

V1 is successful if:

- the purple agent is no longer a direct raw-message-to-tool-call loop
- CAR runs still function through the same A2A interface
- the core can reject or reroute unsafe actions before execution
- the implementation leaves a clean seam for a future OSWorld bridge

V1 is not required to:

- solve all current CAR failure buckets
- match final desired benchmark performance
- provide full cross-environment support yet

## Likely V1.5 Additions

If V1 lands cleanly, the next additions should be:

- `capability_registry`
- `budget_controller`
- `policy_linter`

After that:

- standalone `postcondition_checker`
- `entity_resolver`
- optional narrow reviewers for policy or GUI grounding
