"""Environment-specific policy profile for CAR-bench."""

from __future__ import annotations

from purple_core.policy_linter import PolicyProfile


CAR_POLICY_PROFILE = PolicyProfile(
    name="car_bench",
    response_constraints={"time_format": "24h"},
    confirmation_required_tools={
        "send_email": "send this email",
    },
)
