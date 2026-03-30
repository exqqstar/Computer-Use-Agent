import re
import unittest
from pathlib import Path


LIVE_SECRET_PATTERNS = (
    re.compile(r"AIza[0-9A-Za-z\-_]{20,}"),
    re.compile(r"sk-[A-Za-z0-9_\-]{20,}"),
)


class SecretHygieneTests(unittest.TestCase):
    def test_tracked_env_templates_do_not_contain_live_credentials(self) -> None:
        repo_root = Path(__file__).resolve().parent.parent

        for relative_path in (".env.example", "sample.env"):
            file_path = repo_root / relative_path
            if not file_path.exists():
                continue

            contents = file_path.read_text()
            for pattern in LIVE_SECRET_PATTERNS:
                self.assertIsNone(
                    pattern.search(contents),
                    f"{relative_path} contains a live credential matching {pattern.pattern}",
                )


if __name__ == "__main__":
    unittest.main()
