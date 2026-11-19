# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Behavior contracts for the generic Input Builder boundary."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from revocompute import atomworks
from revocompute.clone_plan import build_plan, recorded_authoring
from revocompute.input_builders import (
    MAX_STATE_BYTES,
    SHARED_BUILDERS,
    BuilderDescriptor,
    BuilderValidationError,
    validate_capability_options,
    validate_envelope,
)

DIGEST = hashlib.sha256(b"x").hexdigest()
BIONUTA = SHARED_BUILDERS["bionuta"]


def _capability(**options):
    return SimpleNamespace(
        id="bionuta_builder",
        plugin="input-builder",
        options={
            "builder": "bionuta",
            "target": "alphafold3",
            "outputs": {"input": "specification"},
            **options,
        },
    )


def _role(name: str, formats: list[str]):
    return SimpleNamespace(name=name, formats=formats)


def _envelope(**overrides):
    value = {
        "version": 1,
        "builder": "bionuta",
        "builder_version": 2,
        "state_schema_version": 1,
        "target": "alphafold3",
        "revision": 3,
        "state": {"document": {"job": {"entities": []}}},
        "dependencies": [],
        "outputs": [
            {"logical": "input", "role": "specification", "name": "af3.json", "size": 1, "sha256": DIGEST}
        ],
    }
    value.update(overrides)
    return value


def _saved(role="specification", name="af3.json", size=1, digest=DIGEST):
    return [{"role": role, "original_name": name, "size": size, "hash": digest}]


def test_shared_builder_declares_the_verified_targets_and_formats():
    assert BIONUTA.output_format("alphafold3") == "json"
    assert BIONUTA.output_format("bioemu2") == "yaml"
    assert BIONUTA.accepts_role_format("bioemu2", {"yml"})
    assert not BIONUTA.accepts_role_format("alphafold3", {"yaml"})


@pytest.mark.parametrize(
    "options",
    [
        {"target": "not-a-target"},
        {"outputs": {"input": "unknown_role"}},
        {"outputs": {"other": "specification"}},
        {"outputs": {}},
        {"exclusive": "yes"},
    ],
)
def test_capability_binding_rejects_invalid_declarations(options):
    with pytest.raises(ValueError):
        validate_capability_options(
            {
                "builder": "bionuta",
                "target": "alphafold3",
                "outputs": {"input": "specification"},
                **options,
            },
            builder=BIONUTA,
            roles={"specification": _role("specification", ["json"])},
        )


def test_capability_binding_rejects_an_unknown_builder():
    with pytest.raises(ValueError, match="Unknown input builder"):
        validate_capability_options(
            {"builder": "missing", "target": "alphafold3", "outputs": {"input": "specification"}},
            builder=None,
            roles={"specification": _role("specification", ["json"])},
        )


def test_capability_binding_rejects_a_role_that_cannot_hold_the_target_format():
    with pytest.raises(ValueError, match="does not accept"):
        validate_capability_options(
            {"builder": "bionuta", "target": "alphafold3", "outputs": {"input": "specification"}},
            builder=BIONUTA,
            roles={"specification": _role("specification", ["yaml"])},
        )


def test_envelope_binds_exactly_the_accepted_bytes():
    validate_envelope(_capability(), _envelope(), _saved(), builder=BIONUTA)


@pytest.mark.parametrize(
    ("value", "saved", "code"),
    [
        (_envelope(outputs=[]), _saved(), "builder_output_unbound"),
        (_envelope(outputs=[{**_envelope()["outputs"][0], "sha256": "0" * 64}]), _saved(), "builder_output_digest_mismatch"),
        (_envelope(), _saved(digest="0" * 64), "builder_output_digest_mismatch"),
        (
            _envelope(outputs=[{**_envelope()["outputs"][0], "role": "system"}]),
            _saved(),
            "builder_output_unbound",
        ),
        (_envelope(dependencies=[{"id": "dep-1"}]), _saved(), "builder_dependency_unsupported"),
        (_envelope(builder="other"), _saved(), "builder_binding_mismatch"),
        (_envelope(version=2), _saved(), "builder_envelope_version"),
        (_envelope(unexpected=True), _saved(), "builder_envelope_invalid"),
        (_envelope(state=["not", "an", "object"]), _saved(), "builder_state_invalid"),
    ],
)
def test_envelope_rejects_a_stale_or_foreign_binding(value, saved, code):
    with pytest.raises(BuilderValidationError) as error:
        validate_envelope(_capability(), value, saved, builder=BIONUTA)
    assert error.value.code == code


def test_envelope_rejects_a_stale_builder_version():
    with pytest.raises(BuilderValidationError) as error:
        validate_envelope(_capability(), _envelope(builder_version=3), _saved(), builder=BIONUTA)
    assert error.value.code == "builder_version_mismatch"


@pytest.mark.parametrize("logical", [["input"], {"name": "input"}])
def test_envelope_rejects_a_non_string_logical_output(logical):
    with pytest.raises(BuilderValidationError) as error:
        validate_envelope(
            _capability(),
            _envelope(outputs=[{**_envelope()["outputs"][0], "logical": logical}]),
            _saved(),
            builder=BIONUTA,
        )
    assert error.value.code == "builder_output_invalid"


def test_envelope_rejects_an_extra_file_in_a_builder_owned_role():
    with pytest.raises(BuilderValidationError, match="only accepted file"):
        validate_envelope(
            _capability(),
            _envelope(),
            _saved() + [{"role": "specification", "original_name": "extra.json", "size": 1, "hash": DIGEST}],
            builder=BIONUTA,
        )


def test_envelope_bounds_the_opaque_state():
    oversized = {"blob": "x" * (MAX_STATE_BYTES + 1)}
    with pytest.raises(BuilderValidationError) as error:
        validate_envelope(_capability(), _envelope(state=oversized), _saved(), builder=BIONUTA)
    assert error.value.code == "builder_state_too_large"


def test_exclusive_builder_refuses_any_other_accepted_file():
    with pytest.raises(BuilderValidationError) as error:
        validate_envelope(
            _capability(exclusive=True),
            _envelope(),
            _saved() + [{"role": "scaffold", "original_name": "s.cif", "size": 1, "hash": DIGEST}],
            builder=BIONUTA,
        )
    assert error.value.code == "builder_exclusive_input"


def test_runner_cannot_shadow_a_deployment_owned_builder():
    from revocompute.plugins import PluginManifest

    with pytest.raises(ValueError, match="deployment-owned"):
        PluginManifest.from_mapping({
            "id": "synthetic_family",
            "contributions": {"input_builders": [{"id": "bionuta", "targets": {"af3": "json"}}]},
        })


def test_contribution_descriptor_validates_identity_and_targets():
    descriptor = BuilderDescriptor.from_contribution(
        "atomworks",
        {"targets": {"rfd4": "cif"}, "api_version": 1, "builder_version": 1, "state_schema_version": 1},
        owner="synthetic_runner",
    )
    assert descriptor.global_id == "synthetic_runner:atomworks"
    with pytest.raises(ValueError, match="api_version is not supported"):
        BuilderDescriptor.from_contribution(
            "x", {"api_version": 2, "targets": {"af3": "json"}}, owner="synthetic_runner"
        )
    with pytest.raises(ValueError):
        BuilderDescriptor.from_contribution("x", {"targets": {}}, owner="synthetic_runner")
    with pytest.raises(ValueError):
        BuilderDescriptor.from_contribution("x", {"targets": {"rfd4": "pdb"}}, owner="synthetic_runner")


def _source_form(*, state=None, output_digest=DIGEST):
    return {
        "entities": [
            {"name": "af3.json", "type": "file", "role": "specification", "value": "af3.json", "size": 1, "hash": DIGEST},
        ],
        "workspace": {
            "version": 2,
            "capabilities": {
                "bionuta_builder": {
                    "version": 1,
                    "builder": "bionuta",
                    "builder_version": 2,
                    "state_schema_version": 1,
                    "target": "alphafold3",
                    "revision": 4,
                    "state": {"document": {}} if state is None else state,
                    "dependencies": [],
                    "outputs": [
                        {
                            "logical": "input",
                            "role": "specification",
                            "name": "af3.json",
                            "size": 1,
                            "sha256": output_digest,
                        }
                    ],
                }
            },
        },
    }


def _plan(form):
    return build_plan(
        {"md5sum": "a" * 32, "task_type": "alphafold3", "input_form": json.dumps(form), "uploaded_at": 1},
        current_type=None,
        target_enabled=None,
        files_owned=True,
        snapshot_root=None,
        builder_bindings={
            "bionuta_builder": (
                BIONUTA,
                {"builder": "bionuta", "target": "alphafold3", "outputs": {"input": "specification"}},
            )
        },
    )


def test_clone_plan_carries_bounded_metadata_and_never_the_document():
    plan = _plan(_source_form())
    entry = plan["authoring"][0]
    assert entry["compatible"] and entry["state_available"]
    assert entry["builder"] == "bionuta" and entry["revision"] == 4
    assert "state" not in entry
    assert entry["outputs"][0]["sha256"] == DIGEST


def test_clone_plan_warns_when_the_builder_capability_was_removed():
    plan = build_plan(
        {"md5sum": "a" * 32, "task_type": "alphafold3", "input_form": json.dumps(_source_form()), "uploaded_at": 1},
        current_type=None,
        target_enabled=None,
        files_owned=True,
        snapshot_root=None,
        builder_bindings={},
    )
    assert plan["authoring"] == []
    assert any(item["code"] == "authoring_capability_removed" for item in plan["warnings"])


def test_clone_plan_reports_a_tampered_or_incompatible_state_as_blocked():
    tampered = _plan(_source_form(output_digest="0" * 64))
    assert not tampered["authoring"][0]["compatible"]
    assert tampered["authoring"][0]["reason"] == "authoring_output_mismatch"
    assert any(item["code"] == "authoring_output_mismatch" for item in tampered["warnings"])

    incompatible = _source_form()
    incompatible["workspace"]["capabilities"]["bionuta_builder"]["state_schema_version"] = 99
    blocked = _plan(incompatible)
    assert blocked["authoring"][0]["reason"] == "authoring_incompatible"


def test_clone_plan_never_exposes_another_users_authoring_state():
    plan = build_plan(
        {"md5sum": "a" * 32, "task_type": "alphafold3", "input_form": json.dumps(_source_form()), "uploaded_at": 1},
        current_type=None,
        target_enabled=None,
        files_owned=False,
        snapshot_root=None,
        builder_bindings={
            "bionuta_builder": (
                BIONUTA,
                {"builder": "bionuta", "target": "alphafold3", "outputs": {"input": "specification"}},
            )
        },
    )
    entry = plan["authoring"][0]
    assert entry["reason"] == "authoring_not_owner"
    assert entry["state_available"] is False and entry["compatible"] is False
    assert any(item["code"] == "authoring_not_owner" for item in plan["warnings"])


def test_recorded_authoring_bounds_state_and_needs_an_object():
    source = {"input_form": json.dumps(_source_form())}
    assert recorded_authoring(source, "bionuta_builder")["state"] == {"document": {}}
    assert recorded_authoring(source, "unknown") is None
    huge = _source_form(state={"blob": "x" * (MAX_STATE_BYTES + 1)})
    assert recorded_authoring({"input_form": json.dumps(huge)}, "bionuta_builder") is None


def test_atomworks_session_store_is_owner_scoped_and_expiring(tmp_path):
    store = atomworks.AtomWorksSessionStore(str(tmp_path / "sessions.sqlite3"), ttl_seconds=60)
    store.record("a" * 32, user_id=7)
    assert store.owns("a" * 32, user_id=7)
    assert not store.owns("a" * 32, user_id=8)
    assert not store.owns("a" * 32, user_id=7, now=10**12)
    store.record("b" * 32, user_id=7)
    store.forget("b" * 32)
    assert not store.owns("b" * 32, user_id=7)


@pytest.mark.parametrize(
    ("method", "path", "allowed", "session"),
    [
        ("POST", "/api/sessions", True, None),
        ("GET", "/api/sessions/" + "a" * 32, True, "a" * 32),
        ("POST", "/api/sessions/" + "a" * 32 + "/export", True, "a" * 32),
        ("DELETE", "/api/sessions/" + "a" * 32, True, "a" * 32),
        ("GET", "/api/health", True, None),
        ("GET", "/api/secret", False, None),
        ("POST", "/api/secret", False, None),
        ("GET", "/api/sessions/../../etc/passwd", False, None),
    ],
)
def test_atomworks_gateway_route_allowlist(method, path, allowed, session):
    assert atomworks.route_allowed(method, path) is allowed
    assert atomworks.session_id_from_path(path) == session
