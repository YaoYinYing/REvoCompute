# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Real Runner manifests project into the frontend contract without execution.

The frontend fixture harness serves deterministic synthetic payloads; these
tests prove the other direction. Representative *real* ``task.yaml`` manifests
still project through the server's canonical loaders into the same frontend
contract the harness serves, so a fixture cannot quietly drift from a manifest
the product actually ships.

Nothing here executes a Runner, enables one for deployment, or needs its image,
weights, database, or GPU. The isolated application discovers the manifests the
same way production does and the tests read its own API projections.

Cases are chosen for the frontend grammar they exercise — a sequence input, a
molecular-structure input, a parameter-rich CPU method, a GPU method, a
restricted-access GPU method, and a multi-step input workspace — not for
popularity.
"""

from __future__ import annotations

from pathlib import Path

from conftest import _load_pssm_module
from frontend_fixtures import validate_payload

ROOT = Path(__file__).resolve().parents[2]

# One representative per frontend grammar the harness must be able to stand in
# for. None of these needs to be enabled, built, or executable on this host.
SEQUENCE_RUNNER = "colabfold_af2"
STRUCTURE_INPUT_RUNNER = "fpocket"
RESTRICTED_GPU_RUNNER = "alphafold3"
MULTI_ROLE_RUNNER = "boltz_predict"
RICH_METADATA_RUNNER = "gremlin_lh_fit"

STATIC_PLUGINS = {"files", "sequence", "structure", "parameters", "review"}

REPRESENTATIVE_RUNNERS = (
    SEQUENCE_RUNNER,
    STRUCTURE_INPUT_RUNNER,
    RESTRICTED_GPU_RUNNER,
    MULTI_ROLE_RUNNER,
    RICH_METADATA_RUNNER,
)


def _client(monkeypatch, tmp_path):
    module = _load_pssm_module(monkeypatch, tmp_path, extra_env={"RUNNER_UID": "1234", "RUNNER_GID": "5678"})
    return module, module.app.test_client()


def _detail(client, name: str) -> dict:
    response = client.get(f"/compute/api/types/{name}")
    assert response.status_code == 200, response.get_data(as_text=True)
    payload = response.get_json()
    validate_payload("TaskTypeDetail", payload)
    return payload


def _parameters(client, name: str) -> dict:
    response = client.get(f"/compute/api/task-parameters/{name}")
    assert response.status_code == 200, response.get_data(as_text=True)
    payload = response.get_json()
    validate_payload("TaskParameterSchema", payload)
    return payload["properties"]


def _step(payload: dict, step_id: str) -> dict:
    steps = {step["id"]: step for step in payload["input_workspace"]["steps"]}
    assert step_id in steps, f"input workspace has no {step_id!r} step"
    return steps[step_id]


def _capability(step: dict, plugin: str) -> dict:
    matches = [capability for capability in step["capabilities"] if capability["plugin"] == plugin]
    assert matches, f"step {step['id']!r} has no {plugin!r} capability"
    return matches[0]


def test_catalog_projects_every_discovered_runner_into_the_frontend_contract(monkeypatch, tmp_path):
    """The catalog is the frontend's Runner list; every row must be canonical."""
    _module, client = _client(monkeypatch, tmp_path)
    response = client.get("/compute/api/types")
    assert response.status_code == 200
    catalog = response.get_json()
    validate_payload("TaskCatalog", catalog)

    summaries = catalog["task_types"]
    assert len(summaries) >= 40  # the fleet, not a single enabled Runner
    for summary in summaries:
        validate_payload("TaskTypeSummary", summary)
        assert summary["detail_url"] == f"/compute/api/types/{summary['name']}"
        assert summary["parameters_url"] == f"/compute/api/task-parameters/{summary['name']}"
        assert summary["access"]["restricted"] in {True, False}

    names = {summary["name"] for summary in summaries}
    for name in REPRESENTATIVE_RUNNERS:
        assert name in names, f"{name} is missing from the projectable catalog"

    categories = {category["name"] for category in catalog["categories"]}
    assert {"structure", "evolution"} <= categories


def test_sequence_runner_projects_its_input_role_parameters_gpu_metadata_and_workspace(monkeypatch, tmp_path):
    """A GPU sequence Runner: role, parameter schema, GPU flag, workflow, steps."""
    _module, client = _client(monkeypatch, tmp_path)
    detail = _detail(client, SEQUENCE_RUNNER)

    role = detail["inputs"][0]
    assert (role["id"], role["type"]) == ("sequence", "protein_sequence")
    assert set(role["formats"]) >= {"fasta"}
    assert role["cardinality"] == {"min": 1, "max": 1}
    assert role["accept"]

    assert detail["gpus"] is True
    gpu_stages = [stage for stage in detail["workflow"] if stage["requires_gpu"]]
    assert gpu_stages, "a GPU Runner must declare at least one GPU workflow stage"
    assert all(stage["display_name"] for stage in detail["workflow"])

    material = _step(detail, "material")
    assert _capability(material, "sequence")["options"] == {"role": "sequence"}
    assert _capability(material, "files")["title"]
    parameters = _capability(_step(detail, "settings"), "parameters")
    assert parameters["id"]
    assert _capability(_step(detail, "review"), "review")["options"] == {"show_paths": True}

    declared = {step["id"] for step in detail["input_workspace"]["steps"]}
    assert declared == {"material", "settings", "review"}
    assert detail["max_request_bytes"] > 0
    assert detail["citations"], "a method with an upstream publication declares citations"

    schema = _parameters(client, SEQUENCE_RUNNER)
    assert schema["num_recycle"]["type"] == "integer"
    assert schema["num_recycle"]["minimum"] <= schema["num_recycle"]["default"] <= schema["num_recycle"]["maximum"]
    assert schema["model_type"]["enum"]
    assert schema["model_type"]["default"] in schema["model_type"]["enum"]


def test_molecular_structure_runner_projects_its_structure_input_role(monkeypatch, tmp_path):
    """A structure-input Runner: file role, structure inspection, numeric bounds."""
    _module, client = _client(monkeypatch, tmp_path)
    detail = _detail(client, STRUCTURE_INPUT_RUNNER)

    role = detail["inputs"][0]
    assert (role["id"], role["type"]) == ("structure", "protein_structure")
    assert set(role["formats"]) >= {"pdb", "cif"}
    assert role["cardinality"] == {"min": 1, "max": 1}

    structure_step = _step(detail, "structure")
    assert _capability(structure_step, "files")["id"]
    inspection = _capability(structure_step, "structure")
    # The declared options reach the browser unchanged; the step is also where
    # the frontend renders the structure summary rather than a separate page.
    assert inspection["options"]["source"] == "source_files"
    assert inspection["options"]["select_chains"] is False

    schema = _parameters(client, STRUCTURE_INPUT_RUNNER)
    radius = schema["min_alpha_sphere_radius"]
    assert radius["type"] == "number"
    assert radius["minimum"] < radius["maximum"]
    assert schema["min_alpha_spheres_per_pocket"]["type"] == "integer"


def test_gpu_runner_projects_declared_gpu_and_network_metadata(monkeypatch, tmp_path):
    """AlphaFold 3 is GPU-only and restricted; both flags are frontend-visible."""
    _module, client = _client(monkeypatch, tmp_path)
    detail = _detail(client, RESTRICTED_GPU_RUNNER)

    assert detail["gpus"] is True
    assert detail["requires_network"] is False
    gpu_stages = [stage for stage in detail["workflow"] if stage["requires_gpu"]]
    assert gpu_stages and all(stage["display_name"] for stage in detail["workflow"])
    assert _step(detail, "material")["capabilities"]
    assert set(detail["input_workspace"]["steps"][0]["capabilities"][0]) == {
        "plugin",
        "id",
        "title",
        "description",
        "options",
    }

    schema = _parameters(client, RESTRICTED_GPU_RUNNER)
    assert schema["num_diffusion_samples"]["type"] == "integer"
    assert schema["num_diffusion_samples"]["minimum"] <= schema["num_diffusion_samples"]["maximum"]
    assert schema["resolve_msa_overlaps"]["type"] == "boolean"


def test_restricted_runner_projects_access_through_both_frontend_projections(monkeypatch, tmp_path):
    """Catalog carries the compact access state; the detail carries the policy."""
    _module, client = _client(monkeypatch, tmp_path)

    catalog = client.get("/compute/api/types").get_json()
    summary = next(item for item in catalog["task_types"] if item["name"] == RESTRICTED_GPU_RUNNER)
    assert summary["access"]["restricted"] is True
    assert summary["access"]["request_status"] in {None, "pending", "approved", "rejected"}
    validate_payload("TaskTypeSummary", summary)

    access = _detail(client, RESTRICTED_GPU_RUNNER)["access"]
    validate_payload("RunnerAccess", access)
    assert access["restricted"] is True
    assert access["policy_id"]
    assert access["requestable"] is True
    assert access["notice"]["title"]
    assert access["license"]["name"]


def test_runner_with_several_roles_projects_the_multi_step_input_workspace(monkeypatch, tmp_path):
    """Boltz declares two roles and an optional-asset cardinality range."""
    _module, client = _client(monkeypatch, tmp_path)
    response = client.get(f"/compute/api/types/{MULTI_ROLE_RUNNER}")
    assert response.status_code == 200, response.get_data(as_text=True)
    detail = response.get_json()

    roles = {role["id"]: role for role in detail["inputs"]}
    assert set(roles) == {"specification", "assets"}
    assert roles["specification"]["cardinality"] == {"min": 1, "max": 1}
    # An optional role is expressed as a zero minimum, not as a missing role.
    assert roles["assets"]["cardinality"]["min"] == 0
    assert roles["assets"]["cardinality"]["max"] > 1
    assert detail["gpus"] is True
    assert detail["requires_network"] is True

    steps = [step["id"] for step in detail["input_workspace"]["steps"]]
    assert steps == ["material", "settings", "review"]
    for step in detail["input_workspace"]["steps"]:
        for capability in step["capabilities"]:
            assert capability["plugin"] in STATIC_PLUGINS

    schema = _parameters(client, MULTI_ROLE_RUNNER)
    assert schema["use_msa_server"]["type"] == "boolean"
    assert schema["use_msa_server"]["default"] is False


def test_rich_method_metadata_projects_considerations_citations_and_parameters(monkeypatch, tmp_path):
    """A parameter-rich CPU method: guidance prose, citations, and typed schema."""
    _module, client = _client(monkeypatch, tmp_path)
    detail = _detail(client, RICH_METADATA_RUNNER)

    for field in ("summary", "use_when", "input_summary", "output_summary"):
        assert detail[field], f"{field} must project for the Runner detail page"
    assert detail["display_name"]
    assert detail["considerations"] and all(isinstance(item, str) for item in detail["considerations"])
    assert detail["gpus"] is False
    assert detail["citations"], "citations must project"
    for citation in detail["citations"]:
        assert citation["num"] >= 1
        assert citation["doi"] and citation["title"] and citation["url"]

    schema = _parameters(client, RICH_METADATA_RUNNER)
    assert len(schema) >= 10
    assert schema["regularization"]["enum"]
    assert schema["regularization"]["default"] in schema["regularization"]["enum"]
    assert schema["use_bias"]["type"] == "boolean"
    assert schema["iterations"]["type"] == "integer"
    assert schema["iterations"]["minimum"] < schema["iterations"]["maximum"]


def test_disabled_runner_leaves_every_frontend_projection(monkeypatch, tmp_path):
    """Enablement is orthogonal to the manifest contract, and it fails closed."""
    module, client = _client(monkeypatch, tmp_path)
    assert client.get(f"/compute/api/types/{SEQUENCE_RUNNER}").status_code == 200

    module.manage_db.task_type_upsert(SEQUENCE_RUNNER, enabled=False)
    catalog = client.get("/compute/api/types").get_json()
    assert SEQUENCE_RUNNER not in {item["name"] for item in catalog["task_types"]}
    assert client.get(f"/compute/api/types/{SEQUENCE_RUNNER}").status_code == 404
    assert client.get(f"/compute/api/task-parameters/{SEQUENCE_RUNNER}").status_code == 404


def test_real_manifests_load_through_the_canonical_discovery_path():
    """The projection source is a real TaskType, not a fixture-shaped copy.

    Discovery is the production entry point, so this asserts directly on the
    loaded ``TaskType`` rather than on an HTTP projection of it.
    """
    from revocompute.task_types import discover_plugins, get, list_types

    discover_plugins(str(ROOT / "docker" / "runners"))

    names = {task_type.name for task_type in list_types()}
    assert set(REPRESENTATIVE_RUNNERS) <= names

    sequence, _runner = get(SEQUENCE_RUNNER)
    assert sequence.inputs and sequence.inputs[0].name == "sequence"
    assert sequence.input_workspace and sequence.input_workspace[0].capabilities
    assert sequence.schema["properties"]

    structure, _runner = get(STRUCTURE_INPUT_RUNNER)
    assert structure.inputs[0].type == "protein_structure"
    assert structure.input_workspace[0].capabilities


def test_pssm_gremlin_fixture_mirrors_the_real_manifest_result_workspace():
    """The named fixture's result views must match the owning manifest.

    ``pssm_gremlin_scenario()`` claims the ``gremlin_lh_fit`` identity, so its
    view ids, roles, and primary matrix must agree with the real
    ``result_workspace`` the server loads. A drift here would let a browser test
    pass against a contract the product does not ship — including inverting raw
    (primary) and APC (evidence).
    """
    from revocompute.task_types import discover_plugins, get
    from frontend_fixtures import pssm_gremlin_scenario

    discover_plugins(str(ROOT / "docker" / "runners"))
    task, _runner = get(RICH_METADATA_RUNNER)

    real_roles = {view.id: (view.plugin, view.role) for view in task.result_workspace}
    manifest = pssm_gremlin_scenario().result_manifest()
    assert manifest is not None
    fixture_roles = {view["id"]: (view["plugin"], view["role"]) for view in manifest["views"]}

    assert set(fixture_roles) == set(real_roles)
    for view_id, (plugin, role) in real_roles.items():
        assert fixture_roles[view_id] == (plugin, role), view_id

    # The declaration the science depends on: raw is primary, APC is evidence.
    assert real_roles["raw_couplings"][1] == "primary"
    assert real_roles["apc_couplings"][1] == "evidence"

    # The views' sources and rendering mappings are the contract the frontend
    # reads (matrix row labels, scalar-summary fields, ...); they must match too.
    real_views = {view.id: view for view in task.result_workspace}
    fixture_views = {view["id"]: view for view in manifest["views"]}
    for view_id, real in real_views.items():
        assert fixture_views[view_id]["mapping"] == real.mapping, view_id
        real_sources = {name: [selector.value for selector in selectors] for name, selectors in real.sources.items()}
        assert fixture_views[view_id]["sources"] == real_sources, view_id


def test_pssm_gremlin_fixture_mirrors_the_real_manifest_input_and_parameters():
    """The fixture's roles and parameter schema track the real manifest.

    Names alone are too weak: the projected parameter document IS the task.yaml
    schema, so the fixture's property maps must be equal (defaults, exclusive
    bounds, enum, and x-ui-control included). A fixture that drops the seed
    control or widens exclusiveMinimum to an inclusive bound would render a
    control production never ships.
    """
    from revocompute.task_types import discover_plugins, get
    from frontend_fixtures import build_parameter_schema, pssm_gremlin_scenario

    discover_plugins(str(ROOT / "docker" / "runners"))
    task, _runner = get(RICH_METADATA_RUNNER)
    scenario = pssm_gremlin_scenario()

    assert {role.id for role in scenario.runner.inputs} == {role.name for role in task.inputs}
    assert scenario.runner.display_name == task.display_name

    projected = build_parameter_schema(scenario.runner)["properties"]
    real = task.schema["properties"]
    assert set(projected) == set(real)
    for name, expected in real.items():
        assert projected[name] == expected, f"{name}: {projected[name]} != {expected}"


def test_pssm_gremlin_fixture_artifacts_match_the_server_projection(monkeypatch, tmp_path):
    """Every gremlin artifact's role, capability, and preview is server-derived.

    The fixture's own hand-declared role/capability could silently disagree with
    the manifest: the server publishes ``raw_scores.csv`` as the primary matrix,
    ``model/metadata.json``/``summary.json`` as provenance rendered inline, and
    no preview for the ``.stdout`` diagnostic. This projects the fixture's
    artifact paths through the server's own result logic and asserts they agree,
    so a fixture that shows a label production never emits fails here.
    """
    module, _test_client = _client(monkeypatch, tmp_path)
    from revocompute import task_runtime
    from revocompute.result_storyboard import declared_file_roles, expected_file_tree
    from revocompute.task_types import get
    from frontend_fixtures import pssm_gremlin_scenario

    task, _runner = get(RICH_METADATA_RUNNER)
    server_dir = module.CONFIG.server_dir

    fixture = pssm_gremlin_scenario().result
    assert fixture is not None
    artifacts = []
    for spec in fixture.artifacts:
        preview = task_runtime._preview_kind(spec.path)
        artifacts.append(
            {
                "path": spec.path,
                "size": 1,
                "preview": preview,
                "capability": task_runtime.artifact_capability(preview),
                "role": task_runtime._default_artifact_role(spec.path),
            }
        )
    tree = expected_file_tree(task, server_dir)
    roles = declared_file_roles(tree, [artifact["path"] for artifact in artifacts])
    task_runtime._resolve_result_views(task, artifacts, server_dir, roles)

    projected = {artifact["path"]: artifact for artifact in artifacts}
    for spec in fixture.artifacts:
        real = projected[spec.path]
        assert spec.role == real["role"], f"{spec.path} role: fixture={spec.role} server={real['role']}"
        assert spec.capability == real["capability"], (
            f"{spec.path} capability: fixture={spec.capability} server={real['capability']}"
        )
        # An artifact the server renders inline carries a text preview; the
        # fixture must declare the matching capability rather than download-only.
        assert (spec.capability == "text") == (real["preview"] == "text"), f"{spec.path} preview mismatch"
