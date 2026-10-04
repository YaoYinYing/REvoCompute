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
    / "production-api-bf03f76ef310eb7a4ac62abe5579c93a.json"
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
    bundle = capture_replay_bundle(task_id=TASK_ID, result_root=root, display_name="alignment.a3m")
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
    first = capture_replay_bundle(task_id=TASK_ID, result_root=root)
    second = capture_replay_bundle(task_id=TASK_ID, result_root=root)
    assert first == second


# ── round-trip: capture -> bundle -> served projection ───────────────────────


def test_round_trip_preserves_the_served_manifest_after_normalization(tmp_path: Path) -> None:
    root = _write_result_root(tmp_path, _synthetic_fixture())
    published = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    bundle = capture_replay_bundle(task_id=TASK_ID, result_root=root)
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
    bundle = capture_replay_bundle(task_id=TASK_ID, result_root=root)
    replay = ReplayBundle(bundle)
    for path in bundle["payloads"]:
        body = replay.payload(path)
        assert body is not None
        assert _sha(body[0]) == bundle["payloads"][path]["sha256"], path
        assert body[0] == (root / path).read_bytes(), path


def test_round_trip_serves_a_bounded_table_page(tmp_path: Path) -> None:
    root = _write_result_root(tmp_path, _synthetic_fixture())
    replay = ReplayBundle(capture_replay_bundle(task_id=TASK_ID, result_root=root))
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
    bundle = capture_replay_bundle(task_id=TASK_ID, result_root=root)
    replay = ReplayBundle(bundle)
    assert replay.logical_artifact_path("raw_matrix", 0) == "couplings/raw_scores.csv"
    assert replay.logical_artifact_path("raw_matrix", 5) is None
    assert replay.payload(replay.logical_artifact_path("raw_matrix", 0))[0] == (root / "couplings/raw_scores.csv").read_bytes()


# ── task scoping ──────────────────────────────────────────────────────────────


def test_a_mismatched_task_id_does_not_resolve(tmp_path: Path) -> None:
    root = _write_result_root(tmp_path, _synthetic_fixture())
    replay = ReplayBundle(capture_replay_bundle(task_id=TASK_ID, result_root=root))
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
        capture_replay_bundle(task_id=TASK_ID, result_root=root)


def test_capture_refuses_a_non_terminal_task_row(tmp_path: Path) -> None:
    root = _write_result_root(tmp_path, _synthetic_fixture())
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
        capture_replay_bundle(task_id=TASK_ID, result_root=root)


def test_a_symlinked_artifact_is_not_captured(tmp_path: Path) -> None:
    root = _write_result_root(tmp_path, _synthetic_fixture())
    target = root / "couplings" / "raw_scores.csv"
    real = tmp_path / "real.csv"
    real.write_bytes(target.read_bytes())
    target.unlink()
    target.symlink_to(real)
    with pytest.raises(ReplayBundleError, match="required view source"):
        capture_replay_bundle(task_id=TASK_ID, result_root=root)


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
    bundle = capture_replay_bundle(task_id=TASK_ID, result_root=root, max_payload_bytes=1024)
    excluded = {entry["path"]: entry for entry in bundle["excluded"]}
    assert excluded["models/weights.bin"]["sha256"] == _sha(big)
    assert excluded["models/weights.bin"]["reason"] == "exceeds the per-file payload budget"
    assert "models/weights.bin" not in bundle["payloads"]


def test_an_oversized_required_view_source_fails_the_capture(tmp_path: Path) -> None:
    root = _write_result_root(tmp_path, _synthetic_fixture())
    with pytest.raises(ReplayBundleError):
        capture_replay_bundle(task_id=TASK_ID, result_root=root, max_payload_bytes=16)


def test_the_bundle_budget_excludes_the_optional_largest_payload_first(tmp_path: Path) -> None:
    root = _write_result_root(tmp_path, _synthetic_fixture())
    # A budget that fits every required view source but not the 4 KiB optional
    # diagnostic: the diagnostic must drop out (with its hash) instead of a view
    # source, so a tight budget can never silently break a declared view.
    bundle = capture_replay_bundle(task_id=TASK_ID, result_root=root, max_bundle_bytes=2800)
    excluded = {entry["path"]: entry for entry in bundle["excluded"]}
    assert "execution/slurm.stdout" in excluded
    assert excluded["execution/slurm.stdout"]["reason"] == "exceeds the bundle payload budget"
    assert "couplings/raw_scores.csv" in bundle["payloads"]
    assert "tables/pairs.tsv" in bundle["payloads"]


def test_a_required_view_source_that_exceeds_the_bundle_budget_fails_the_capture(tmp_path: Path) -> None:
    root = _write_result_root(tmp_path, _synthetic_fixture())
    with pytest.raises(ReplayBundleError, match="exceeds the bundle payload budget"):
        capture_replay_bundle(task_id=TASK_ID, result_root=root, max_bundle_bytes=32)


# ── checksum and drift ────────────────────────────────────────────────────────


def test_capture_refuses_bytes_that_disagree_with_the_manifest_hash(tmp_path: Path) -> None:
    root = _write_result_root(tmp_path, _synthetic_fixture())
    (root / "summary.json").write_text('{"tampered": true}\n', encoding="utf-8")
    with pytest.raises(ReplayBundleError, match="disagree with the manifest sha256"):
        capture_replay_bundle(task_id=TASK_ID, result_root=root)


def test_load_refuses_a_corrupted_payload(tmp_path: Path) -> None:
    from frontend_fixtures import bundle_digest

    root = _write_result_root(tmp_path, _synthetic_fixture())
    bundle = capture_replay_bundle(task_id=TASK_ID, result_root=root)
    bundle["payloads"]["summary.json"]["payload"] = '{"changed": true}\n'
    # Re-digest so the tamper is only in the payload bytes, not the bundle digest.
    bundle["bundle_digest"] = bundle_digest(bundle)
    with pytest.raises(ReplayBundleError, match="does not match its own sha256"):
        load_bundle(bundle)


def test_load_refuses_a_missing_required_view_source(tmp_path: Path) -> None:
    from frontend_fixtures import bundle_digest

    root = _write_result_root(tmp_path, _synthetic_fixture())
    bundle = capture_replay_bundle(task_id=TASK_ID, result_root=root)
    del bundle["payloads"]["couplings/raw_scores.csv"]
    bundle["bundle_digest"] = bundle_digest(bundle)
    with pytest.raises(ReplayBundleError, match="required view source is not captured"):
        load_bundle(bundle)


def test_load_refuses_a_tampered_digest(tmp_path: Path) -> None:
    root = _write_result_root(tmp_path, _synthetic_fixture())
    bundle = capture_replay_bundle(task_id=TASK_ID, result_root=root)
    bundle["response"]["task_type"] = "something_else"
    with pytest.raises(ReplayBundleError, match="bundle_digest"):
        load_bundle(bundle)


def test_load_refuses_a_manifest_that_violates_the_canonical_contract(tmp_path: Path) -> None:
    root = _write_result_root(tmp_path, _synthetic_fixture())
    bundle = capture_replay_bundle(task_id=TASK_ID, result_root=root)
    # Remove a field the contract requires, then re-digest so only the schema fails.
    del bundle["response"]["output_check"]
    from frontend_fixtures import bundle_digest

    bundle["bundle_digest"] = bundle_digest(bundle)
    with pytest.raises(ReplayBundleError, match="canonical contract"):
        load_bundle(bundle)


def test_persisted_bundle_round_trips_through_disk(tmp_path: Path) -> None:
    root = _write_result_root(tmp_path, _synthetic_fixture())
    bundle = capture_replay_bundle(task_id=TASK_ID, result_root=root)
    destination = write_bundle(tmp_path / "bundle.json", bundle)
    loaded = ReplayBundle.load(destination)
    assert loaded.bundle["bundle_digest"] == bundle["bundle_digest"]
    assert loaded.served_manifest() == bundle["response"]


# ── storyboard ────────────────────────────────────────────────────────────────


def test_storyboard_source_is_captured_and_served(tmp_path: Path) -> None:
    root = _write_result_root(tmp_path, _storyboard_fixture())
    bundle = capture_replay_bundle(task_id=TASK_ID, result_root=root)
    assert bundle["storyboard"]["entrypoint"] == "index.js"
    assert _sha(bundle["storyboard"]["source"].encode("utf-8")) == bundle["storyboard"]["sha256"]
    assert ReplayBundle(bundle).storyboard_source("index.js") == (
        "export default { mount(host) { host.dataset.mounted = '1'; return { destroy() {} }; } };\n"
    )


def test_a_missing_storyboard_entrypoint_fails_the_capture(tmp_path: Path) -> None:
    root = _write_result_root(tmp_path, _storyboard_fixture())
    (root / "storyboard" / "index.js").unlink()
    with pytest.raises(ReplayBundleError, match="storyboard entrypoint does not resolve"):
        capture_replay_bundle(task_id=TASK_ID, result_root=root)


# ── secret sanitization ───────────────────────────────────────────────────────


def test_secret_bearing_metadata_is_sanitized_before_persistence(tmp_path: Path) -> None:
    root = _write_result_root(tmp_path, _synthetic_fixture())
    bundle = capture_replay_bundle(
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
    bundle = capture_replay_bundle(task_id=TASK_ID, result_root=root)
    assert "rvk_" not in json.dumps(bundle)
    assert "[redacted]" in bundle["response"]["run"]["method"]["summary"]


# ── provenance pointer (degradable against the receipt contract) ─────────────


def test_production_receipt_pointer_reads_the_canonical_receipt_fields() -> None:
    if not GREMLIN_RECEIPT.is_file():
        pytest.skip("the production receipt is not present on this base")
    document = json.loads(GREMLIN_RECEIPT.read_text(encoding="utf-8"))
    pointer = production_receipt_pointer(
        GREMLIN_RECEIPT,
        task_id=document["task_id"],
        receipt_path="docker/runners/gremlin_lh/receipts/" + GREMLIN_RECEIPT.name,
    )
    assert pointer["source"] == "production_api_acceptance_receipt"
    assert pointer["task_id"] == document["task_id"]
    assert pointer["receipt_digest"] == document["receipt_digest"]
    assert pointer["deployment_commit"] == document["deployment"]["commit"]


def test_production_receipt_pointer_refuses_an_unrelated_task() -> None:
    document = {"task_id": "a" * 32, "receipt_version": 1, "receipt_digest": "sha256:" + "b" * 64}
    with pytest.raises(ProvenanceError, match="not for the captured task"):
        production_receipt_pointer(document, task_id="c" * 32)


# ── the checked-in real GREMLIN_LH bundle ────────────────────────────────────


def test_real_gremlin_bundle_loads_and_verifies_every_captured_hash() -> None:
    if not REAL_BUNDLE.is_file():
        pytest.skip("the captured GREMLIN_LH replay bundle is not present")
    replay = ReplayBundle.load(REAL_BUNDLE)
    assert replay.task_id == "944ed43af62ead9f5c9560bae1ccd897"
    assert replay.bundle["task"]["type"] == "gremlin_lh_fit"
    assert replay.provenance["related_production_receipt"]["source"] == "production_api_acceptance_receipt"
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
