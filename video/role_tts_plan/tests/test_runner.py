import base64
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import importlib.util
import io
import json
import sys
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

MODULE_PATH = Path(__file__).resolve().parents[1] / "runner.py"
spec = importlib.util.spec_from_file_location("role_tts_plan_runner", MODULE_PATH)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def manifest():
    value = json.loads((MODULE_PATH.parent / "manifest.example.json").read_text())
    value["approval_state"] = "approved"
    return value


def evidence(summary, now=None):
    return {
        "confirmed_at_utc": (now or datetime.now(timezone.utc)).isoformat(),
        "approved_manifest_sha256": summary["manifest_sha256"],
        "authorization_id": runner.BATCH_AUTHORIZATION_ID,
        "actions_zero_budget_blocks_overage": True,
        "actions_storage_within_free_allowance": True,
        "actions_compute_used_usd": 1.83,
        "actions_compute_included_usd": 12,
        "volc_tts_overage_disabled": True,
        "volc_afp_remaining": 100,
        "volc_character_budget_verified": True,
        "approved_max_requests": summary["segments"],
        "approved_max_characters": summary["characters"],
        "source_note": "Synthetic offline test; not billing evidence",
    }


class ManifestTests(unittest.TestCase):
    def test_example_is_valid_for_offline_checks_but_not_generation(self):
        value = manifest()
        value["approval_state"] = "draft"
        summary = runner.validate_manifest(value)
        with tempfile.TemporaryDirectory() as output, patch.object(runner, "generate") as generate:
            with self.assertRaises(runner.SafeStop):
                runner.execute(value, summary, Path(output), "synthetic-not-secret", evidence(summary))
            generate.assert_not_called()

    def test_duplicate_ids_and_path_traversal_rejected(self):
        value = manifest()
        for bad in (value["segments"][0]["id"], "../paragraph"):
            value["segments"][1]["id"] = bad
            with self.assertRaises(runner.SafeStop):
                runner.validate_manifest(value)

    def test_extra_audio_reference_field_rejected(self):
        value = manifest()
        value["segments"][0]["reference_audio"] = "not-opened.wav"
        with self.assertRaises(runner.SafeStop):
            runner.validate_manifest(value)

    def test_multiline_and_excessive_text_rejected(self):
        for bad in ("一段。\n二段。", "字" * 1001):
            value = manifest()
            value["segments"][0]["text"] = bad
            with self.assertRaises(runner.SafeStop):
                runner.validate_manifest(value)

    def test_role_voice_changes_and_forbidden_reference_ids_rejected(self):
        value = manifest()
        value["segments"][1]["role"] = value["segments"][0]["role"]
        with self.assertRaises(runner.SafeStop):
            runner.validate_manifest(value)
        for sid in ("Result-10", "Result-4"):
            value = manifest()
            value["segments"][0]["id"] = sid
            with self.assertRaises(runner.SafeStop):
                runner.validate_manifest(value)

    def test_total_character_cap(self):
        value = manifest()
        base = value["segments"][0]
        value["segments"] = [{**deepcopy(base), "id": f"p{i}", "text": "字" * 1000} for i in range(9)]
        with self.assertRaises(runner.SafeStop):
            runner.validate_manifest(value)

    def test_boundaries_and_mutation_change_digest(self):
        value = manifest()
        first = runner.validate_manifest(value)
        value["segments"][0]["rhythm"]["speech_rate"] = -1
        self.assertNotEqual(first["manifest_sha256"], runner.validate_manifest(value)["manifest_sha256"])
        value["segments"] *= 11
        with self.assertRaises(runner.SafeStop):
            runner.validate_manifest(value)


class QuotaTests(unittest.TestCase):
    def test_missing_stale_or_wrong_manifest_evidence_blocks_execution(self):
        summary = runner.validate_manifest(manifest())
        old = evidence(summary, datetime.now(timezone.utc) - timedelta(hours=2))
        wrong = evidence(summary)
        wrong["approved_manifest_sha256"] = "wrong"
        for value in ({}, old, wrong):
            with self.assertRaises(runner.SafeStop):
                runner.validate_quota(value, summary)

    def test_off_switches_and_nan_do_not_pass(self):
        summary = runner.validate_manifest(manifest())
        for key, bad in (("volc_tts_overage_disabled", False),
                         ("actions_zero_budget_blocks_overage", False),
                         ("actions_compute_used_usd", float("nan")),
                         ("volc_afp_remaining", float("inf"))):
            value = evidence(summary)
            value[key] = bad
            with self.assertRaises(runner.SafeStop):
                runner.validate_quota(value, summary)

    def test_compute_snapshot_rejects_nan_reverse_insufficient_and_nonnumeric(self):
        summary = runner.validate_manifest(manifest())
        for used, included in ((float("nan"), 12), (1, float("inf")), (13, 12),
                               (-1, 12), (0, -1), (11.51, 12), (True, 12), (1, "12")):
            value = evidence(summary)
            value.update(actions_compute_used_usd=used, actions_compute_included_usd=included)
            with self.assertRaises(runner.SafeStop):
                runner.validate_quota(value, summary)
        value = evidence(summary)
        value.update(actions_compute_used_usd=11.5, actions_compute_included_usd=12)
        runner.validate_quota(value, summary)

    def test_draft_evidence_is_rejected_even_when_other_fields_are_valid(self):
        summary = runner.validate_manifest(manifest())
        value = evidence(summary)
        value["draft_only"] = True
        with self.assertRaises(runner.SafeStop):
            runner.validate_quota(value, summary)


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        silent = patch.object(runner, "print", create=True)
        silent.start()
        self.addCleanup(silent.stop)
        gate = patch.object(runner, "require_single_push_run", return_value={"run_id": 101})
        gate.start()
        self.addCleanup(gate.stop)

    def test_failure_stops_remaining_paragraphs_and_resume_does_not_retry(self):
        value = manifest()
        summary = runner.validate_manifest(value)
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "output"
            with patch.object(runner, "generate", side_effect=runner.SafeStop("synthetic failure")) as generate:
                with self.assertRaises(runner.SafeStop):
                    runner.execute(value, summary, output, "synthetic-not-secret", evidence(summary))
                self.assertEqual(generate.call_count, 1)
            state = runner.load_json(output / "state.json")
            self.assertEqual(len(state["segments"]), 1)
            self.assertEqual(next(iter(state["segments"].values()))["status"], "failed_or_uncertain")
            with patch.object(runner, "generate") as generate:
                with self.assertRaises(runner.SafeStop):
                    runner.execute(value, summary, output, "synthetic-not-secret", evidence(summary))
                generate.assert_not_called()

    def test_completed_outputs_are_reused_but_changed_audio_is_rejected(self):
        value = manifest()
        summary = runner.validate_manifest(value)
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "output"
            with patch.object(runner, "generate", return_value=b"synthetic-audio") as generate:
                runner.execute(value, summary, output, "synthetic-not-secret", evidence(summary))
                self.assertEqual(generate.call_count, 2)
            with patch.object(runner, "generate") as generate:
                runner.execute(value, summary, output, "synthetic-not-secret", evidence(summary))
                generate.assert_not_called()
            (output / (value["segments"][0]["id"] + ".mp3")).write_bytes(b"changed")
            with patch.object(runner, "generate") as generate:
                with self.assertRaises(runner.SafeStop):
                    runner.execute(value, summary, output, "synthetic-not-secret", evidence(summary))
                generate.assert_not_called()

    def test_partial_success_is_preserved(self):
        value = manifest()
        summary = runner.validate_manifest(value)
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "output"
            with patch.object(runner, "generate", side_effect=[b"first-original", runner.SafeStop("stop")]):
                with self.assertRaises(runner.SafeStop):
                    runner.execute(value, summary, output, "synthetic-not-secret", evidence(summary))
            self.assertEqual((output / (value["segments"][0]["id"] + ".mp3")).read_bytes(), b"first-original")
            self.assertFalse((output / (value["segments"][1]["id"] + ".mp3")).exists())


class ProtocolTests(unittest.TestCase):
    def response(self, rows):
        return io.BytesIO(b"\n".join(json.dumps(row).encode() for row in rows))

    def test_fixed_package_request_and_context_are_separate_from_text(self):
        segment = manifest()["segments"][0]
        fake = self.response([{"code": 0, "data": base64.b64encode(b"audio").decode()}, {"code": 20000000}])
        with patch.object(runner.urllib.request, "build_opener") as builder:
            builder.return_value.open.return_value = fake
            self.assertEqual(runner.generate(segment, "synthetic-not-secret"), b"audio")
            request = builder.return_value.open.call_args.args[0]
            self.assertEqual(request.full_url, runner.TTS_URL)
            self.assertEqual(request.get_header("X-api-resource-id"), "seed-tts-2.0")
            payload = json.loads(request.data)
            self.assertEqual(payload["req_params"]["text"], segment["text"])
            self.assertNotIn("上下文", payload["req_params"]["text"])
            self.assertIn(segment["performance_context"], payload["req_params"]["additions"])
            builder.return_value.open.assert_called_once()

    def test_service_error_or_truncation_stops_without_fallback(self):
        segment = manifest()["segments"][0]
        cases = ([{"code": 45000000, "message": "untrusted response not logged"}],
                 [{"code": 0, "data": base64.b64encode(b"audio").decode()}])
        for rows in cases:
            with patch.object(runner.urllib.request, "build_opener") as builder:
                builder.return_value.open.return_value = self.response(rows)
                with self.assertRaises(runner.SafeStop):
                    runner.generate(segment, "synthetic-not-secret")
                builder.return_value.open.assert_called_once()


class DriveTests(unittest.TestCase):
    def setUp(self):
        silent = patch.object(runner, "print", create=True)
        silent.start()
        self.addCleanup(silent.stop)
        gate = patch.object(runner, "require_single_push_run", return_value={"run_id": 101})
        gate.start()
        self.addCleanup(gate.stop)
        credentials = patch.dict(runner.os.environ, {name: "synthetic-not-credentials" for name in
            ("GDRIVE_CLIENT_ID", "GDRIVE_CLIENT_SECRET", "GDRIVE_REFRESH_TOKEN")})
        credentials.start()
        self.addCleanup(credentials.stop)

    def test_preflight_failures_stop_before_any_tts_or_output(self):
        value = manifest(); summary = runner.validate_manifest(value)
        for reason in ("missing requests", "OAuth unavailable", "parent audience unconfirmed"):
            with tempfile.TemporaryDirectory() as tmp, patch.object(runner, "preflight_drive", side_effect=runner.SafeStop(reason)), patch.object(runner, "generate") as generate:
                output = Path(tmp) / "output"
                with self.assertRaises(runner.SafeStop):
                    runner.execute(value, summary, output, "synthetic", evidence(summary),
                                   before_synthesis=runner.preflight_drive)
                generate.assert_not_called()
                self.assertFalse(output.exists())

    def test_real_preflight_missing_dependency_or_oauth_failure_causes_zero_tts(self):
        value = manifest(); summary = runner.validate_manifest(value)
        fake_drive = types.SimpleNamespace(_token=lambda: (_ for _ in ()).throw(RuntimeError("untrusted-private-response")))
        for modules in ({"requests": None}, {"requests": types.SimpleNamespace(), "gdrive": fake_drive}):
            with tempfile.TemporaryDirectory() as tmp, patch.dict("sys.modules", modules), patch.object(runner, "generate") as generate:
                with self.assertRaises(runner.SafeStop) as caught:
                    runner.execute(value, summary, Path(tmp) / "out", "synthetic", evidence(summary),
                                   before_synthesis=runner.preflight_drive)
                generate.assert_not_called()
                self.assertNotIn("untrusted-private-response", str(caught.exception))

    def test_oauth_failure_is_sanitized_without_retry(self):
        fake_drive = types.SimpleNamespace(_token=lambda: (_ for _ in ()).throw(RuntimeError("synthetic-sensitive-message")))
        fake_requests = types.SimpleNamespace()
        with patch.dict("sys.modules", {"gdrive": fake_drive, "requests": fake_requests}):
            with self.assertRaises(runner.SafeStop) as caught:
                runner.upload_drive(Path("not-read"), "test")
            self.assertNotIn("synthetic-sensitive-message", str(caught.exception))

    def test_create_only_upload_and_metadata_verification(self):
        class Response:
            def __init__(self, value):
                self.value = value
            def raise_for_status(self):
                pass
            def json(self):
                return self.value

        class Session:
            def __init__(self, output):
                self.headers, self.posted, self.output = {}, [], output
            def post(self, url, **kwargs):
                self.posted.append((url, kwargs))
                self.assert_no_redirect(kwargs)
                return Response({"id": "folder", "parents": [runner.DRIVE_PARENT]} if len(self.posted) == 1 else {"id": "file_" + str(len(self.posted))})
            @staticmethod
            def assert_no_redirect(kwargs):
                assert kwargs["allow_redirects"] is False
            def get(self, url, **kwargs):
                self.assert_no_redirect(kwargs)
                if url.endswith("/permissions"):
                    return Response({"permissions": [{"id": "owner", "type": "user", "role": "owner"}]})
                if url.endswith("/" + runner.DRIVE_PARENT) or url.endswith("/folder"):
                    return Response({"id": url.rsplit("/", 1)[1], "mimeType": "application/vnd.google-apps.folder", "trashed": False, "capabilities": {"canAddChildren": True}})
                index = int(url.rsplit("_", 1)[1]) - 2
                name = ["manifest.frozen.json", "state.json", "quota_evidence.json", "ep01_s01_xiaowen_p001.mp3", "ep01_s01_xiaowen_p001.receipt.json", "ep01_s01_narrator_p001.mp3", "ep01_s01_narrator_p001.receipt.json"][index]
                data = (self.output / name).read_bytes()
                return Response({"id": "file", "name": name, "parents": ["folder"], "size": str(len(data)), "md5Checksum": runner.hashlib.md5(data).hexdigest()})

        value = manifest()
        summary = runner.validate_manifest(value)
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "output"
            with patch.object(runner, "generate", return_value=b"synthetic-audio"):
                runner.execute(value, summary, output, "synthetic-not-secret", evidence(summary))
            # Unrelated/forbidden-named media must never be scanned or uploaded.
            (output / "Result-10.mp3").write_bytes(b"not-to-be-read")
            session = Session(output)
            fake_drive = types.SimpleNamespace(_token=lambda: "synthetic-not-secret", API="https://www.googleapis.com/drive/v3/files", UPLOAD="https://www.googleapis.com/upload/drive/v3/files", FOLDER="application/vnd.google-apps.folder")
            fake_requests = types.SimpleNamespace(Session=lambda: session)
            with patch.dict("sys.modules", {"gdrive": fake_drive, "requests": fake_requests}):
                runner.upload_drive(output, "test")
            receipt = runner.load_json(output / "drive_upload.json")
            self.assertEqual(len(receipt["files"]), 7)
            self.assertEqual(len(session.posted), 8)
            self.assertTrue(all(url.startswith("https://www.googleapis.com/") for url, _ in session.posted))

    def test_public_domain_or_unreadable_parent_causes_zero_creates(self):
        class Response:
            def __init__(self, value): self.value = value
            def raise_for_status(self): pass
            def json(self): return self.value

        for permissions in ([{"id": "public", "type": "anyone", "role": "reader"}],
                            [{"id": "domain", "type": "domain", "role": "reader"}], None, []):
            session = unittest.mock.Mock()
            session.headers = {}
            session.get.side_effect = [Response({"id": runner.DRIVE_PARENT, "mimeType": "application/vnd.google-apps.folder", "trashed": False, "capabilities": {"canAddChildren": True}}), Response({"permissions": permissions})]
            fake_drive = types.SimpleNamespace(_token=lambda: "synthetic", API="https://www.googleapis.com/drive/v3/files")
            fake_requests = types.SimpleNamespace(Session=lambda: session)
            with patch.dict("sys.modules", {"gdrive": fake_drive, "requests": fake_requests}):
                with self.assertRaises(runner.SafeStop):
                    runner.upload_drive(Path("never-read"), "test")
            session.post.assert_not_called()

    def test_new_folder_permissions_rechecked_before_any_media_upload(self):
        class Response:
            def __init__(self, value): self.value = value
            def raise_for_status(self): pass
            def json(self): return self.value
        session = unittest.mock.Mock()
        session.headers = {}
        meta = lambda fid: {"id": fid, "mimeType": "application/vnd.google-apps.folder", "trashed": False, "capabilities": {"canAddChildren": True}}
        session.get.side_effect = [Response(meta(runner.DRIVE_PARENT)), Response({"permissions": [{"id": "owner", "type": "user", "role": "owner"}]}), Response(meta("folder")), Response({"permissions": [{"id": "public", "type": "anyone", "role": "reader"}]})]
        session.post.return_value = Response({"id": "folder", "parents": [runner.DRIVE_PARENT]})
        fake_drive = types.SimpleNamespace(_token=lambda: "synthetic", API="https://www.googleapis.com/drive/v3/files", FOLDER="application/vnd.google-apps.folder")
        with patch.dict("sys.modules", {"gdrive": fake_drive, "requests": types.SimpleNamespace(Session=lambda: session)}):
            with self.assertRaises(runner.SafeStop):
                runner.upload_drive(Path("never-read"), "test")
        self.assertEqual(session.post.call_count, 1)  # Only the folder was created.


class CrossRunGateTests(unittest.TestCase):
    def setUp(self):
        # Synthetic manifests remain local to tests; production hashes stay frozen.
        batches = patch.dict(runner.BATCHES, {runner.BATCH_AUTHORIZATION_ID: {
            "workflow_path": runner.WORKFLOW_PATH,
            "manifest_sha256": runner.validate_manifest(manifest())["manifest_sha256"]}})
        batches.start()
        self.addCleanup(batches.stop)

    def environment(self, run_id):
        return {"GITHUB_ACTIONS": "true", "GITHUB_EVENT_NAME": "push", "GITHUB_REPOSITORY": runner.REPOSITORY,
                "GITHUB_RUN_ATTEMPT": "1", "GITHUB_REF": "refs/heads/claude/project-thread-l4wz3r",
                "GITHUB_RUN_ID": str(run_id), "GITHUB_SHA": "a" * 40}

    def history(self, ids):
        return {"total_count": len(ids), "workflow_runs": [{"id": rid, "run_attempt": 1, "workflow_id": 77,
                "head_sha": "a" * 40, "event": "push", "status": "in_progress"} for rid in ids]}

    def api(self, ids):
        return [{"id": 77, "path": runner.WORKFLOW_PATH, "state": "active"}, self.history(ids)]

    def test_two_independent_runs_same_evidence_cannot_regenerate_after_failure_or_success(self):
        value = manifest()
        summary = runner.validate_manifest(value)
        same_evidence = evidence(summary)
        for first_failed in (False, True):
            with tempfile.TemporaryDirectory() as tmp:
                first, second = Path(tmp) / "run101", Path(tmp) / "run102"
                with patch.dict(runner.os.environ, self.environment(101)), patch.object(runner, "github_read", side_effect=self.api([101])), patch.object(runner, "generate", side_effect=runner.SafeStop("synthetic") if first_failed else None, return_value=b"audio"), patch.object(runner, "print", create=True):
                    if first_failed:
                        with self.assertRaises(runner.SafeStop): runner.execute(value, summary, first, "synthetic", same_evidence)
                    else:
                        runner.execute(value, summary, first, "synthetic", same_evidence)
                # New empty runner directory and exactly the same manifest/evidence.
                with patch.dict(runner.os.environ, self.environment(102)), patch.object(runner, "github_read", side_effect=self.api([101, 102])), patch.object(runner, "generate") as generate:
                    with self.assertRaises(runner.SafeStop): runner.execute(value, summary, second, "synthetic", same_evidence)
                    generate.assert_not_called()
                    self.assertFalse(second.exists())

    def test_missing_or_incomplete_history_blocks_without_generation(self):
        value = manifest(); summary = runner.validate_manifest(value)
        for history in ({}, {"total_count": 0, "workflow_runs": []}, {"total_count": 1, "workflow_runs": [{}]}):
            with tempfile.TemporaryDirectory() as tmp, patch.dict(runner.os.environ, self.environment(101)), patch.object(runner, "github_read", side_effect=[{"id": 77, "path": runner.WORKFLOW_PATH, "state": "active"}, history]), patch.object(runner, "generate") as generate:
                with self.assertRaises(runner.SafeStop): runner.execute(value, summary, Path(tmp) / "out", "synthetic", evidence(summary))
                generate.assert_not_called()


class FrozenProductionInputTests(unittest.TestCase):
    def test_both_batches_match_frozen_sources_ids_lines_and_compiled_hashes(self):
        base = MODULE_PATH.parent
        provenance = json.loads((base / "r06_frozen/provenance.json").read_text())
        voice_bytes = (base / "r06_frozen/voice_lines_r06.json").read_bytes()
        script_bytes = (base / "r06_frozen/episode01_sound_production_r06.md").read_bytes()
        self.assertEqual(runner.digest(voice_bytes), provenance["source_voice_lines_sha256"])
        self.assertEqual(runner.digest(script_bytes), provenance["source_script_sha256"])
        source = json.loads(voice_bytes)["lines"]
        source_by_id = {line["id"]: line for line in source}
        script = script_bytes.decode().splitlines()
        found = []
        for number, expected_count, expected_characters in ((1, 20, 640), (2, 7, 198)):
            batch_id = f"ep01-role-tts-once-20261102-{number:02d}"
            value = json.loads((base / f"batches/batch{number:02d}/manifest.candidate.json").read_text())
            summary = runner.validate_manifest(value)
            self.assertEqual(summary["segments"], expected_count)
            self.assertEqual(summary["characters"], expected_characters)
            self.assertEqual(summary["manifest_sha256"], runner.BATCHES[batch_id]["manifest_sha256"])
            for segment in value["segments"]:
                original = source_by_id[segment["id"]]
                self.assertEqual(segment["text"], original["text"])
                self.assertIn(segment["text"], script[original["source_line"] - 1])
                self.assertGreaterEqual(len(segment["performance_context"]), 100)
                if segment["id"] == "S1_02":
                    self.assertEqual(segment["role"], "陆青禾_幼年")
                    self.assertEqual(segment["speaker"], "zh_male_tiancaitongsheng_uranus_bigtts")
                found.append(segment["id"])
        self.assertEqual(found, [row["id"] for row in source])

    def test_fixed_invalid_fixture_cannot_authorize_production(self):
        summary = runner.validate_manifest(manifest())
        invalid = json.loads((MODULE_PATH.parent / "tests/fixtures/quota_invalid.json").read_text())
        with self.assertRaises(runner.SafeStop):
            runner.validate_quota(invalid, summary)

    def test_suite_passes_with_valid_production_evidence_without_reading_it(self):
        original_read = Path.read_text
        production_reads = []
        def mocked_read(path, *args, **kwargs):
            if path.name in ("quota_evidence.pending.json", "quota_evidence.draft.json"):
                production_reads.append(path)
                value = json.loads(original_read(path.parent / "manifest.candidate.json"))
                summary = runner.validate_manifest(value)
                valid = evidence(summary)
                valid["authorization_id"] = "ep01-role-tts-once-20261102-" + path.parent.name[-2:]
                return json.dumps(valid)
            return original_read(path, *args, **kwargs)
        def flatten(suite):
            for test in suite:
                if isinstance(test, unittest.TestSuite):
                    yield from flatten(test)
                elif test.id() != self.id():
                    yield test
        suite = unittest.TestSuite(flatten(unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])))
        result = unittest.TestResult()
        with patch.object(Path, "read_text", mocked_read):
            # Establish that the mock production paths really hold valid evidence.
            # No real pending/draft file is opened by mocked_read.
            for number in (1, 2):
                folder = MODULE_PATH.parent / f"batches/batch{number:02d}"
                summary = runner.validate_manifest(json.loads(original_read(folder / "manifest.candidate.json")))
                runner.validate_quota(json.loads((folder / "quota_evidence.pending.json").read_text()), summary)
            production_reads.clear()
            suite.run(result)
        self.assertTrue(result.wasSuccessful(), result.errors + result.failures)
        self.assertGreater(result.testsRun, 20)
        self.assertEqual(production_reads, [], "Tests must not depend on mutable production quota paths")


if __name__ == "__main__":
    unittest.main()
