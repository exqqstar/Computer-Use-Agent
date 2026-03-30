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


class NavigationStateMachineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.normalizer = ObservationNormalizer()
        self.state_store = SessionStateStore()
        self.validator = BasicValidator()
        self.plan = PlanProposal(
            objective="handle navigation edits",
            current_step_type="act",
            reason="test",
        )

    def test_rewrites_incompatible_replace_final_destination_to_route_read(self) -> None:
        state = self.state_store.get_or_create("nav-replace-read")
        self.state_store.merge_observation(
            state,
            self.normalizer.from_car(
                user_text="Instead of going to Dusseldorf, I want to go to Dresden.",
                tools=[_tool_schema("get_current_navigation_state", ["detailed_information"])],
                tool_results=[
                    {
                        "tool_name": "get_current_navigation_state",
                        "content": json.dumps(
                            {
                                "status": "SUCCESS",
                                "result": {
                                    "navigation_active": True,
                                    "waypoints_id": ["loc_dor_399984", "loc_düs_892560"],
                                    "routes_to_final_destination_id": ["rll_dor_düs_836702"],
                                },
                            }
                        ),
                    }
                ],
                system_prompt=None,
            ),
        )
        self.state_store.merge_observation(
            state,
            self.normalizer.from_car(
                user_text=None,
                tools=[_tool_schema("get_routes_from_start_to_destination", ["start_id", "destination_id"])],
                tool_results=[
                    {
                        "tool_name": "get_routes_from_start_to_destination",
                        "content": json.dumps(
                            {
                                "status": "SUCCESS",
                                "result": {
                                    "routes": [
                                        {
                                            "route_id": "rll_düs_dre_717882",
                                            "start_id": "loc_düs_892560",
                                            "destination_id": "loc_dre_279657",
                                            "alias": ["fastest", "first"],
                                        }
                                    ]
                                },
                            }
                        ),
                    }
                ],
                system_prompt=None,
            ),
        )

        result = self.validator.validate_llm_response(
            assistant_content={
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_replace_final",
                        "type": "function",
                        "function": {
                            "name": "navigation_replace_final_destination",
                            "arguments": json.dumps(
                                {
                                    "new_destination_id": "loc_dre_279657",
                                    "route_id_leading_to_new_destination": "rll_düs_dre_717882",
                                }
                            ),
                        },
                    }
                ],
            },
            available_tools=[
                _tool_schema(
                    "navigation_replace_final_destination",
                    ["new_destination_id", "route_id_leading_to_new_destination"],
                ),
                _tool_schema("get_routes_from_start_to_destination", ["start_id", "destination_id"]),
            ],
            plan=self.plan,
            state=state,
        )

        self.assertEqual(result.status, "approved")
        self.assertEqual(len(result.approved_tool_calls), 1)
        rewritten_call = result.approved_tool_calls[0]
        self.assertEqual(rewritten_call["function"]["name"], "get_routes_from_start_to_destination")
        self.assertEqual(
            json.loads(rewritten_call["function"]["arguments"]),
            {"destination_id": "loc_dre_279657", "start_id": "loc_dor_399984"},
        )
        self.assertEqual(
            result.metadata.get("transition_rules"),
            ["navigation_replace_requires_route_from_previous_waypoint"],
        )

    def test_rewrites_set_new_navigation_to_replace_when_navigation_is_active(self) -> None:
        state = self.state_store.get_or_create("nav-switch-route")
        self.state_store.merge_observation(
            state,
            self.normalizer.from_car(
                user_text="Switch to route 2 for Dresden.",
                tools=[_tool_schema("get_current_navigation_state", ["detailed_information"])],
                tool_results=[
                    {
                        "tool_name": "get_current_navigation_state",
                        "content": json.dumps(
                            {
                                "status": "SUCCESS",
                                "result": {
                                    "navigation_active": True,
                                    "waypoints_id": ["loc_dor_399984", "loc_dre_279657"],
                                    "routes_to_final_destination_id": ["rll_dor_dre_747767"],
                                },
                            }
                        ),
                    }
                ],
                system_prompt=None,
            ),
        )
        self.state_store.merge_observation(
            state,
            self.normalizer.from_car(
                user_text=None,
                tools=[_tool_schema("get_routes_from_start_to_destination", ["start_id", "destination_id"])],
                tool_results=[
                    {
                        "tool_name": "get_routes_from_start_to_destination",
                        "content": json.dumps(
                            {
                                "status": "SUCCESS",
                                "result": {
                                    "routes": [
                                        {
                                            "route_id": "rll_dor_dre_747767",
                                            "start_id": "loc_dor_399984",
                                            "destination_id": "loc_dre_279657",
                                            "alias": ["fastest", "first"],
                                        },
                                        {
                                            "route_id": "rll_dor_dre_852230",
                                            "start_id": "loc_dor_399984",
                                            "destination_id": "loc_dre_279657",
                                            "alias": ["second"],
                                        },
                                    ]
                                },
                            }
                        ),
                    }
                ],
                system_prompt=None,
            ),
        )

        result = self.validator.validate_llm_response(
            assistant_content={
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_switch_route",
                        "type": "function",
                        "function": {
                            "name": "set_new_navigation",
                            "arguments": json.dumps({"route_ids": ["rll_dor_dre_852230"]}),
                        },
                    }
                ],
            },
            available_tools=[
                _tool_schema("set_new_navigation", ["route_ids"]),
                _tool_schema(
                    "navigation_replace_final_destination",
                    ["new_destination_id", "route_id_leading_to_new_destination"],
                ),
            ],
            plan=self.plan,
            state=state,
        )

        self.assertEqual(result.status, "approved")
        self.assertEqual(len(result.approved_tool_calls), 1)
        rewritten_call = result.approved_tool_calls[0]
        self.assertEqual(rewritten_call["function"]["name"], "navigation_replace_final_destination")
        self.assertEqual(
            json.loads(rewritten_call["function"]["arguments"]),
            {
                "new_destination_id": "loc_dre_279657",
                "route_id_leading_to_new_destination": "rll_dor_dre_852230",
            },
        )
        self.assertEqual(
            result.metadata.get("transition_rules"),
            ["active_navigation_route_switch_uses_replace_final_destination"],
        )

    def test_blocks_premature_route_commit_without_user_selection(self) -> None:
        state = self.state_store.get_or_create("nav-needs-route-choice")
        self.state_store.merge_observation(
            state,
            self.normalizer.from_car(
                user_text="Change my navigation destination from Dusseldorf to Dresden.",
                tools=[_tool_schema("get_current_navigation_state", ["detailed_information"])],
                tool_results=[
                    {
                        "tool_name": "get_current_navigation_state",
                        "content": json.dumps(
                            {
                                "status": "SUCCESS",
                                "result": {
                                    "navigation_active": True,
                                    "waypoints_id": ["loc_dor_399984", "loc_düs_892560"],
                                    "routes_to_final_destination_id": ["rll_dor_düs_836702"],
                                },
                            }
                        ),
                    }
                ],
                system_prompt=None,
            ),
        )
        self.state_store.merge_observation(
            state,
            self.normalizer.from_car(
                user_text=None,
                tools=[_tool_schema("get_routes_from_start_to_destination", ["start_id", "destination_id"])],
                tool_results=[
                    {
                        "tool_name": "get_routes_from_start_to_destination",
                        "content": json.dumps(
                            {
                                "status": "SUCCESS",
                                "result": {
                                    "routes": [
                                        {
                                            "route_id": "rll_dor_dre_747767",
                                            "start_id": "loc_dor_399984",
                                            "destination_id": "loc_dre_279657",
                                            "name_via": "L186, L858, L872",
                                            "distance_km": 505.3,
                                            "duration_hours": 6,
                                            "duration_minutes": 27,
                                            "alias": ["fastest", "first", "shortest"],
                                        },
                                        {
                                            "route_id": "rll_dor_dre_852230",
                                            "start_id": "loc_dor_399984",
                                            "destination_id": "loc_dre_279657",
                                            "name_via": "B350, B497, B843",
                                            "distance_km": 526.08,
                                            "duration_hours": 6,
                                            "duration_minutes": 35,
                                            "alias": ["second"],
                                        },
                                    ]
                                },
                            }
                        ),
                    }
                ],
                system_prompt=None,
            ),
        )

        result = self.validator.validate_llm_response(
            assistant_content={
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_pick_fastest_too_early",
                        "type": "function",
                        "function": {
                            "name": "navigation_replace_final_destination",
                            "arguments": json.dumps(
                                {
                                    "new_destination_id": "loc_dre_279657",
                                    "route_id_leading_to_new_destination": "rll_dor_dre_747767",
                                }
                            ),
                        },
                    }
                ],
            },
            available_tools=[
                _tool_schema(
                    "navigation_replace_final_destination",
                    ["new_destination_id", "route_id_leading_to_new_destination"],
                )
            ],
            plan=self.plan,
            state=state,
        )

        self.assertEqual(result.status, "blocked_needs_clarification")
        self.assertIn("multiple route options", result.blocked_reason.lower())
        self.assertIn("which route", (result.user_message_hint or "").lower())


if __name__ == "__main__":
    unittest.main()
