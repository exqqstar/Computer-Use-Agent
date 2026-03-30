"""Recovery decisions after blocked actions or failed execution."""

from __future__ import annotations

from purple_core.models import ObservationFrame, PlanProposal, RecoveryDecision, SessionState, ValidationResult


class RecoveryPolicy:
    """Chooses a bounded next move when validation or execution fails."""

    def decide_from_validation(
        self,
        *,
        validation_result: ValidationResult,
        plan: PlanProposal,
        state: SessionState,
        observation: ObservationFrame,
    ) -> RecoveryDecision:
        if validation_result.status == "blocked_needs_read":
            return RecoveryDecision(
                action="re_read",
                reason=validation_result.blocked_reason or "Need more evidence before acting.",
                user_message=validation_result.user_message_hint or "Let me check the current state first.",
                metadata={"plan_step": plan.current_step_type, "environment": observation.environment},
            )

        if validation_result.status in {"blocked_needs_clarification", "blocked_needs_confirmation"}:
            return RecoveryDecision(
                action="clarify",
                reason=validation_result.blocked_reason or "The task still needs user input.",
                user_message=validation_result.user_message_hint or "I need a quick confirmation before I continue.",
                metadata={"plan_step": plan.current_step_type, "environment": observation.environment},
            )

        if validation_result.status == "blocked_boundary":
            state.boundary_mode = bool(validation_result.metadata.get("hard_stop"))
            return RecoveryDecision(
                action="stop_cleanly",
                reason=validation_result.blocked_reason or "Capability boundary reached.",
                user_message=validation_result.user_message_hint or "I can't safely continue with that request here.",
                metadata={"plan_step": plan.current_step_type, "environment": observation.environment},
            )

        return RecoveryDecision(
            action="replan",
            reason=validation_result.blocked_reason or "The proposed action is not valid in the current state.",
            user_message=validation_result.user_message_hint or "I need to re-check the details before I continue.",
            metadata={"plan_step": plan.current_step_type, "environment": observation.environment},
        )
