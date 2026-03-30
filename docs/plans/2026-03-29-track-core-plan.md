# Track-Level Core Plan For CAR-Bench And OSWorld

This plan is based on the current CAR-bench purple agent plus the newly added OSWorld green-agent wrapper:

- [car_bench_agent.py](/Users/enxiangqiu/Desktop/car-bench-agentbeats-main/src/purple_car_bench_agent/car_bench_agent.py)
- [agent.py](/Users/enxiangqiu/Desktop/car-bench-agentbeats-main/osworld-green-main/src/agent.py)
- [amber-manifest.json5](/Users/enxiangqiu/Desktop/car-bench-agentbeats-main/osworld-green-main/amber-manifest.json5)

## What We Learned From OSWorld Green

The OSWorld green agent has a very different surface from CAR-bench.

Per step, OSWorld green sends the purple agent:

- a text instruction
- `env_config` with fields like `action_space` and `observation_type`
- a screenshot as `FilePart`
- optionally an accessibility tree
- optionally terminal output

It expects the purple agent to return:

- optional text
- `DataPart({"actions": list[str]})`

The key difference is that OSWorld does not hand the purple agent an explicit function schema like CAR-bench does. Instead, it gives the agent a multimodal observation plus an environment action language.

Important limitation discovered locally:

- [agent.py](/Users/enxiangqiu/Desktop/car-bench-agentbeats-main/osworld-green-main/src/agent.py) imports `../osworld`, but [osworld-green-main](/Users/enxiangqiu/Desktop/car-bench-agentbeats-main/osworld-green-main) currently does not contain that directory.
- So this repo is enough to analyze the A2A interface, but not enough to run OSWorld end-to-end yet.

## Core Principle

We should not build two separate benchmark-specific agents.

We should also not pretend that CAR and OSWorld have identical I/O. They do not.

The right split is:

- one shared agent core
- one thin environment bridge per environment

The bridge is not allowed to encode benchmark-solving strategy. It is only allowed to translate environment observations and actions into a common agent-internal representation.

## Strict Boundary: Core Vs Bridge

### Shared Core

The shared core should contain only environment-agnostic agent logic:

- session state
- working memory
- goal decomposition
- uncertainty handling
- prerequisite-evidence planning
- action validation
- post-action verification
- recovery and replanning
- stop criteria and budget control

This is the part that should generalize to future production environments.

### Environment Bridge

The bridge may only do I/O normalization:

- parse inbound observation parts
- normalize them into a shared observation model
- serialize outbound actions into the environment's native action format
- capture execution feedback into shared state

Allowed examples:

- CAR: convert tool schemas and tool results into normalized affordances and observations
- OSWorld: convert screenshot/a11y/terminal/env-config into normalized observations, and convert agent actions into `list[str]`

Not allowed in the bridge:

- CAR-specific climate strategy
- OSWorld-specific app heuristics
- benchmark-task templates
- evaluator-targeted special cases

### Environment Skills

If needed later, environment-specific skills should sit above the bridge and below the shared planner, but only when the environment truly exposes unique capabilities.

Examples:

- CAR route mutation helper
- GUI grounding helper

Even here, the bar should be high. If something can be expressed as a generic planning or validation rule, it belongs in core.

## Shared Core Modules We Should Build

### 1. Observation Normalizer

Input:

- CAR text + tools + tool results
- OSWorld instruction + screenshot + a11y tree + terminal + env config

Output:

- one normalized `ObservationFrame`

Suggested fields:

- `user_goal_text`
- `available_affordances`
- `environment_feedback`
- `structured_state`
- `visual_context`
- `terminal_context`
- `constraints`

This is the minimum needed to stop the current CAR agent from depending on raw messages alone.

### 2. Session State And Working Memory

Store:

- current task and subgoals
- facts already observed
- unresolved unknowns
- pending confirmation
- last action plan
- last execution result
- whether the agent is in boundary mode

This is shared across CAR and OSWorld. Only the source of the facts changes.

### 3. Planner

The planner should not emit final environment-native actions directly.

It should emit:

- objective
- current subgoal
- missing information
- whether clarification is needed
- whether the environment already provides enough evidence
- a proposed high-level action step

That high-level action step should be environment-neutral, like:

- inspect
- ask user
- act
- verify
- stop

### 4. Validator

A validator should gate every executable step.

Shared checks:

- do we have enough information to act
- is the proposed action legal in current state
- is confirmation required
- does the action violate a hard policy or known capability boundary

This validator is where a lot of current CAR failures disappear, and it also maps directly to GUI environments where invalid actions are common.

### 5. Postcondition Checker

After each action, check whether the environment actually changed in the expected direction.

Examples:

- CAR: a tool result or follow-up read confirms the change
- OSWorld: the next screenshot/a11y/terminal state shows the expected result

This is a genuinely shared core behavior.

### 6. Recovery Loop

When a step fails, classify the failure:

- missing evidence
- invalid parameters
- environment rejection
- ambiguous goal
- unsupported capability
- no progress after action

Then choose one next move:

- re-read
- clarify
- retry with corrected action
- replan
- stop cleanly

This is important in both CAR and OSWorld.

## What We Should Not Build Into Core

These should stay out of the shared core:

- CAR climate policy bundles
- CAR navigation-specific route mutation rules
- email-specific formatting rules
- GUI app-specific button heuristics
- OSWorld app-specific workflows

Those may become optional domain modules later, but they are not the first step.

## Recommended Plan

### Phase 0: Finish Interface Discovery

Goal:

- make sure we can inspect at least a small number of real OSWorld trajectories before implementation decisions harden

Blocking issue:

- the local [osworld-green-main](/Users/enxiangqiu/Desktop/car-bench-agentbeats-main/osworld-green-main) wrapper references an `osworld` runtime directory that is not present, so we cannot run it yet without adding the actual benchmark checkout or containerized runtime

Action:

- get the missing OSWorld runtime or example trajectory artifacts

### Phase 1: Build Core Skeleton Inside The Current Purple Agent

Add shared modules first:

- `observation_normalizer.py`
- `session_state.py`
- `planner.py`
- `validator.py`
- `recovery.py`

Keep the CAR-bench path as the first environment bridge so we can test the core quickly.

### Phase 2: Refactor CAR Into A Bridge

Move current CAR-specific parsing out of the main loop.

The CAR bridge should only:

- parse `System:` and `User:`
- ingest tool schemas and tool results
- normalize tool affordances and environment feedback
- serialize validated CAR actions back into tool calls

No CAR-specific solving logic yet.

### Phase 3: Add OSWorld Bridge

Once the core exists, add an OSWorld bridge that:

- parses screenshot, a11y tree, terminal, and env config
- exposes normalized observations to the core
- serializes validated actions to `actions: list[str]`

This will tell us what is truly shared and what is still leaking environment assumptions.

### Phase 4: Add Small Optional Domain Modules

Only after the shared core works, add narrow high-value helpers:

- CAR action safety helper
- GUI grounding helper

These should be optional modules invoked by the planner, not hardcoded task solvers.

## Concrete Deliverables

I would do the next work in this order:

1. Create the shared session-state and observation model.
2. Put a validator in front of the current CAR execution path.
3. Split current CAR parsing into a `car_bridge`.
4. Wire a stub `osworld_bridge` from the wrapper interface, even before we can fully run OSWorld.
5. After we obtain runnable OSWorld assets, sample-run a small slice and compare failure modes.

## Why This Keeps Us Honest

This plan avoids benchmark cheating because the shared core never reasons in terms of:

- task IDs
- gold actions
- evaluator-specific shortcuts

It only reasons over:

- observations
- available affordances
- state
- uncertainty
- validation
- recovery

That is the right shape for both a benchmark agent and a production agent.
