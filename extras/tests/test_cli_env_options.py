"""
Tests for CLI configuration options:
- --env-file: run with an explicitly specified .env file
- CLI options overriding .env values (ConfigLoader overrides)
- --help exposing all configuration options
"""

import sys
import os
import subprocess
import tempfile
import unittest
from argparse import Namespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from config_loader import ConfigLoader

_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def _write_env(content: str) -> str:
    """Write content to a temp .env file and return its path."""
    fd, path = tempfile.mkstemp(suffix=".env")
    with os.fdopen(fd, "w") as f:
        f.write(content)
    return path


class TestEnvFileOption(unittest.TestCase):
    """ConfigLoader must load the explicitly specified .env file."""

    def test_env_file_loads_specified_file(self):
        path = _write_env("PLMN=99988\nWEBUI_PORT=1234\n")
        try:
            loader = ConfigLoader(env_file=path)
            self.assertEqual(loader.env_file, path)
            self.assertEqual(loader.get_plmn(), "99988")
            self.assertEqual(loader.get_int("WEBUI_PORT"), 1234)
        finally:
            os.unlink(path)

    def test_env_file_missing_raises(self):
        with self.assertRaises(FileNotFoundError):
            ConfigLoader(env_file="/nonexistent/path/custom.env")

    def test_env_file_takes_precedence_over_cwd(self):
        path = _write_env("PLMN=11122\n")
        try:
            loader = ConfigLoader(env_file=path, profile_name="someprofile")
            self.assertEqual(loader.env_file, path)
        finally:
            os.unlink(path)


class TestCliOverrides(unittest.TestCase):
    """CLI overrides must take precedence over .env file values."""

    def setUp(self):
        self.path = _write_env("DNN=internet\nWEBUI_PORT=9999\nENABLE_IMS=true\n")
        self.addCleanup(os.unlink, self.path)

    def test_override_beats_file_value(self):
        loader = ConfigLoader(env_file=self.path, overrides={"DNN": "ims"})
        self.assertEqual(loader.get("DNN"), "ims")

    def test_override_applies_to_get_int(self):
        loader = ConfigLoader(env_file=self.path, overrides={"WEBUI_PORT": "8080"})
        self.assertEqual(loader.get_int("WEBUI_PORT"), 8080)

    def test_file_value_used_when_no_override(self):
        loader = ConfigLoader(env_file=self.path, overrides={"DNN": "ims"})
        self.assertEqual(loader.get_int("WEBUI_PORT"), 9999)
        self.assertEqual(loader.get("ENABLE_IMS"), "true")

    def test_set_override_after_init(self):
        loader = ConfigLoader(env_file=self.path)
        loader.set_override("DNN", "voip")
        self.assertEqual(loader.get("DNN"), "voip")


class TestBuildCliOverrides(unittest.TestCase):
    """_build_cli_overrides maps CLI options to .env keys."""

    def _args(self, **kwargs):
        defaults = {
            "count": None, "core_address": None, "webui_port": None,
            "username": None, "password": None, "api_token": None,
            "initial_imsi_index": None, "gnb_address": None,
            "gnb_nr_cell_id": None, "slices": None, "dnn": None,
            "enb_address": None, "apn": None, "mme_port": None,
            "enb_id": None, "enb_cell_id": None, "imeisv": None,
            "plmn": None, "ki": None, "opc": None, "tac": None,
            "log_level": None, "gtpu_port": None, "upf_ip": None,
            "pcscf_ip": None, "pcscf_port": None, "caller_phone": None,
            "callee_phone": None, "enable_ims": None,
        }
        defaults.update(kwargs)
        return Namespace(**defaults)

    def test_none_args_produce_no_overrides(self):
        from coresim_runner import _build_cli_overrides
        self.assertEqual(_build_cli_overrides(self._args()), {})

    def test_set_args_mapped_to_env_keys(self):
        from coresim_runner import _build_cli_overrides
        overrides = _build_cli_overrides(self._args(
            webui_port=8080, username="root", dnn="ims", plmn="46001"
        ))
        self.assertEqual(overrides["WEBUI_PORT"], "8080")
        self.assertEqual(overrides["USERNAME"], "root")
        self.assertEqual(overrides["DNN"], "ims")
        self.assertEqual(overrides["PLMN"], "46001")

    def test_enable_ims_tristate(self):
        from coresim_runner import _build_cli_overrides
        self.assertEqual(
            _build_cli_overrides(self._args(enable_ims=True))["ENABLE_IMS"], "true")
        self.assertEqual(
            _build_cli_overrides(self._args(enable_ims=False))["ENABLE_IMS"], "false")
        self.assertNotIn(
            "ENABLE_IMS", _build_cli_overrides(self._args(enable_ims=None)))


class TestHelpExposesOptions(unittest.TestCase):
    """--help must document the configuration options."""

    @classmethod
    def setUpClass(cls):
        result = subprocess.run(
            [sys.executable, os.path.join(_PROJECT_ROOT, "coresim_runner.py"), "--help"],
            capture_output=True, text=True, timeout=60
        )
        cls.help_text = result.stdout

    def test_env_file_documented(self):
        self.assertIn("--env-file", self.help_text)

    def test_all_env_overrides_documented(self):
        for option in [
            "--webui-port", "--username", "--password", "--api-token",
            "--initial-imsi-index", "--enable-ims", "--no-ims", "--slices",
            "--gnb-nr-cell-id", "--imeisv", "--gtpu-port", "--profile",
        ]:
            self.assertIn(option, self.help_text, f"{option} missing from --help")


if __name__ == "__main__":
    unittest.main()
