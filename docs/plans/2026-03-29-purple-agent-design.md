# Purple Agent Redesign For CAR-Bench

This design is grounded in the current implementation:

- [car_bench_agent.py](/Users/enxiangqiu/Desktop/car-bench-agentbeats-main/src/purple_car_bench_agent/car_bench_agent.py)
- [2026-03-29-minimax-m2.7-failure-taxonomy.md](/Users/enxiangqiu/Desktop/car-bench-agentbeats-main/docs/plans/2026-03-29-minimax-m2.7-failure-taxonomy.md)
- [2026-03-29-minimax-m2.7-representative-case-pack.md](/Users/enxiangqiu/Desktop/car-bench-agentbeats-main/docs/plans/2026-03-29-minimax-m2.7-representative-case-pack.md)

## Current Baseline

The current purple agent is a direct LLM loop:

1. Parse inbound parts into `messages` and `tools`.
2. Send the whole conversation directly to the model.
3. Trust the model's tool calls as final.
4. Return text plus tool calls with no intermediate validation layer.

That baseline is simple, but the benchmark results show its ceiling:

- it misses prerequisite reads
- it emits schema-invalid tool calls
- it violates policy on multi-step actions
- it formats user-facing text inconsistently
- it fails to stop cleanly when capability boundaries are hit

This is not a problem that prompt tuning alone will solve well, especially with MiniMax M2.7. The model is usually close on intent. It is unstable on execution discipline.

## Three Possible Directions

### Option A: Prompt-Only Upgrade

Add more policy text, more examples, and stronger instructions.

Pros:

- lowest engineering effort
- keeps the current code path almost unchanged

Cons:

- low ceiling on tool grounding and sequencing
- weak control over multi-turn state
- likely to improve style more than evaluator pass rate

### Option B: Fully Programmed Agent

Replace most reasoning with domain-specific planners and rule engines.

Pros:

- highest determinism
- easiest to enforce policy exactly

Cons:

- too much engineering cost
- brittle and hard to extend
- high risk of overfitting to current observed failures

### Option C: Hybrid Controlled Agent

Keep the LLM for intent understanding and clarification, but insert deterministic control layers around tool execution and final user-facing output.

Pros:

- best accuracy-to-effort tradeoff
- directly addresses the observed failure modes
- preserves generality without baking in task IDs

Cons:

- requires state management and a few domain modules
- slightly more latency per turn

## Recommendation

Build Option C.

The right design is not "a smarter prompt". It is a structured execution stack:

- LLM for intent and natural language
- typed state for what is known
- deterministic validators for what may be executed
- domain-specific executors for the most failure-prone action families
- final response linting before anything is sent

## Target Architecture

### 1. Session State Per Context

Add structured state on top of raw conversation history.

Store:

- `message_history`
- `available_tools`
- `observed_state`
- `active_workflow`
- `pending_confirmation`
- `boundary_mode`
- `last_tool_results`

`observed_state` should include normalized facts like:

- window positions
- climate settings
- temperatures
- seat occupancy
- seat heating levels
- active navigation state
- known location IDs and route IDs
- known contacts and calendar entries

This is the foundation for everything else. Right now the agent only has raw messages, so every turn is a fragile memory test.

### 2. Thin LLM Planner

The LLM should produce a structured intent, not final unchecked execution.

Planner output should answer:

- what the user wants
- what domain this belongs to
- whether clarification is required
- what facts are missing
- whether the task is bounded by missing capability
- whether confirmation is required before any write tool

The planner can still be implemented with one LLM call, but its output should be interpreted as a proposal, not as the final action.

### 3. Precondition Read Planner

Before any write or computed answer, run a deterministic pass that asks:

- what must be known first
- which read tools provide those facts
- whether those facts are already in `observed_state`

Examples:

- charging-stop estimation requires charging status and range tools
- AC activation requires climate and window state
- route editing requires current navigation state plus compatible route IDs
- email sending requires contacts, recipients, and explicit confirmation

This module directly targets the `r_tool_subset` failures.

### 4. Domain Executors

Do not let the model directly assemble every tool sequence.

Add small deterministic executors for the highest-value domains.

#### Climate / Vehicle Control Executor

Responsibilities:

- AC policy bundles
- defrost bundles
- seat-heating-with-occupancy logic
- window normalization before climate actions
- climate temperature changes by zone

This module should transform a high-level request like "turn on AC" into:

- read current climate and windows if needed
- close windows above policy threshold if needed
- set minimum fan speed if needed
- then enable AC

#### Navigation State Machine

Responsibilities:

- decide between `set_new_navigation` and edit tools
- validate active route topology
- track current waypoints and route IDs
- prevent invalid route-to-waypoint bindings

Supported operation types:

- start navigation
- replace final destination
- add waypoint
- replace waypoint
- delete waypoint
- delete navigation

This module directly targets the `SetNewNavigation_001` and route-binding failures.

#### Communication Executor

Responsibilities:

- draft communication payloads
- store pending email confirmation state
- prevent `send_email` before explicit confirmation
- normalize time and unit formatting in draft content

This module directly targets the email-policy failures.

### 5. Schema Canonicalizer And Validator

Every tool call should pass through a typed validation layer before dispatch.

Checks:

- tool exists
- required arguments are present
- enum values are canonical
- IDs come from known resolved entities
- route / waypoint references are consistent with current state
- arguments required by tool-specific constraints are present

If validation fails:

- do not dispatch the tool
- either ask a clarification question, do a prerequisite read, or enter boundary mode

This directly addresses failures like:

- missing `percentage`
- `destination_id = loc_madrid`
- missing `at_kilometer`

### 6. Boundary Controller

The agent needs an explicit non-execution mode for unsupported or underdetermined tasks.

Trigger boundary mode when:

- required state is `unknown`
- the tool result says the capability is unavailable
- the schema validator cannot build a legal call
- the user requests something outside supported tools

Boundary mode rules:

- explain the limitation clearly
- do not invent a workaround unless a supported one exists
- do not continue speculative action execution
- end the conversation cleanly when appropriate

This is the main fix for the hallucination split.

### 7. Response Linter

Before sending any user-facing text, run a deterministic formatter.

Checks:

- 24-hour time only
- explicit `Celsius` wording where required
- confirmation language present before communication tools
- route presentation policy satisfied
- if fastest route was chosen proactively, say so explicitly

This is cheap to build and should recover a meaningful share of the `r_policy` losses.

## Why This Is Not Cheating

This design does not rely on task IDs or gold actions.

It uses only:

- current tool schema
- current policy prompt
- live tool observations
- conversation state

That means it generalizes to unseen tasks within the same environment. The control logic is policy-aware and tool-aware, not benchmark-item-aware.

## Best Place To Start

Do not start with a giant refactor.

Start with the narrowest high-leverage control layer:

### Phase 1: Validation Wrapper Around Current Agent

Keep the current LLM loop, but insert:

- session state
- schema validator
- response linter
- pending confirmation guard
- boundary controller

This can live close to [car_bench_agent.py](/Users/enxiangqiu/Desktop/car-bench-agentbeats-main/src/purple_car_bench_agent/car_bench_agent.py) at first.

Expected impact:

- immediate reduction in schema failures
- immediate reduction in email-policy failures
- immediate reduction in hallucination overreach

### Phase 2: Climate And Navigation Executors

Once the wrapper exists, extract two deterministic domain modules first:

- climate / vehicle-control executor
- navigation state machine

Expected impact:

- biggest lift on `base`
- strong lift on `disambiguation`

### Phase 3: Precondition Read Planner

After the agent can execute safely, improve what it knows before acting.

Expected impact:

- fewer `r_tool_subset` misses
- better charging and route-planning performance

## Suggested File Split

If we decide to implement this, a good split is:

- `src/purple_car_bench_agent/session_state.py`
- `src/purple_car_bench_agent/planner.py`
- `src/purple_car_bench_agent/schema_validation.py`
- `src/purple_car_bench_agent/boundary_controller.py`
- `src/purple_car_bench_agent/response_linter.py`
- `src/purple_car_bench_agent/executors/climate.py`
- `src/purple_car_bench_agent/executors/navigation.py`
- `src/purple_car_bench_agent/executors/communication.py`

The current [car_bench_agent.py](/Users/enxiangqiu/Desktop/car-bench-agentbeats-main/src/purple_car_bench_agent/car_bench_agent.py) would become an orchestrator instead of containing the whole agent.

## What I Would Implement First

If the goal is maximum score gain per unit of work, I would do this exact order:

1. Add `pending_confirmation` and block `send_email` without explicit approval.
2. Add a response linter for 24-hour time and `Celsius`.
3. Add tool-call schema validation before dispatch.
4. Add boundary mode for unknown / unsupported tool situations.
5. Add a climate executor for AC, windows, defrost, and seat-heating bundles.
6. Add a navigation state machine for active-route edits.
7. Add precondition-read planning for charging and route-analysis tasks.

That sequence is intentionally biased toward fast score recovery, not architectural purity.

## Success Criteria

The redesign is working if the next MiniMax run shows:

- fewer `r_user_end_conversation` failures in hallucination
- fewer `r_policy` failures from formatting and confirmation
- fewer `r_tool_execution` failures from bad arguments
- fewer `SetNewNavigation_001` and AC-policy failures
- fewer `r_tool_subset` misses in charging and range tasks

The key idea is simple:

keep the LLM for understanding, but stop trusting it with unchecked execution.
