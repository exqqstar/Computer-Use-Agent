"""Validation and canonicalization for candidate actions."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
import json
from typing import Any

from purple_core.models import PlanProposal, SessionState, ValidationResult


@dataclass(slots=True)
class _TransitionDecision:
    tool_call: dict[str, Any] | None = None
    validation_error: ValidationResult | None = None
    transition_rules: list[str] = field(default_factory=list)


class BasicValidator:
    """Applies basic safety and shape checks before execution."""

    _WINDOW_PRIORITY = (
        "DRIVER",
        "PASSENGER",
        "DRIVER_REAR",
        "PASSENGER_REAR",
    )
    _WINDOW_AC_THRESHOLD = 20

    _DOMAIN_TOOL_GUARDS = {
        "battery_status_lookup": {"get_charging_specs_and_status"},
        "charging_estimation": {
            "get_charging_specs_and_status",
            "get_distance_by_soc",
            "calculate_charging_time_by_soc",
        },
        "trip_charging_planning": {
            "get_location_id_by_location_name",
            "get_routes_from_start_to_destination",
            "search_poi_along_the_route",
            "search_poi_at_location",
        },
        "route_charging_station_lookup": {
            "search_poi_along_the_route",
            "get_location_id_by_location_name",
            "search_poi_at_location",
            "get_routes_from_start_to_destination",
        },
        "window_position_grounding": {"open_close_window"},
    }

    _DOMAIN_KEYWORDS = {
        "battery_status_lookup": (
            "battery",
            "state of charge",
            "current charge",
            "current battery",
            "charge status",
        ),
        "charging_estimation": (
            "charge",
            "charging",
            "battery",
            "state of charge",
            "range",
            "80%",
            "80 percent",
            "10%",
            "10 percent",
        ),
        "trip_charging_planning": (
            "charging stop",
            "charging stops",
            "charge stop",
            "charge stops",
            "how many stops",
            "how many charging",
            "stop along the way",
            "stops along the way",
        ),
        "route_charging_station_lookup": (
            "charging station",
            "charger",
            "charging stop",
            "charge stop",
            "along the route",
            "along my route",
            "route",
        ),
        "window_position_grounding": ("window", "air flow", "airflow"),
    }

    def validate_llm_response(
        self,
        *,
        assistant_content: dict[str, Any],
        available_tools: list[dict[str, Any]],
        plan: PlanProposal,
        state: SessionState,
    ) -> ValidationResult:
        raw_tool_calls = assistant_content.get("tool_calls") or []
        text_content = assistant_content.get("content") or ""

        if state.boundary_mode and raw_tool_calls:
            return ValidationResult(
                status="blocked_boundary",
                blocked_reason="Boundary mode prevents additional tool execution.",
                user_message_hint="I can't safely continue with more actions in the current state.",
                metadata={"plan_step": plan.current_step_type},
            )

        boundary_text_validation = self._validate_boundary_text_response(
            text_content=text_content,
            raw_tool_calls=raw_tool_calls,
            state=state,
        )
        if boundary_text_validation is not None:
            return boundary_text_validation

        if not raw_tool_calls:
            return ValidationResult(
                status="approved",
                metadata={"text_only": True, "plan_step": plan.current_step_type},
            )

        tool_lookup = self._build_tool_lookup(available_tools)
        approved_tool_calls: list[dict[str, Any]] = []
        transition_rules_applied: list[str] = []
        for raw_tool_call in raw_tool_calls:
            canonical_tool_call = self._canonicalize_tool_call(raw_tool_call)
            original_tool_name = canonical_tool_call.get("function", {}).get("name")
            transition_decision = self._apply_transition_gate(
                canonical_tool_call,
                tool_lookup,
                state=state,
            )
            if transition_decision.validation_error is not None:
                return transition_decision.validation_error

            candidate_tool_call = transition_decision.tool_call or canonical_tool_call
            transition_rules_applied.extend(transition_decision.transition_rules)
            candidate_tool_name = candidate_tool_call.get("function", {}).get("name")

            if (
                original_tool_name == "set_air_conditioning"
                and candidate_tool_name != original_tool_name
            ):
                return ValidationResult(
                    status="approved",
                    approved_tool_calls=[candidate_tool_call],
                    metadata={
                        "plan_step": plan.current_step_type,
                        "tool_call_count": 1,
                        "transition_rules": transition_rules_applied,
                    },
                )

            validation_error = self._validate_single_tool_call(
                candidate_tool_call,
                tool_lookup,
                state=state,
            )
            if validation_error is not None:
                return validation_error
            approved_tool_calls.append(candidate_tool_call)

        return ValidationResult(
            status="approved",
            approved_tool_calls=approved_tool_calls,
            metadata={
                "plan_step": plan.current_step_type,
                "tool_call_count": len(approved_tool_calls),
                "transition_rules": transition_rules_applied,
            },
        )

    def _build_tool_lookup(self, available_tools: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        lookup: dict[str, dict[str, Any]] = {}
        for tool in available_tools or []:
            function = tool.get("function", {})
            name = function.get("name")
            if name:
                lookup[name] = tool
        return lookup

    def _validate_single_tool_call(
        self,
        raw_tool_call: dict[str, Any],
        tool_lookup: dict[str, dict[str, Any]],
        *,
        state: SessionState,
    ) -> ValidationResult | None:
        function = raw_tool_call.get("function", {})
        tool_name = function.get("name")
        if not tool_name or tool_name not in tool_lookup:
            return ValidationResult(
                status="blocked_invalid_action",
                blocked_reason=f"Tool '{tool_name}' is not available in the current affordances.",
                user_message_hint="I need to re-check the available actions before continuing.",
            )

        try:
            arguments = self._parse_arguments(function.get("arguments"))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            return ValidationResult(
                status="blocked_invalid_action",
                blocked_reason=f"Tool arguments for '{tool_name}' are not valid JSON: {exc}",
                user_message_hint="I need to re-check the action details before continuing.",
            )

        required_fields = self._required_fields(tool_lookup[tool_name])
        missing_fields = [field for field in required_fields if field not in arguments]
        if missing_fields:
            return ValidationResult(
                status="blocked_invalid_action",
                blocked_reason=f"Tool '{tool_name}' is missing required arguments: {', '.join(missing_fields)}.",
                user_message_hint="I need a bit more information before I can do that.",
            )

        boundary_tool_validation = self._validate_boundary_tool_call(
            tool_name=tool_name,
            state=state,
        )
        if boundary_tool_validation is not None:
            return boundary_tool_validation

        boundary_domain_validation = self._validate_boundary_domain_tool_call(
            tool_name=tool_name,
            state=state,
        )
        if boundary_domain_validation is not None:
            return boundary_domain_validation

        percentage_validation = self._validate_missing_requested_percentage(
            tool_name=tool_name,
            arguments=arguments,
            state=state,
        )
        if percentage_validation is not None:
            return percentage_validation

        route_selection_validation = self._validate_navigation_route_selection(
            tool_name=tool_name,
            arguments=arguments,
            state=state,
        )
        if route_selection_validation is not None:
            return route_selection_validation

        return None

    def _canonicalize_tool_call(self, raw_tool_call: dict[str, Any]) -> dict[str, Any]:
        canonical = copy.deepcopy(raw_tool_call)
        function = canonical.setdefault("function", {})
        arguments = self._parse_arguments(function.get("arguments"))
        function["arguments"] = json.dumps(arguments, ensure_ascii=True, sort_keys=True)
        canonical.setdefault("type", "function")
        return canonical

    def _parse_arguments(self, raw_arguments: Any) -> dict[str, Any]:
        if raw_arguments is None or raw_arguments == "":
            return {}
        if isinstance(raw_arguments, dict):
            return raw_arguments
        parsed = json.loads(raw_arguments)
        if not isinstance(parsed, dict):
            raise TypeError("arguments must decode to an object")
        return parsed

    def _required_fields(self, tool_schema: dict[str, Any]) -> list[str]:
        parameters = tool_schema.get("function", {}).get("parameters", {})
        required = parameters.get("required", [])
        if isinstance(required, list):
            return [field for field in required if isinstance(field, str)]
        return []

    def _validate_boundary_tool_call(
        self,
        *,
        tool_name: str,
        state: SessionState,
    ) -> ValidationResult | None:
        blocked_tools = state.boundary_flags.get("blocked_tools", {})
        signal = blocked_tools.get(tool_name)
        if signal is None:
            return None
        return ValidationResult(
            status="blocked_boundary",
            blocked_reason=signal.get("reason") or f"Tool '{tool_name}' is blocked by a boundary signal.",
            user_message_hint=signal.get("user_message_hint")
            or "I can't safely continue with that action from the current system response.",
            metadata={
                "blocked_tool": tool_name,
                "signal_type": signal.get("type"),
                "hard_stop": signal.get("hard_stop", False),
            },
        )

    def _validate_boundary_domain_tool_call(
        self,
        *,
        tool_name: str,
        state: SessionState,
    ) -> ValidationResult | None:
        blocked_domains = state.boundary_flags.get("blocked_domains", {})
        if not blocked_domains:
            return None

        for domain_name, signal in blocked_domains.items():
            guarded_tools = self._DOMAIN_TOOL_GUARDS.get(domain_name, set())
            if tool_name not in guarded_tools:
                continue
            if not self._goal_matches_domain(domain_name, state.active_goal):
                continue
            return ValidationResult(
                status="blocked_boundary",
                blocked_reason=signal.get("reason")
                or f"Domain '{domain_name}' is currently blocked by an earlier boundary signal.",
                user_message_hint=signal.get("user_message_hint")
                or "I can't safely continue that line of action from the current system response.",
                metadata={
                    "blocked_tool": tool_name,
                    "blocked_domain": domain_name,
                    "signal_type": signal.get("type"),
                    "hard_stop": signal.get("hard_stop", False),
                },
            )
        return None

    def _validate_boundary_text_response(
        self,
        *,
        text_content: str,
        raw_tool_calls: list[dict[str, Any]],
        state: SessionState,
    ) -> ValidationResult | None:
        if raw_tool_calls or not text_content:
            return None
        signal = self._select_active_boundary_signal(state)
        if signal is None:
            return None
        if self._proposes_blocked_workaround(text_content):
            return ValidationResult(
                status="blocked_boundary",
                blocked_reason=signal.get("reason")
                or "The response proposes a workaround even though the required evidence is unavailable.",
                user_message_hint=signal.get("user_message_hint")
                or "I can't safely continue from the current system response.",
                metadata={
                    "signal_type": signal.get("type"),
                    "text_only": True,
                    "hard_stop": signal.get("hard_stop", False),
                    "offered_blocked_workaround": True,
                },
            )
        if self._overstates_unknown_value_as_absence(text_content, signal):
            return ValidationResult(
                status="blocked_boundary",
                blocked_reason=signal.get("reason")
                or "The response overstates a missing field as an unsupported or absent capability.",
                user_message_hint=signal.get("user_message_hint")
                or "I can't safely continue from the current system response.",
                metadata={
                    "signal_type": signal.get("type"),
                    "text_only": True,
                    "hard_stop": signal.get("hard_stop", False),
                    "overstated_missing_field": True,
                },
            )
        if self._requests_missing_information_after_boundary(text_content):
            return ValidationResult(
                status="blocked_boundary",
                blocked_reason=signal.get("reason")
                or "The response asks the user to fill in evidence that the system has already reported as unavailable.",
                user_message_hint=signal.get("user_message_hint")
                or "I can't safely continue from the current system response.",
                metadata={
                    "signal_type": signal.get("type"),
                    "text_only": True,
                    "hard_stop": signal.get("hard_stop", False),
                    "requested_user_substitute": True,
                },
            )
        if self._acknowledges_limitation(text_content):
            return None
        return ValidationResult(
            status="blocked_boundary",
            blocked_reason=signal.get("reason") or "The response should acknowledge the current system limitation.",
            user_message_hint=signal.get("user_message_hint")
            or "I can't safely continue from the current system response.",
            metadata={
                "signal_type": signal.get("type"),
                "text_only": True,
                "hard_stop": signal.get("hard_stop", False),
            },
        )

    def _select_active_boundary_signal(self, state: SessionState) -> dict[str, Any] | None:
        last_observation = state.last_observation
        if last_observation is not None:
            signal = next(
                (item for item in last_observation.error_signals if item.get("acknowledge_limits")),
                None,
            )
            if signal is not None:
                return signal

        blocked_domains = state.boundary_flags.get("blocked_domains", {})
        for domain_name, signal in blocked_domains.items():
            if not signal.get("acknowledge_limits"):
                continue
            if self._goal_matches_domain(domain_name, state.active_goal):
                return signal

        blocked_tools = state.boundary_flags.get("blocked_tools", {})
        for signal in blocked_tools.values():
            if signal.get("acknowledge_limits"):
                return signal
        return None

    def _acknowledges_limitation(self, text: str) -> bool:
        lowered = text.lower()
        limitation_markers = [
            "can't",
            "cannot",
            "unable",
            "don't have enough",
            "do not have enough",
            "not enough data",
            "unknown",
            "not available",
            "couldn't",
            "could not",
            "can't safely",
        ]
        return any(marker in lowered for marker in limitation_markers)

    def _proposes_blocked_workaround(self, text: str) -> bool:
        lowered = text.lower()
        workaround_markers = [
            "would you like me to try",
            "want me to try",
            "i can try",
            "shall i try",
            "should i try",
            "try setting",
            "try searching",
            "try looking",
        ]
        return any(marker in lowered for marker in workaround_markers)

    def _requests_missing_information_after_boundary(self, text: str) -> bool:
        lowered = text.lower()
        request_markers = [
            "could you let me know",
            "can you tell me",
            "would you mind telling me",
            "what percentage",
            "what's your current",
            "what is your current",
            "let me know your",
            "tell me your current",
        ]
        return any(marker in lowered for marker in request_markers)

    def _overstates_unknown_value_as_absence(
        self,
        text: str,
        signal: dict[str, Any],
    ) -> bool:
        if signal.get("type") != "unknown_value":
            return False
        lowered = text.lower()
        absence_markers = [
            "not equipped",
            "isn't equipped",
            "aren't equipped",
            "not available in this vehicle",
            "isn't available in this vehicle",
            "aren't available in this vehicle",
            "not installed",
            "doesn't exist",
            "do not exist",
            "don't exist",
            "not supported",
        ]
        return any(marker in lowered for marker in absence_markers)

    def _goal_matches_domain(self, domain_name: str, goal_text: str | None) -> bool:
        if not goal_text:
            return True
        lowered_goal = goal_text.lower()
        keywords = self._DOMAIN_KEYWORDS.get(domain_name, ())
        if not keywords:
            return True
        return any(keyword in lowered_goal for keyword in keywords)

    def _validate_missing_requested_percentage(
        self,
        *,
        tool_name: str,
        arguments: dict[str, Any],
        state: SessionState,
    ) -> ValidationResult | None:
        if tool_name != "open_close_window":
            return None
        goal_text = (state.active_goal or "").lower()
        if "percent" not in goal_text and "%" not in goal_text:
            return None
        if "percentage" in arguments:
            return None
        return ValidationResult(
            status="blocked_boundary",
            blocked_reason=(
                "The requested window action depends on a percentage target, but the current tool call "
                "does not expose a usable percentage parameter."
            ),
            user_message_hint=(
                "I can't safely set the windows to a specific percentage because the current window-control "
                "interface does not expose that percentage setting."
            ),
            metadata={"blocked_tool": tool_name, "hard_stop": True, "signal_type": "missing_percentage_parameter"},
        )

    def _apply_transition_gate(
        self,
        tool_call: dict[str, Any],
        tool_lookup: dict[str, dict[str, Any]],
        *,
        state: SessionState,
    ) -> _TransitionDecision:
        function = tool_call.get("function", {})
        tool_name = function.get("name")
        arguments = self._parse_arguments(function.get("arguments"))

        navigation_state = state.domain_snapshots.get("navigation_state")
        route_catalog = state.domain_snapshots.get("route_catalog", {})
        if not isinstance(navigation_state, dict) or not isinstance(route_catalog, dict):
            route_catalog = {}
            navigation_state = {}

        climate_transition = self._apply_air_conditioning_gate(
            tool_name=tool_name,
            arguments=arguments,
            tool_lookup=tool_lookup,
            state=state,
        )
        if climate_transition is not None:
            return climate_transition

        if tool_name == "navigation_replace_final_destination":
            route_id = arguments.get("route_id_leading_to_new_destination")
            route_metadata = route_catalog.get(route_id)
            tail_waypoint_id = navigation_state.get("tail_waypoint_id")
            destination_id = arguments.get("new_destination_id")
            if (
                isinstance(route_metadata, dict)
                and tail_waypoint_id
                and destination_id
                and route_metadata.get("start_id") != tail_waypoint_id
                and "get_routes_from_start_to_destination" in tool_lookup
            ):
                return _TransitionDecision(
                    tool_call=self._build_tool_call(
                        tool_name="get_routes_from_start_to_destination",
                        arguments={
                            "start_id": tail_waypoint_id,
                            "destination_id": destination_id,
                        },
                    ),
                    transition_rules=["navigation_replace_requires_route_from_previous_waypoint"],
                )

        if tool_name == "set_new_navigation":
            route_ids = arguments.get("route_ids")
            if (
                navigation_state.get("navigation_active")
                and isinstance(route_ids, list)
                and len(route_ids) == 1
                and route_ids[0] in route_catalog
                and "navigation_replace_final_destination" in tool_lookup
            ):
                route_metadata = route_catalog[route_ids[0]]
                destination_id = route_metadata.get("destination_id")
                if destination_id:
                    return _TransitionDecision(
                        tool_call=self._build_tool_call(
                            tool_name="navigation_replace_final_destination",
                            arguments={
                                "new_destination_id": destination_id,
                                "route_id_leading_to_new_destination": route_ids[0],
                            },
                        ),
                        transition_rules=["active_navigation_route_switch_uses_replace_final_destination"],
                    )

        return _TransitionDecision(tool_call=tool_call)

    def _apply_air_conditioning_gate(
        self,
        *,
        tool_name: str | None,
        arguments: dict[str, Any],
        tool_lookup: dict[str, dict[str, Any]],
        state: SessionState,
    ) -> _TransitionDecision | None:
        if tool_name != "set_air_conditioning" or arguments.get("on") is not True:
            return None

        climate_settings = state.domain_snapshots.get("climate_settings")
        if not isinstance(climate_settings, dict):
            climate_settings = {}
        window_positions = state.domain_snapshots.get("window_positions")
        if not isinstance(window_positions, dict):
            window_positions = {}

        if not climate_settings and "get_climate_settings" in tool_lookup:
            return _TransitionDecision(
                tool_call=self._build_tool_call(tool_name="get_climate_settings", arguments={}),
                transition_rules=["air_conditioning_requires_climate_read"],
            )

        if not window_positions and "get_vehicle_window_positions" in tool_lookup:
            return _TransitionDecision(
                tool_call=self._build_tool_call(tool_name="get_vehicle_window_positions", arguments={}),
                transition_rules=["air_conditioning_requires_window_read"],
            )

        for window_name in self._WINDOW_PRIORITY:
            position = window_positions.get(window_name)
            if (
                isinstance(position, (int, float))
                and position > self._WINDOW_AC_THRESHOLD
                and "open_close_window" in tool_lookup
            ):
                return _TransitionDecision(
                    tool_call=self._build_tool_call(
                        tool_name="open_close_window",
                        arguments={"window": window_name, "percentage": 0},
                    ),
                    transition_rules=["air_conditioning_requires_window_closure"],
                )

        fan_speed = climate_settings.get("fan_speed")
        if fan_speed == 0 and "set_fan_speed" in tool_lookup:
            return _TransitionDecision(
                tool_call=self._build_tool_call(
                    tool_name="set_fan_speed",
                    arguments={"level": 1},
                ),
                transition_rules=["air_conditioning_requires_nonzero_fan"],
            )

        return _TransitionDecision(
            tool_call=self._build_tool_call(
                tool_name="set_air_conditioning",
                arguments=arguments,
            )
        )

    def _validate_navigation_route_selection(
        self,
        *,
        tool_name: str,
        arguments: dict[str, Any],
        state: SessionState,
    ) -> ValidationResult | None:
        if tool_name != "navigation_replace_final_destination":
            return None

        navigation_state = state.domain_snapshots.get("navigation_state")
        route_catalog = state.domain_snapshots.get("route_catalog", {})
        if not isinstance(navigation_state, dict) or not navigation_state.get("navigation_active"):
            return None
        if not isinstance(route_catalog, dict):
            return None

        route_id = arguments.get("route_id_leading_to_new_destination")
        route_metadata = route_catalog.get(route_id)
        if not isinstance(route_metadata, dict):
            return None

        sibling_routes = [
            route
            for route in route_catalog.values()
            if isinstance(route, dict)
            and route.get("start_id") == route_metadata.get("start_id")
            and route.get("destination_id") == route_metadata.get("destination_id")
        ]
        if len(sibling_routes) < 2:
            return None
        if self._goal_explicitly_selects_route(state.active_goal, route_metadata):
            return None

        return ValidationResult(
            status="blocked_needs_clarification",
            blocked_reason="Multiple route options are available and no explicit route choice is recorded yet.",
            user_message_hint=self._build_route_choice_hint(sibling_routes),
            metadata={
                "transition_rule": "navigation_requires_explicit_route_choice",
                "candidate_route_id": route_id,
            },
        )

    def _goal_explicitly_selects_route(
        self,
        goal_text: str | None,
        route_metadata: dict[str, Any],
    ) -> bool:
        if not goal_text:
            return False
        lowered_goal = goal_text.lower()
        aliases = [str(alias).lower() for alias in route_metadata.get("alias", [])]
        for alias in aliases:
            if alias in lowered_goal:
                return True
            if alias == "first" and ("route 1" in lowered_goal or "first route" in lowered_goal):
                return True
            if alias == "second" and ("route 2" in lowered_goal or "second route" in lowered_goal):
                return True
            if alias == "third" and ("route 3" in lowered_goal or "third route" in lowered_goal):
                return True
        name_via = route_metadata.get("name_via")
        if isinstance(name_via, str) and name_via.lower() in lowered_goal:
            return True
        return False

    def _build_route_choice_hint(self, sibling_routes: list[dict[str, Any]]) -> str:
        choice_labels: list[str] = []
        for route in sibling_routes:
            aliases = [str(alias).lower() for alias in route.get("alias", [])]
            if "fastest" in aliases:
                choice_labels.append("the fastest route")
            elif "shortest" in aliases:
                choice_labels.append("the shortest route")
            elif "second" in aliases:
                choice_labels.append("the second route")
            elif "third" in aliases:
                choice_labels.append("the third route")

        if not choice_labels:
            return "I found multiple route options. Which route would you like me to use?"

        rendered_choices = ", ".join(dict.fromkeys(choice_labels[:-1]))
        last_choice = choice_labels[-1]
        if rendered_choices:
            return f"I found multiple route options. Which route would you like me to use: {rendered_choices}, or {last_choice}?"
        return f"I found multiple route options. Which route would you like me to use: {last_choice}?"

    def _build_tool_call(self, *, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": f"transition_{tool_name}",
            "type": "function",
            "function": {
                "name": tool_name,
                "arguments": json.dumps(arguments, ensure_ascii=True, sort_keys=True),
            },
        }
