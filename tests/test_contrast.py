"""Exercise the public CLI with realistic CSS regressions."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = (ROOT / "example-site/style.css").read_text()


class ContrastGateTests(unittest.TestCase):
    def check_css(self, css, expected, message):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "style.css"
            path.write_text(css)
            result = subprocess.run([sys.executable, str(ROOT / "check-contrast.py"), str(path)], capture_output=True, text=True)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        self.assertIn(message, result.stdout)

    def test_fixture_passes(self):
        self.check_css(FIXTURE, 0, "all contrast pairs clear")

    def test_low_contrast_body_fails(self):
        self.check_css(FIXTURE + "\np { color: var(--ss-cream); }", 1, "need >= 4.5")

    def test_unknown_foreground_fails(self):
        self.check_css(FIXTURE + "\np { color: var(--ss-typo); }", 1, "unregistered foreground")

    def test_unknown_background_fails(self):
        self.check_css(FIXTURE + "\np { color: var(--ss-ink); background: var(--ss-typo); }", 1, "unresolvable background")

    def test_unreviewed_brass_body_fails(self):
        self.check_css(FIXTURE + "\np { color: var(--ss-brass); background: #000000; }", 1, "brass used as a text colour")

    def test_stale_exemption_fails(self):
        self.check_css(FIXTURE.replace(".wordmark .amp", ".removed-logo"), 1, "stale allowlist")

    def test_dark_rail_surface_is_used(self):
        self.check_css(FIXTURE.replace(".nav a { color: var(--ss-cream)", ".nav a { color: var(--ss-ink)"), 1, "green rail (surface map)")
