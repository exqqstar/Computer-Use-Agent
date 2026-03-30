"""CAR-bench purple agent orchestrated through the shared purple core."""

from __future__ import annotations

import copy
from pathlib import Path
import sys
from typing import Any

from dotenv import load_dotenv

load_dotenv()

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.utils import new_agent_parts_message
from litellm import completion

sys.path.insert(0, str(Path(__file__).parent.parent))
from logging_utils import configure_logger
from purple_car_bench_agent.car_bridge import CARBridge
from purple_car_bench_agent.policy_profile import CAR_POLICY_PROFILE
from purple_core.kernel import PurpleKernel
from purple_core.models import ObservationFrame
from purple_core.observation_normalizer import ObservationNormalizer
sys.path.pop(0)

logger = configure_logger(role="agent", context="-")


class CARBenchAgentExecutor(AgentExecutor):
    """Executor for the CAR-bench purple agent."""

    def __init__(
        self,
        model: str,
        temperature: float = 0.0,
        thinking: bool = False,
        reasoning_effort: str = "medium",
        interleaved_thinking: bool = False,
        api_base: str | None = None,
        api_key: str | None = None,
    ) -> None:
        self.model = model
        self.temperature = temperature
        self.thinking = thinking
        self.reasoning_effort = reasoning_effort
        self.interleaved_thinking = interleaved_thinking
        self.api_base = api_base
        self.api_key = api_key

        self.bridge = CARBridge()
        self.normalizer = ObservationNormalizer()
        self.policy_profile = CAR_POLICY_PROFILE
        self.kernel = PurpleKernel()

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        ctx_logger = logger.bind(role="agent", context=f"ctx:{context.context_id[:8]}")
        parts = self.kernel.execute_turn(
            context_id=context.context_id,
            inbound_message=context.message,
            fallback_user_input=context.get_user_input(),
            bridge=self.bridge,
            normalize_turn=self._normalize_turn,
            llm_call=self._call_llm,
            policy_profile=self.policy_profile,
            logger=ctx_logger,
        )
        response_message = new_agent_parts_message(parts=parts, context_id=context.context_id)
        await event_queue.enqueue_event(response_message)

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        """Cancel the current execution."""
        logger.bind(role="agent", context=f"ctx:{context.context_id[:8]}").info(
            "Canceling context",
            context_id=context.context_id[:8],
        )
        self.kernel.reset_context(context.context_id)

    def _normalize_turn(self, turn: Any, fallback_user_input: str | None) -> ObservationFrame:
        return self.normalizer.from_car(
            user_text=turn.user_message_text or fallback_user_input,
            tools=turn.tools,
            tool_results=turn.incoming_tool_results,
            system_prompt=turn.system_prompt,
        )

    def _call_llm(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> dict[str, Any]:
        completion_kwargs: dict[str, Any] = {
            "model": self.model,
            "tools": self._prepare_tools_for_completion(tools) if tools else None,
            "temperature": self.temperature,
        }
        if self.api_base:
            completion_kwargs["api_base"] = self.api_base
        if self.api_key:
            completion_kwargs["api_key"] = self.api_key

        if self.thinking:
            if self.model == "claude-opus-4-6":
                completion_kwargs["thinking"] = {"type": "adaptive"}
            else:
                if self.reasoning_effort in ["none", "disable", "low", "medium", "high"]:
                    completion_kwargs["reasoning_effort"] = self.reasoning_effort
                else:
                    try:
                        thinking_budget = int(self.reasoning_effort)
                    except ValueError as exc:
                        raise ValueError(
                            "reasoning_effort must be 'none', 'disable', 'low', 'medium', 'high', or an integer value"
                        ) from exc
                    completion_kwargs["thinking"] = {
                        "type": "enabled",
                        "budget_tokens": thinking_budget,
                    }
                if self.interleaved_thinking:
                    completion_kwargs["extra_headers"] = {
                        "anthropic-beta": "interleaved-thinking-2025-05-14"
                    }

        response = completion(
            messages=self._prepare_messages_for_completion(messages),
            **completion_kwargs,
        )
        llm_message = response.choices[0].message
        assistant_content = llm_message.model_dump(exclude_unset=True)
        return assistant_content

    def _prepare_messages_for_completion(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        cloned_messages = copy.deepcopy(messages)
        if cloned_messages:
            cloned_messages[0]["cache_control"] = {"type": "ephemeral"}
        return cloned_messages

    def _prepare_tools_for_completion(self, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        cloned_tools = copy.deepcopy(tools)
        if cloned_tools:
            cloned_tools[-1].setdefault("function", {})
            cloned_tools[-1]["function"]["cache_control"] = {"type": "ephemeral"}
        return cloned_tools
