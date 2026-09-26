# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Opt-in acceptance against exact candidate Tool SIFs on an Apptainer host."""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from pathlib import Path

import pytest

from revocompute.tool_calls import ToolCallDatabase, new_tool_call_id
from revocompute.tool_runtime_manager import ToolExecutionTimeout, ToolRuntimeManager
from revocompute.tool_types import ToolRegistry
from revocompute.tool_workspace import ToolWorkspace

REPO_ROOT = Path(__file__).resolve().parents[2]


def _candidate_registry() -> ToolRegistry:
    image_dir = os.environ.get("REVOCOMPUTE_TOOL_ACCEPTANCE_IMAGE_DIR")
    if not image_dir:
        pytest.skip("REVOCOMPUTE_TOOL_ACCEPTANCE_IMAGE_DIR is not configured")
    return ToolRegistry.discover(
        REPO_ROOT / "docker" / "tools",
        enabled={"bioio", "chemio"},
        image_root=image_dir,
    )


def _execute_tool(manager, workspace, tool, source: Path, role: str, filename: str, parameters: dict):
    call_id = new_tool_call_id()
    workspace.create(call_id)
    item = workspace.materialize_file(
        call_id,
        role=role,
        filename=filename,
        accepted_formats=tool.inputs[0].formats,
        source=source,
    )
    workspace.write_request(call_id, tool, {role: [item]}, parameters)
    started = time.monotonic()
    cold = manager.ensure_warm(tool.runtime)
    root = workspace.call_root(call_id)
    result = manager.execute(
        tool.runtime,
        [
            *tool.runtime.entrypoint,
            "run",
            "--tool",
            tool.name,
            "--request",
            "/tool/scratch/request.json",
            "--output",
            "/tool/output",
        ],
        binds=(
            (root / "input", "/tool/input", "ro"),
            (root / "output", "/tool/output", "rw"),
            (root / "scratch", "/tool/scratch", "rw"),
        ),
        timeout_seconds=tool.timeout_seconds,
        output_max_bytes=workspace.output_max_bytes,
    )
    assert result.returncode == 0, result.stderr
    outputs, warnings, provenance = workspace.collect(call_id, tool)
    return call_id, cold, time.monotonic() - started, outputs, warnings, provenance


def test_exact_candidate_tool_runtime_lifecycle_and_scientific_outputs(tmp_path):
    registry = _candidate_registry()
    calls = ToolCallDatabase(str(tmp_path / "calls.sqlite3"))
    workspace = ToolWorkspace(tmp_path / "workspaces", request_max_bytes=1_000_000, output_max_bytes=1_000_000)
    manager = ToolRuntimeManager(tmp_path / "runtime-state", calls, idle_ttl_seconds=1)
    runtimes = registry.families()
    structure = REPO_ROOT / "tests" / "data" / "3fap_hf3_A_short.pdb"
    ligand = REPO_ROOT / "tests" / "data" / "docking" / "ethanol.sdf"
    metrics: dict[str, float | int] = {}
    try:
        manager.reset_cold(runtimes)
        direct_started = time.monotonic()
        direct = subprocess.run(
            [
                "apptainer",
                "exec",
                "--cleanenv",
                str(registry.get("structure_inspect").runtime.image),
                *registry.get("structure_inspect").runtime.health_command,
            ],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        metrics["direct_bioio_exec_seconds"] = time.monotonic() - direct_started
        assert direct.returncode == 0, direct.stderr
        first_id, first_cold, first_seconds, first_outputs, _, _ = _execute_tool(
            manager, workspace, registry.get("structure_inspect"), structure, "structure", "sample.pdb", {}
        )
        assert first_cold is True
        inspection = json.loads(Path(first_outputs["inspection"][0]["physical_path"]).read_text(encoding="utf-8"))
        assert inspection["models"] == 1
        assert inspection["atom_count"] > 0

        _, warm_cold, warm_seconds, fasta_outputs, _, _ = _execute_tool(
            manager, workspace, registry.get("structure_to_fasta"), structure, "structure", "sample.pdb", {}
        )
        assert warm_cold is False
        assert Path(fasta_outputs["sequence"][0]["physical_path"]).read_text(encoding="utf-8").startswith(">A\n")
        _, convert_warm, _, converted_outputs, _, _ = _execute_tool(
            manager,
            workspace,
            registry.get("structure_convert"),
            structure,
            "structure",
            "sample.pdb",
            {"output_format": "mmcif"},
        )
        assert convert_warm is False
        assert Path(converted_outputs["structure"][0]["physical_path"]).read_text(encoding="utf-8").startswith("data_")
        _, fasta_warm, _, fasta_inspection_outputs, _, _ = _execute_tool(
            manager,
            workspace,
            registry.get("fasta_inspect"),
            REPO_ROOT / "tests" / "data" / "simplefold_tiny.fa",
            "sequence",
            "sequence.fasta",
            {},
        )
        assert fasta_warm is False
        fasta_inspection = json.loads(
            Path(fasta_inspection_outputs["inspection"][0]["physical_path"]).read_text(encoding="utf-8")
        )
        assert fasta_inspection["sequence_count"] >= 1

        _, chem_cold, chem_seconds, ligand_outputs, _, provenance = _execute_tool(
            manager,
            workspace,
            registry.get("ligand_convert"),
            ligand,
            "ligand",
            "ethanol.sdf",
            {"output_format": "mol2"},
        )
        assert chem_cold is True
        mol2 = Path(ligand_outputs["ligand"][0]["physical_path"]).read_text(encoding="utf-8")
        assert "NO_CHARGES" in mol2
        assert "GASTEIGER" not in mol2
        assert provenance["declared"]["mode"] == "representation_only"
        _, chem_warm, chem_warm_seconds, _, _, _ = _execute_tool(
            manager, workspace, registry.get("ligand_inspect"), ligand, "ligand", "ethanol.sdf", {}
        )
        assert chem_warm is False

        bioio = registry.get("structure_inspect").runtime
        manager.reset_cold((bioio,))
        acquisitions: list[bool] = []
        threads = [threading.Thread(target=lambda: acquisitions.append(manager.ensure_warm(bioio))) for _ in range(3)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert sorted(acquisitions) == [False, False, True]

        foreign = workspace.root / "foreign-marker"
        foreign.write_text("must not be visible", encoding="utf-8")
        root = workspace.call_root(first_id)
        isolated = manager.execute(
            bioio,
            [
                "python3",
                "-c",
                "import os,socket,pathlib,sys; "
                "sys.exit(0 if os.environ.get('OMP_NUM_THREADS') == '1' "
                "and [n for _,n in socket.if_nameindex()] == ['lo'] "
                "and not pathlib.Path('/tool/foreign-marker').exists() else 1)",
            ],
            binds=(
                (root / "input", "/tool/input", "ro"),
                (root / "output", "/tool/output", "rw"),
                (root / "scratch", "/tool/scratch", "rw"),
            ),
            timeout_seconds=10,
        )
        assert isolated.returncode == 0, isolated.stderr

        with pytest.raises(ToolExecutionTimeout):
            manager.execute(
                bioio,
                ["sleep", "10"],
                binds=(
                    (root / "input", "/tool/input", "ro"),
                    (root / "output", "/tool/output", "rw"),
                    (root / "scratch", "/tool/scratch", "rw"),
                ),
                timeout_seconds=1,
            )
        recovered = manager.execute(
            bioio,
            list(bioio.health_command),
            binds=(
                (root / "input", "/tool/input", "ro"),
                (root / "output", "/tool/output", "rw"),
                (root / "scratch", "/tool/scratch", "rw"),
            ),
            timeout_seconds=10,
        )
        assert recovered.returncode == 0

        time.sleep(1.1)
        assert manager.stop_idle((bioio,)) == ["bioio"]
        assert manager.ensure_warm(bioio) is True

        status = manager.status(bioio)
        assert status.timeout_count == 1
        assert status.cold_start_count >= 2
        metrics.update(
            first_call_seconds=first_seconds,
            warm_call_seconds=warm_seconds,
            chemio_first_call_seconds=chem_seconds,
            chemio_warm_call_seconds=chem_warm_seconds,
            runtime_start_seconds=status.runtime_start_seconds,
            warm_hit_count=status.warm_hit_count,
        )
        print(json.dumps(metrics, sort_keys=True))
    finally:
        manager.reset_cold(runtimes)
        calls.engine.dispose()
