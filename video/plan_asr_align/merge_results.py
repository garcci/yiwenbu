"""Offline merge of actual pilot+remaining26 reports; never synthesizes timing."""
import argparse
import json
import math
from pathlib import Path

import runner as core


def merge(pilot, remaining):
    inputs = core.load_inputs()
    expected = {row["voice_id"]: row for row in inputs["segments"]}
    if (pilot.get("run_scope") != "pilot_S1_01_only" or remaining.get("run_scope") != "remaining26_excluding_S1_01"
            or len(pilot.get("segments", [])) != 1 or len(remaining.get("segments", [])) != 26):
        raise core.Stop("Need the actual one-pilot and complete 26-paragraph reports")
    rows = {}
    for report in (pilot, remaining):
        if report.get("inputs_sha256") != core.FROZEN_INPUT_SHA256 or report.get("time_unit") != "seconds":
            raise core.Stop("Report provenance/unit mismatch")
        for row in report["segments"]:
            sid = row.get("voice_id")
            if sid not in expected or sid in rows or row.get("audio_sha256") != expected[sid]["audio_sha256"]:
                raise core.Stop("Duplicate, unknown, or altered source audio in alignment report")
            if row.get("human_checked") is not False:
                raise core.Stop("Expected unchanged machine reports, not invented human approval")
            if row.get("auto_match"):
                if row.get("flags") or row.get("normalized_text_match") is not True or not row.get("words"):
                    raise core.Stop("Inconsistent automatic-match claim")
                last = 0
                for word in row["words"]:
                    start, end = word.get("start"), word.get("end")
                    if (type(start) not in (int, float) or type(end) not in (int, float)
                            or not math.isfinite(start) or not math.isfinite(end)
                            or not 0 <= last <= start < end <= row["duration_seconds"]):
                        raise core.Stop("Invalid word times; no interpolation allowed")
                    last = end
            rows[sid] = row
    if list(pilot["segments"])[0]["voice_id"] != "S1_01" or "S1_01" in [r["voice_id"] for r in remaining["segments"]]:
        raise core.Stop("Successful pilot must never be duplicated in remaining26")
    if set(rows) != set(expected):
        raise core.Stop("Incomplete episode coverage")
    ordered = [rows[row["voice_id"]] for row in inputs["segments"]]
    return {"schema_version": 1, "time_unit": "seconds", "inputs_sha256": core.FROZEN_INPUT_SHA256,
            "run_scope": "merged_actual_pilot_plus_remaining26", "segments": ordered,
            "coverage_complete_for_episode": True, "complete_for_episode": True, "human_checked": False,
            "auto_match_all": all(row.get("auto_match") is True for row in ordered),
            "review_required_ids": [row["voice_id"] for row in ordered if row.get("auto_match") is not True],
            "limitation": "Coverage is not listening approval. Do not automatically use rows with mismatch/missing timestamps."}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("pilot", type=Path)
    parser.add_argument("remaining", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise core.Stop("Merge output already exists; do not overwrite")
    result = merge(core.read_json(args.pilot), core.read_json(args.remaining))
    core.write_json(args.output, result)


if __name__ == "__main__":
    main()
