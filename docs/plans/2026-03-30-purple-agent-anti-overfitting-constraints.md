# Purple Agent Anti-Overfitting Constraints

## Purpose

This document defines the boundary between:

- legitimate agent design improvements
- benchmark-specific overfitting

The goal is to improve the purple agent by strengthening general decision-making, validation, and execution control, without encoding answers to known tasks.

## Current Assessment

The current implementation is mostly on the acceptable side, but not fully safe by default.

What is already good:

- Runtime code under `src/` does not branch on task IDs.
- Runtime code under `src/` does not branch on benchmark split names like `base`, `hallucination`, or `disambiguation`.
- The existing improvements are mostly expressed as:
  - tool/result normalization
  - validation gates
  - transition rules
  - policy profiles

What still needs discipline:

- Several rules are CAR-specific at the tool and tool-result level.
- CAR-specific logic is acceptable only if it is treated as an environment bridge or environment policy profile, not as a hidden answer key.
- Failure-driven development is useful for discovering missing abstractions, but those abstractions must be implemented in task-agnostic form.

## Non-Negotiable Rule

We may use benchmark failures to discover missing capabilities.

We may not use benchmark failures to encode per-task behavior.

That means:

- allowed: "climate-changing actions require prerequisite evidence"
- not allowed: "if this looks like `base_5`, check windows and fan first"

## Allowed Design Inputs

The following are valid inputs for runtime logic:

- available tool schema
- tool argument schema
- tool result structure
- session state
- pending confirmations
- environment affordances
- observation uncertainty
- action type
- whether an action is reversible, destructive, external-facing, or commit-like

The following are valid inputs for environment-specific logic:

- CAR tool names and CAR result structure
- OSWorld observation/action protocol
- environment policy profiles

These are acceptable because they describe the interface of the environment, not the correct answer to a benchmark item.

## Forbidden Design Inputs

The following must not influence runtime behavior:

- task IDs
- benchmark split names
- copied task instructions
- gold action sequences
- per-case text fingerprints
- "if user says X exact sentence, run Y because this is that benchmark case"
- hidden assumptions derived only from one known task rather than from tool semantics

The following are also forbidden:

- storing benchmark item descriptions as templates for future dispatch
- adding validator branches that exist only to make one known failure pass
- encoding fixed action sequences that bypass planning and state validation

## The Acceptable Abstraction Test

A new rule is allowed only if it passes all of these checks:

1. It can be stated without naming a task.
2. It is triggered by state, schema, or action type, not by benchmark identity.
3. It would still make sense in a production agent.
4. It can plausibly help multiple unseen tasks.
5. It can be explained as a safety, validation, planning, or execution-discipline improvement.

If a proposed rule fails one of these checks, it should not be added.

## How To Treat The Current Failure Buckets

The current high-value fixes should be interpreted as abstractions, not case patches.

### 1. Climate Hard Gate

Allowed form:

- before changing climate state, require the minimum relevant evidence to be present
- if the action depends on windows, fan speed, or existing climate settings, read them first

Forbidden form:

- always call `get_vehicle_window_positions` before `set_air_conditioning` because `base_5` needs it

### 2. Charging Prerequisite Read Gate

Allowed form:

- charging estimates and trip charging plans require a minimum fact set
- if key battery fields or charger availability are missing, downgrade to partial assistance instead of estimating

Forbidden form:

- always call `search_poi_at_location` before `get_distance_by_soc` because `base_39` failed

### 3. Missing-Field Wording Gate

Allowed form:

- distinguish between:
  - field missing
  - field unknown
  - operation unsupported
  - capability absent
- only make the weakest justified claim

Forbidden form:

- special-case rear windows because `hallucination_25` exists

### 4. Delayed Navigation Commit Gate

Allowed form:

- treat navigation writes as commit actions
- do not commit navigation while route choice, charging stop choice, or user intent is still unresolved

Forbidden form:

- avoid setting Hamburg navigation first because `disambiguation_47` expects a Warsaw charging step

## Architecture Boundary

To stay honest, logic should be placed in the following layers:

### Shared Core

Allowed:

- uncertainty handling
- validator gates
- confirmation gates
- boundary phrasing discipline
- commit/draft distinction
- recovery behavior
- general postcondition and transition discipline

Not allowed:

- CAR answer heuristics
- route- or climate-specific behavior tied to benchmark wording

### Environment Bridge

Allowed:

- parse tool results
- normalize unknown/missing/error signals
- map environment observations into shared state
- expose environment-specific action categories

Not allowed:

- solve the task inside the bridge
- choose the benchmark-intended route or station inside the bridge

### Environment Policy/Profile

Allowed:

- `send_email` requires explicit confirmation
- `time_format = 24h`
- destructive GUI actions require confirmation

Not allowed:

- per-task policy exceptions

## Current Codebase Assessment

Based on the current runtime code:

- `src/purple_core/validator.py` uses domain guards and transition rules keyed off tool semantics, not task IDs.
- `src/purple_core/observation_normalizer.py` maps missing/unknown tool results into structured signals.
- `src/purple_car_bench_agent/policy_profile.py` expresses CAR-specific policy as a profile, which is the right direction.

This means the current implementation is already closer to:

- environment-aware validation

than to:

- task-aware answer scripting

However, there is still one real risk:

- a CAR-specific rule can still become benchmark-specific if it encodes a single expected action sequence rather than a general state/action constraint

That is the main line we need to police during further development.

## Required Review Checklist For Every New Rule

Before merging a new validator, boundary rule, or state-machine rule, check:

- Does it mention or depend on a task ID?
- Does it depend on a benchmark split?
- Can it be described as a production-safe policy?
- Is it triggered by tool semantics or state semantics?
- Would it still help on an unseen task?
- Does it narrow claims rather than inject guessed answers?

If the answer to the first two questions is yes, reject it.

If the answer to the last four questions is no, reject it.

## Evaluation Discipline

To reduce overfitting risk:

- use failure cases to discover missing abstractions
- implement only the abstraction
- validate on the known regression case
- then validate on unseen or broader samples

Regression sets are for bug reproduction, not for runtime dispatch logic.

## Decision

From this point onward:

- we are allowed to improve the purple agent using abstract capability constraints
- we are not allowed to encode benchmark-item-specific behavior
- every future optimization must be explained in abstraction-first language before implementation
