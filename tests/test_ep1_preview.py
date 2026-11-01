import copy
import datetime as dt
import importlib.util
import json
from pathlib import Path
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("ep1_preview", ROOT / "video/ep1_preview/run.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class PreviewChecks(unittest.TestCase):
    def setUp(self):
        self.cfg = json.loads((ROOT / "video/ep1_preview/request.json").read_text())
        self.now = dt.datetime(2026, 11, 1, 8, 17, tzinfo=dt.timezone.utc)

    def test_selected_voice_and_source(self):
        self.assertIs(mod.validate(self.cfg, self.now), self.cfg)
        source = (ROOT / "discuss/07-第一集配音稿-v3.md")
        if source.exists():
            raw = source.read_text()
            for text in mod.EXPECTED_TEXT:
                self.assertIn(text, raw)

    def test_no_overage_or_unverified_cost(self):
        for key in ("tts_overage_disabled", "actions_spending_blocked"):
            cfg = copy.deepcopy(self.cfg); cfg[key] = False
            with self.assertRaises(ValueError):
                mod.validate(cfg, self.now)

    def test_stale_check_blocks(self):
        with self.assertRaises(ValueError):
            mod.validate(self.cfg, dt.datetime(2026, 11, 2, tzinfo=dt.timezone.utc))

    def test_wrong_voice_or_modified_script_blocks(self):
        for field in ("voice", "text"):
            cfg = copy.deepcopy(self.cfg)
            if field == "voice": cfg["narrator"] = "other"
            else: cfg["opening"][0]["text"] += "新增台词"
            with self.assertRaises(ValueError): mod.validate(cfg, self.now)

    def test_paid_endpoint_never_opened(self):
        with mock.patch.object(mod.urllib.request, "urlopen") as net:
            with self.assertRaises(ValueError):
                mod.post("https://ark.cn-beijing.volces.com/api/v3/images/generations", {}, {})
            net.assert_not_called()

    def test_timestamp_rollover(self):
        self.assertEqual(mod.stamp(59.9996), "00:01:00,000")


if __name__ == "__main__": unittest.main()
