"""Generic policy linting and confirmation gating."""

from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass, field
from typing import Any

from purple_core.models import SessionState, ValidationResult


_TWELVE_HOUR_TIME_RE = re.compile(
    r"\b(?P<hour>1[0-2]|0?[1-9])(?::(?P<minute>[0-5]\d))?\s*(?P<meridiem>[APap])\.?\s*M\.?\b"
)


@dataclass(slots=True)
class PolicyProfile:
    """Environment-provided policy configuration for the shared linter."""

    name: str = "default"
    response_constraints: dict[str, Any] = field(default_factory=dict)
    confirmation_required_tools: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class PolicyLintOutcome:
    """Result of applying policy linting to an assistant response."""

    assistant_content: dict[str, Any]
    validation_result: ValidationResult | None = None


class PolicyLinter:
    """Applies generic interaction-policy constraints to agent output."""

    def lint_response(
        self,
        *,
        assistant_content: dict[str, Any],
        state: SessionState,
        policy_profile: PolicyProfile | None,
    ) -> PolicyLintOutcome:
        profile = policy_profile or PolicyProfile()
        state.response_constraints.update(profile.response_constraints)
        self._sync_confirmation_state(state)

        linted_content = copy.deepcopy(assistant_content)
        linted_content = self._apply_response_constraints(
            linted_content=linted_content,
            constraints=state.response_constraints,
        )

        risky_tool_call = self._find_confirmation_required_tool_call(
            linted_content.get("tool_calls") or [],
            profile=profile,
        )
        if risky_tool_call is None:
            return PolicyLintOutcome(assistant_content=linted_content)

        if self._matches_confirmed_pending(state.pending_confirmation, risky_tool_call):
            state.pending_confirmation = None
            return PolicyLintOutcome(assistant_content=linted_content)

        confirmation_prompt = self._build_confirmation_prompt(
            tool_call=risky_tool_call,
            profile=profile,
        )
        state.pending_confirmation = self._build_pending_confirmation(
            tool_call=risky_tool_call,
            profile=profile,
            prompt=confirmation_prompt,
        )
        return PolicyLintOutcome(
            assistant_content={
                "content": confirmation_prompt,
                "reasoning_content": linted_content.get("reasoning_content"),
            },
            validation_result=ValidationResult(
                status="blocked_needs_confirmation",
                blocked_reason=(
                    f"Tool '{risky_tool_call['function']['name']}' requires explicit confirmation "
                    "before execution."
                ),
                user_message_hint=confirmation_prompt,
                metadata={"source": "policy_linter", "profile": profile.name},
            ),
        )

    def _sync_confirmation_state(self, state: SessionState) -> None:
        if not state.pending_confirmation or not state.last_observation:
            return
        user_text = (state.last_observation.raw_user_text or "").strip()
        if not user_text:
            return

        if self._looks_negative(user_text):
            state.pending_confirmation = None
            return

        if self._looks_affirmative(user_text):
            state.pending_confirmation["confirmed"] = True

    def _find_confirmation_required_tool_call(
        self,
        tool_calls: list[dict[str, Any]],
        *,
        profile: PolicyProfile,
    ) -> dict[str, Any] | None:
        for tool_call in tool_calls:
            tool_name = tool_call.get("function", {}).get("name")
            if tool_name in profile.confirmation_required_tools:
                return tool_call
        return None

    def _matches_confirmed_pending(
        self,
        pending_confirmation: dict[str, Any] | None,
        tool_call: dict[str, Any],
    ) -> bool:
        if not pending_confirmation or not pending_confirmation.get("confirmed"):
            return False
        function = tool_call.get("function", {})
        return (
            pending_confirmation.get("tool_name") == function.get("name")
            and pending_confirmation.get("arguments") == function.get("arguments")
        )

    def _build_pending_confirmation(
        self,
        *,
        tool_call: dict[str, Any],
        profile: PolicyProfile,
        prompt: str,
    ) -> dict[str, Any]:
        function = tool_call.get("function", {})
        return {
            "profile": profile.name,
            "tool_name": function.get("name"),
            "arguments": function.get("arguments"),
            "prompt": prompt,
            "confirmed": False,
        }

    def _build_confirmation_prompt(
        self,
        *,
        tool_call: dict[str, Any],
        profile: PolicyProfile,
    ) -> str:
        function = tool_call.get("function", {})
        tool_name = function.get("name", "this action")
        action_label = profile.confirmation_required_tools.get(
            tool_name,
            tool_name.replace("_", " "),
        )
        arguments = self._parse_arguments(function.get("arguments"))
        arguments_preview = json.dumps(arguments, ensure_ascii=True, sort_keys=True)
        return (
            f"Please confirm: I will {action_label} with these details: "
            f"{arguments_preview}. Reply yes to continue or no to cancel."
        )

    def _apply_response_constraints(
        self,
        *,
        linted_content: dict[str, Any],
        constraints: dict[str, Any],
    ) -> dict[str, Any]:
        if constraints.get("time_format") != "24h":
            return linted_content

        if linted_content.get("content"):
            linted_content["content"] = self._rewrite_value(linted_content["content"], constraints)

        tool_calls = linted_content.get("tool_calls") or []
        for tool_call in tool_calls:
            function = tool_call.setdefault("function", {})
            arguments = self._parse_arguments(function.get("arguments"))
            rewritten = self._rewrite_value(arguments, constraints)
            function["arguments"] = json.dumps(rewritten, ensure_ascii=True, sort_keys=True)
        return linted_content

    def _rewrite_value(self, value: Any, constraints: dict[str, Any]) -> Any:
        if isinstance(value, str):
            return self._rewrite_text(value, constraints)
        if isinstance(value, list):
            return [self._rewrite_value(item, constraints) for item in value]
        if isinstance(value, dict):
            return {key: self._rewrite_value(item, constraints) for key, item in value.items()}
        return value

    def _rewrite_text(self, text: str, constraints: dict[str, Any]) -> str:
        rewritten = text
        if constraints.get("time_format") == "24h":
            rewritten = _TWELVE_HOUR_TIME_RE.sub(self._to_24_hour, rewritten)
        return rewritten

    def _parse_arguments(self, raw_arguments: Any) -> dict[str, Any]:
        if raw_arguments is None or raw_arguments == "":
            return {}
        if isinstance(raw_arguments, dict):
            return raw_arguments
        parsed = json.loads(raw_arguments)
        if not isinstance(parsed, dict):
            return {}
        return parsed

    def _looks_affirmative(self, text: str) -> bool:
        lowered = text.strip().lower()
        normalized = re.sub(r"[^a-z0-9\s]", "", lowered)
        return normalized in {
            "yes",
            "yes please",
            "please do",
            "do it",
            "confirm",
            "confirmed",
            "send it",
            "go ahead",
            "thats right",
            "that's right",
        }

    def _looks_negative(self, text: str) -> bool:
        lowered = text.strip().lower()
        normalized = re.sub(r"[^a-z0-9\s]", "", lowered)
        return normalized in {
            "no",
            "no thanks",
            "cancel",
            "dont",
            "don't",
            "stop",
        }

    def _to_24_hour(self, match: re.Match[str]) -> str:
        hour = int(match.group("hour"))
        minute = match.group("minute") or "00"
        meridiem = match.group("meridiem").lower()
        if meridiem == "p" and hour != 12:
            hour += 12
        if meridiem == "a" and hour == 12:
            hour = 0
        return f"{hour:02d}:{minute}"
