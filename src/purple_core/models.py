"""Shared data models for the purple core."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


StepType = Literal["inspect", "clarify", "act", "stop"]
ValidationStatus = Literal[
    "approved",
    "blocked_needs_read",
    "blocked_needs_clarification",
    "blocked_needs_confirmation",
    "blocked_boundary",
    "blocked_invalid_action",
]
RecoveryAction = Literal[
    "re_read",
    "clarify",
    "retry_corrected",
    "replan",
    "stop_cleanly",
]


@dataclass(slots=True)
class ObservationFrame:
    """Environment-agnostic snapshot of the latest turn."""

    environment: str
    goal_text: str = ""
    available_affordances: list[dict[str, Any]] = field(default_factory=list)
    feedback: list[dict[str, Any]] = field(default_factory=list)
    facts_delta: dict[str, Any] = field(default_factory=dict)
    error_signals: list[dict[str, Any]] = field(default_factory=list)
    constraints: dict[str, Any] = field(default_factory=dict)
    raw_user_text: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PlanProposal:
    """High-level next-step proposal produced by the planner."""

    objective: str
    current_step_type: StepType
    reason: str
    missing_information: list[str] = field(default_factory=list)
    candidate_action: dict[str, Any] | None = None
    expected_effect: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ValidationResult:
    """Validation decision for a proposed agent response."""

    status: ValidationStatus
    approved_tool_calls: list[dict[str, Any]] = field(default_factory=list)
    blocked_reason: str | None = None
    user_message_hint: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class RecoveryDecision:
    """Next move after validation or execution failure."""

    action: RecoveryAction
    reason: str
    user_message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SessionState:
    """Structured working state for one agent context."""

    message_history: list[dict[str, Any]] = field(default_factory=list)
    available_affordances: list[dict[str, Any]] = field(default_factory=list)
    observed_facts: dict[str, Any] = field(default_factory=dict)
    domain_snapshots: dict[str, Any] = field(default_factory=dict)
    inferred_facts: dict[str, Any] = field(default_factory=dict)
    unknowns: set[str] = field(default_factory=set)
    active_goal: str | None = None
    boundary_flags: dict[str, Any] = field(default_factory=dict)
    pending_confirmation: dict[str, Any] | None = None
    response_constraints: dict[str, Any] = field(default_factory=dict)
    last_plan: PlanProposal | None = None
    last_result: ValidationResult | RecoveryDecision | None = None
    boundary_mode: bool = False
    last_observation: ObservationFrame | None = None
