# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Round-trip and drift guarantees of the real-result replay bundle.

The bundle is the test-only bridge between a real Runner result and the
frontend-visible API surface. These tests assert that the bridge preserves the
canonical semantics it exists to carry -- manifest identity, artifact bytes,
logical-file identity, view declarations, task scoping -- and that it fails
loudly when the bytes, the contract, or the declared views no longer agree.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from frontend_fixtures import (
    PROVENANCE_SOURCE,
    REPLAY_BUNDLE_KIND,
    REPLAY_BUNDLE_VERSION,
    OutputCheckSpec,
    ProvenanceError,
    ReplayBundle,
    ReplayBundleError,
    build_result_manifest,
    capture_replay_bundle,
    load_bundle,
    normalize,
    production_receipt_pointer,
    project_manifest_for_serve,
    required_view_sources,
    view_entry,
    write_bundle,
)
from frontend_fixtures.models import ResultArtifactSpec, ResultFixture, StoryboardSpec

ROOT = Path(__file__).resolve().parents[1]
TASK_ID = "0123456789abcdef0123456789abcdef"
REAL_BUNDLE = ROOT / "tests" / "data" / "gremlin_lh_replay" / "2kl8_seed0_944ed43af62e.json"
GREMLIN_RECEIPT = (
    ROOT / "docker" / "runners" / "gremlin_lh" / "receipts"
    / "production-api-944ed43af62ead9f5c9560bae1ccd897.json"
)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _synthetic_fixture() -> ResultFixture:
    """A small canonical result fixture spanning matrix, table, text, JSON.

    ``output_check`` marks each declared view's source required, so the capture
    treats the matrix CSV, the ranked-pairs table, the alignment, and the JSON
    summary as bytes a replay must carry.
    """
    checks = tuple(
        (("view_id", view_id), ("source", source), ("required", True), ("status", "passed"), ("matched", len(paths)))
        for view_id, source, paths in (
            ("raw_couplings", "matrices", ("couplings/raw_scores.csv",)),
            ("ranked_pairs", "table", ("tables/pairs.tsv",)),
            ("filtered_alignment", "alignment", ("alignment/filtered_alignment.a3m",)),
            ("fit_summary", "data", ("summary.json",)),
        )
    )
    return ResultFixture(
        name="replay_sample",
        task_type="sequence_demo",
        output_check=OutputCheckSpec(state="passed", checks=checks),
        artifacts=(
            ResultArtifactSpec(
                "couplings/raw_scores.csv", role="primary", capability="table",
                media_type="text/csv", body="position,10,11\n10,0.0,0.51\n11,0.51,0.0\n",
            ),
            ResultArtifactSpec(
                "tables/pairs.tsv", role="evidence", capability="table",
                media_type="text/tab-separated-values",
                body="alignment_i\talignment_j\tapc_score\n10\t11\t0.42\n",
            ),
            ResultArtifactSpec(
                "alignment/filtered_alignment.a3m", role="evidence", capability="text",
                media_type="text/x-a3m", body=">seq1\nACDEFG\n>seq2\nACD-FG\n",
            ),
            ResultArtifactSpec(
                "summary.json", role="provenance", capability="text",
                media_type="application/json", body='{"alignment": {"sequence_count": 2}}\n',
            ),
            # An optional diagnostic referenced by no view: large enough that a
            # tight bundle budget drops it in favour of every required source.
            ResultArtifactSpec(
                "execution/slurm.stdout", role="diagnostic", capability="download_only",
                media_type="text/plain", body="o" * 4096,
            ),
        ),
        logical_files=(("raw_matrix", ("couplings/raw_scores.csv",)),),
        views=(
            view_entry("matrix", "raw_couplings", "Raw couplings", {"matrices": ["couplings/raw_scores.csv"]}, role="primary", row_labels_column="position", unit="coupling score", scale="sequential"),
            view_entry("entity-table", "ranked_pairs", "Ranked pairs", {"table": ["tables/pairs.tsv"]}, role="evidence"),
            view_entry("alignment", "filtered_alignment", "Filtered alignment", {"alignment": ["alignment/filtered_alignment.a3m"]}, role="evidence"),
            view_entry("scalar-summary", "fit_summary", "Summary", {"data": ["summary.json"]}, role="evidence", fields=[{"path": "alignment.sequence_count", "label": "MSA rows"}]),
        ),
        run_inputs=(("alignment", "alignment.a3m", "a3m"),),
    )


def _write_result_root(tmp_path: Path, fixture: ResultFixture, *, task_id: str = TASK_ID) -> Path:
    """Persist a canonical manifest plus real artifact bytes at a result root.

    The manifest's per-artifact ``size``/``sha256`` are recomputed from the
    bytes actually written, because the capture re-hashes them and refuses a
    bundle whose declared hash disagrees with disk.
    """
    root = tmp_path / "result"
    root.mkdir()
    manifest = build_result_manifest(fixture, task_id=task_id)
    by_path = {artifact["path"]: artifact for artifact in manifest["artifacts"]}
    for artifact in manifest["artifacts"]:
        spec = fixture.artifact_for(artifact["path"])
        body = (spec.body or "").encode("utf-8")
        target = root / artifact["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
        artifact["size"] = len(body)
        artifact["sha256"] = _sha(body)
    # The published on-disk manifest carries a resolved ``path``/``sha256``/``size``
    # on each ``result.files`` entry (the shape the Server's route reads); the
    # builder's in-memory logical projection omits them, so restore them here.
    for file_id, entries in manifest["result"]["files"].items():
        paths = fixture.logical_file_paths()[file_id]
        for index, entry in enumerate(entries):
            entry["path"] = paths[index]
            entry["sha256"] = by_path[paths[index]]["sha256"]
            entry["size"] = by_path[paths[index]]["size"]
    manifest["total_size"] = sum(artifact["size"] for artifact in manifest["artifacts"])
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    if fixture.storyboard is not None:
        storyboard = root / "storyboard"
        storyboard.mkdir()
        (storyboard / fixture.storyboard.entrypoint).write_text(
            fixture.storyboard.module_body or "export default { mount() { return {}; } };\n", encoding="utf-8"
        )
    return root


def _storyboard_fixture() -> ResultFixture:
    checks = ((("view_id", "raw_couplings"), ("source", "matrices"), ("required", True), ("status", "passed"), ("matched", 1)),)
    return ResultFixture(
        name="replay_storyboard",
        task_type="sequence_demo",
        output_check=OutputCheckSpec(state="passed", checks=checks),
        artifacts=(
            ResultArtifactSpec("couplings/raw_scores.csv", role="primary", capability="table", media_type="text/csv",
                               body="position,10\n10,0.0\n"),
        ),
        views=(view_entry("matrix", "raw_couplings", "Raw couplings", {"matrices": ["couplings/raw_scores.csv"]}, role="primary", row_labels_column="position"),),
        storyboard=StoryboardSpec(identifier="demo", entrypoint="index.js", requires=("raw_matrix",),
                                  module_body="export default { mount(host) { host.dataset.mounted = '1'; return { destroy() {} }; } };\n"),
    )


# ── capture schema ────────────────────────────────────────────────────────────


def test_capture_produces_a_versioned_bounded_bundle(tmp_path: Path) -> None:
    root = _write_result_root(tmp_path, _synthetic_fixture())
    bundle = capture_replay_bundle(require_finished=False, task_id=TASK_ID, result_root=root, display_name="alignment.a3m")
    assert bundle["bundle_version"] == REPLAY_BUNDLE_VERSION
    assert bundle["kind"] == REPLAY_BUNDLE_KIND
    assert bundle["task"] == {"id": TASK_ID, "type": "sequence_demo", "display_name": "alignment.a3m"}
    assert bundle["bundle_digest"].startswith("sha256:")
    # Every kept payload carries its own byte hash, and it matches the bytes.
    for path, entry in bundle["payloads"].items():
        assert _sha(entry["payload"].encode("utf-8")) == entry["sha256"], path
    assert load_bundle(bundle)["bundle_digest"] == bundle["bundle_digest"]


def test_capture_is_deterministic_for_the_same_result(tmp_path: Path) -> None:
    root = _write_result_root(tmp_path, _synthetic_fixture())
    first = capture_replay_bundle(require_finished=False, task_id=TASK_ID, result_root=root)
    second = capture_replay_bundle(require_finished=False, task_id=TASK_ID, result_root=root)
    assert first == second


# ── round-trip: capture -> bundle -> served projection ───────────────────────


def test_round_trip_preserves_the_served_manifest_after_normalization(tmp_path: Path) -> None:
    root = _write_result_root(tmp_path, _synthetic_fixture())
    published = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    bundle = capture_replay_bundle(require_finished=False, task_id=TASK_ID, result_root=root)
    served = ReplayBundle(bundle).served_manifest()
    assert normalize(served) == normalize(project_manifest_for_serve(published, task_id=TASK_ID))
    # Identity, views, and per-file projection survive the round trip verbatim.
    assert served["task_id"] == TASK_ID
    assert served["task_type"] == "sequence_demo"
    assert [(v["id"], v["plugin"], v["role"]) for v in served["views"]] == [
        (v["id"], v["plugin"], v["role"]) for v in published["views"]
    ]
    assert set(served["result"]["files"]) == set(published["result"]["files"])


def test_round_trip_serves_the_exact_captured_artifact_bytes(tmp_path: Path) -> None:
    root = _write_result_root(tmp_path, _synthetic_fixture())
    bundle = capture_replay_bundle(require_finished=False, task_id=TASK_ID, result_root=root)
    replay = ReplayBundle(bundle)
    for path in bundle["payloads"]:
        body = replay.payload(path)
        assert body is not None
        assert _sha(body[0]) == bundle["payloads"][path]["sha256"], path
        assert body[0] == (root / path).read_bytes(), path


def test_round_trip_serves_a_bounded_table_page(tmp_path: Path) -> None:
    root = _write_result_root(tmp_path, _synthetic_fixture())
    replay = ReplayBundle(capture_replay_bundle(require_finished=False, task_id=TASK_ID, result_root=root))
    page = replay.table_page("tables/pairs.tsv")
    assert page == {
        "columns": ["alignment_i", "alignment_j", "apc_score"],
        "rows": [["10", "11", "0.42"]],
        "offset": 0,
        "limit": 100,
        "has_more": False,
    }
    # The matrix endpoint pages the real CSV through the same bounded route.
    matrix = replay.table_page("couplings/raw_scores.csv", matrix=True)
    assert matrix["columns"] == ["position", "10", "11"]
    assert matrix["rows"] == [["10", "0.0", "0.51"], ["11", "0.51", "0.0"]]


def test_logical_file_identity_resolves_to_the_captured_payload(tmp_path: Path) -> None:
    root = _write_result_root(tmp_path, _synthetic_fixture())
    bundle = capture_replay_bundle(require_finished=False, task_id=TASK_ID, result_root=root)
    replay = ReplayBundle(bundle)
    assert replay.logical_artifact_path("raw_matrix", 0) == "couplings/raw_scores.csv"
    assert replay.logical_artifact_path("raw_matrix", 5) is None
    assert replay.payload(replay.logical_artifact_path("raw_matrix", 0))[0] == (root / "couplings/raw_scores.csv").read_bytes()


# ── task scoping ──────────────────────────────────────────────────────────────


def test_a_mismatched_task_id_does_not_resolve(tmp_path: Path) -> None:
    root = _write_result_root(tmp_path, _synthetic_fixture())
    replay = ReplayBundle(capture_replay_bundle(require_finished=False, task_id=TASK_ID, result_root=root))
    assert replay.served_manifest(TASK_ID) is not None
    assert replay.served_manifest("f" * 32) is None
    with pytest.raises(ReplayBundleError):
        ReplayBundle(replay.bundle, task_id="f" * 32)


def test_capture_refuses_a_manifest_whose_identity_disagrees(tmp_path: Path) -> None:
    root = _write_result_root(tmp_path, _synthetic_fixture())
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    manifest["task_id"] = "f" * 32
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ReplayBundleError, match="task identity"):
        capture_replay_bundle(require_finished=False, task_id=TASK_ID, result_root=root)


def test_capture_refuses_a_non_terminal_task_row(tmp_path: Path) -> None:
    root = _write_result_root(tmp_path, _synthetic_fixture())
    with pytest.raises(ReplayBundleError, match="not a finished success"):
        capture_replay_bundle(
            task_id=TASK_ID, result_root=root,
            task_row={"md5sum": TASK_ID, "status": "running", "task_type": "sequence_demo"},
        )


def test_a_real_capture_requires_a_finished_task_row(tmp_path: Path) -> None:
    # A real capture (the default) must prove the result came from a finished
    # task; without the canonical store row it fails closed rather than trusting
    # the manifest alone. A synthetic fixture capture may relax only this.
    root = _write_result_root(tmp_path, _synthetic_fixture())
    with pytest.raises(ReplayBundleError, match="requires the canonical finished task store row"):
        capture_replay_bundle(task_id=TASK_ID, result_root=root)
    # With a finished row it succeeds; with a non-finished row it still refuses.
    ok = capture_replay_bundle(
        task_id=TASK_ID, result_root=root,
        task_row={"md5sum": TASK_ID, "status": "finished", "task_type": "sequence_demo"},
    )
    assert ok["task"]["id"] == TASK_ID
    with pytest.raises(ReplayBundleError, match="not a finished success"):
        capture_replay_bundle(
            task_id=TASK_ID, result_root=root,
            task_row={"md5sum": TASK_ID, "status": "running", "task_type": "sequence_demo"},
        )


# ── path containment ──────────────────────────────────────────────────────────


def test_capture_refuses_an_artifact_path_that_escapes_the_result_root(tmp_path: Path) -> None:
    root = _write_result_root(tmp_path, _synthetic_fixture())
    (tmp_path / "outside.txt").write_text("secret\n", encoding="utf-8")
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    manifest["artifacts"].append({
        "path": "../outside.txt", "size": 7, "sha256": _sha(b"secret\n"),
        "media_type": "text/plain", "preview": "text", "capability": "text",
        "role": "artifact", "url": f"/compute/api/results/{TASK_ID}/artifacts/../outside.txt",
    })
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ReplayBundleError, match="safe relative path"):
        capture_replay_bundle(require_finished=False, task_id=TASK_ID, result_root=root)


def test_a_symlinked_artifact_is_not_captured(tmp_path: Path) -> None:
    root = _write_result_root(tmp_path, _synthetic_fixture())
    target = root / "couplings" / "raw_scores.csv"
    real = tmp_path / "real.csv"
    real.write_bytes(target.read_bytes())
    target.unlink()
    target.symlink_to(real)
    with pytest.raises(ReplayBundleError, match="required view source"):
        capture_replay_bundle(require_finished=False, task_id=TASK_ID, result_root=root)


# ── size policy ───────────────────────────────────────────────────────────────


def test_an_oversized_optional_artifact_is_excluded_with_its_hash(tmp_path: Path) -> None:
    root = _write_result_root(tmp_path, _synthetic_fixture())
    big = b"x" * 4096
    (root / "models").mkdir()
    (root / "models" / "weights.bin").write_bytes(big)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    manifest["artifacts"].append({
        "path": "models/weights.bin", "size": len(big), "sha256": _sha(big),
        "media_type": "application/octet-stream", "preview": None, "capability": "download_only",
        "role": "artifact", "url": f"/compute/api/results/{TASK_ID}/artifacts/models/weights.bin",
    })
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    bundle = capture_replay_bundle(require_finished=False, task_id=TASK_ID, result_root=root, max_payload_bytes=1024)
    excluded = {entry["path"]: entry for entry in bundle["excluded"]}
    assert excluded["models/weights.bin"]["sha256"] == _sha(big)
    assert excluded["models/weights.bin"]["reason"] == "exceeds the per-file payload budget"
    assert "models/weights.bin" not in bundle["payloads"]


def test_an_oversized_required_view_source_fails_the_capture(tmp_path: Path) -> None:
    root = _write_result_root(tmp_path, _synthetic_fixture())
    with pytest.raises(ReplayBundleError):
        capture_replay_bundle(require_finished=False, task_id=TASK_ID, result_root=root, max_payload_bytes=16)


def test_the_bundle_budget_excludes_the_optional_largest_payload_first(tmp_path: Path) -> None:
    root = _write_result_root(tmp_path, _synthetic_fixture())
    # A budget that fits every required view source but not the 4 KiB optional
    # diagnostic: the diagnostic must drop out (with its hash) instead of a view
    # source, so a tight budget can never silently break a declared view.
    bundle = capture_replay_bundle(require_finished=False, task_id=TASK_ID, result_root=root, max_bundle_bytes=2800)
    excluded = {entry["path"]: entry for entry in bundle["excluded"]}
    assert "execution/slurm.stdout" in excluded
    assert excluded["execution/slurm.stdout"]["reason"] == "exceeds the bundle payload budget"
    assert "couplings/raw_scores.csv" in bundle["payloads"]
    assert "tables/pairs.tsv" in bundle["payloads"]


def test_a_required_view_source_that_exceeds_the_bundle_budget_fails_the_capture(tmp_path: Path) -> None:
    root = _write_result_root(tmp_path, _synthetic_fixture())
    with pytest.raises(ReplayBundleError, match="required view sources exceed the bundle payload budget"):
        capture_replay_bundle(require_finished=False, task_id=TASK_ID, result_root=root, max_bundle_bytes=32)


# ── checksum and drift ────────────────────────────────────────────────────────


def test_capture_refuses_bytes_that_disagree_with_the_manifest_hash(tmp_path: Path) -> None:
    root = _write_result_root(tmp_path, _synthetic_fixture())
    (root / "summary.json").write_text('{"tampered": true}\n', encoding="utf-8")
    with pytest.raises(ReplayBundleError, match="disagree with the manifest sha256"):
        capture_replay_bundle(require_finished=False, task_id=TASK_ID, result_root=root)


def test_load_refuses_a_corrupted_payload(tmp_path: Path) -> None:
    from frontend_fixtures import bundle_digest

    root = _write_result_root(tmp_path, _synthetic_fixture())
    bundle = capture_replay_bundle(require_finished=False, task_id=TASK_ID, result_root=root)
    bundle["payloads"]["summary.json"]["payload"] = '{"changed": true}\n'
    # Re-digest so the tamper is only in the payload bytes, not the bundle digest.
    bundle["bundle_digest"] = bundle_digest(bundle)
    with pytest.raises(ReplayBundleError, match="does not match its own sha256"):
        load_bundle(bundle)


def test_load_refuses_a_missing_required_view_source(tmp_path: Path) -> None:
    from frontend_fixtures import bundle_digest

    root = _write_result_root(tmp_path, _synthetic_fixture())
    bundle = capture_replay_bundle(require_finished=False, task_id=TASK_ID, result_root=root)
    del bundle["payloads"]["couplings/raw_scores.csv"]
    bundle["bundle_digest"] = bundle_digest(bundle)
    with pytest.raises(ReplayBundleError, match="required view source is not captured"):
        load_bundle(bundle)


def test_load_refuses_a_tampered_digest(tmp_path: Path) -> None:
    root = _write_result_root(tmp_path, _synthetic_fixture())
    bundle = capture_replay_bundle(require_finished=False, task_id=TASK_ID, result_root=root)
    bundle["response"]["task_type"] = "something_else"
    with pytest.raises(ReplayBundleError, match="bundle_digest"):
        load_bundle(bundle)


def test_load_refuses_a_manifest_that_violates_the_canonical_contract(tmp_path: Path) -> None:
    root = _write_result_root(tmp_path, _synthetic_fixture())
    bundle = capture_replay_bundle(require_finished=False, task_id=TASK_ID, result_root=root)
    # Remove a field the contract requires, then re-digest so only the schema fails.
    del bundle["response"]["output_check"]
    from frontend_fixtures import bundle_digest

    bundle["bundle_digest"] = bundle_digest(bundle)
    with pytest.raises(ReplayBundleError, match="canonical contract"):
        load_bundle(bundle)


def test_persisted_bundle_round_trips_through_disk(tmp_path: Path) -> None:
    root = _write_result_root(tmp_path, _synthetic_fixture())
    bundle = capture_replay_bundle(require_finished=False, task_id=TASK_ID, result_root=root)
    destination = write_bundle(tmp_path / "bundle.json", bundle)
    loaded = ReplayBundle.load(destination)
    assert loaded.bundle["bundle_digest"] == bundle["bundle_digest"]
    assert loaded.served_manifest() == bundle["response"]


# ── storyboard ────────────────────────────────────────────────────────────────


def _storyboard_runner_tree(tmp_path: Path, task_type: str, task_id: str, body: str) -> Path:
    """A minimal runner tree whose plugin declares ``task_type`` and its storyboard."""
    import yaml

    root = tmp_path / "runners"
    family = root / "sequence_demo"
    (family / "storyboard").mkdir(parents=True)
    (family / "tasks" / task_id).mkdir(parents=True)
    (family / "plugin.yaml").write_text(
        yaml.safe_dump({"id": family.name, "tasks": [f"tasks/{task_id}/task.yaml"]}), encoding="utf-8"
    )
    (family / "tasks" / task_id / "task.yaml").write_text(yaml.safe_dump({"id": task_type}), encoding="utf-8")
    (family / "storyboard" / "index.js").write_text(body, encoding="utf-8")
    return root


def test_storyboard_source_is_read_from_the_runner_tree_not_the_result_root(tmp_path: Path) -> None:
    """Production serves the storyboard from the runner deployment tree."""
    body = "export default { mount(host) { host.dataset.mounted = '1'; return { destroy() {} }; } };\n"
    runner_tree = _storyboard_runner_tree(tmp_path, "sequence_demo", "gremlin_lh_fit", body)
    root = _write_result_root(tmp_path, _storyboard_fixture())
    # A stale storyboard under the result root must be ignored.
    (root / "storyboard" / "index.js").write_text("STALE\n", encoding="utf-8")
    bundle = capture_replay_bundle(require_finished=False, task_id=TASK_ID, result_root=root, storyboard_dirs=[runner_tree])
    assert bundle["storyboard"]["entrypoint"] == "index.js"
    assert bundle["storyboard"]["source"] == body
    assert ReplayBundle(bundle).storyboard_source("index.js") == body


def test_a_missing_storyboard_in_the_runner_tree_fails_the_capture(tmp_path: Path) -> None:
    runner_tree = _storyboard_runner_tree(tmp_path, "sequence_demo", "gremlin_lh_fit", "export default {};\n")
    root = _write_result_root(tmp_path, _storyboard_fixture())
    (runner_tree / "sequence_demo" / "storyboard" / "index.js").unlink()
    with pytest.raises(ReplayBundleError, match="storyboard entrypoint does not resolve"):
        capture_replay_bundle(require_finished=False, task_id=TASK_ID, result_root=root, storyboard_dirs=[runner_tree])


def test_a_storyboard_family_that_does_not_declare_the_task_fails_closed(tmp_path: Path) -> None:
    runner_tree = _storyboard_runner_tree(tmp_path, "some_other_task", "gremlin_lh_fit", "export default {};\n")
    root = _write_result_root(tmp_path, _storyboard_fixture())
    with pytest.raises(ReplayBundleError, match="storyboard entrypoint does not resolve"):
        capture_replay_bundle(require_finished=False, task_id=TASK_ID, result_root=root, storyboard_dirs=[runner_tree])


# ── secret sanitization ───────────────────────────────────────────────────────


def test_secret_bearing_metadata_is_sanitized_before_persistence(tmp_path: Path) -> None:
    root = _write_result_root(tmp_path, _synthetic_fixture())
    bundle = capture_replay_bundle(require_finished=False, 
        task_id=TASK_ID,
        result_root=root,
        provenance={
            "submitted_by": "tester",
            "api_token": "rvk_abcdefghijklmnop",
            "note": "Authorization: Bearer abcdefghijklmnopqrstuvwxyz012345",
        },
    )
    assert bundle["provenance"] == {"submitted_by": "tester", "note": "[redacted]"}
    assert "rvk_" not in json.dumps(bundle)
    assert "Bearer" not in json.dumps(bundle)


def test_a_secret_shaped_value_under_an_ordinary_key_is_redacted(tmp_path: Path) -> None:
    root = _write_result_root(tmp_path, _synthetic_fixture())
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    manifest["run"]["method"]["summary"] = "token rvk_abcdefghijklmnop leaked"
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    bundle = capture_replay_bundle(require_finished=False, task_id=TASK_ID, result_root=root)
    assert "rvk_" not in json.dumps(bundle)
    assert "[redacted]" in bundle["response"]["run"]["method"]["summary"]


def test_a_host_local_path_in_metadata_is_scrubbed(tmp_path: Path) -> None:
    root = _write_result_root(tmp_path, _synthetic_fixture())
    bundle = capture_replay_bundle(require_finished=False, 
        task_id=TASK_ID,
        result_root=root,
        provenance={"backup": "/mnt/hdd/revocompute/backups/config-20260101", "keep": "relative/ok"},
    )
    assert bundle["provenance"]["backup"] == " [host-path-omitted]"
    assert bundle["provenance"]["keep"] == "relative/ok"
    assert "/mnt/" not in json.dumps(bundle)


def test_a_host_local_path_inside_an_artifact_payload_is_not_checked_in(tmp_path: Path) -> None:
    root = _write_result_root(tmp_path, _synthetic_fixture())
    payload = "WARNING: chdir /var/lib/revodesign: no such file\n"
    block = (root / "execution" / "slurm.stdout")
    block.write_text(payload, encoding="utf-8")
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    for artifact in manifest["artifacts"]:
        if artifact["path"] == "execution/slurm.stdout":
            artifact["size"] = len(payload.encode("utf-8"))
            artifact["sha256"] = _sha(payload.encode("utf-8"))
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    bundle = capture_replay_bundle(require_finished=False, task_id=TASK_ID, result_root=root)
    assert "execution/slurm.stdout" not in bundle["payloads"]
    excluded = {entry["path"]: entry for entry in bundle["excluded"]}
    assert excluded["execution/slurm.stdout"]["reason"] == "payload embeds a host-local path"
    assert "/var/lib/revodesign" not in json.dumps(bundle)


# ── provenance pointer (degradable against the receipt contract) ─────────────


def test_production_receipt_pointer_reads_the_canonical_receipt_fields() -> None:
    # The receipt must be present: this is the check that locks the bundle's
    # provenance to #42's checked-in receipt, so a missing receipt fails rather
    # than silently skipping the integration.
    assert GREMLIN_RECEIPT.is_file(), f"the cited production receipt is missing: {GREMLIN_RECEIPT}"
    document = json.loads(GREMLIN_RECEIPT.read_text(encoding="utf-8"))
    pointer = production_receipt_pointer(
        GREMLIN_RECEIPT,
        task_id=document["task_id"],
        receipt_path="docker/runners/gremlin_lh/receipts/" + GREMLIN_RECEIPT.name,
    )
    assert pointer["source"] == "production_api_acceptance_receipt"
    assert pointer["task_id"] == document["task_id"]
    assert pointer["receipt_digest"] == document["receipt_digest"]
    assert pointer["receipt_digest_verified"] is True
    assert pointer["deployment_commit"] == document["deployment"]["commit"]


def _valid_receipt_body(*, task_id: str) -> dict:
    """The minimal receipt body the canonical parser accepts."""
    return {
        "receipt_version": 1,
        "kind": "production_api_acceptance",
        "task_id": task_id,
        "complete": True,
        "tool": {"source_digest": "sha256:" + "1" * 64},
        "result": {"artifacts": [{"path": "x", "sha256": "0" * 64}]},
    }


def test_production_receipt_pointer_refuses_an_unrelated_task() -> None:
    from frontend_fixtures import bundle_digest

    body = _valid_receipt_body(task_id="a" * 32)
    document = {**body, "receipt_digest": bundle_digest(body)}
    with pytest.raises(ProvenanceError, match="not for the captured task"):
        production_receipt_pointer(document, task_id="c" * 32)


def test_production_receipt_pointer_refuses_a_tampered_receipt() -> None:
    from frontend_fixtures import bundle_digest

    body = _valid_receipt_body(task_id="a" * 32)
    document = {**body, "receipt_digest": bundle_digest(body)}
    document["complete"] = False  # tamper after digesting
    with pytest.raises(ProvenanceError, match="receipt_digest does not match"):
        production_receipt_pointer(document, task_id="a" * 32)


def test_production_receipt_pointer_verifies_through_the_canonical_parser() -> None:
    from frontend_fixtures import bundle_digest

    # A receipt the canonical parser rejects (no collector tool identity) must
    # be refused, so the pointer and the parser can never disagree.
    body = _valid_receipt_body(task_id="a" * 32)
    del body["tool"]
    document = {**body, "receipt_digest": bundle_digest(body)}
    with pytest.raises(ProvenanceError, match="collector tool source"):
        production_receipt_pointer(document, task_id="a" * 32)


def _pointer_bundle(tmp_path: Path, *, name: str = "result", **overrides) -> dict:
    """A captured synthetic bundle whose persisted pointer is fully valid."""
    from frontend_fixtures import bundle_digest

    root = tmp_path / name
    root.mkdir()
    root = _write_result_root(root, _synthetic_fixture())
    bundle = capture_replay_bundle(require_finished=False, task_id=TASK_ID, result_root=root)
    pointer = {
        "source": "production_api_acceptance_receipt",
        "task_id": TASK_ID,
        "receipt_digest": "sha256:" + "0" * 64,
        "receipt_digest_verified": True,
    }
    pointer.update(overrides)
    bundle["provenance"] = {"production_receipt": pointer}
    bundle["bundle_digest"] = bundle_digest(bundle)
    return bundle


def test_load_refuses_a_provenance_pointer_for_a_different_task(tmp_path: Path) -> None:
    # The bundle digest proves the bytes have not drifted, not that the persisted
    # production-receipt pointer is about *this* task. A pointer citing another
    # task must fail on load rather than record unrelated provenance.
    from frontend_fixtures import bundle_digest

    with pytest.raises(ReplayBundleError, match="cites a different task"):
        load_bundle(_pointer_bundle(tmp_path, name="a", task_id="f" * 32))
    # A well-formed pointer for the bundle's own task, and no pointer at all,
    # both load.
    assert load_bundle(_pointer_bundle(tmp_path, name="b"))["task"]["id"] == TASK_ID
    empty_root = tmp_path / "c"
    empty_root.mkdir()
    empty = capture_replay_bundle(
        require_finished=False, task_id=TASK_ID, result_root=_write_result_root(empty_root, _synthetic_fixture())
    )
    empty["provenance"] = {}
    empty["bundle_digest"] = bundle_digest(empty)
    assert load_bundle(empty)["task"]["id"] == TASK_ID


def test_load_refuses_a_provenance_pointer_from_a_noncanonical_source(tmp_path: Path) -> None:
    bundle = _pointer_bundle(tmp_path, source="some_other_receipt_format")
    with pytest.raises(ReplayBundleError, match="not from the canonical receipt source"):
        load_bundle(bundle)


def test_load_refuses_a_provenance_pointer_that_is_not_verified(tmp_path: Path) -> None:
    bundle = _pointer_bundle(tmp_path, name="a", receipt_digest_verified=False)
    with pytest.raises(ReplayBundleError, match="does not record a verified receipt"):
        load_bundle(bundle)
    missing = _pointer_bundle(tmp_path, name="b")
    del missing["provenance"]["production_receipt"]["receipt_digest_verified"]
    from frontend_fixtures import bundle_digest

    missing["bundle_digest"] = bundle_digest(missing)
    with pytest.raises(ReplayBundleError, match="does not record a verified receipt"):
        load_bundle(missing)


def test_load_refuses_a_provenance_pointer_without_a_receipt_digest(tmp_path: Path) -> None:
    bundle = _pointer_bundle(tmp_path, receipt_digest="")
    with pytest.raises(ReplayBundleError, match="carries no receipt digest"):
        load_bundle(bundle)


def test_load_refuses_a_provenance_pointer_without_a_task_identity(tmp_path: Path) -> None:
    bundle = _pointer_bundle(tmp_path)
    del bundle["provenance"]["production_receipt"]["task_id"]
    from frontend_fixtures import bundle_digest

    bundle["bundle_digest"] = bundle_digest(bundle)
    with pytest.raises(ReplayBundleError, match="carries no task identity"):
        load_bundle(bundle)


# ── the checked-in real GREMLIN_LH bundle ────────────────────────────────────


def test_real_gremlin_bundle_loads_and_verifies_every_captured_hash() -> None:
    if not REAL_BUNDLE.is_file():
        pytest.skip("the captured GREMLIN_LH replay bundle is not present")
    replay = ReplayBundle.load(REAL_BUNDLE)
    assert replay.task_id == "944ed43af62ead9f5c9560bae1ccd897"
    assert replay.bundle["task"]["type"] == "gremlin_lh_fit"
    assert replay.provenance["production_receipt"]["source"] == "production_api_acceptance_receipt"
    # Every captured payload re-hashes to its recorded digest.
    for path, entry in replay.bundle["payloads"].items():
        assert _sha(entry["payload"].encode("utf-8")) == entry["sha256"], path
    # The real 2KL8 input identity is carried by the manifest.
    inputs = replay.manifest["run"]["inputs"]
    assert [item["path"] for item in inputs] == ["2KL8.i90c75_aln.a3m"]
    assert inputs[0]["sha256"] == "b099f030c2bca669ce75961104a625d8aad4f3bd49a71ad5a07fa97d32df113f"


def test_real_gremlin_bundle_carries_the_declared_views_and_required_sources() -> None:
    if not REAL_BUNDLE.is_file():
        pytest.skip("the captured GREMLIN_LH replay bundle is not present")
    replay = ReplayBundle.load(REAL_BUNDLE)
    assert [(v["id"], v["plugin"], v["role"]) for v in replay.manifest["views"]] == [
        ("raw_couplings", "matrix", "primary"),
        ("apc_couplings", "matrix", "evidence"),
        ("ranked_pairs", "entity-table", "evidence"),
        ("filtered_alignment", "alignment", "evidence"),
        ("fit_summary", "scalar-summary", "evidence"),
    ]
    for _, _, path in required_view_sources(replay.manifest):
        assert path in replay.bundle["payloads"], path


def test_real_gremlin_bundle_pointer_matches_the_canonical_receipt() -> None:
    """The checked-in bundle's persisted pointer must cite the real #42 receipt.

    The bundle digest proves its own bytes have not drifted; it does not prove the
    production-receipt pointer it persists is about the receipt #42 actually
    checked in. This binds the two independently: the pointer the bundle carries
    must agree, field for field, with the pointer the canonical receipt source
    projects -- same task, same receipt digest, same canonical source, and the
    same recorded verification -- so the fixture can never quietly cite a receipt
    the merged contract no longer names.
    """
    if not REAL_BUNDLE.is_file():
        pytest.skip("the captured GREMLIN_LH replay bundle is not present")
    assert GREMLIN_RECEIPT.is_file(), f"the cited production receipt is missing: {GREMLIN_RECEIPT}"
    persisted = ReplayBundle.load(REAL_BUNDLE).provenance["production_receipt"]
    canonical = production_receipt_pointer(
        GREMLIN_RECEIPT,
        task_id=persisted["task_id"],
        receipt_path="docker/runners/gremlin_lh/receipts/" + GREMLIN_RECEIPT.name,
    )
    # The four fields that bind the pointer to the canonical receipt.
    assert persisted["task_id"] == canonical["task_id"] == "944ed43af62ead9f5c9560bae1ccd897"
    assert persisted["receipt_digest"] == canonical["receipt_digest"]
    assert persisted["receipt_digest"] == "sha256:975ed6916181234932f78c35bc590ab1c985d5ec5a96b8d85633744a655acc4b"
    assert persisted["source"] == canonical["source"] == PROVENANCE_SOURCE
    assert persisted["receipt_digest_verified"] is True
    assert persisted["receipt_path"] == canonical["receipt_path"]


def test_real_gremlin_bundle_records_the_excluded_artifacts_with_hashes() -> None:
    if not REAL_BUNDLE.is_file():
        pytest.skip("the captured GREMLIN_LH replay bundle is not present")
    excluded = {entry["path"]: entry for entry in ReplayBundle.load(REAL_BUNDLE).bundle["excluded"]}
    # The 341 KiB NPZ exceeds the per-file budget; the PNG is binary. Both keep
    # their hash and provenance, and neither is truncated into a partial file.
    assert excluded["model/gremlin_mrf.npz"]["reason"] == "exceeds the per-file payload budget"
    assert excluded["model/gremlin_mrf.npz"]["sha256"] == (
        "bcaaed6b2e2d5a85bea8df2646440e0aeb8233e0775a6d54c1f928345d220244"
    )
    assert excluded["plots/coupling_apc.png"]["reason"] == "binary payload is not checked in"
