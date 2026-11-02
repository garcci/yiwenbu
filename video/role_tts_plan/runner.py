"""Role/paragraph TTS; preparation is offline, execution requires fresh quota evidence."""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import urllib.error
import urllib.request
import uuid

TTS_URL = "https://openspeech.bytedance.com/api/v3/plan/tts/unidirectional"
RESOURCE = "seed-tts-2.0"
DRIVE_PARENT = "11uMWY64q_tLolJ210NmLhfqnkW1D5fBR"
MAX_SEGMENTS = 20
MAX_SEGMENT_CHARACTERS = 1000
MAX_TOTAL_CHARACTERS = 8000
MAX_RESPONSE_BYTES = 16 * 1024 * 1024
FORBIDDEN_REFERENCE_NAMES = {"result-10", "result-4", "未命名"}
BATCH_AUTHORIZATION_ID = "ep01-role-tts-once-20261102-01"
WORKFLOW_PATH = ".github/workflows/role_tts_plan.yml"
REPOSITORY = "garcci/yiwenbu"
BATCHES = {
    "ep01-role-tts-once-20261102-01": {
        "workflow_path": WORKFLOW_PATH,
        "manifest_sha256": "9147640684bda6bdc88f56dbf7b8b704d01343aed40cfde502088c36901fdca9",
    },
    "ep01-role-tts-once-20261102-02": {
        "workflow_path": ".github/workflows/role_tts_plan_batch02.yml",
        "manifest_sha256": "6c45872ff0ef53569c904108e4e6a3c5f2d5674350d14cc9f934cd8351854a9d",
    },
}


class SafeStop(Exception):
    """Only messages authored by this module may be printed."""


def digest(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def write_json(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(canonical(value))
    temporary.replace(path)


def load_json(path):
    if path.is_symlink() or path.stem.casefold() in FORBIDDEN_REFERENCE_NAMES:
        raise SafeStop("Forbidden reference or symlink input")
    if path.stat().st_size > 512 * 1024:
        raise SafeStop("JSON input too large")
    return json.loads(path.read_text(encoding="utf-8"))


def validate_manifest(manifest):
    if set(manifest) != {"schema_version", "project", "approval_state", "segments"} or manifest["schema_version"] != 1:
        raise SafeStop("Unexpected manifest schema")
    if manifest["approval_state"] not in ("draft", "approved"):
        raise SafeStop("Invalid approval state")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,60}", manifest["project"]):
        raise SafeStop("Invalid project ID")
    segments = manifest["segments"]
    if not isinstance(segments, list) or not 1 <= len(segments) <= MAX_SEGMENTS:
        raise SafeStop("Segment count outside hard limit")
    ids, total, role_voices = set(), 0, {}
    for segment in segments:
        if set(segment) != {"id", "role", "text", "speaker", "performance_context", "rhythm"}:
            raise SafeStop("Unexpected segment schema; audio/reference inputs are not accepted")
        sid = segment["id"]
        if (not re.fullmatch(r"[A-Za-z0-9_-]{1,60}", sid) or sid in ids
                or sid.casefold() in FORBIDDEN_REFERENCE_NAMES):
            raise SafeStop("Segment IDs must be unique and path-safe")
        ids.add(sid)
        text = segment["text"]
        if not isinstance(text, str) or not text.strip() or text != text.strip():
            raise SafeStop("Text must be a nonempty natural paragraph")
        if len(text) > MAX_SEGMENT_CHARACTERS or any(c in text for c in "\r\n\x00"):
            raise SafeStop("Paragraph is multiline or exceeds hard limit")
        if not re.fullmatch(r"zh_[A-Za-z0-9_]{1,96}", segment["speaker"]):
            raise SafeStop("Invalid voice ID")
        for field, low, high in (("role", 1, 80), ("performance_context", 30, 1500)):
            value = segment[field]
            if not isinstance(value, str) or not low <= len(value.strip()) <= high:
                raise SafeStop("Missing role or detailed performance context")
        if segment["role"] in role_voices and role_voices[segment["role"]] != segment["speaker"]:
            raise SafeStop("One role must keep one reviewed voice within a batch")
        role_voices[segment["role"]] = segment["speaker"]
        rhythm = segment["rhythm"]
        if set(rhythm) != {"speech_rate", "direction"}:
            raise SafeStop("Unexpected rhythm schema")
        if type(rhythm["speech_rate"]) is not int or not -30 <= rhythm["speech_rate"] <= 30:
            raise SafeStop("Speech rate outside reviewed range")
        if not isinstance(rhythm["direction"], str) or not 5 <= len(rhythm["direction"].strip()) <= 500:
            raise SafeStop("Rhythm direction is required")
        total += len(text)
    if total > MAX_TOTAL_CHARACTERS:
        raise SafeStop("Total characters exceed hard limit")
    return {"manifest_sha256": digest(canonical(manifest)), "segments": len(segments), "characters": total}


def validate_quota(evidence, summary, now=None):
    """An attestation is a gate, not an independent online billing check."""
    if evidence.get("draft_only") is True:
        raise SafeStop("Draft quota evidence must not authorize generation")
    try:
        confirmed = datetime.fromisoformat(evidence["confirmed_at_utc"].replace("Z", "+00:00"))
        now = now or datetime.now(timezone.utc)
        age = (now - confirmed).total_seconds()
        if confirmed.utcoffset() is None or not 0 <= age <= 3600:
            raise SafeStop("Quota evidence is stale, future-dated or lacks timezone")
        if evidence["approved_manifest_sha256"] != summary["manifest_sha256"]:
            raise SafeStop("Quota evidence does not approve this exact manifest")
        if evidence["authorization_id"] not in BATCHES:
            raise SafeStop("One-time batch authorization ID does not match")
        for key in ("actions_zero_budget_blocks_overage", "actions_storage_within_free_allowance",
                    "volc_tts_overage_disabled", "volc_character_budget_verified"):
            if evidence[key] is not True:
                raise SafeStop("Required zero-cost evidence is not confirmed")
        if not evidence["source_note"].strip():
            raise SafeStop("Quota evidence needs a source note")
        for key, required in (("approved_max_requests", summary["segments"]),
                              ("approved_max_characters", summary["characters"])):
            if type(evidence[key]) is not int or evidence[key] < required:
                raise SafeStop("Approved request/character budget insufficient")
        used = evidence["actions_compute_used_usd"]
        included = evidence["actions_compute_included_usd"]
        if type(used) not in (int, float) or type(included) not in (int, float):
            raise SafeStop("Compute snapshot must contain numeric amounts, not inferred minutes")
        afp = float(evidence["volc_afp_remaining"])
        if (not math.isfinite(used) or not math.isfinite(included) or used < 0 or included <= 0
                or used > included or included - used < 0.50):
            raise SafeStop("Compute snapshot is invalid or has less than USD 0.50 included balance")
        if not math.isfinite(afp) or afp <= 0:
            raise SafeStop("No positive package balance confirmed")
    except (KeyError, TypeError, ValueError, OverflowError):
        raise SafeStop("Malformed quota evidence") from None


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def github_read(path):
    token = os.environ.get("GITHUB_TOKEN", "")
    if not token:
        raise SafeStop("Actions history read token is missing")
    request = urllib.request.Request("https://api.github.com/repos/" + REPOSITORY + path,
                                     headers={"Authorization": f"Bearer {token}",
                                              "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.build_opener(NoRedirect).open(request, timeout=30) as response:
            data = response.read(2 * 1024 * 1024 + 1)
        if len(data) > 2 * 1024 * 1024:
            raise SafeStop("Actions history response exceeds limit")
        return json.loads(data)
    except SafeStop:
        raise
    except Exception:
        raise SafeStop("Cannot establish Actions history; no generation permitted") from None


def require_single_push_run(summary, evidence):
    """Conservative one-push fallback, NOT a durable atomic consumption service.

    The dedicated workflow can be used only when its entire visible history is
    exactly the current push run. Deleted/rewritten GitHub history is outside
    this check's guarantees; never reuse this batch/workflow after a first run.
    """
    env = os.environ
    batch = BATCHES[evidence["authorization_id"]]
    workflow_path = batch["workflow_path"]
    if summary["manifest_sha256"] != batch["manifest_sha256"]:
        raise SafeStop("Manifest differs from this frozen one-time batch")
    if (env.get("GITHUB_ACTIONS") != "true" or env.get("GITHUB_EVENT_NAME") != "push"
            or env.get("GITHUB_REPOSITORY") != REPOSITORY or env.get("GITHUB_RUN_ATTEMPT") != "1"
            or env.get("GITHUB_REF") != "refs/heads/claude/project-thread-l4wz3r"):
        raise SafeStop("Generation is limited to this batch's first dedicated push run")
    try:
        run_id = int(env["GITHUB_RUN_ID"])
        sha = env["GITHUB_SHA"]
        workflow_name = workflow_path.rsplit("/", 1)[1]
        workflow = github_read("/actions/workflows/" + workflow_name)
        if workflow.get("path") != workflow_path or workflow.get("state") != "active":
            raise SafeStop("Dedicated workflow identity is uncertain")
        history = github_read("/actions/workflows/" + workflow_name + "/runs?per_page=100&page=1")
        runs = history.get("workflow_runs")
        if history.get("total_count") != 1 or not isinstance(runs, list) or len(runs) != 1:
            raise SafeStop("Another run exists or workflow history is missing; batch is consumed or uncertain")
        current = runs[0]
        if (current.get("id") != run_id or current.get("run_attempt") != 1
                or current.get("workflow_id") != workflow["id"] or current.get("head_sha") != sha
                or current.get("event") != "push" or current.get("status") != "in_progress"):
            raise SafeStop("Current first-run identity cannot be confirmed")
        return {"authorization_id": evidence["authorization_id"],
                "manifest_sha256": summary["manifest_sha256"], "run_id": run_id,
                "head_sha": sha, "gate": "single_visible_push_history_not_atomic_storage"}
    except (KeyError, TypeError, ValueError):
        raise SafeStop("Incomplete Actions history; no generation permitted") from None


def generate(segment, key):
    context = segment["performance_context"] + "\n节奏要求：" + segment["rhythm"]["direction"]
    payload = {"user": {"uid": "yiwenbu"}, "req_params": {
        "text": segment["text"], "speaker": segment["speaker"],
        "audio_params": {"format": "mp3", "sample_rate": 24000,
                         "speech_rate": segment["rhythm"]["speech_rate"]},
        "additions": json.dumps({"context_texts": [context]}, ensure_ascii=False)}}
    request = urllib.request.Request(TTS_URL, data=canonical(payload), headers={
        "Content-Type": "application/json", "Authorization": f"Bearer {key}",
        "X-Api-Key": key, "X-Api-Resource-Id": RESOURCE})
    try:
        with urllib.request.build_opener(NoRedirect).open(request, timeout=120) as response:
            blob = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raise SafeStop(f"Package HTTP {exc.code}; stopped without retry") from None
    except Exception:
        raise SafeStop("Package network error; outcome unknown; stopped without retry") from None
    if len(blob) > MAX_RESPONSE_BYTES:
        raise SafeStop("Response exceeds hard limit")
    try:
        audio, completed = bytearray(), False
        for line in blob.splitlines():
            if not line.strip():
                continue
            part = json.loads(line)
            code = part.get("code", 0)
            if code not in (0, 20000000):
                raise SafeStop("Package returned an error; no fallback or retry")
            if completed:
                raise SafeStop("Unexpected data after package completion")
            if part.get("data"):
                audio.extend(base64.b64decode(part["data"], validate=True))
            if code == 20000000:
                completed = True
        if not audio or not completed:
            raise SafeStop("Missing audio or completion marker; no retry")
        return bytes(audio)
    except (ValueError, TypeError, AttributeError):
        raise SafeStop("Invalid package response; raw content suppressed") from None


def execute(manifest, summary, output, key, quota_evidence, before_synthesis=None):
    if manifest["approval_state"] != "approved":
        raise SafeStop("Draft/example manifest must not generate audio")
    validate_quota(quota_evidence, summary)
    run_gate = require_single_push_run(summary, quota_evidence)
    if not key.strip():
        raise SafeStop("ARK_API_KEY is missing")
    if output.is_symlink():
        raise SafeStop("Symlink output directory is forbidden")
    if before_synthesis is not None:
        # OAuth/dependency/audience failures must happen before any TTS request.
        before_synthesis()
    output.mkdir(parents=True, exist_ok=True)
    state_path = output / "state.json"
    if state_path.exists():
        state = load_json(state_path)
        if state.get("manifest_sha256") != summary["manifest_sha256"]:
            raise SafeStop("Output belongs to a different manifest")
        if any(s.get("status") != "completed" for s in state["segments"].values()):
            raise SafeStop("Prior request has failed or uncertain outcome; manual review required")
    else:
        # A directory with unrelated outputs must never be reused or overwritten.
        if any(output.iterdir()):
            raise SafeStop("Output directory is not empty")
        state = {**summary, "segments": {}, "quality": "not listened or approved"}
        state["single_push_run"] = run_gate
        write_json(output / "manifest.frozen.json", manifest)
        write_json(output / "quota_evidence.json", quota_evidence)
        write_json(state_path, state)
    # Keep all fresh attestations when resuming; do not overwrite the first evidence snapshot.
    evidence_hash = digest(canonical(quota_evidence))
    state.setdefault("quota_evidence_history", {})[evidence_hash] = quota_evidence
    write_json(state_path, state)
    for segment in manifest["segments"]:
        sid = segment["id"]
        path = output / (sid + ".mp3")
        existing = state["segments"].get(sid)
        if existing:
            if path.is_symlink() or not path.exists() or digest(path.read_bytes()) != existing["audio_sha256"]:
                raise SafeStop("Completed audio missing or changed; stop, do not regenerate")
            continue
        if path.exists():
            raise SafeStop("Untracked audio exists; stop, do not overwrite")
        # Persist before POST: interruption/timeout must not silently charge a second request.
        state["segments"][sid] = {"status": "started", "request_count": 1}
        write_json(state_path, state)
        try:
            audio = generate(segment, key)
            with path.open("xb") as stream:
                stream.write(audio)
            record = {"status": "completed", "request_count": 1, "role": segment["role"],
                      "speaker": segment["speaker"], "characters": len(segment["text"]),
                      "input_sha256": digest(canonical(segment)), "audio_sha256": digest(audio),
                      "audio_bytes": len(audio), "resource": RESOURCE,
                      "quota_evidence_sha256": evidence_hash,
                      "authorization_id": quota_evidence["authorization_id"], "github_run_id": run_gate["run_id"],
                      "completed_at_utc": datetime.now(timezone.utc).isoformat(),
                      "quality": "not listened or approved"}
            write_json(output / (sid + ".receipt.json"), record)
            state["segments"][sid] = record
            write_json(state_path, state)
            print("Completed one paragraph; listening approval pending")
        except Exception:
            state["segments"][sid]["status"] = "failed_or_uncertain"
            write_json(state_path, state)
            raise
    return state


def require_private_folder(session, api, folder_id):
    """Fail closed if effective audience or destination type cannot be read."""
    response = session.get(api + "/" + folder_id,
                           params={"fields": "id,mimeType,trashed,capabilities(canAddChildren)",
                                   "supportsAllDrives": "true"}, timeout=30, allow_redirects=False)
    response.raise_for_status()
    meta = response.json()
    if (meta.get("id") != folder_id or meta.get("mimeType") != "application/vnd.google-apps.folder"
            or meta.get("trashed") is not False or meta.get("capabilities", {}).get("canAddChildren") is not True):
        raise SafeStop("Drive destination type or write capability is unconfirmed")
    token, seen, count = None, set(), 0
    while True:
        params = {"fields": "permissions(id,type,role,deleted),nextPageToken", "pageSize": 100,
                  "supportsAllDrives": "true"}
        if token:
            params["pageToken"] = token
        response = session.get(api + "/" + folder_id + "/permissions", params=params,
                               timeout=30, allow_redirects=False)
        response.raise_for_status()
        page = response.json()
        permissions = page.get("permissions")
        if not isinstance(permissions, list):
            raise SafeStop("Drive permissions are not readable")
        for permission in permissions:
            if (not permission.get("id") or permission.get("type") not in ("user", "group")
                    or permission.get("role") not in ("owner", "organizer", "fileOrganizer", "writer", "commenter", "reader")
                    or permission.get("deleted") is True):
                raise SafeStop("Public/domain/unknown Drive permission; no upload permitted")
            count += 1
        token = page.get("nextPageToken")
        if not token:
            break
        if token in seen or len(seen) >= 100:
            raise SafeStop("Drive permission pagination is uncertain")
        seen.add(token)
    if not count:
        raise SafeStop("Empty Drive permissions cannot establish private audience")


def preflight_drive():
    """Read-only readiness check: imports, OAuth, destination metadata/permissions."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    try:
        import requests
        import gdrive
        if not all(os.environ.get(name, "").strip() for name in
                   ("GDRIVE_CLIENT_ID", "GDRIVE_CLIENT_SECRET", "GDRIVE_REFRESH_TOKEN")):
            raise SafeStop("Drive credentials are missing; no TTS requested")
        token = gdrive._token()
        if not isinstance(token, str) or not token.strip():
            raise SafeStop("Drive OAuth did not establish a session; no TTS requested")
        session = requests.Session()
        session.headers.update({"Authorization": f"Bearer {token}"})
        require_private_folder(session, gdrive.API, DRIVE_PARENT)
        return gdrive, session
    except SafeStop:
        raise
    except Exception:
        raise SafeStop("Drive read-only preflight failed; no TTS requested; raw error suppressed") from None


def upload_drive(output, project, context=None):
    """Create-only uploads; reuse the preflight session without persisting tokens."""
    try:
        if context is None:
            gdrive, session = preflight_drive()
        else:
            gdrive, session = context
            # Recheck after synthesis: the audience may have changed in between.
            require_private_folder(session, gdrive.API, DRIVE_PARENT)
        response = session.post(gdrive.API, json={
            "name": f"{project}-tts-{uuid.uuid4().hex}", "mimeType": gdrive.FOLDER,
            "parents": [DRIVE_PARENT]}, params={"fields": "id,parents"},
            timeout=30, allow_redirects=False)
        response.raise_for_status()
        folder = response.json()
        if folder.get("parents") != [DRIVE_PARENT] or not re.fullmatch(r"[\w-]+", folder["id"]):
            raise SafeStop("Unexpected Drive destination")
        require_private_folder(session, gdrive.API, folder["id"])
        uploaded = []
        # Upload only files belonging to this validated manifest, never scan unrelated media.
        frozen = load_json(output / "manifest.frozen.json")
        validate_manifest(frozen)
        files = [output / name for name in ("manifest.frozen.json", "state.json", "quota_evidence.json")]
        for segment in frozen["segments"]:
            files.extend([output / (segment["id"] + ".mp3"), output / (segment["id"] + ".receipt.json")])
        for path in files:
            if path.is_symlink():
                raise SafeStop("Symlink upload input is forbidden")
            data = path.read_bytes()
            boundary = "tts_" + uuid.uuid4().hex
            metadata = canonical({"name": path.name, "parents": [folder["id"]]})
            mime = "audio/mpeg" if path.suffix == ".mp3" else "application/json"
            body = (f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n".encode()
                    + metadata + f"\r\n--{boundary}\r\nContent-Type: {mime}\r\n\r\n".encode()
                    + data + f"\r\n--{boundary}--\r\n".encode())
            response = session.post(gdrive.UPLOAD, params={"uploadType": "multipart", "fields": "id"},
                                    headers={"Content-Type": f"multipart/related; boundary={boundary}"},
                                    data=body, timeout=120, allow_redirects=False)
            response.raise_for_status()
            fid = response.json()["id"]
            if not re.fullmatch(r"[\w-]+", fid):
                raise SafeStop("Invalid Drive file ID")
            response = session.get(gdrive.API + "/" + fid,
                                   params={"fields": "id,name,size,md5Checksum,parents"},
                                   timeout=30, allow_redirects=False)
            response.raise_for_status()
            meta = response.json()
            if (meta.get("name") != path.name or meta.get("parents") != [folder["id"]]
                    or int(meta["size"]) != len(data)
                    or meta.get("md5Checksum") != hashlib.md5(data).hexdigest()):
                raise SafeStop("Drive metadata mismatch")
            uploaded.append({"name": path.name, "id": fid})
            write_json(output / "drive_upload.json", {"folder_id": folder["id"], "files": uploaded})
        print("https://drive.google.com/drive/folders/" + folder["id"])
    except SafeStop:
        raise
    except Exception:
        raise SafeStop("Drive upload stopped; no retry; original audio retained in artifact") from None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--quota-evidence", type=Path)
    parser.add_argument("--request", type=Path)
    parser.add_argument("--output", type=Path, default=Path("role-tts-output"))
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--upload-drive", action="store_true")
    args = parser.parse_args()
    manifest = load_json(args.manifest)
    summary = validate_manifest(manifest)
    print(json.dumps(summary))
    if not args.execute:
        print("Offline validation only; zero network requests")
        return 0
    if not args.quota_evidence or not args.request:
        raise SafeStop("Fresh quota evidence and the one-time trigger request are required")
    quota = load_json(args.quota_evidence)
    request = load_json(args.request)
    if (set(request) != {"authorization_id", "manifest_sha256"}
            or request["authorization_id"] != quota.get("authorization_id")
            or request["manifest_sha256"] != summary["manifest_sha256"]):
        raise SafeStop("One-time trigger does not bind this exact batch")
    drive_context = None
    def before_synthesis():
        nonlocal drive_context
        drive_context = preflight_drive()
    execute(manifest, summary, args.output, os.environ.get("ARK_API_KEY", ""),
            quota, before_synthesis=before_synthesis if args.upload_drive else None)
    if args.upload_drive:
        upload_drive(args.output, manifest["project"], context=drive_context)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SafeStop as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
    except Exception:
        print("Stopped safely; raw exception and response suppressed", file=sys.stderr)
        sys.exit(1)
