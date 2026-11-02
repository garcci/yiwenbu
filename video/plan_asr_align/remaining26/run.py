"""Prepared one-shot scope for the 26 originals after the successful S1_01 pilot."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

BASE = Path(__file__).resolve().parent
SCOPE_SHA256 = "18aa896e00619034d730bf09bd6509c1c0144a8d9cbb46b3264fd5ee05ff8e1e"
spec = importlib.util.spec_from_file_location("plan_asr_shared_core", BASE.parent / "runner.py")
core = importlib.util.module_from_spec(spec)
spec.loader.exec_module(core)


def load_scope():
    raw = (BASE / "scope.frozen.json").read_bytes()
    if hashlib.sha256(raw).hexdigest() != SCOPE_SHA256:
        raise core.Stop("Remaining26 selection changed")
    scope = json.loads(raw)
    inputs = core.load_inputs()
    expected_ids = [r["voice_id"] for r in inputs["segments"] if r["voice_id"] != "S1_01"]
    if (scope["voice_ids"] != expected_ids or len(scope["voice_ids"]) != 26
            or scope["excluded_voice_ids"] != ["S1_01"]
            or scope["inputs_sha256"] != core.FROZEN_INPUT_SHA256
            or scope["authorization_id"] != "ep01-plan-asr-r06-remaining26-20261102-01"
            or scope["workflow"] != "plan_asr_align_remaining26_once.yml"
            or scope["max_total_ms"] != 600000):
        raise core.Stop("Remaining26 scope does not match frozen originals")
    scope["scope_sha256"] = SCOPE_SHA256
    return inputs, scope


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    inputs, scope = load_scope()
    print("Remaining26 scope validated; S1_01 excluded; no network requests yet")
    if not args.execute:
        return 0
    expected = {"authorization_id": scope["authorization_id"], "inputs_sha256": core.FROZEN_INPUT_SHA256,
                "scope_sha256": SCOPE_SHA256}
    if core.read_json(BASE / "execute_once.json") != expected:
        raise core.Stop("Remaining26 trigger does not bind this exact selection")
    core.execute(inputs, core.read_json(BASE / "quota_evidence.pending.json"),
                 Path("plan-asr-remaining26-output"), scope=scope)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (core.Stop, core.ProtocolStop) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
    except Exception:
        print("Remaining26 stopped; no retry; raw exception suppressed", file=sys.stderr)
        sys.exit(1)
