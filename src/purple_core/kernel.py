"""Shared execution kernel for purple agents."""

from __future__ import annotations

from typing import Any, Callable, Protocol

from purple_core.models import ObservationFrame
from purple_core.planner import ThinPlanner
from purple_core.policy_linter import PolicyLinter, PolicyProfile
from purple_core.recovery import RecoveryPolicy
from purple_core.session_state import SessionStateStore
from purple_core.validator import BasicValidator


class ParsedTurn(Protocol):
    """Minimum parsed-turn contract expected by the shared kernel."""

    system_prompt: str | None
    user_message_text: str | None
    incoming_tool_results: list[dict[str, Any]] | None
    tools: list[dict[str, Any]]


class EnvironmentBridge(Protocol):
    """Bridge contract for environment-specific I/O translation."""

    def parse_inbound_message(
        self,
        inbound_message: Any,
        previous_tools: list[dict[str, Any]] | None,
    ) -> ParsedTurn: ...

    def apply_turn_to_history(
        self,
        *,
        messages: list[dict[str, Any]],
        turn: ParsedTurn,
        fallback_user_input: str | None,
        logger: Any,
    ) -> None: ...

    def build_response_parts(self, assistant_content: dict[str, Any]) -> list[Any]: ...

    def assistant_message_for_history(self, assistant_content: dict[str, Any]) -> dict[str, Any]: ...


NormalizeTurn = Callable[[ParsedTurn, str | None], ObservationFrame]
LLMCall = Callable[[list[dict[str, Any]], list[dict[str, Any]]], dict[str, Any]]


class PurpleKernel:
    """Environment-agnostic execution loop for a purple agent."""

    def __init__(
        self,
        *,
        state_store: SessionStateStore | None = None,
        planner: ThinPlanner | None = None,
        validator: BasicValidator | None = None,
        policy_linter: PolicyLinter | None = None,
        recovery: RecoveryPolicy | None = None,
    ) -> None:
        self.state_store = state_store or SessionStateStore()
        self.planner = planner or ThinPlanner()
        self.validator = validator or BasicValidator()
        self.policy_linter = policy_linter or PolicyLinter()
        self.recovery = recovery or RecoveryPolicy()

    def execute_turn(
        self,
        *,
        context_id: str,
        inbound_message: Any,
        fallback_user_input: str | None,
        bridge: EnvironmentBridge,
        normalize_turn: NormalizeTurn,
        llm_call: LLMCall,
        policy_profile: PolicyProfile | None,
        logger: Any,
    ) -> list[Any]:
        state = self.state_store.get_or_create(context_id)

        try:
            turn = bridge.parse_inbound_message(
                inbound_message=inbound_message,
                previous_tools=state.available_affordances,
            )
        except Exception as exc:
            logger.warning("Failed to parse inbound message", error=str(exc))
            turn = bridge.parse_inbound_message(
                inbound_message=_EmptyInboundMessage(),
                previous_tools=state.available_affordances,
            )
            turn.user_message_text = fallback_user_input

        effective_fallback = None
        if not turn.user_message_text and not turn.incoming_tool_results:
            effective_fallback = fallback_user_input

        bridge.apply_turn_to_history(
            messages=state.message_history,
            turn=turn,
            fallback_user_input=effective_fallback,
            logger=logger,
        )
        self.state_store.set_available_affordances(state, turn.tools)

        observation = normalize_turn(turn, effective_fallback)
        self.state_store.merge_observation(state, observation)

        logger.info(
            "Received turn",
            context_id=context_id[:8],
            turn=len(state.message_history),
            message_preview=(
                (observation.raw_user_text or "")[:100]
                if observation.raw_user_text
                else f"[{len(observation.feedback)} tool results]"
                if observation.feedback
                else ""
            ),
        )
        logger.debug(
            "Turn details",
            context_id=context_id[:8],
            num_parts=len(inbound_message.parts),
            num_tools=len(state.available_affordances),
            num_tool_results=len(observation.feedback),
        )

        plan = self.planner.create_proposal(state, observation)
        self.state_store.record_plan(state, plan)

        try:
            assistant_content = llm_call(state.message_history, state.available_affordances)
            validation_result = self.validator.validate_llm_response(
                assistant_content=assistant_content,
                available_tools=state.available_affordances,
                plan=plan,
                state=state,
            )
            self.state_store.record_result(state, validation_result)

            blocking_result = validation_result if validation_result.status != "approved" else None

            if blocking_result is None:
                assistant_content["tool_calls"] = validation_result.approved_tool_calls
                policy_outcome = self.policy_linter.lint_response(
                    assistant_content=assistant_content,
                    state=state,
                    policy_profile=policy_profile,
                )
                assistant_content = policy_outcome.assistant_content
                blocking_result = policy_outcome.validation_result
                if blocking_result is not None:
                    self.state_store.record_result(state, blocking_result)

            if blocking_result is not None:
                recovery_decision = self.recovery.decide_from_validation(
                    validation_result=blocking_result,
                    plan=plan,
                    state=state,
                    observation=observation,
                )
                self.state_store.record_result(state, recovery_decision)
                logger.info(
                    "Response blocked by validator",
                    status=blocking_result.status,
                    blocked_reason=blocking_result.blocked_reason,
                    recovery_action=recovery_decision.action,
                )
                assistant_content = {
                    "content": (
                        recovery_decision.user_message
                        or blocking_result.user_message_hint
                        or ""
                    ),
                    "reasoning_content": assistant_content.get("reasoning_content"),
                }

            parts = bridge.build_response_parts(assistant_content)
            logger.info(
                "Prepared response",
                has_tool_calls=bool(assistant_content.get("tool_calls")),
                num_tool_calls=len(assistant_content.get("tool_calls") or []),
                has_content=bool(assistant_content.get("content")),
            )
        except Exception as exc:
            logger.error("LLM error", error=str(exc))
            assistant_content = {"content": f"Error processing request: {exc}"}
            parts = bridge.build_response_parts(assistant_content)

        state.message_history.append(bridge.assistant_message_for_history(assistant_content))
        return parts

    def reset_context(self, context_id: str) -> None:
        """Discard state for a finished or canceled context."""
        self.state_store.reset(context_id)


class _EmptyInboundMessage:
    """Fallback inbound-message stub used after parse failures."""

    parts: list[Any] = []
