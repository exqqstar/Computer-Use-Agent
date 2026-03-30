"""Session state storage and merge helpers."""

from __future__ import annotations

from purple_core.models import ObservationFrame, PlanProposal, RecoveryDecision, SessionState, ValidationResult


class SessionStateStore:
    """Owns per-context structured state."""

    def __init__(self) -> None:
        self._states: dict[str, SessionState] = {}

    def get_or_create(self, context_id: str) -> SessionState:
        if context_id not in self._states:
            self._states[context_id] = SessionState()
        return self._states[context_id]

    def reset(self, context_id: str) -> None:
        self._states.pop(context_id, None)

    def merge_observation(self, state: SessionState, observation: ObservationFrame) -> None:
        state.last_observation = observation
        if observation.goal_text:
            state.active_goal = observation.goal_text
        if observation.facts_delta:
            state.observed_facts.update(observation.facts_delta)
            navigation_state = observation.facts_delta.get("navigation_state")
            if isinstance(navigation_state, dict):
                state.domain_snapshots["navigation_state"] = navigation_state

            route_catalog = observation.facts_delta.get("route_catalog")
            if isinstance(route_catalog, dict):
                existing_catalog = state.domain_snapshots.setdefault("route_catalog", {})
                existing_catalog.update(route_catalog)

            window_positions = observation.facts_delta.get("window_positions")
            if isinstance(window_positions, dict):
                existing_positions = state.domain_snapshots.setdefault("window_positions", {})
                all_percentage = window_positions.get("ALL")
                if isinstance(all_percentage, (int, float)):
                    target_windows = existing_positions.keys() or {
                        "DRIVER",
                        "PASSENGER",
                        "DRIVER_REAR",
                        "PASSENGER_REAR",
                    }
                    for window_name in list(target_windows):
                        existing_positions[window_name] = all_percentage
                for window_name, percentage in window_positions.items():
                    if window_name == "ALL":
                        continue
                    existing_positions[window_name] = percentage
                state.observed_facts["window_positions"] = dict(existing_positions)

            climate_settings = observation.facts_delta.get("climate_settings")
            if isinstance(climate_settings, dict):
                existing_climate = state.domain_snapshots.setdefault("climate_settings", {})
                existing_climate.update(climate_settings)
                state.observed_facts["climate_settings"] = dict(existing_climate)
        if observation.error_signals:
            blocked_tools = state.boundary_flags.setdefault("blocked_tools", {})
            blocked_domains = state.boundary_flags.setdefault("blocked_domains", {})
            limit_hints = state.boundary_flags.setdefault("limit_hints", [])
            for signal in observation.error_signals:
                for tool_name in signal.get("blocked_tools", []):
                    blocked_tools[tool_name] = signal
                for domain_name in signal.get("blocked_domains", []):
                    blocked_domains[domain_name] = signal
                if signal.get("acknowledge_limits") and signal.get("user_message_hint"):
                    hint = signal["user_message_hint"]
                    if hint not in limit_hints:
                        limit_hints.append(hint)
        if observation.raw_user_text:
            state.unknowns.discard("missing_user_goal")
        if observation.available_affordances:
            # Keep the raw schemas in available_affordances elsewhere; this tracks
            # only that the environment currently exposes affordances.
            state.inferred_facts["last_affordance_count"] = len(observation.available_affordances)

    def set_available_affordances(self, state: SessionState, affordances: list[dict]) -> None:
        if affordances:
            state.available_affordances = affordances

    def record_plan(self, state: SessionState, plan: PlanProposal) -> None:
        state.last_plan = plan

    def record_result(self, state: SessionState, result: ValidationResult | RecoveryDecision) -> None:
        state.last_result = result
