import gzip
from datetime import datetime, timedelta, timezone
import importlib.util
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import threading
import types
import unittest
from unittest.mock import patch

BASE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("plan_asr_align_runner", BASE / "runner.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
protocol = sys.modules["protocol"]


def server_frame(payload, final=True, flags=None):
    raw = gzip.compress(json.dumps(payload).encode())
    flags = (3 if final else 1) if flags is None else flags
    head = bytes([0x11, 0x90 | flags, 0x11, 0])
    seq = struct.pack(">i", -2 if final else 2) if flags & 1 else b""
    return head + seq + struct.pack(">I", len(raw)) + raw


def quota(now=None):
    return {"confirmed_at_utc": (now or datetime.now(timezone.utc)).isoformat(),
            "authorization_id": runner.AUTHORIZATION, "inputs_sha256": runner.FROZEN_INPUT_SHA256,
            "actions_zero_budget_blocks_overage": True, "actions_storage_within_free_allowance": True,
            "actions_compute_used_usd": 2, "actions_compute_included_usd": 12,
            "asr_included_in_agent_plan": True, "asr_overage_disabled": True,
            "asr_audio_budget_verified": True, "volc_afp_remaining": 1000,
            "approved_max_connections": 1, "approved_max_audio_ms": runner.MAX_TOTAL_MS}


def transcript(text="妈，我没事。"):
    return {"result": {"text": text, "utterances": [{"text": text, "definite": True,
            "start_time": 0, "end_time": 900, "words": [
                {"text": c, "start_time": i * 100, "end_time": (i + 1) * 100}
                for i, c in enumerate("妈我没事")]}]}}


class ProtocolTests(unittest.TestCase):
    def test_full_request_has_no_reference_prompt_and_asks_for_word_timestamps(self):
        packet = protocol.full_request()
        self.assertEqual(packet[:4], bytes([0x11, 0x11, 0x11, 0]))
        self.assertEqual(struct.unpack_from(">i", packet, 4)[0], 1)
        request = json.loads(gzip.decompress(packet[12:]))
        self.assertTrue(request["request"]["show_utterances"])
        self.assertFalse(request["request"]["enable_ddc"])
        self.assertFalse(request["request"]["enable_itn"])
        self.assertNotIn("text", request["request"])
        self.assertNotIn("corpus", request["request"])
        self.assertEqual(request["audio"]["rate"], 16000)

    def test_final_audio_has_negative_sequence_and_raw_serialization(self):
        packet = protocol.encode(2, 3, b"pcm", final=True)
        self.assertEqual(packet[:4], bytes([0x11, 0x23, 0x01, 0]))
        self.assertEqual(struct.unpack_from(">i", packet, 4)[0], -3)
        self.assertEqual(gzip.decompress(packet[12:]), b"pcm")

    def test_server_frame_final_and_payload_preserved(self):
        value = protocol.decode(server_frame(transcript()))
        self.assertTrue(value["final"])
        self.assertEqual(value["payload"], transcript())

    def test_errors_and_truncated_frames_stop_without_exposing_response(self):
        error = bytes([0x11, 0xF0, 0x10, 0]) + struct.pack(">II", 45000001, 22) + b"untrusted-private-body"
        with self.assertRaises(protocol.ProtocolStop) as caught:
            protocol.decode(error)
        self.assertNotIn("private", str(caught.exception))
        for frame in (b"short", server_frame(transcript())[:-1], server_frame(transcript()) + b"extra"):
            with self.assertRaises(protocol.ProtocolStop):
                protocol.decode(frame)


class ComparisonTests(unittest.TestCase):
    def setUp(self):
        self.row = runner.load_inputs()["segments"][0]

    def test_compatible_seconds_output_from_actual_millisecond_words(self):
        value = runner.compare(self.row, transcript(), 1000)
        self.assertTrue(value["auto_match"])
        self.assertEqual(value["voice_id"], "S1_01")
        self.assertEqual(value["audio_sha256"], self.row["audio_sha256"])
        self.assertEqual(value["words"][1], {"text": "我", "start": .1, "end": .2})
        self.assertFalse(value["human_checked"])

    def test_missing_timestamps_are_never_fabricated(self):
        response = transcript()
        del response["result"]["utterances"][0]["words"]
        value = runner.compare(self.row, response, 1000)
        self.assertFalse(value["auto_match"])
        self.assertEqual(value["words"], [])
        self.assertIn("missing_word_timestamps", value["flags"])

    def test_wrong_words_numbers_and_utterance_bounds_fail_automatic_matching(self):
        value = runner.compare(self.row, transcript("妈，我有事。"), 1000)
        self.assertFalse(value["auto_match"])
        self.assertTrue(value["differences"])
        row = {**self.row, "expected_text": "3点09分"}
        self.assertFalse(runner.compare(row, {"result": {"text": "三点零九分"}}, 1000)["auto_match"])
        response = transcript()
        response["result"]["utterances"][0]["words"][0]["start_time"] = -1
        self.assertFalse(runner.compare(self.row, response, 1000)["auto_match"])
        response = transcript()
        response["result"]["utterances"][0]["end_time"] = 100
        self.assertFalse(runner.compare(self.row, response, 1000)["auto_match"])


class ScopeTests(unittest.TestCase):
    def test_workflow_dependency_is_verified_pinned_release_with_hash(self):
        dependency = json.loads((BASE / "dependency_evidence.json").read_text())
        self.assertEqual(dependency["version"], "1.9.2")
        expected = "websocket-client==1.9.2 --hash=sha256:" + dependency["wheel_sha256"]
        self.assertEqual((BASE / "requirements.txt").read_text().strip(), expected)
        workflow = (BASE.parents[1] / ".github/workflows/plan_asr_align_once.yml").read_text()
        self.assertIn("--require-hashes -r video/plan_asr_align/requirements.txt", workflow)
        self.assertNotIn("websocket-client==1.10.0", workflow)

    def test_frozen_27_sources_and_receipts_are_exact(self):
        value = runner.load_inputs()
        self.assertEqual(len(value["segments"]), 27)
        self.assertEqual(tuple(value["folders"]), runner.FOLDERS)
        self.assertTrue(all(row["audio_filename"] == row["voice_id"] + ".mp3" for row in value["segments"]))

    def test_arbitrary_drive_ids_rejected_before_network(self):
        reader = object.__new__(runner.FixedDriveReader)
        reader.rows = {}
        reader.headers = {}
        with patch.object(runner, "http_bytes") as request:
            with self.assertRaises(runner.Stop): reader.metadata("forbidden-outside-id")
            with self.assertRaises(runner.Stop): reader.private_folder("forbidden-folder")
            request.assert_not_called()

    def test_receipt_mismatch_blocks(self):
        row = runner.load_inputs()["segments"][0]
        with self.assertRaises(runner.Stop): runner.validate_receipt(row, b"changed")

    def test_draft_stale_nan_and_asr_overage_enabled_block(self):
        now = datetime.now(timezone.utc)
        cases = [quota(now - timedelta(hours=2)), {**quota(), "draft_only": True},
                 {**quota(), "asr_overage_disabled": False}, {**quota(), "actions_compute_used_usd": float("nan")},
                 {**quota(), "approved_max_connections": 27}]
        for evidence in cases:
            with self.assertRaises(runner.Stop): runner.quota_check(evidence)


class PilotTests(unittest.TestCase):
    def test_websocket_transport_uses_one_fixed_connection_and_binary_final_packet(self):
        ready = threading.Event()
        class FakeSocket:
            status = 101
            def __init__(self): self.sent, self.closed = [], False
            def recv(self):
                if not ready.wait(2): raise RuntimeError("synthetic timeout")
                return server_frame(transcript())
            def send_binary(self, packet):
                self.sent.append(packet)
                if packet[1] & 2: ready.set()
            def close(self): self.closed = True
        socket = FakeSocket()
        create = unittest.mock.Mock(return_value=socket)
        fake = types.SimpleNamespace(create_connection=create, enableTrace=lambda _: None)
        with patch.dict(sys.modules, {"websocket": fake}), patch.object(runner.time, "sleep"):
            events, packets = runner.recognize(b"\0" * 32000, "synthetic-not-credential")
        create.assert_called_once()
        args = create.call_args
        self.assertEqual(args.args[0], runner.ASR_URL)
        self.assertEqual(args.kwargs["redirect_limit"], 0)
        self.assertEqual(args.kwargs["header"]["X-Api-Resource-Id"], runner.RESOURCE)
        self.assertEqual(len(socket.sent), 6)  # parameters plus five 200ms chunks
        self.assertEqual(socket.sent[-1][1], 0x23)
        self.assertTrue(events[-1]["final"])
        self.assertEqual(len(packets), 1)
        self.assertTrue(socket.closed)

    def test_only_S1_01_downloaded_and_identified_once(self):
        inputs = runner.load_inputs()
        downloads, folders = [], []
        class FakeDrive:
            def __init__(self, _): pass
            def private_folder(self, fid): folders.append(fid)
            def download(self, row, receipt=False):
                downloads.append((row["voice_id"], receipt))
                return (BASE / "receipts.frozen" / row["receipt_filename"]).read_bytes() if receipt else b"synthetic-audio"
        events = [{"final": True, "payload": transcript()}]
        with tempfile.TemporaryDirectory() as tmp, patch.object(runner, "first_run_gate"), patch.dict(os.environ, {"ARK_API_KEY": "synthetic"}), patch.dict(sys.modules, {"websocket": types.SimpleNamespace(create_connection=lambda: None)}), patch.object(runner, "FixedDriveReader", FakeDrive), patch.object(runner, "decode_pcm", return_value=b"\0" * 32000), patch.object(runner, "recognize", return_value=(events, [server_frame(transcript())])) as recognize, patch.object(runner, "print", create=True):
            output = Path(tmp) / "output"
            runner.execute(inputs, quota(), output)
            recognize.assert_called_once()
            report = json.loads((output / "alignment.json").read_text())
            self.assertEqual(len(report["segments"]), 1)
            self.assertFalse(report["complete_for_episode"])
            self.assertFalse(report["human_checked"])
            self.assertEqual(downloads, [("S1_01", True), ("S1_01", False)])
            self.assertEqual(folders, [runner.FOLDERS[0]])

    def test_preflight_failure_opens_no_asr_connection(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(runner, "first_run_gate"), patch.dict(os.environ, {"ARK_API_KEY": "synthetic"}), patch.dict(sys.modules, {"websocket": types.SimpleNamespace(create_connection=lambda: None)}), patch.object(runner, "FixedDriveReader", side_effect=runner.Stop("synthetic Drive failure")), patch.object(runner, "recognize") as recognize:
            with self.assertRaises(runner.Stop):
                runner.execute(runner.load_inputs(), quota(), Path(tmp) / "out")
            recognize.assert_not_called()

    def test_prior_or_missing_cloud_run_history_blocks(self):
        environment = {"GITHUB_ACTIONS": "true", "GITHUB_EVENT_NAME": "push", "GITHUB_REPOSITORY": runner.REPOSITORY,
                       "GITHUB_RUN_ATTEMPT": "1", "GITHUB_REF": "refs/heads/claude/project-thread-l4wz3r",
                       "GITHUB_RUN_ID": "101", "GITHUB_SHA": "a" * 40, "GITHUB_TOKEN": "synthetic"}
        workflow = {"id": 77, "path": ".github/workflows/" + runner.WORKFLOW}
        for history in ({}, {"total_count": 2, "workflow_runs": [{}, {}]}):
            with patch.dict(os.environ, environment), patch.object(runner, "http_bytes", side_effect=[json.dumps(workflow).encode(), json.dumps(history).encode()]):
                with self.assertRaises(runner.Stop): runner.first_run_gate()


if __name__ == "__main__":
    unittest.main()
