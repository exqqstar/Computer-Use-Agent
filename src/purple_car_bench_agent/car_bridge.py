"""CAR-bench environment bridge for the shared purple core."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from a2a.types import DataPart, Part, TextPart

from purple_car_bench_agent.tool_call_types import ToolCall, ToolCallsData


@dataclass(slots=True)
class CARTurnInput:
    """Parsed inbound CAR-bench turn."""

    system_prompt: str | None
    user_message_text: str | None
    incoming_tool_results: list[dict[str, Any]] | None
    tools: list[dict[str, Any]]


class CARBridge:
    """Translates CAR-bench A2A messages to and from the shared core."""

    def parse_inbound_message(
        self,
        inbound_message: Any,
        previous_tools: list[dict[str, Any]] | None,
    ) -> CARTurnInput:
        user_message_text = None
        incoming_tool_results = None
        tools = list(previous_tools or [])
        system_prompt = None

        for part in inbound_message.parts:
            if isinstance(part.root, TextPart):
                text = part.root.text
                if "System:" in text and "\n\nUser:" in text:
                    system_prompt, user_message_text = self._split_system_and_user(text)
                else:
                    user_message_text = text
            elif isinstance(part.root, DataPart):
                data = part.root.data
                if "tools" in data:
                    tools = data["tools"]
                elif "tool_results" in data:
                    incoming_tool_results = data["tool_results"]

        return CARTurnInput(
            system_prompt=system_prompt,
            user_message_text=user_message_text,
            incoming_tool_results=incoming_tool_results,
            tools=tools,
        )

    def apply_turn_to_history(
        self,
        *,
        messages: list[dict[str, Any]],
        turn: CARTurnInput,
        fallback_user_input: str | None,
        logger: Any,
    ) -> None:
        if turn.system_prompt and not messages:
            messages.append({"role": "system", "content": turn.system_prompt})

        user_message_text = turn.user_message_text or fallback_user_input
        if messages and messages[-1].get("role") == "assistant" and messages[-1].get("tool_calls"):
            tool_results = self._format_tool_results(
                previous_tool_calls=messages[-1]["tool_calls"],
                incoming_tool_results=turn.incoming_tool_results,
                fallback_text=user_message_text or "",
                logger=logger,
            )
            messages.extend(tool_results)
            return

        messages.append({"role": "user", "content": user_message_text or ""})

    def build_response_parts(self, assistant_content: dict[str, Any]) -> list[Part]:
        parts: list[Part] = []

        if assistant_content.get("content"):
            parts.append(Part(root=TextPart(kind="text", text=assistant_content["content"])))

        if assistant_content.get("tool_calls"):
            tool_calls_list = []
            for tool_call in assistant_content["tool_calls"]:
                arguments = tool_call.get("function", {}).get("arguments", "{}")
                if isinstance(arguments, str):
                    parsed_arguments = json.loads(arguments)
                else:
                    parsed_arguments = arguments
                tool_calls_list.append(
                    ToolCall(
                        tool_name=tool_call["function"]["name"],
                        arguments=parsed_arguments,
                    )
                )

            parts.append(
                Part(
                    root=DataPart(
                        kind="data",
                        data=ToolCallsData(tool_calls=tool_calls_list).model_dump(),
                    )
                )
            )

        if assistant_content.get("reasoning_content"):
            parts.append(
                Part(
                    root=DataPart(
                        kind="data",
                        data={"reasoning_content": assistant_content["reasoning_content"]},
                    )
                )
            )

        if not parts:
            parts.append(Part(root=TextPart(kind="text", text=assistant_content.get("content", ""))))

        return parts

    def assistant_message_for_history(self, assistant_content: dict[str, Any]) -> dict[str, Any]:
        message = {
            "role": "assistant",
            "content": assistant_content.get("content"),
        }
        if assistant_content.get("tool_calls"):
            message["tool_calls"] = assistant_content["tool_calls"]
        if assistant_content.get("thinking_blocks"):
            message["thinking_blocks"] = assistant_content["thinking_blocks"]
        if assistant_content.get("reasoning_content"):
            message["reasoning_content"] = assistant_content["reasoning_content"]
        return message

    def _split_system_and_user(self, text: str) -> tuple[str, str]:
        system_part, user_part = text.split("\n\nUser:", 1)
        return system_part.replace("System:", "").strip(), user_part.strip()

    def _format_tool_results(
        self,
        *,
        previous_tool_calls: list[dict[str, Any]],
        incoming_tool_results: list[dict[str, Any]] | None,
        fallback_text: str,
        logger: Any,
    ) -> list[dict[str, Any]]:
        if incoming_tool_results:
            tool_call_by_name: dict[str, list[dict[str, Any]]] = {}
            for tool_call in previous_tool_calls:
                name = tool_call["function"]["name"]
                tool_call_by_name.setdefault(name, []).append(tool_call)

            tool_results = []
            for tool_result in incoming_tool_results:
                result_name = tool_result.get("tool_name", "")
                matching_calls = tool_call_by_name.get(result_name, [])
                if matching_calls:
                    matched_tool_call = matching_calls.pop(0)
                    tool_results.append(
                        {
                            "role": "tool",
                            "tool_call_id": matched_tool_call["id"],
                            "content": tool_result.get("content", ""),
                        }
                    )
                else:
                    logger.warning(
                        "No matching tool_call_id for tool result",
                        tool_name=result_name,
                    )
                    tool_results.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_result.get("tool_call_id", f"unknown_{result_name}"),
                            "content": tool_result.get("content", ""),
                        }
                    )
            return tool_results

        return [
            {
                "role": "tool",
                "tool_call_id": tool_call["id"],
                "content": fallback_text,
            }
            for tool_call in previous_tool_calls
        ]
