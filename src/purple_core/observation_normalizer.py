"""Observation normalization into a shared frame."""

from __future__ import annotations

import json
from typing import Any

from purple_core.models import ObservationFrame


class ObservationNormalizer:
    """Translate environment-specific inputs into a shared observation model."""

    _WINDOW_RESULT_FIELDS = {
        "window_driver_position": "DRIVER",
        "window_passenger_position": "PASSENGER",
        "window_driver_rear_position": "DRIVER_REAR",
        "window_passenger_rear_position": "PASSENGER_REAR",
    }

    _CLIMATE_RESULT_FIELDS = (
        "fan_speed",
        "fan_airflow_direction",
        "air_conditioning",
        "air_circulation",
        "window_front_defrost",
        "window_rear_defrost",
    )

    def from_car(
        self,
        *,
        user_text: str | None,
        tools: list[dict[str, Any]] | None,
        tool_results: list[dict[str, Any]] | None,
        system_prompt: str | None,
    ) -> ObservationFrame:
        affordances = []
        for tool in tools or []:
            function = tool.get("function", {})
            affordances.append(
                {
                    "kind": "tool",
                    "name": function.get("name", ""),
                    "description": function.get("description", ""),
                }
            )

        feedback: list[dict[str, Any]] = []
        error_signals: list[dict[str, Any]] = []
        facts_delta: dict[str, Any] = {}
        for result in tool_results or []:
            normalized_result = {
                "kind": "tool_result",
                "tool_name": result.get("tool_name", ""),
                "content": result.get("content", ""),
                "tool_call_id": result.get("tool_call_id", ""),
            }
            feedback.append(normalized_result)
            error_signals.extend(self._extract_car_error_signals(normalized_result))
            self._merge_car_facts(facts_delta, normalized_result)

        if feedback:
            facts_delta["tool_results"] = feedback

        constraints = {"environment": "car_bench"}
        if system_prompt:
            constraints["system_prompt"] = system_prompt

        return ObservationFrame(
            environment="car_bench",
            goal_text=user_text or "",
            available_affordances=affordances,
            feedback=feedback,
            facts_delta=facts_delta,
            error_signals=error_signals,
            constraints=constraints,
            raw_user_text=user_text,
            metadata={"num_tools": len(tools or []), "num_tool_results": len(tool_results or [])},
        )

    def _merge_car_facts(self, facts_delta: dict[str, Any], normalized_result: dict[str, Any]) -> None:
        tool_name = normalized_result.get("tool_name", "")
        parsed_content = self._parse_tool_result_content(normalized_result.get("content", ""))
        if not isinstance(parsed_content, dict) or parsed_content.get("status") != "SUCCESS":
            return

        result_payload = parsed_content.get("result")
        if not isinstance(result_payload, dict):
            return

        if tool_name == "get_current_navigation_state":
            waypoints = result_payload.get("waypoints_id") or []
            if isinstance(waypoints, list):
                facts_delta["navigation_state"] = {
                    "navigation_active": bool(result_payload.get("navigation_active")),
                    "waypoints_id": list(waypoints),
                    "routes_to_final_destination_id": list(result_payload.get("routes_to_final_destination_id") or []),
                    "current_destination_id": waypoints[-1] if waypoints else None,
                    "tail_waypoint_id": waypoints[-2] if len(waypoints) >= 2 else None,
                }
            return

        if tool_name == "get_routes_from_start_to_destination":
            routes = result_payload.get("routes")
            if not isinstance(routes, list):
                return
            route_catalog = facts_delta.setdefault("route_catalog", {})
            if not isinstance(route_catalog, dict):
                return
            for route in routes:
                if not isinstance(route, dict):
                    continue
                route_id = route.get("route_id")
                if not route_id:
                    continue
                route_catalog[route_id] = {
                    "route_id": route_id,
                    "start_id": route.get("start_id"),
                    "destination_id": route.get("destination_id"),
                    "name_via": route.get("name_via"),
                    "distance_km": route.get("distance_km"),
                    "duration_hours": route.get("duration_hours"),
                    "duration_minutes": route.get("duration_minutes"),
                    "alias": list(route.get("alias") or []),
                }
            return

        if tool_name == "get_vehicle_window_positions":
            window_positions = self._extract_window_positions(result_payload)
            if window_positions:
                facts_delta["window_positions"] = window_positions
            return

        if tool_name == "open_close_window":
            window_name = result_payload.get("window")
            percentage = result_payload.get("percentage")
            if isinstance(window_name, str) and isinstance(percentage, (int, float)):
                facts_delta["window_positions"] = {window_name: percentage}
            return

        if tool_name == "get_climate_settings":
            climate_settings = self._extract_climate_settings(result_payload)
            if climate_settings:
                facts_delta["climate_settings"] = climate_settings
            return

        if tool_name == "set_fan_speed":
            level = result_payload.get("level")
            if isinstance(level, (int, float)):
                facts_delta["climate_settings"] = {"fan_speed": level}
            return

        if tool_name == "set_air_conditioning":
            on = result_payload.get("on")
            if isinstance(on, bool):
                facts_delta["climate_settings"] = {"air_conditioning": on}

    def _extract_car_error_signals(self, normalized_result: dict[str, Any]) -> list[dict[str, Any]]:
        tool_name = normalized_result.get("tool_name", "")
        raw_content = normalized_result.get("content", "")
        lowered_content = raw_content.lower()
        parsed_content = self._parse_tool_result_content(raw_content)
        signals: list[dict[str, Any]] = []

        if "removed" in lowered_content and "can not be used" in lowered_content:
            signals.append(
                {
                    "type": "removed_parameter",
                    "tool_name": tool_name,
                    "blocked_tools": [tool_name],
                    "reason": f"Tool '{tool_name}' reported a removed parameter and should not be retried.",
                    "user_message_hint": (
                        "I can't complete that action because the required control is currently unavailable "
                        "from the car system."
                    ),
                    "acknowledge_limits": True,
                    "hard_stop": True,
                }
            )

        if not isinstance(parsed_content, dict):
            return signals

        status = parsed_content.get("status")
        result_payload = parsed_content.get("result")
        if status == "FAILURE":
            signals.append(
                {
                    "type": "tool_failure",
                    "tool_name": tool_name,
                    "blocked_tools": [tool_name],
                    "reason": f"Tool '{tool_name}' returned a failure response.",
                    "user_message_hint": self._failure_hint_for_tool(tool_name),
                    "acknowledge_limits": True,
                    "hard_stop": False,
                }
            )

        if not isinstance(result_payload, dict):
            return signals

        unknown_paths = self._find_unknown_paths(result_payload)
        if unknown_paths:
            signal = self._unknown_signal_for_tool(tool_name, unknown_paths)
            if signal is not None:
                signals.append(signal)
        return signals

    def _parse_tool_result_content(self, raw_content: str) -> dict[str, Any] | None:
        try:
            parsed = json.loads(raw_content)
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        if isinstance(parsed, dict):
            return parsed
        return None

    def _find_unknown_paths(self, value: Any, *, path: str = "") -> list[str]:
        unknown_paths: list[str] = []
        if isinstance(value, dict):
            for key, item in value.items():
                next_path = f"{path}.{key}" if path else key
                unknown_paths.extend(self._find_unknown_paths(item, path=next_path))
            return unknown_paths
        if isinstance(value, list):
            for index, item in enumerate(value):
                next_path = f"{path}[{index}]"
                unknown_paths.extend(self._find_unknown_paths(item, path=next_path))
            return unknown_paths
        if isinstance(value, str) and value.strip().lower() == "unknown":
            unknown_paths.append(path or "value")
        return unknown_paths

    def _unknown_signal_for_tool(
        self,
        tool_name: str,
        unknown_paths: list[str],
    ) -> dict[str, Any] | None:
        if tool_name == "get_vehicle_window_positions":
            return {
                "type": "unknown_value",
                "tool_name": tool_name,
                "blocked_tools": ["open_close_window"],
                "blocked_domains": ["window_position_grounding"],
                "reason": "Rear-window positions are unknown, so follow-up adjustments cannot be grounded safely.",
                "user_message_hint": (
                    "I can't safely match the rear windows because the car system response is missing the "
                    "rear window positions and only reports them as unknown."
                ),
                "acknowledge_limits": True,
                "hard_stop": False,
                "unknown_paths": unknown_paths,
            }

        if tool_name == "get_charging_specs_and_status":
            return {
                "type": "unknown_value",
                "tool_name": tool_name,
                "blocked_tools": [
                    "get_charging_specs_and_status",
                    "get_distance_by_soc",
                    "calculate_charging_time_by_soc",
                ],
                "blocked_domains": [
                    "battery_status_lookup",
                    "charging_estimation",
                    "trip_charging_planning",
                ],
                "reason": "Key battery fields are unknown, so downstream charging estimates are not grounded.",
                "user_message_hint": (
                    "I already checked the car system, but it is returning key battery data as unknown. "
                    "I can report the available chargers and remaining range, but I can't safely estimate "
                    "charging time or charging stops from that data."
                ),
                "acknowledge_limits": True,
                "hard_stop": False,
                "unknown_paths": unknown_paths,
            }

        if tool_name == "search_poi_along_the_route":
            return {
                "type": "unknown_value",
                "tool_name": tool_name,
                "blocked_tools": ["search_poi_along_the_route"],
                "blocked_domains": ["route_charging_station_lookup"],
                "reason": "Along-route POI search returned unknown results.",
                "user_message_hint": (
                    "I couldn't reliably retrieve charging stations along the route from the current system response, "
                    "so I shouldn't guess a stop."
                ),
                "acknowledge_limits": True,
                "hard_stop": False,
                "unknown_paths": unknown_paths,
            }

        return None

    def _extract_window_positions(self, result_payload: dict[str, Any]) -> dict[str, int | float]:
        positions: dict[str, int | float] = {}
        for result_field, window_name in self._WINDOW_RESULT_FIELDS.items():
            value = result_payload.get(result_field)
            if isinstance(value, (int, float)):
                positions[window_name] = value
        return positions

    def _extract_climate_settings(self, result_payload: dict[str, Any]) -> dict[str, Any]:
        settings: dict[str, Any] = {}
        for field_name in self._CLIMATE_RESULT_FIELDS:
            if field_name in result_payload:
                settings[field_name] = result_payload[field_name]
        return settings

    def _failure_hint_for_tool(self, tool_name: str) -> str:
        if tool_name == "get_distance_by_soc":
            return (
                "I can't safely estimate charging time or charging stops from the current car data because the "
                "battery inputs needed for that calculation are unavailable or inconsistent."
            )
        return "I can't safely continue that calculation from the current system response."
