"""Thin planner for the shared purple core."""

from __future__ import annotations

from purple_core.models import ObservationFrame, PlanProposal, SessionState


class ThinPlanner:
    """Produces a bounded, high-level next-step proposal."""

    def create_proposal(self, state: SessionState, observation: ObservationFrame) -> PlanProposal:
        objective = observation.goal_text or state.active_goal or "handle the current turn"
        if state.boundary_mode:
            return PlanProposal(
                objective=objective,
                current_step_type="stop",
                reason="Boundary mode is active for this context.",
                expected_effect="Stop cleanly without speculative execution.",
            )

        if observation.raw_user_text:
            step_type = "act"
            reason = "The user provided a new request or clarification."
        elif observation.feedback:
            step_type = "act"
            reason = "The environment returned feedback from prior actions."
        elif state.available_affordances:
            step_type = "inspect"
            reason = "Affordances are available but no fresh user text was provided."
        else:
            step_type = "clarify"
            reason = "The current turn does not contain enough signal to proceed."

        return PlanProposal(
            objective=objective,
            current_step_type=step_type,
            reason=reason,
            missing_information=sorted(state.unknowns),
            candidate_action={"mode": "llm_response"},
            expected_effect="Advance the current task by one bounded step.",
            metadata={"environment": observation.environment},
        )
