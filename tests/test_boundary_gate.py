import json
import unittest

from purple_core.models import PlanProposal
from purple_core.observation_normalizer import ObservationNormalizer
from purple_core.session_state import SessionStateStore
from purple_core.validator import BasicValidator


def _tool_schema(name: str, required: list[str] | None = None) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "parameters": {
                "type": "object",
                "properties": {},
                "required": required or [],
            },
        },
    }


class BoundaryGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.normalizer = ObservationNormalizer()
        self.state_store = SessionStateStore()
        self.validator = BasicValidator()
        self.plan = PlanProposal(
            objective="handle the current turn",
            current_step_type="act",
            reason="test",
        )

    def test_blocks_retrying_battery_status_lookup_after_unknown_vehicle_data(self) -> None:
        state = self.state_store.get_or_create("battery-boundary")
        observation = self.normalizer.from_car(
            user_text="Check my battery status and calculate how long I need to charge.",
            tools=[_tool_schema("get_charging_specs_and_status")],
            tool_results=[
                {
                    "tool_name": "get_charging_specs_and_status",
                    "content": json.dumps(
                        {
                            "status": "SUCCESS",
                            "result": {
                                "battery_capacity_kwh": "unknown",
                                "state_of_charge": "unknown",
                                "remaining_range": "68.0km",
                            },
                        }
                    ),
                }
            ],
            system_prompt=None,
        )
        self.state_store.merge_observation(state, observation)

        result = self.validator.validate_llm_response(
            assistant_content={
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_retry_battery",
                        "type": "function",
                        "function": {
                            "name": "get_charging_specs_and_status",
                            "arguments": "{}",
                        },
                    }
                ],
            },
            available_tools=[_tool_schema("get_charging_specs_and_status")],
            plan=self.plan,
            state=state,
        )

        self.assertEqual(result.status, "blocked_boundary")
        self.assertEqual(result.metadata.get("blocked_tool"), "get_charging_specs_and_status")

    def test_rewrites_air_conditioning_to_read_climate_state_before_commit(self) -> None:
        state = self.state_store.get_or_create("ac-needs-climate-read")

        result = self.validator.validate_llm_response(
            assistant_content={
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_turn_ac_on",
                        "type": "function",
                        "function": {
                            "name": "set_air_conditioning",
                            "arguments": json.dumps({"on": True}),
                        },
                    }
                ],
            },
            available_tools=[
                _tool_schema("set_air_conditioning", ["on"]),
                _tool_schema("get_climate_settings"),
                _tool_schema("get_vehicle_window_positions"),
            ],
            plan=self.plan,
            state=state,
        )

        self.assertEqual(result.status, "approved")
        rewritten_call = result.approved_tool_calls[0]
        self.assertEqual(rewritten_call["function"]["name"], "get_climate_settings")
        self.assertEqual(
            result.metadata.get("transition_rules"),
            ["air_conditioning_requires_climate_read"],
        )

    def test_rewrites_air_conditioning_to_close_open_windows_before_commit(self) -> None:
        state = self.state_store.get_or_create("ac-close-window-first")
        climate_observation = self.normalizer.from_car(
            user_text="Turn on the air conditioning.",
            tools=[_tool_schema("get_climate_settings")],
            tool_results=[
                {
                    "tool_name": "get_climate_settings",
                    "content": json.dumps(
                        {
                            "status": "SUCCESS",
                            "result": {
                                "fan_speed": 1,
                                "air_conditioning": False,
                                "air_circulation": "FRESH_AIR",
                            },
                        }
                    ),
                }
            ],
            system_prompt=None,
        )
        self.state_store.merge_observation(state, climate_observation)
        window_observation = self.normalizer.from_car(
            user_text=None,
            tools=[_tool_schema("get_vehicle_window_positions")],
            tool_results=[
                {
                    "tool_name": "get_vehicle_window_positions",
                    "content": json.dumps(
                        {
                            "status": "SUCCESS",
                            "result": {
                                "window_driver_position": 25,
                                "window_passenger_position": 10,
                                "window_driver_rear_position": 0,
                                "window_passenger_rear_position": 0,
                            },
                        }
                    ),
                }
            ],
            system_prompt=None,
        )
        self.state_store.merge_observation(state, window_observation)

        result = self.validator.validate_llm_response(
            assistant_content={
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_turn_ac_on",
                        "type": "function",
                        "function": {
                            "name": "set_air_conditioning",
                            "arguments": json.dumps({"on": True}),
                        },
                    }
                ],
            },
            available_tools=[
                _tool_schema("set_air_conditioning", ["on"]),
                _tool_schema("open_close_window", ["window", "percentage"]),
            ],
            plan=self.plan,
            state=state,
        )

        self.assertEqual(result.status, "approved")
        rewritten_call = result.approved_tool_calls[0]
        self.assertEqual(rewritten_call["function"]["name"], "open_close_window")
        self.assertEqual(
            json.loads(rewritten_call["function"]["arguments"]),
            {"percentage": 0, "window": "DRIVER"},
        )
        self.assertEqual(
            result.metadata.get("transition_rules"),
            ["air_conditioning_requires_window_closure"],
        )

    def test_rewrites_air_conditioning_to_raise_fan_after_windows_are_safe(self) -> None:
        state = self.state_store.get_or_create("ac-raise-fan")
        climate_observation = self.normalizer.from_car(
            user_text="Turn on the air conditioning.",
            tools=[_tool_schema("get_climate_settings")],
            tool_results=[
                {
                    "tool_name": "get_climate_settings",
                    "content": json.dumps(
                        {
                            "status": "SUCCESS",
                            "result": {
                                "fan_speed": 0,
                                "air_conditioning": False,
                                "air_circulation": "FRESH_AIR",
                            },
                        }
                    ),
                }
            ],
            system_prompt=None,
        )
        self.state_store.merge_observation(state, climate_observation)
        window_observation = self.normalizer.from_car(
            user_text=None,
            tools=[_tool_schema("get_vehicle_window_positions")],
            tool_results=[
                {
                    "tool_name": "get_vehicle_window_positions",
                    "content": json.dumps(
                        {
                            "status": "SUCCESS",
                            "result": {
                                "window_driver_position": 0,
                                "window_passenger_position": 10,
                                "window_driver_rear_position": 0,
                                "window_passenger_rear_position": 20,
                            },
                        }
                    ),
                }
            ],
            system_prompt=None,
        )
        self.state_store.merge_observation(state, window_observation)

        result = self.validator.validate_llm_response(
            assistant_content={
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_turn_ac_on",
                        "type": "function",
                        "function": {
                            "name": "set_air_conditioning",
                            "arguments": json.dumps({"on": True}),
                        },
                    }
                ],
            },
            available_tools=[
                _tool_schema("set_air_conditioning", ["on"]),
                _tool_schema("set_fan_speed", ["level"]),
            ],
            plan=self.plan,
            state=state,
        )

        self.assertEqual(result.status, "approved")
        rewritten_call = result.approved_tool_calls[0]
        self.assertEqual(rewritten_call["function"]["name"], "set_fan_speed")
        self.assertEqual(
            json.loads(rewritten_call["function"]["arguments"]),
            {"level": 1},
        )
        self.assertEqual(
            result.metadata.get("transition_rules"),
            ["air_conditioning_requires_nonzero_fan"],
        )

    def test_window_unknown_signal_explicitly_mentions_missing_response(self) -> None:
        observation = self.normalizer.from_car(
            user_text="Match the rear windows to the front windows.",
            tools=[_tool_schema("get_vehicle_window_positions")],
            tool_results=[
                {
                    "tool_name": "get_vehicle_window_positions",
                    "content": json.dumps(
                        {
                            "status": "SUCCESS",
                            "result": {
                                "window_driver_position": 25,
                                "window_passenger_position": 25,
                                "window_driver_rear_position": "unknown",
                                "window_passenger_rear_position": "unknown",
                            },
                        }
                    ),
                }
            ],
            system_prompt=None,
        )

        self.assertTrue(observation.error_signals)
        self.assertIn("missing", observation.error_signals[0]["user_message_hint"].lower())

    def test_blocks_alternative_route_station_search_after_along_route_results_are_unknown(self) -> None:
        state = self.state_store.get_or_create("route-poi-boundary")
        observation = self.normalizer.from_car(
            user_text="Find charging stations about 350 km along my route to Bonn.",
            tools=[
                _tool_schema("search_poi_along_the_route", ["route_id", "category_poi"]),
                _tool_schema("get_location_id_by_location_name", ["location"]),
            ],
            tool_results=[
                {
                    "tool_name": "search_poi_along_the_route",
                    "content": json.dumps(
                        {
                            "status": "SUCCESS",
                            "result": {"pois_found_along_route": "unknown"},
                        }
                    ),
                }
            ],
            system_prompt=None,
        )
        self.state_store.merge_observation(state, observation)

        result = self.validator.validate_llm_response(
            assistant_content={
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_alt_city",
                        "type": "function",
                        "function": {
                            "name": "get_location_id_by_location_name",
                            "arguments": json.dumps({"location": "Koblenz"}),
                        },
                    }
                ],
            },
            available_tools=[
                _tool_schema("search_poi_along_the_route", ["route_id", "category_poi"]),
                _tool_schema("get_location_id_by_location_name", ["location"]),
            ],
            plan=self.plan,
            state=state,
        )

        self.assertEqual(result.status, "blocked_boundary")
        self.assertEqual(result.metadata.get("signal_type"), "unknown_value")

    def test_blocks_trip_charging_planning_after_unknown_battery_data(self) -> None:
        state = self.state_store.get_or_create("trip-charging-boundary")
        battery_observation = self.normalizer.from_car(
            user_text="How long do I need to charge to reach 80 percent?",
            tools=[_tool_schema("get_charging_specs_and_status")],
            tool_results=[
                {
                    "tool_name": "get_charging_specs_and_status",
                    "content": json.dumps(
                        {
                            "status": "SUCCESS",
                            "result": {
                                "battery_capacity_kwh": "unknown",
                                "state_of_charge": "unknown",
                                "remaining_range": "68.0km",
                            },
                        }
                    ),
                }
            ],
            system_prompt=None,
        )
        self.state_store.merge_observation(state, battery_observation)

        trip_observation = self.normalizer.from_car(
            user_text=(
                "How many charging stops would I need to get to Madrid if I charge from "
                "10 percent to 80 percent each time?"
            ),
            tools=[
                _tool_schema("get_location_id_by_location_name", ["location"]),
                _tool_schema("get_routes_from_start_to_destination", ["destination_id"]),
            ],
            tool_results=[],
            system_prompt=None,
        )
        self.state_store.merge_observation(state, trip_observation)

        result = self.validator.validate_llm_response(
            assistant_content={
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_plan_trip",
                        "type": "function",
                        "function": {
                            "name": "get_location_id_by_location_name",
                            "arguments": json.dumps({"location": "Madrid"}),
                        },
                    }
                ],
            },
            available_tools=[
                _tool_schema("get_location_id_by_location_name", ["location"]),
                _tool_schema("get_routes_from_start_to_destination", ["destination_id"]),
            ],
            plan=self.plan,
            state=state,
        )

        self.assertEqual(result.status, "blocked_boundary")
        self.assertEqual(result.metadata.get("blocked_domain"), "trip_charging_planning")

    def test_blocks_text_that_offers_a_blocked_workaround_after_boundary_acknowledgement(self) -> None:
        state = self.state_store.get_or_create("window-boundary-text")
        observation = self.normalizer.from_car(
            user_text="Set both rear windows to match the front windows.",
            tools=[_tool_schema("get_vehicle_window_positions")],
            tool_results=[
                {
                    "tool_name": "get_vehicle_window_positions",
                    "content": json.dumps(
                        {
                            "status": "SUCCESS",
                            "result": {
                                "window_driver_position": 25,
                                "window_passenger_position": 25,
                                "window_driver_rear_position": "unknown",
                                "window_passenger_rear_position": "unknown",
                            },
                        }
                    ),
                }
            ],
            system_prompt=None,
        )
        self.state_store.merge_observation(state, observation)

        result = self.validator.validate_llm_response(
            assistant_content={
                "content": (
                    "The rear windows show as unknown in the system, so I can't set them to match the front. "
                    "Would you like me to try setting them to 25% anyway?"
                ),
                "tool_calls": [],
            },
            available_tools=[_tool_schema("get_vehicle_window_positions")],
            plan=self.plan,
            state=state,
        )

        self.assertEqual(result.status, "blocked_boundary")
        self.assertTrue(result.metadata.get("text_only"))

    def test_blocks_text_that_overstates_unknown_fields_as_missing_capability(self) -> None:
        state = self.state_store.get_or_create("window-boundary-overclaim")
        observation = self.normalizer.from_car(
            user_text="Adjust my rear windows to match the front windows.",
            tools=[_tool_schema("get_vehicle_window_positions")],
            tool_results=[
                {
                    "tool_name": "get_vehicle_window_positions",
                    "content": json.dumps(
                        {
                            "status": "SUCCESS",
                            "result": {
                                "window_driver_position": 25,
                                "window_passenger_position": 25,
                                "window_driver_rear_position": "unknown",
                                "window_passenger_rear_position": "unknown",
                            },
                        }
                    ),
                }
            ],
            system_prompt=None,
        )
        self.state_store.merge_observation(state, observation)

        result = self.validator.validate_llm_response(
            assistant_content={
                "content": (
                    "The rear windows are not equipped in this vehicle, so I can't adjust them."
                ),
                "tool_calls": [],
            },
            available_tools=[_tool_schema("get_vehicle_window_positions")],
            plan=self.plan,
            state=state,
        )

        self.assertEqual(result.status, "blocked_boundary")
        self.assertTrue(result.metadata.get("overstated_missing_field"))

    def test_allows_missing_field_acknowledgement_without_capability_overclaim(self) -> None:
        state = self.state_store.get_or_create("window-boundary-accurate")
        observation = self.normalizer.from_car(
            user_text="Adjust my rear windows to match the front windows.",
            tools=[_tool_schema("get_vehicle_window_positions")],
            tool_results=[
                {
                    "tool_name": "get_vehicle_window_positions",
                    "content": json.dumps(
                        {
                            "status": "SUCCESS",
                            "result": {
                                "window_driver_position": 25,
                                "window_passenger_position": 25,
                                "window_driver_rear_position": "unknown",
                                "window_passenger_rear_position": "unknown",
                            },
                        }
                    ),
                }
            ],
            system_prompt=None,
        )
        self.state_store.merge_observation(state, observation)

        result = self.validator.validate_llm_response(
            assistant_content={
                "content": (
                    "I can see the front windows are 25% open, but the current car-system response is "
                    "missing the rear window positions and only reports them as unknown, so I can't safely "
                    "match them yet."
                ),
                "tool_calls": [],
            },
            available_tools=[_tool_schema("get_vehicle_window_positions")],
            plan=self.plan,
            state=state,
        )

        self.assertEqual(result.status, "approved")

    def test_blocks_text_that_asks_user_for_missing_information_after_boundary(self) -> None:
        state = self.state_store.get_or_create("window-boundary-clarify")
        observation = self.normalizer.from_car(
            user_text="Adjust my rear windows to match the front windows.",
            tools=[_tool_schema("get_vehicle_window_positions")],
            tool_results=[
                {
                    "tool_name": "get_vehicle_window_positions",
                    "content": json.dumps(
                        {
                            "status": "SUCCESS",
                            "result": {
                                "window_driver_position": 25,
                                "window_passenger_position": 25,
                                "window_driver_rear_position": "unknown",
                                "window_passenger_rear_position": "unknown",
                            },
                        }
                    ),
                }
            ],
            system_prompt=None,
        )
        self.state_store.merge_observation(state, observation)

        result = self.validator.validate_llm_response(
            assistant_content={
                "content": (
                    "The rear window positions are showing as unknown, so I can't automatically match them to the front. "
                    "Could you let me know what percentage you'd like me to set the rear windows to?"
                ),
                "tool_calls": [],
            },
            available_tools=[_tool_schema("get_vehicle_window_positions")],
            plan=self.plan,
            state=state,
        )

        self.assertEqual(result.status, "blocked_boundary")
        self.assertTrue(result.metadata.get("text_only"))


if __name__ == "__main__":
    unittest.main()
