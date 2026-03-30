# Purple Core v1.1 Failure-Bucket Integration Plan

## Goal

Integrate the 5 high-value failure buckets into the current shared-core pipeline without turning the agent into a CAR-specific solver.

The current pipeline is:

`CAR bridge -> observation normalizer -> session state -> planner -> validator -> LLM tool/text response -> recovery -> CAR bridge`

The next step is not to bolt on benchmark hacks. The next step is to make each stage more disciplined so the same kernel can later support OSWorld.

## The 5 Buckets

1. `Evidence / Precondition`
   Fixes "act before checking" failures.
2. `Action Grounding / State Machine`
   Fixes invalid action sequences and illegal state transitions.
3. `Policy / Formatting / Confirmation`
   Fixes 24-hour time, explicit confirmation, units, and user-facing compliance.
4. `Hallucination Boundary / Graceful Stop`
   Fixes "unknown/removed/unsupported" cases where the agent should stop or narrow scope instead of guessing.
5. `Disambiguation / Preference Resolution`
   Fixes cases where the agent should resolve from context or stored preference instead of asking the user again.

## Integration Principle

Organize by control point, not by benchmark split.

- `normalizer + state`
  Capture better facts, unknowns, and error signals.
- `planner`
  Make ambiguity, confirmation, and required reads explicit.
- `validator`
  Enforce evidence, state-machine, and policy rules before tool execution.
- `recovery`
  Convert blocked or unsafe states into bounded next moves.
- `bridge`
  Stay thin. It should translate environment I/O, not solve benchmark tasks.

## v1.1 Pipeline

The recommended pipeline for the next iteration is:

`bridge -> normalizer -> state.merge -> planner -> validator -> policy_linter -> execute -> outcome_analyzer -> recovery`

Notes:

- `policy_linter` is a new step. It should run both before tool execution and before final text response.
- `outcome_analyzer` can start as a small helper inside `normalizer/state`, then be split later if needed.
- The validator remains the main execution gate.

## Bucket 1: Evidence / Precondition

### What it should do

Before allowing an action, check whether the minimum evidence for that action is already present in state.

### Where it lives

- Primary: `src/purple_core/validator.py`
- Supporting state: `src/purple_core/session_state.py`
- Supporting extraction: `src/purple_core/observation_normalizer.py`

### What to add

- `SessionState.required_facts`
  Track facts needed for the current intent, such as current navigation state, climate state, or charging state.
- `ObservationFrame.fact_keys`
  Normalize which facts were just observed from tool results.
- `PlanProposal.required_reads`
  Let the planner declare which reads it thinks are needed.
- `BasicValidator` evidence gate
  If an action depends on missing facts, return `blocked_needs_read`.

### First CAR rules

- `set_air_conditioning(true)` requires recent window positions and climate settings.
- charging/time estimation requires charging status and any needed range conversion input.
- navigation mutation requires current navigation state before write actions.

## Bucket 2: Action Grounding / State Machine

### What it should do

Prevent invalid transitions even when the tool exists and the parameters are syntactically valid.

### Where it lives

- Primary: `src/purple_core/validator.py`
- Supporting state snapshot: `src/purple_core/session_state.py`
- Thin environment hints: `src/purple_car_bench_agent/car_bridge.py`

### What to add

- `SessionState.domain_snapshots`
  Keep compact environment snapshots such as `navigation_state`, `climate_state`, `charging_state`.
- `ValidationResult.metadata.transition_rule`
  Record which state-machine rule blocked the action.
- transition guards in `BasicValidator`
  Example: if final-destination replacement fails, do not silently degrade into `delete_current_navigation + set_new_navigation` unless explicitly allowed by policy.

### First CAR rules

- navigation edits must respect the currently active route topology.
- route switching after presenting alternatives should use the valid route mutation path, not reset navigation unless necessary.
- action fallback must not destroy state just to force a tool to accept new input.

## Bucket 3: Policy / Formatting / Confirmation

### What it should do

Catch cases where the action is semantically right but the user-facing behavior violates policy.

### Where it lives

- New file: `src/purple_core/policy_linter.py`
- Supporting state: `src/purple_core/session_state.py`
- Orchestrator wiring: `src/purple_car_bench_agent/car_bench_agent.py`

### What to add

- `SessionState.pending_confirmation`
  Store pending high-risk actions and the exact parameters that still need explicit user approval.
- `SessionState.response_constraints`
  Store active output constraints such as `24h_time`, `celsius_only`, `explicit_confirmation_required`.
- `PolicyLinter.lint_tool_calls(...)`
  Blocks tools like `send_email` until a confirmation contract exists.
- `PolicyLinter.lint_text(...)`
  Rewrites or blocks policy-breaking text, such as `3:30 PM` instead of `15:30`.

### First CAR rules

- `send_email` requires explicit confirmation with recipients and content summary.
- time shown to users must be 24-hour format.
- temperature/unit wording should be explicit when policy requires it.

## Bucket 4: Hallucination Boundary / Graceful Stop

### What it should do

Detect when the environment has removed a parameter, omitted a field, or returned unknown data, then stop or narrow scope instead of inferring unsupported facts.

### Where it lives

- Primary extraction: `src/purple_core/observation_normalizer.py`
- Boundary flags: `src/purple_core/session_state.py`
- Decisioning: `src/purple_core/recovery.py`
- Guardrails: `src/purple_core/validator.py`

### What to add

- `ObservationFrame.error_signals`
  Normalize tool-result phrases like `removed`, `unknown`, `cannot be used`, `unsupported`.
- `SessionState.boundary_flags`
  Keep structured flags like `removed_parameter`, `missing_observation`, `unsupported_action`.
- validator block for boundary-sensitive follow-up actions
  Example: if a tool explicitly says a parameter is removed, block retries using the same tool family.
- recovery branch for graceful stop
  Prefer a bounded explanation over speculative estimates.

### First CAR rules

- if a tool says a parameter is removed, do not retry with variants.
- if core battery fields are `unknown`, do not fabricate SoC estimates.
- if a requested calculation cannot be grounded, explain the limitation and stop cleanly.

## Bucket 5: Disambiguation / Preference Resolution

### What it should do

Represent ambiguity explicitly and resolve it from context when possible before asking the user.

### Where it lives

- Primary state: `src/purple_core/session_state.py`
- Planner support: `src/purple_core/planner.py`
- Validator enforcement: `src/purple_core/validator.py`

### What to add

- `SessionState.preference_hints`
  Track stable user preferences inferred from system prompt, prior turns, or environment context.
- `SessionState.unresolved_slots`
  Track which fields are still ambiguous.
- `PlanProposal.ambiguities`
  Let the planner distinguish between true ambiguity and resolvable ambiguity.
- validator rule
  If the ambiguity is resolvable from state, block unnecessary clarification and proceed with the grounded choice.

### First CAR rules

- if the task states the assistant should internally choose among charging stations from preference/context, do not bounce the choice back to the user.
- after presenting route options, preserve which route the user chose and enforce it at execution time.

## Concrete Code Changes

### Step 1: Extend shared models

Update `src/purple_core/models.py` with:

- `ObservationFrame.fact_keys`
- `ObservationFrame.error_signals`
- `SessionState.domain_snapshots`
- `SessionState.required_facts`
- `SessionState.pending_confirmation`
- `SessionState.response_constraints`
- `SessionState.preference_hints`
- `SessionState.unresolved_slots`
- `PlanProposal.required_reads`
- `PlanProposal.ambiguities`

### Step 2: Upgrade normalizer and state merge

Update:

- `src/purple_core/observation_normalizer.py`
- `src/purple_core/session_state.py`

Responsibilities:

- convert CAR tool results into fact keys, snapshots, and error signals
- detect `unknown` and `removed` markers
- preserve navigation/climate/charging snapshots
- track pending confirmation and unresolved ambiguity state

### Step 3: Strengthen planner output

Update `src/purple_core/planner.py` so the planner outputs:

- intended step type
- required reads
- whether confirmation is needed
- whether the task is ambiguous
- whether the ambiguity is resolvable from known preference/state

The planner should still stay thin. It should not emit CAR-specific action bundles.

### Step 4: Expand validator into 3 sub-gates

Keep one entry point in `src/purple_core/validator.py`, but internally split checks into:

- `evidence_gate`
- `transition_gate`
- `boundary_gate`

Then run `policy_linter` after raw validation.

The execution order should be:

1. schema and tool availability
2. evidence / precondition
3. state-machine transition
4. boundary / unsupported-action block
5. policy / formatting / confirmation lint

### Step 5: Add policy linter

Create `src/purple_core/policy_linter.py` and call it from [`car_bench_agent.py`](../../src/purple_car_bench_agent/car_bench_agent.py).

This module should:

- block high-risk tools pending explicit confirmation
- enforce formatting constraints before text leaves the agent
- optionally rewrite small formatting issues when safe

### Step 6: Expand recovery

Update `src/purple_core/recovery.py` to map specific blocked states to bounded outcomes:

- `blocked_needs_read -> re_read`
- `blocked_needs_confirmation -> clarify`
- `blocked_needs_clarification -> clarify`
- `blocked_boundary -> stop_cleanly`
- `blocked_invalid_transition -> replan`
- `blocked_policy -> clarify` or `rephrase`

## Implementation Order

Recommended order:

1. `Policy / Formatting / Confirmation`
   Fastest win, fixes `base_61` and `disambiguation_39`.
2. `Hallucination Boundary / Graceful Stop`
   Highest leverage for hallucination split.
3. `Action Grounding / State Machine`
   Fixes route mutation and illegal fallback behavior.
4. `Disambiguation / Preference Resolution`
   Fixes avoidable user bounce-back.
5. `Evidence / Precondition`
   Extend the evidence rules beyond the first successful fixes.

## Regression Strategy

Keep the targeted suite as the main short-loop regression set:

- `base_5`
- `base_39`
- `base_55`
- `base_61`
- `hallucination_3`
- `hallucination_25`
- `hallucination_37`
- `hallucination_45`
- `disambiguation_39`
- `disambiguation_47`

Track them by bucket, not just by split:

- `Evidence / Precondition`: `base_5`, `base_39`
- `Action Grounding / State Machine`: `base_55`
- `Policy / Formatting / Confirmation`: `base_61`, `disambiguation_39`
- `Hallucination Boundary / Graceful Stop`: `hallucination_3`, `hallucination_25`, `hallucination_37`, `hallucination_45`
- `Disambiguation / Preference Resolution`: `disambiguation_47`

## Success Criteria

The next iteration is successful if:

- the pipeline gains explicit gates for policy, boundary handling, and transition validity
- no new logic is pushed into the CAR bridge beyond environment translation
- targeted regressions flip at least the policy and hallucination cases first
- the core remains structured enough to support a future OSWorld bridge without redesign
