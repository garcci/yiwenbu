from datetime import datetime, timezone
import ast
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

BASE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("remaining26_entrypoint", BASE / "remaining26/run.py")
batch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(batch)
merge_spec = importlib.util.spec_from_file_location("asr_merge_adapter", BASE / "merge_results.py")
adapter = importlib.util.module_from_spec(merge_spec)
merge_spec.loader.exec_module(adapter)


def quota(scope):
    return {"confirmed_at_utc": datetime.now(timezone.utc).isoformat(),
            "authorization_id": scope["authorization_id"], "inputs_sha256": batch.core.FROZEN_INPUT_SHA256,
            "scope_sha256": scope["scope_sha256"], "actions_zero_budget_blocks_overage": True,
            "actions_storage_within_free_allowance": True, "actions_compute_used_usd": 2,
            "actions_compute_included_usd": 12, "asr_included_in_agent_plan": True,
            "asr_overage_disabled": True, "asr_audio_budget_verified": True,
            "volc_afp_remaining": 1000, "approved_max_connections": 26, "approved_max_audio_ms": 600000}


def final_response(row):
    text = row["expected_text"]
    return {"result": {"text": text, "utterances": [{"text": text, "definite": True,
            "start_time": 0, "end_time": 1900, "words": [
                {"text": char, "start_time": i * 10, "end_time": (i + 1) * 10}
                for i, char in enumerate(batch.core.normalized(text))]}]}}


class RemainingTests(unittest.TestCase):
    def test_exact26_scope_does_not_repeat_pilot(self):
        inputs, scope = batch.load_scope()
        self.assertEqual(scope["voice_ids"], [r["voice_id"] for r in inputs["segments"]][1:])
        self.assertEqual(len(scope["voice_ids"]), 26)
        self.assertNotIn("S1_01", scope["voice_ids"])
        self.assertNotEqual(scope["authorization_id"], batch.core.AUTHORIZATION)
        self.assertNotEqual(scope["workflow"], batch.core.WORKFLOW)
        workflow = (BASE.parents[1] / ".github/workflows/plan_asr_align_remaining26_once.yml").read_text()
        self.assertIn('paths: ["video/plan_asr_align/remaining26/execute_once.json"]', workflow)
        self.assertIn("--require-hashes", workflow)

    def test_scope_digest_and_connection_budget_must_match(self):
        _, scope = batch.load_scope()
        for change in ({"scope_sha256": "wrong"}, {"approved_max_connections": 27}, {"authorization_id": batch.core.AUTHORIZATION}):
            with self.assertRaises(batch.core.Stop):
                batch.core.quota_check({**quota(scope), **change}, scope=scope)

    def test_mock_execution_reads_only26_and_stops_on_first_service_failure(self):
        inputs, scope = batch.load_scope()
        selected = inputs["segments"][1:]
        for fail in (False, True):
            downloads = []
            class FakeDrive:
                def __init__(self, _): pass
                def private_folder(self, _): pass
                def download(self, row, receipt=False):
                    downloads.append(row["voice_id"])
                    return (BASE / "receipts.frozen" / row["receipt_filename"]).read_bytes() if receipt else b"synthetic-original"
            results = [([{ "final": True, "payload": final_response(row)}], [b"synthetic-frame"]) for row in selected]
            side_effect = batch.core.Stop("synthetic service failure") if fail else results
            with tempfile.TemporaryDirectory() as tmp, patch.object(batch.core, "first_run_gate"), patch.dict(os.environ, {"ARK_API_KEY": "synthetic"}), patch.dict(sys.modules, {"websocket": types.SimpleNamespace(create_connection=lambda: None)}), patch.object(batch.core, "FixedDriveReader", FakeDrive), patch.object(batch.core, "decode_pcm", return_value=b"\0" * 64000), patch.object(batch.core, "recognize", side_effect=side_effect) as recognize, patch.object(batch.core, "print", create=True):
                output = Path(tmp) / "out"
                if fail:
                    with self.assertRaises(batch.core.Stop): batch.core.execute(inputs, quota(scope), output, scope=scope)
                    self.assertEqual(recognize.call_count, 1)
                    state = json.loads((output / "state.json").read_text())
                    self.assertEqual(state["segments"], {"S1_02": "started_outcome_uncertain"})
                else:
                    batch.core.execute(inputs, quota(scope), output, scope=scope)
                    self.assertEqual(recognize.call_count, 26)
                    report = json.loads((output / "alignment.json").read_text())
                    self.assertEqual(len(report["segments"]), 26)
                    self.assertTrue(report["complete_for_scope"])
                    self.assertFalse(report["complete_for_episode"])
                self.assertNotIn("S1_01", downloads)
                self.assertEqual(set(downloads), set(scope["voice_ids"]))

    def test_merger_keeps_mismatches_and_rejects_duplicate_pilot(self):
        inputs, scope = batch.load_scope()
        pilot = json.loads((BASE / "pilot_verified_41404174217.json").read_text())["asr_result"]
        remaining = {"inputs_sha256": batch.core.FROZEN_INPUT_SHA256, "time_unit": "seconds",
                     "run_scope": scope["name"], "segments": [
                         batch.core.compare(row, final_response(row), 2000) for row in inputs["segments"][1:]]}
        remaining["segments"][0].update(auto_match=False, flags=["missing_word_timestamps"], words=[])
        merged = adapter.merge(pilot, remaining)
        self.assertEqual(len(merged["segments"]), 27)
        self.assertFalse(merged["auto_match_all"])
        self.assertTrue(merged["complete_for_episode"])
        self.assertEqual(merged["review_required_ids"], ["S1_02"])
        self.assertEqual(merged["segments"][0]["words"], pilot["segments"][0]["words"])
        self.assertFalse(merged["human_checked"])
        remaining["segments"][0] = pilot["segments"][0]
        with self.assertRaises(adapter.core.Stop): adapter.merge(pilot, remaining)

    def test_merged_report_meets_real_preview_contract_only_when_all_rows_match(self):
        inputs, scope = batch.load_scope()
        pilot = json.loads((BASE / "pilot_verified_41404174217.json").read_text())["asr_result"]
        remaining = {"inputs_sha256": batch.core.FROZEN_INPUT_SHA256, "time_unit": "seconds",
                     "run_scope": scope["name"], "segments": [
                         batch.core.compare(row, final_response(row), 2000) for row in inputs["segments"][1:]]}
        # Frozen consumer-contract expressions, not an import of uncommitted worker code.
        # When the real runner is present, require its actual AST guards to agree.
        expressions = [
            "alignment.get('complete_for_episode') is True and len(alignment.get('segments', [])) == 27",
            "all(x.get('auto_match') is True and not x.get('flags') for x in alignment['segments'])",
        ]
        preview = BASE.parent / "r06_timeline/run_private_preview.py"
        if preview.exists():
            actual = []
            for node in ast.walk(ast.parse(preview.read_text())):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "need"
                        and len(node.args) >= 2 and isinstance(node.args[1], ast.Constant)
                        and node.args[1].value in ("ASR pilot/incomplete timestamps cannot calibrate an episode", "ASR mismatch/flags require manual correction")):
                    actual.append(ast.dump(node.args[0], include_attributes=False))
            self.assertEqual(set(actual), {ast.dump(ast.parse(expr, mode="eval").body, include_attributes=False) for expr in expressions})
        contract = [compile(ast.parse(expr, mode="eval"), "frozen-preview-contract", "eval") for expr in expressions]
        def accepted(report):
            return all(eval(expression, {"alignment": report, "len": len, "all": all}) for expression in contract)
        merged = adapter.merge(pilot, remaining)
        self.assertTrue(merged["complete_for_episode"])
        self.assertTrue(merged["auto_match_all"])
        self.assertTrue(accepted(merged))
        for flags in (["missing_word_timestamps"], ["transcript_differs_from_frozen_text"]):
            remaining["segments"][0].update(auto_match=False, flags=flags, words=[])
            failed = adapter.merge(pilot, remaining)
            self.assertTrue(failed["complete_for_episode"])  # coverage, not quality
            self.assertFalse(failed["auto_match_all"])
            self.assertFalse(accepted(failed))
            self.assertEqual(failed["segments"][1]["flags"], flags)


if __name__ == "__main__":
    unittest.main()
