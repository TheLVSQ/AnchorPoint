"""Unit tests for the print agent's cut-after-label logic.

Standalone (no Django, no network): run with `python3 -m unittest` from the
agent/ directory. `requests` is stubbed so the module imports without the dep.
"""

import sys
import types
import unittest
from unittest import mock

# Stub `requests` before importing the agent (it imports requests at top level).
sys.modules.setdefault("requests", types.ModuleType("requests"))

import anchorpoint_agent as agent  # noqa: E402


def _fake_png(width=696, height=300):
    """Minimal bytes with a valid PNG signature + IHDR width/height."""
    return (
        b"\x89PNG\r\n\x1a\n"          # signature
        + b"\x00\x00\x00\x0dIHDR"      # IHDR chunk header (len + type)
        + width.to_bytes(4, "big")
        + height.to_bytes(4, "big")
    )


class PrintCutOptionTests(unittest.TestCase):
    def setUp(self):
        agent._cut_support_cache.clear()

    def _run_print(self, **kwargs):
        captured = {}

        def fake_run(cmd, *a, **kw):
            captured["cmd"] = cmd
            return mock.Mock(returncode=0, stdout="", stderr="")

        with mock.patch.object(agent.subprocess, "run", side_effect=fake_run):
            ok, err = agent._print_png(_fake_png(), "Brother_QL", **kwargs)
        self.assertTrue(ok, err)
        return captured["cmd"]

    def test_cut_added_when_printer_supports_it(self):
        with mock.patch.object(agent, "_printer_supports_cut", return_value=True):
            cmd = self._run_print()
        self.assertIn("CutMedia=EndOfPage", cmd)

    def test_cut_omitted_when_unsupported(self):
        with mock.patch.object(agent, "_printer_supports_cut", return_value=False):
            cmd = self._run_print()
        self.assertNotIn("CutMedia=EndOfPage", cmd)

    def test_cut_disabled_by_empty_cut_media(self):
        # cut_media="" short-circuits — support is never even queried.
        with mock.patch.object(agent, "_printer_supports_cut") as supports:
            cmd = self._run_print(cut_media="")
        supports.assert_not_called()
        self.assertFalse(any("CutMedia" in str(part) for part in cmd))

    def test_media_size_still_passed(self):
        with mock.patch.object(agent, "_printer_supports_cut", return_value=True):
            cmd = self._run_print(width_mm=62)
        self.assertTrue(any("media=Custom.62x" in str(part) for part in cmd))


class PrinterSupportsCutTests(unittest.TestCase):
    def setUp(self):
        agent._cut_support_cache.clear()

    def test_detects_cutmedia_option(self):
        out = mock.Mock(stdout="PageSize/Media Size: 4x6\nCutMedia/Cut: None EndOfPage\n")
        with mock.patch.object(agent.subprocess, "run", return_value=out):
            self.assertTrue(agent._printer_supports_cut("Brother_QL"))

    def test_returns_false_without_cutmedia(self):
        out = mock.Mock(stdout="PageSize/Media Size: 4x6\nResolution/Res: 203dpi\n")
        with mock.patch.object(agent.subprocess, "run", return_value=out):
            self.assertFalse(agent._printer_supports_cut("Rollo"))

    def test_result_is_cached(self):
        out = mock.Mock(stdout="CutMedia/Cut: None EndOfPage\n")
        with mock.patch.object(agent.subprocess, "run", return_value=out) as run:
            agent._printer_supports_cut("Brother_QL")
            agent._printer_supports_cut("Brother_QL")
        self.assertEqual(run.call_count, 1)  # second call served from cache

    def test_lpoptions_failure_is_safe(self):
        with mock.patch.object(agent.subprocess, "run", side_effect=OSError("boom")):
            self.assertFalse(agent._printer_supports_cut("X"))


if __name__ == "__main__":
    unittest.main()
