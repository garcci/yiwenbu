"""Cloud-only, fixed-input Agent Plan ASR calibration. Default: offline validation."""
import argparse
from datetime import datetime, timezone
import difflib
import hashlib
import json
import logging
import math
import os
from pathlib import Path
import struct
import subprocess
import sys
import threading
import time
import unicodedata
import urllib.parse
import urllib.request
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
from protocol import ProtocolStop, decode, encode, full_request

BASE = Path(__file__).resolve().parent
ASR_URL = "wss://openspeech.bytedance.com/api/v3/plan/sauc/bigmodel_nostream"
RESOURCE = "volc.seedasr.sauc.duration"
FOLDERS = ("1izOd2bZjaCTlCq_NS0IVvBsHLZKCHHmQ", "1XBq5kFbvg4bKcDJi1v61VobkaGb5Ap2a")
FROZEN_INPUT_SHA256 = "f997b17d44424d7bfaa642b0b17c36868044fc3944f46b432b77a0b68b5a01c9"
AUTHORIZATION = "ep01-plan-asr-r06-pilot-20261102-01"
WORKFLOW = "plan_asr_align_once.yml"
REPOSITORY = "garcci/yiwenbu"
MAX_AUDIO_MS = 60000
MAX_TOTAL_MS = 60000
MAX_SEGMENTS = 27
PILOT_VOICE_ID = "S1_01"


class Stop(Exception):
    pass


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2).encode()
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(raw)
    temporary.replace(path)


def read_json(path):
    if path.is_symlink() or path.stat().st_size > 1024 * 1024:
        raise Stop("Unsafe JSON input")
    return json.loads(path.read_bytes())


def load_inputs():
    path = BASE / "inputs.frozen.json"
    raw = path.read_bytes()
    if sha(raw) != FROZEN_INPUT_SHA256:
        raise Stop("Frozen input was changed")
    value = json.loads(raw)
    if tuple(value["folders"]) != FOLDERS or len(value["segments"]) != MAX_SEGMENTS:
        raise Stop("Input scope differs from the two fixed TTS folders")
    ids = []
    for row in value["segments"]:
        sid = row["voice_id"]
        if not __import__("re").fullmatch(r"S[1-7]_[0-9]{2}", sid) or sid in ids:
            raise Stop("Invalid/duplicate fixed voice ID")
        if row["folder_id"] not in FOLDERS or row["audio_filename"] != sid + ".mp3" or row["receipt_filename"] != sid + ".receipt.json":
            raise Stop("Unexpected audio/reference file")
        ids.append(sid)
        frozen = (BASE / "receipts.frozen" / row["receipt_filename"]).read_bytes()
        validate_receipt(row, frozen)
    return value


def validate_receipt(row, raw):
    if sha(raw) != row["receipt_sha256"]:
        raise Stop("TTS receipt bytes differ from the frozen copy")
    receipt = json.loads(raw)
    for key, expected in (("resource", "seed-tts-2.0"), ("status", "completed"), ("request_count", 1),
                          ("audio_sha256", row["audio_sha256"]), ("audio_bytes", row["audio_bytes"]),
                          ("input_sha256", row["tts_input_sha256"]), ("github_run_id", row["tts_github_run_id"])):
        if receipt.get(key) != expected:
            raise Stop("TTS receipt provenance mismatch")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def http_bytes(url, headers=None, body=None, limit=1024 * 1024):
    try:
        request = urllib.request.Request(url, headers=headers or {}, data=body)
        with urllib.request.build_opener(NoRedirect).open(request, timeout=60) as response:
            data = response.read(limit + 1)
        if len(data) > limit:
            raise Stop("HTTP response exceeds fixed size limit")
        return data
    except Stop:
        raise
    except Exception:
        raise Stop("Read failed; raw response, URL and headers suppressed; no retry") from None


class FixedDriveReader:
    API = "https://www.googleapis.com/drive/v3/files/"

    def __init__(self, inputs):
        self.rows = {fid: row for row in inputs["segments"] for fid in (row["audio_file_id"], row["receipt_file_id"])}
        names = ("GDRIVE_CLIENT_ID", "GDRIVE_CLIENT_SECRET", "GDRIVE_REFRESH_TOKEN")
        if not all(os.environ.get(name, "").strip() for name in names):
            raise Stop("Drive credentials missing")
        body = urllib.parse.urlencode({"client_id": os.environ[names[0]], "client_secret": os.environ[names[1]],
                                       "refresh_token": os.environ[names[2]], "grant_type": "refresh_token"}).encode()
        response = json.loads(http_bytes("https://oauth2.googleapis.com/token", body=body,
                                        headers={"Content-Type": "application/x-www-form-urlencoded"}))
        token = response.get("access_token")
        if not isinstance(token, str) or not token:
            raise Stop("Drive OAuth failed")
        self.headers = {"Authorization": "Bearer " + token}

    def metadata(self, fid):
        if fid not in self.rows and fid not in FOLDERS:
            raise Stop("Drive ID is outside frozen scope")
        fields = "id,name,mimeType,size,parents,trashed"
        return json.loads(http_bytes(self.API + fid + "?" + urllib.parse.urlencode({"fields": fields}), self.headers))

    def private_folder(self, fid):
        if fid not in FOLDERS:
            raise Stop("Folder outside authorized scope")
        meta = self.metadata(fid)
        if meta.get("mimeType") != "application/vnd.google-apps.folder" or meta.get("trashed") is not False:
            raise Stop("Folder identity/type unconfirmed")
        page_token, seen, count = None, set(), 0
        while True:
            params = {"fields": "permissions(id,type,role),nextPageToken", "pageSize": 100}
            if page_token:
                params["pageToken"] = page_token
            page = json.loads(http_bytes(self.API + fid + "/permissions?" + urllib.parse.urlencode(params), self.headers))
            permissions = page.get("permissions")
            if not isinstance(permissions, list):
                raise Stop("Folder audience cannot be confirmed")
            for permission in permissions:
                if (not permission.get("id") or permission.get("type") not in ("user", "group")
                        or permission.get("role") not in ("owner", "organizer", "fileOrganizer", "writer", "commenter", "reader")):
                    raise Stop("Public/domain/unknown audience; no audio downloaded")
                count += 1
            page_token = page.get("nextPageToken")
            if not page_token:
                break
            if page_token in seen or len(seen) > 100:
                raise Stop("Folder permission pagination uncertain")
            seen.add(page_token)
        if not count:
            raise Stop("Empty folder permissions are not a private-audience proof")

    def download(self, row, receipt=False):
        fid = row["receipt_file_id"] if receipt else row["audio_file_id"]
        if fid not in self.rows or self.rows[fid] != row:
            raise Stop("Drive audio/reference expansion forbidden")
        meta = self.metadata(fid)
        expected_name = row["receipt_filename"] if receipt else row["audio_filename"]
        expected_sha = row["receipt_sha256"] if receipt else row["audio_sha256"]
        expected_size = None if receipt else row["audio_bytes"]
        if (meta.get("name") != expected_name or meta.get("parents") != [row["folder_id"]]
                or meta.get("trashed") is not False):
            raise Stop("Drive file moved/renamed or is outside frozen folder")
        if expected_size is not None and int(meta["size"]) != expected_size:
            raise Stop("Drive original audio byte count changed")
        data = http_bytes(self.API + fid + "?alt=media", self.headers, limit=4096 if receipt else 8 * 1024 * 1024)
        if sha(data) != expected_sha:
            raise Stop("Drive original/receipt SHA mismatch")
        return data


def decode_pcm(path):
    # Cloud ffmpeg decoding/resampling only: no model, trimming, stretching or denoising.
    process = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(path), "-ac", "1", "-ar", "16000",
                              "-f", "s16le", "-t", "61", "pipe:1"], capture_output=True, timeout=60)
    if process.returncode or not process.stdout or len(process.stdout) % 2:
        raise Stop("Original audio could not be fully decoded")
    duration = len(process.stdout) / 32
    if not 0 < duration <= MAX_AUDIO_MS:
        raise Stop("Audio duration exceeds per-paragraph cap")
    return process.stdout


def recognize(pcm, key):
    import websocket
    websocket.enableTrace(False)
    logging.getLogger("websocket").disabled = True
    connection_id = str(uuid.uuid4())
    headers = {"X-Api-Key": key, "X-Api-Resource-Id": RESOURCE,
               "X-Api-Request-Id": connection_id, "X-Api-Connect-Id": connection_id, "X-Api-Sequence": "-1"}
    ws, packets, events, failure = None, [], [], []
    done = threading.Event()
    try:
        ws = websocket.create_connection(ASR_URL, header=headers, timeout=20, redirect_limit=0,
                                         enable_multithread=True, suppress_origin=True)
        if ws.status != 101:
            raise Stop("ASR handshake did not upgrade; no redirect or retry")
        def receive():
            try:
                total = 0
                for _ in range(4096):
                    raw = ws.recv()
                    parsed = decode(raw)
                    total += len(raw)
                    if total > 16 * 1024 * 1024:
                        raise Stop("ASR responses exceed cap")
                    packets.append(raw)
                    events.append(parsed)
                    if parsed["final"]:
                        return
                raise Stop("ASR frame count exceeds cap")
            except Exception as exc:
                failure.append(type(exc).__name__)
            finally:
                done.set()
        receiver = threading.Thread(target=receive, daemon=True)
        receiver.start()
        ws.send_binary(full_request())
        chunk = 6400  # 200 ms of 16kHz, mono, signed 16-bit PCM.
        for offset in range(0, len(pcm), chunk):
            if done.is_set():
                raise Stop("ASR ended before all audio was sent; no retry")
            final = offset + chunk >= len(pcm)
            ws.send_binary(encode(2, offset // chunk + 2, pcm[offset:offset + chunk], final=final))
            if not final:
                time.sleep(0.2)
        if not done.wait(90) or failure or not events or not events[-1]["final"]:
            raise Stop("ASR failed or final marker missing; outcome uncertain; no retry")
        return events, packets
    except Stop:
        raise
    except Exception:
        raise Stop("ASR connection/protocol failed; raw response suppressed; no retry") from None
    finally:
        if ws is not None:
            try:
                ws.close()
            except Exception:
                pass


def normalized(text):
    return "".join(c for c in text if not c.isspace() and not unicodedata.category(c).startswith("P"))


def compare(row, final_payload, duration_ms):
    result = final_payload.get("result", {})
    if not isinstance(result, dict) or not isinstance(result.get("text"), str):
        raise Stop("ASR final result missing transcription")
    transcript = result["text"]
    expected, actual = normalized(row["expected_text"]), normalized(transcript)
    flags, words, utterances, previous_end = [], [], [], 0
    raw_utterances = result.get("utterances")
    if not isinstance(raw_utterances, list) or not raw_utterances:
        flags.append("missing_utterances")
        raw_utterances = []
    for utterance in raw_utterances:
        if not isinstance(utterance, dict) or utterance.get("definite") is not True:
            flags.append("utterance_not_definite")
            continue
        start, end = utterance.get("start_time"), utterance.get("end_time")
        if type(start) is not int or type(end) is not int or not 0 <= start < end <= duration_ms:
            flags.append("invalid_utterance_timestamp")
        else:
            utterances.append({"text": utterance.get("text", ""), "start": start / 1000, "end": end / 1000})
        raw_words = utterance.get("words")
        if not isinstance(raw_words, list) or not raw_words:
            flags.append("missing_word_timestamps")
            continue
        for word in raw_words:
            if not isinstance(word, dict):
                flags.append("invalid_word_record")
                continue
            start, end, text = word.get("start_time"), word.get("end_time"), word.get("text")
            utterance_start, utterance_end = utterance.get("start_time"), utterance.get("end_time")
            if (type(start) is not int or type(end) is not int or not isinstance(text, str) or not text
                    or not 0 <= previous_end <= start < end <= duration_ms
                    or type(utterance_start) is not int or type(utterance_end) is not int
                    or not utterance_start <= start < end <= utterance_end):
                flags.append("invalid_or_overlapping_word_timestamp")
                continue
            previous_end = end
            words.append({"text": text, "start": start / 1000, "end": end / 1000})
    if not words:
        flags.append("missing_word_timestamps")
    if normalized("".join(w["text"] for w in words)) != actual:
        flags.append("word_text_does_not_cover_transcript")
    if expected != actual:
        flags.append("transcript_differs_from_frozen_text")
    differences = [{"operation": op, "expected": expected[a:b], "recognized": actual[c:d],
                    "expected_span": [a, b], "recognized_span": [c, d]}
                   for op, a, b, c, d in difflib.SequenceMatcher(None, expected, actual).get_opcodes() if op != "equal"]
    return {"voice_id": row["voice_id"], "audio_sha256": row["audio_sha256"],
            "words": words, "utterances": utterances, "expected_text": row["expected_text"],
            "recognized_text": transcript, "exact_text_match": row["expected_text"] == transcript,
            "normalized_text_match": expected == actual, "auto_match": not flags,
            "flags": sorted(set(flags)), "differences": differences,
            "duration_seconds": duration_ms / 1000, "human_checked": False,
            "quality_note": "ASR comparison only; not listening approval or guaranteed word synchronization"}


def quota_check(evidence, now=None):
    if evidence.get("draft_only") is True:
        raise Stop("Draft ASR evidence is not executable")
    try:
        observed = datetime.fromisoformat(evidence["confirmed_at_utc"].replace("Z", "+00:00"))
        age = ((now or datetime.now(timezone.utc)) - observed).total_seconds()
        if not 0 <= age <= 3600:
            raise Stop("ASR quota evidence is stale/future-dated")
        if evidence["authorization_id"] != AUTHORIZATION or evidence["inputs_sha256"] != FROZEN_INPUT_SHA256:
            raise Stop("ASR evidence authorizes a different frozen input")
        for field in ("actions_zero_budget_blocks_overage", "actions_storage_within_free_allowance",
                      "asr_included_in_agent_plan", "asr_overage_disabled", "asr_audio_budget_verified"):
            if evidence[field] is not True:
                raise Stop("ASR zero-cost facts are not confirmed")
        used, included, afp = (evidence[k] for k in ("actions_compute_used_usd", "actions_compute_included_usd", "volc_afp_remaining"))
        if any(type(v) not in (int, float) or not math.isfinite(v) for v in (used, included, afp)):
            raise Stop("Invalid ASR budget snapshot")
        if used < 0 or included - used < .5 or afp <= 0:
            raise Stop("Insufficient confirmed included budget")
        if evidence["approved_max_connections"] != 1 or evidence["approved_max_audio_ms"] != MAX_TOTAL_MS:
            raise Stop("ASR request/duration budget differs from fixed caps")
    except (KeyError, TypeError, ValueError, OverflowError):
        raise Stop("Malformed ASR quota evidence") from None


def first_run_gate():
    env = os.environ
    if (env.get("GITHUB_ACTIONS") != "true" or env.get("GITHUB_EVENT_NAME") != "push"
            or env.get("GITHUB_REPOSITORY") != REPOSITORY or env.get("GITHUB_RUN_ATTEMPT") != "1"
            or env.get("GITHUB_REF") != "refs/heads/claude/project-thread-l4wz3r"):
        raise Stop("ASR execution requires this dedicated first cloud push run")
    token = env.get("GITHUB_TOKEN")
    if not token:
        raise Stop("Actions read token missing")
    headers = {"Authorization": "Bearer " + token, "Accept": "application/vnd.github+json"}
    base = "https://api.github.com/repos/" + REPOSITORY + "/actions/workflows/" + WORKFLOW
    workflow = json.loads(http_bytes(base, headers))
    history = json.loads(http_bytes(base + "/runs?per_page=100&page=1", headers))
    runs = history.get("workflow_runs")
    if workflow.get("path") != ".github/workflows/" + WORKFLOW or history.get("total_count") != 1 or not isinstance(runs, list) or len(runs) != 1:
        raise Stop("ASR workflow has another run or uncertain history; no replay")
    run = runs[0]
    if (str(run.get("id")) != env.get("GITHUB_RUN_ID") or run.get("run_attempt") != 1
            or run.get("head_sha") != env.get("GITHUB_SHA") or run.get("workflow_id") != workflow.get("id")
            or run.get("event") != "push" or run.get("status") != "in_progress"):
        raise Stop("ASR current first-run identity unconfirmed")


def execute(inputs, evidence, output):
    quota_check(evidence)
    first_run_gate()
    key = os.environ.get("ARK_API_KEY", "").strip()
    if not key:
        raise Stop("Package API secret missing")
    if output.exists():
        raise Stop("ASR output already exists; stop rather than replay or overwrite")
    import websocket  # dependency preflight before any audio or ASR connection
    if not callable(getattr(websocket, "create_connection", None)):
        raise Stop("WebSocket dependency unavailable")
    drive = FixedDriveReader(inputs)
    selected = [row for row in inputs["segments"] if row["voice_id"] == PILOT_VOICE_ID]
    if len(selected) != 1:
        raise Stop("Fixed one-paragraph pilot is missing")
    for folder in {row["folder_id"] for row in selected}:
        drive.private_folder(folder)
    output.mkdir()
    original_dir = output / "originals"
    original_dir.mkdir()
    prepared, total_ms = [], 0
    # Pilot only: never identify all 27 before the first real protocol check.
    for row in selected:
        receipt = drive.download(row, receipt=True)
        validate_receipt(row, receipt)
        original = drive.download(row)
        path = original_dir / row["audio_filename"]
        path.write_bytes(original)
        (original_dir / row["receipt_filename"]).write_bytes(receipt)
        pcm = decode_pcm(path)
        total_ms += len(pcm) / 32
        if total_ms > MAX_TOTAL_MS:
            raise Stop("Total audio exceeds approved ASR duration")
        prepared.append((row, pcm))
    report = {"schema_version": 1, "time_unit": "seconds", "inputs_sha256": FROZEN_INPUT_SHA256,
              "run_scope": "pilot_S1_01_only", "expected_segments": 1,
              "source_total_segments": MAX_SEGMENTS, "complete_for_episode": False,
              "segments": [], "human_checked": False, "auto_match_all": False}
    state = {"authorization_id": AUTHORIZATION, "inputs_sha256": FROZEN_INPUT_SHA256,
             "actual_audio_ms": total_ms, "segments": {}, "human_checked": False}
    write_json(output / "state.json", state)
    write_json(output / "quota_evidence.json", evidence)
    for row, pcm in prepared:
        sid = row["voice_id"]
        state["segments"][sid] = "started_outcome_uncertain"
        write_json(output / "state.json", state)
        events, packets = recognize(pcm, key)
        # Preserve original successful binary responses and all decoded ASR events privately.
        (output / (sid + ".frames.bin")).write_bytes(b"".join(struct.pack(">I", len(p)) + p for p in packets))
        write_json(output / (sid + ".events.json"), events)
        aligned = compare(row, events[-1]["payload"], len(pcm) / 32)
        report["segments"].append(aligned)
        state["segments"][sid] = "recognized_auto_match" if aligned["auto_match"] else "recognized_review_required"
        write_json(output / "alignment.json", report)
        write_json(output / "state.json", state)
        print("ASR paragraph completed; human_checked=false")
    report["auto_match_all"] = all(s["auto_match"] for s in report["segments"])
    write_json(output / "alignment.json", report)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    inputs = load_inputs()
    print("Frozen 27-paragraph provenance validated; executable scope is only S1_01 pilot; zero requests yet")
    if not args.execute:
        return 0
    request = read_json(BASE / "execute_once.json")
    if request != {"authorization_id": AUTHORIZATION, "inputs_sha256": FROZEN_INPUT_SHA256}:
        raise Stop("ASR trigger does not bind the frozen audio set")
    execute(inputs, read_json(BASE / "quota_evidence.pending.json"), Path("plan-asr-output"))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (Stop, ProtocolStop) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
    except Exception:
        print("ASR stopped; raw exception/response suppressed; no retry", file=sys.stderr)
        sys.exit(1)
