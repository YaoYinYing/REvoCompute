# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Declared demo inputs: the catalog, the obtain route, and the contract.

A demo is a supported input preset a scientist loads into Create Task, so the
server may only ever offer a fixture its own Task declaration already validated:
the catalog is public, the fixture bytes are served by allowlist membership, and
reading either creates, reserves, and authorizes nothing.

The module-level cases drive the parser directly against a Task directory the
test owns, so the whole validation surface - safe relative paths, symlinks, size,
digest, media type, named-role ownership, cardinality, and the Task's own
canonical parameter schema - is exercised without a second implementation of any
of it.  The route cases then drive the built application: an anonymous caller
reads the catalog and the bytes, an unknown or disabled Task is not found, and a
path the declaration does not name is concealed.
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil

import pytest
import yaml

from conftest import _load_pssm_module, _test_client_auth

from revocompute.task_demos import DemoContractError, demo_root, load_task_demos
from revocompute.task_types import get as get_task_type

SYNTHETIC_TASK = "cpu_runner"
TASK_DIR = "tasks/predict"
FIXTURE_NAME = "records.fasta"


def _module(monkeypatch, tmp_path):
    return _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})


def _task_type(module, name: str = SYNTHETIC_TASK):
    """The discovered TaskType with the Task directory the layout declares.

    The Server's loader is the one owner of a Task's directory; the deployed
    Task-scoped layout names it ``tasks/<task-id>``.  Setting it here stubs that
    single upstream value, so the declaration is read from the same address the
    layout defines rather than from a second convention the test invents.
    """
    task_type = get_task_type(name)[0]
    object.__setattr__(task_type, "task_dir", TASK_DIR)
    return task_type


def _declaration(**overrides) -> dict:
    """One syntactically complete declaration the tests then break one field at a time."""
    demo = {
        "id": "records",
        "title": "Records preset",
        "purpose": "Load a working preset.",
        "source": {"name": "Synthetic corpus", "url": "https://example.invalid/synthetic"},
        "license": {"id": "cc0-1.0", "name": "CC0 1.0", "url": "https://example.invalid/cc0"},
        "inputs": {"sequence": [{"path": f"files/{FIXTURE_NAME}", "sha256": "", "media_type": "text/x-fasta"}]},
        "parameters": {"iter": 100},
    }
    demo.update(overrides)
    return {"demos": [demo]}


def _demo_dir(tmp_path: Path) -> Path:
    """A Task directory carrying its own demo fixture, owned by the test."""
    root = tmp_path / "family" / TASK_DIR / "demo"
    (root / "files").mkdir(parents=True)
    shutil.copyfile(
        Path(__file__).resolve().parents[1] / "fixtures" / "runners" / SYNTHETIC_TASK / "tasks" / "predict"
        / "demo" / "files" / FIXTURE_NAME,
        root / "files" / FIXTURE_NAME,
    )
    return root


def _stub(task_type, root: Path):
    """A TaskType-shaped object whose demo directory is the test's own tree."""
    class _Stub:
        pass

    stub = _Stub()
    stub.inputs = task_type.inputs
    stub.schema = task_type.schema
    stub.task_dir = TASK_DIR
    # ``root`` is ``<family>/tasks/predict/demo``, so the family root is two up.
    stub.runtime = type("_Runtime", (), {"root": str(root.parents[2])})()
    return stub


def _write(root: Path, declaration) -> None:
    (root / "demos.yaml").write_text(yaml.safe_dump(declaration, sort_keys=False), encoding="utf-8")


# ---------------------------------------------------------------------------
# The declaration contract, driven directly
# ---------------------------------------------------------------------------


def _load(root: Path, module, declaration: dict, name: str = SYNTHETIC_TASK):
    _write(root, declaration)
    return load_task_demos(_stub(_task_type(module, name), root))


def _complete(root: Path, declaration: dict) -> dict:
    """Fill in the real digest of the fixture the test copied."""
    import hashlib

    digest = hashlib.sha256((root / "files" / FIXTURE_NAME).read_bytes()).hexdigest()
    declaration["demos"][0]["inputs"]["sequence"][0]["sha256"] = digest
    return declaration


def test_a_complete_declaration_loads_with_its_provenance_and_roles(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    root = _demo_dir(tmp_path)
    loaded = _load(root, module, _complete(root, _declaration()))

    assert [demo.id for demo in loaded] == ["records"]
    demo = loaded[0]
    assert demo.title == "Records preset"
    assert demo.license_name == "CC0 1.0"
    # The fixture is bound to the role its declaration named, not to a position.
    assert [(item.role, item.path) for item in demo.files] == [("sequence", f"files/{FIXTURE_NAME}")]
    assert demo.parameters == {"iter": 100}
    assert demo.files_for("sequence") == demo.files


@pytest.mark.parametrize(
    ("label", "mutate"),
    [
        ("digest", lambda d, r: d["demos"][0]["inputs"]["sequence"][0].update(sha256="0" * 64)),
        (
            "traversal",
            lambda d, r: d["demos"][0]["inputs"]["sequence"][0].update(
                path="../files/records.fasta", sha256="0" * 64
            ),
        ),
        ("media_type", lambda d, r: d["demos"][0]["inputs"]["sequence"][0].update(media_type="not a media type")),
        ("unknown_role", lambda d, r: d["demos"][0]["inputs"].update(structure=d["demos"][0]["inputs"]["sequence"])),
        ("required_role", lambda d, r: d["demos"][0]["inputs"].clear()),
        ("cardinality", lambda d, r: d["demos"][0]["inputs"].update(sequence=[])),
        ("unknown_field", lambda d, r: d["demos"][0].update(script="run.sh")),
        (
            "placeholder_license",
            lambda d, r: d["demos"][0].update(license={"id": "unknown", "name": "Unknown"}),
        ),
        ("missing_source", lambda d, r: d["demos"][0].pop("source")),
        ("parameter_out_of_range", lambda d, r: d["demos"][0].update(parameters={"iter": 99999})),
        ("parameter_unknown", lambda d, r: d["demos"][0].update(parameters={"not_a_parameter": 1})),
        ("parameter_type", lambda d, r: d["demos"][0].update(parameters={"iter": "many"})),
        ("bad_id", lambda d, r: d["demos"][0].update(id="Not An Id")),
        ("empty_title", lambda d, r: d["demos"][0].update(title="  ")),
    ],
)
def test_a_declaration_that_breaks_its_contract_is_refused(monkeypatch, tmp_path, label, mutate):
    """Every violation fails closed: a half-validated preset never reaches a form."""
    module = _module(monkeypatch, tmp_path)
    root = _demo_dir(tmp_path)
    declaration = _complete(root, _declaration())
    mutate(declaration, root)

    with pytest.raises(DemoContractError):
        _load(root, module, declaration)


def test_a_fixture_that_is_not_a_single_regular_file_is_refused(monkeypatch, tmp_path):
    """A symlink or hard link could serve bytes the digest never described."""
    module = _module(monkeypatch, tmp_path)
    root = _demo_dir(tmp_path)
    declaration = _complete(root, _declaration())
    target = root / "files" / FIXTURE_NAME
    os.link(target, root / "files" / "second.fasta")
    declaration["demos"][0]["inputs"]["sequence"][0]["path"] = "files/second.fasta"
    declaration["demos"][0]["inputs"]["sequence"][0]["sha256"] = __import__("hashlib").sha256(
        target.read_bytes()
    ).hexdigest()

    with pytest.raises(DemoContractError):
        _load(root, module, declaration)


def test_an_oversize_fixture_is_refused(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    root = _demo_dir(tmp_path)
    import revocompute.task_demos as task_demos

    monkeypatch.setattr(task_demos, "MAX_DEMO_FILE_BYTES", 4)
    with pytest.raises(DemoContractError):
        _load(root, module, _complete(root, _declaration()))


def test_a_malformed_manifest_shape_is_refused(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    root = _demo_dir(tmp_path)
    stub = _stub(_task_type(module), root)
    for document in ("- not a mapping\n", "demos: {}\n", "version: 1\ndemos: []\n"):
        (root / "demos.yaml").write_text(document, encoding="utf-8")
        with pytest.raises(DemoContractError):
            load_task_demos(stub)


def test_a_task_without_a_declared_directory_declares_no_demos(monkeypatch, tmp_path):
    """Not task-scoped means no demos: there is no family-level fallback."""
    module = _module(monkeypatch, tmp_path)
    task_type = _task_type(module)
    object.__setattr__(task_type, "task_dir", "")
    assert demo_root(task_type) is None
    assert load_task_demos(task_type) == ()


# ---------------------------------------------------------------------------
# The catalog and obtain routes, driven through the application
# ---------------------------------------------------------------------------


def test_an_anonymous_caller_reads_the_catalog_without_creating_anything(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    _task_type(module)
    client = module.app.test_client()
    before = module.task_store.list_tasks()
    users_before = module.app.config["user_db"].list_users()

    response = client.get(f"/compute/api/types/{SYNTHETIC_TASK}/demos")

    assert response.status_code == 200
    assert response.mimetype == "application/json"
    body = response.get_json()
    assert body["version"] == 1 and body["task_type"] == SYNTHETIC_TASK
    assert [demo["id"] for demo in body["demos"]] == ["default_controls"]
    first = body["demos"][0]
    assert first["inputs"][f"sequence"] == [
        {
            "role": "sequence",
            "path": f"files/{FIXTURE_NAME}",
            "sha256": first["inputs"]["sequence"][0]["sha256"],
            "size": first["inputs"]["sequence"][0]["size"],
            "media_type": "text/x-fasta",
            "download_url": f"/compute/api/types/{SYNTHETIC_TASK}/demos/default_controls/files/files/{FIXTURE_NAME}",
        }
    ]
    assert first["parameters"] == {"iter": 100, "mass_precision": 2}
    assert first["source"]["name"] == "Synthetic demo corpus"
    assert first["license"]["id"] == "cc-by-4.0"
    # Reading a demo catalog is a read: no Task, no reservation, no user.
    assert module.task_store.list_tasks() == before
    assert module.app.config["user_db"].list_users() == users_before


def test_the_catalog_conforms_to_its_published_schema(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    _task_type(module)
    client = module.app.test_client()
    spec = client.get("/openapi.json").get_json()
    body = client.get(f"/compute/api/types/{SYNTHETIC_TASK}/demos").get_json()

    schema = spec["components"]["schemas"]["TaskDemoCatalog"]
    assert schema.get("additionalProperties") is False
    assert set(body) == set(schema["properties"])
    assert set(schema["required"]) <= set(body)
    demo_schema = spec["components"]["schemas"]["TaskDemo"]
    for demo in body["demos"]:
        assert set(demo) == set(demo_schema["properties"])
        assert set(demo_schema["required"]) <= set(demo)


def test_the_obtain_route_serves_exactly_the_declared_bytes(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    _task_type(module)
    client = module.app.test_client()
    declared = client.get(f"/compute/api/types/{SYNTHETIC_TASK}/demos").get_json()["demos"][0]["inputs"]["sequence"][0]

    response = client.get(declared["download_url"])

    assert response.status_code == 200
    assert response.data == (
        Path(__file__).resolve().parents[1] / "fixtures" / "runners" / SYNTHETIC_TASK / "tasks" / "predict"
        / "demo" / "files" / FIXTURE_NAME
    ).read_bytes()
    assert response.mimetype == "text/x-fasta"
    assert response.headers["Cache-Control"] == "public, max-age=300"


def test_a_path_the_declaration_does_not_name_is_concealed(monkeypatch, tmp_path):
    """Only declared fixtures are reachable, so nothing else can be enumerated."""
    module = _module(monkeypatch, tmp_path)
    _task_type(module)
    client = module.app.test_client()
    base = f"/compute/api/types/{SYNTHETIC_TASK}/demos/default_controls/files"

    for asset in (
        "files/other.fasta",
        "demos.yaml",
        "../demos.yaml",
        "..%2F..%2F..%2Ftasks%2Fpredict%2Ftask.yaml",
        "/etc/passwd",
    ):
        # ``follow_redirects`` so a normalizing redirect cannot stand in for an
        # answer: whatever the request finally resolves to, it is not a fixture.
        response = client.get(f"{base}/{asset}", follow_redirects=True)
        assert response.status_code == 404, asset
    assert client.get(f"/compute/api/types/{SYNTHETIC_TASK}/demos/nope/files/files/{FIXTURE_NAME}").status_code == 404


def test_an_unknown_or_disabled_task_type_is_not_found(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    _task_type(module)
    client = module.app.test_client()
    assert client.get("/compute/api/types/not-a-task/demos").status_code == 404

    module.app.config["manage_db"].task_type_upsert(SYNTHETIC_TASK, enabled=False)
    assert client.get(f"/compute/api/types/{SYNTHETIC_TASK}/demos").status_code == 404
    assert (
        client.get(
            f"/compute/api/types/{SYNTHETIC_TASK}/demos/default_controls/files/files/{FIXTURE_NAME}"
        ).status_code
        == 404
    )


def test_a_task_that_declares_no_demo_returns_an_empty_catalog(monkeypatch, tmp_path):
    module = _module(monkeypatch, tmp_path)
    _task_type(module, "structure_runner")
    body = module.app.test_client().get("/compute/api/types/structure_runner/demos").get_json()

    assert body == {"version": 1, "task_type": "structure_runner", "demos": []}


def test_reading_a_demo_catalog_needs_no_credentials_but_grants_none(monkeypatch, tmp_path):
    """The catalog is public in exactly the way the parameter schema is public."""
    module = _module(monkeypatch, tmp_path)
    _task_type(module)
    client = module.app.test_client()
    headers = _test_client_auth(module)

    anonymous = client.get(f"/compute/api/types/{SYNTHETIC_TASK}/demos")
    authenticated = client.get(f"/compute/api/types/{SYNTHETIC_TASK}/demos", headers=headers)

    assert anonymous.status_code == 200 and authenticated.status_code == 200
    assert anonymous.get_json() == authenticated.get_json()
