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


class JobSerializationTests(unittest.TestCase):
    """A label must finish printing before the next job is submitted, so batches
    don't overrun the ipp-usb USB bridge and wedge the queue."""

    def setUp(self):
        agent._cut_support_cache.clear()

    def test_print_waits_until_job_leaves_the_queue(self):
        # lpstat shows the job still active for two polls, then it clears.
        lpstat_stdout = [
            "ChurchLabel-7 luke 1024 Sun 21 Jun\n",  # still printing
            "ChurchLabel-7 luke 1024 Sun 21 Jun\n",  # still printing
            "",                                       # cleared
        ]
        calls = {"lpstat": 0}

        def fake_run(cmd, *a, **kw):
            if cmd[0] == "lpstat":
                idx = min(calls["lpstat"], len(lpstat_stdout) - 1)
                calls["lpstat"] += 1
                return mock.Mock(returncode=0, stdout=lpstat_stdout[idx], stderr="")
            return mock.Mock(
                returncode=0,
                stdout="request id is ChurchLabel-7 (1 file(s))",
                stderr="",
            )

        with mock.patch.object(agent, "_printer_supports_cut", return_value=False), \
                mock.patch.object(agent.subprocess, "run", side_effect=fake_run), \
                mock.patch.object(agent.time, "sleep") as sleep:
            ok, err = agent._print_png(_fake_png(), "ChurchLabel")

        self.assertTrue(ok, err)
        self.assertGreaterEqual(calls["lpstat"], 3)  # polled until the job cleared
        self.assertTrue(sleep.called)                # paced polls + settle

    def test_no_request_id_means_no_wait(self):
        # If `lp` emits no request id we don't poll lpstat (degrade to old behaviour).
        def fake_run(cmd, *a, **kw):
            self.assertNotEqual(cmd[0], "lpstat")  # lpstat must never be queried
            return mock.Mock(returncode=0, stdout="", stderr="")

        with mock.patch.object(agent, "_printer_supports_cut", return_value=False), \
                mock.patch.object(agent.subprocess, "run", side_effect=fake_run):
            ok, err = agent._print_png(_fake_png(), "ChurchLabel")
        self.assertTrue(ok, err)

    def test_wait_times_out_without_hanging(self):
        # A job that never clears must not loop forever — give up at the timeout.
        clock = {"t": 0.0}

        def fake_monotonic():
            clock["t"] += 1.0
            return clock["t"]

        def fake_run(cmd, *a, **kw):
            return mock.Mock(returncode=0, stdout="ChurchLabel-9 luke 1 Sun\n", stderr="")

        with mock.patch.object(agent.time, "monotonic", side_effect=fake_monotonic), \
                mock.patch.object(agent.time, "sleep"), \
                mock.patch.object(agent.subprocess, "run", side_effect=fake_run):
            agent._wait_for_job("ChurchLabel-9", timeout=5)
        # Reaching this line (no infinite loop) is the assertion.


class RecoveryTests(unittest.TestCase):
    """After a failed print the agent self-heals the print stack so the printer
    comes back without a manual Pi reboot."""

    def setUp(self):
        agent._last_recovery = 0.0
        agent._cut_support_cache.clear()

    def _capture(self):
        calls = []

        def fake_run(cmd, *a, **kw):
            calls.append(" ".join(cmd))
            return mock.Mock(returncode=0, stdout="", stderr="")

        return calls, fake_run

    def test_runs_full_recovery_sequence(self):
        calls, fake_run = self._capture()
        with mock.patch.object(agent, "RECOVER_AFTER_FAILURE", True), \
                mock.patch.object(agent.time, "sleep"), \
                mock.patch.object(agent.subprocess, "run", side_effect=fake_run):
            agent._recover_print_subsystem("ChurchLabel")
        self.assertIn("cancel -a", calls)
        self.assertTrue(any("systemctl restart ipp-usb" in c for c in calls))
        self.assertTrue(any("systemctl restart cups" in c for c in calls))
        self.assertIn("cupsenable ChurchLabel", calls)

    def test_rate_limited_within_cooldown(self):
        _, fake_run = self._capture()
        with mock.patch.object(agent, "RECOVER_AFTER_FAILURE", True), \
                mock.patch.object(agent.time, "sleep"), \
                mock.patch.object(agent.subprocess, "run", side_effect=fake_run) as run:
            agent._recover_print_subsystem("Q")
            after_first = run.call_count
            agent._recover_print_subsystem("Q")  # within cooldown → skipped
        self.assertEqual(run.call_count, after_first)

    def test_disabled_is_noop(self):
        with mock.patch.object(agent, "RECOVER_AFTER_FAILURE", False), \
                mock.patch.object(agent.subprocess, "run") as run:
            agent._recover_print_subsystem("Q")
        run.assert_not_called()

    def test_best_effort_never_raises(self):
        with mock.patch.object(agent, "RECOVER_AFTER_FAILURE", True), \
                mock.patch.object(agent.time, "sleep"), \
                mock.patch.object(agent.subprocess, "run", side_effect=OSError("boom")):
            agent._recover_print_subsystem("Q")  # must not propagate


class IdentityHeaderTests(unittest.TestCase):
    """The agent reports its hostname + LAN IP so the server can show where the
    Pi is (found without scanning the network)."""

    def test_includes_hostname_and_ip(self):
        with mock.patch.object(agent.socket, "gethostname", return_value="bcc-printmon-1"), \
                mock.patch.object(agent, "_local_ip", return_value="192.168.1.50"):
            headers = agent._identity_headers()
        self.assertEqual(headers["X-Agent-Hostname"], "bcc-printmon-1")
        self.assertEqual(headers["X-Agent-Local-IP"], "192.168.1.50")

    def test_omits_blank_ip(self):
        with mock.patch.object(agent.socket, "gethostname", return_value="host"), \
                mock.patch.object(agent, "_local_ip", return_value=""):
            headers = agent._identity_headers()
        self.assertNotIn("X-Agent-Local-IP", headers)
        self.assertEqual(headers["X-Agent-Hostname"], "host")

    def test_never_raises_on_socket_failure(self):
        with mock.patch.object(agent.socket, "gethostname", side_effect=OSError("boom")), \
                mock.patch.object(agent, "_local_ip", return_value=""):
            headers = agent._identity_headers()  # must not raise
        self.assertEqual(headers, {})


if __name__ == "__main__":
    unittest.main()
