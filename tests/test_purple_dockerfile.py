import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DOCKERFILE = ROOT / "src" / "purple_car_bench_agent" / "Dockerfile.car-bench-agent"


class PurpleDockerfileTests(unittest.TestCase):
    def test_runtime_files_are_copied_with_agentbeats_ownership(self) -> None:
        content = DOCKERFILE.read_text()
        self.assertIn(
            "COPY --chown=agentbeats:agentbeats pyproject.toml uv.lock README.md ./",
            content,
        )
        self.assertIn(
            "COPY --chown=agentbeats:agentbeats src src",
            content,
        )


if __name__ == "__main__":
    unittest.main()
