# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Unit tests for SlurmJob — wrapper script generation, srun args, shell quoting."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import threading
from dataclasses import replace
from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from revocompute.job import JobState
from revocompute.job.runners.slurm_runner import JOB_ID_PREFIX, SlurmJob, _sanitize_name, _sh_quote
from revocompute.resource_policy import ResolvedResources


def _make_task_type(**kwargs):
    from revocompute.task_types import RuntimeFamily, TaskInputRole, TaskType

    defaults = dict(
        name="cpu_runner",
        display_name="GREMLIN",
        runtime=RuntimeFamily(
            name="cpu_runner",
            entrypoint=("bash", "/app/run.sh"),
            definition="docker/cpu_runner/cpu_runner.def",
            slurm_image="/opt/images/cpu_runner_v1.sif",
            image_artifact="cpu_runner_v1.sif",
        ),
        inputs=(
            TaskInputRole(
                name="sequence",
                title="Sequence",
                type="protein_sequence",
                formats=("fasta",),
                minimum=1,
                maximum=1,
            ),
        ),
        stage_markers={
            "hhblits": "HHblits MSA",
            "cpu_runner": "GREMLIN opt",
        },
    )
    defaults.update(kwargs)
    return TaskType(**defaults)


def _make_runner(**kwargs):
    from revocompute.task_types import RunnerConfig

    return RunnerConfig(**kwargs)


def _make_entities():
    return [
        {
            "name": "file",
            "type": "file",
            "value": "input.fasta",
            "verified_value": "input.fasta",
            "relative_path": "input.fasta",
            "hash": "abc123",
            "mounted": "/workspace/inputs/input.fasta",
            "snapshot_path": "/srv/workspaces/tester/task-1/inputs/input.fasta",
            "snapshot_root": "/srv/workspaces/tester/task-1/inputs",
            "workspace_key": "tester",
        },
        {
            "name": "iter",
            "type": "param",
            "value": "100",
            "verified_value": "100",
        },
    ]


class _FakeSrunProcess:
    """A subprocess.Popen-shaped scheduler boundary fake."""

    def __init__(
        self,
        *,
        stdout: str = "",
        stderr: str = "",
        returncode: int | None = 0,
        pid: int = 4217,
        timeout_once: bool = False,
    ) -> None:
        self.stdout = StringIO(stdout)
        self.stderr = StringIO(stderr)
        self.returncode = returncode
        self.pid = pid
        self.timeout_once = timeout_once
        self.wait_calls = 0
        self.terminated = False
        self.killed = False

    def wait(self, timeout=None):
        self.wait_calls += 1
        if self.timeout_once and not self.killed:
            self.timeout_once = False
            raise subprocess.TimeoutExpired(["srun"], timeout)
        if self.returncode is None:
            self.returncode = 0
        return self.returncode

    def poll(self):
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = -15

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9


class _BarrierLineStream:
    def __init__(self, line: str, ready: threading.Event, release: threading.Event) -> None:
        self._line = line
        self._ready = ready
        self._release = release
        self.closed = False

    def readline(self) -> str:
        self._ready.set()
        self._release.wait()
        line, self._line = self._line, ""
        return line

    def close(self) -> None:
        self.closed = True


class _EofSignalStream(StringIO):
    def __init__(self, eof: threading.Event) -> None:
        super().__init__("")
        self._eof = eof

    def readline(self) -> str:
        value = super().readline()
        self._eof.set()
        return value


def _policy(**overrides) -> ResolvedResources:
    defaults = dict(
        cpus=1,
        memory="4G",
        max_runtime_seconds=24 * 60 * 60,
        partition=None,
        gres=None,
        nodes=1,
        ntasks=1,
        qos=None,
        account=None,
        constraint=None,
        exclusive=False,
        requires_gpu=False,
        sources={},
    )
    defaults.update(overrides)
    return ResolvedResources(**defaults)


# -- wrapper script -----------------------------------------------------------


def test_render_wrapper_has_shebang_and_set_e(tmp_path):
    job = SlurmJob(
        "task-1",
        _make_task_type(),
        _make_runner(),
        _make_entities(),
        str(tmp_path / "out"),
        username="alice",
    )
    script = job._render_wrapper()
    lines = script.splitlines()
    assert lines[0] == "#!/bin/bash"
    assert "set -euo pipefail" in script
    assert "/usr/bin/time -f" in script
    assert "max_rss_kib=%M" in script
    assert "visible_gpu_devices=%s" in script
    assert "REVODESIGN_RESOURCE_BEGIN" in script
    assert "REVODESIGN_RESOURCE_END" in script
    assert 'exit "$runner_status"' in script
    assert subprocess.run(["bash", "-n"], input=script, text=True, check=False).returncode == 0

    gpu_script = SlurmJob(
        "task-1",
        _make_task_type(gpus=True),
        _make_runner(),
        _make_entities(),
        str(tmp_path / "gpu-out"),
        username="alice",
    )._render_wrapper()
    assert subprocess.run(["bash", "-n"], input=gpu_script, text=True, check=False).returncode == 0


def test_gpu_wrapper_samples_assigned_device_and_emits_resource_evidence(tmp_path):
    workspace = tmp_path / "workspace" / "task-1"
    inputs = workspace / "inputs"
    inputs.mkdir(parents=True)
    input_path = inputs / "input.fasta"
    input_path.write_text(">test\nACDE\n", encoding="utf-8")
    entities = _make_entities()
    entities[0] = {
        **entities[0],
        "snapshot_path": str(input_path),
        "snapshot_root": str(inputs),
        "hash": hashlib.sha256(input_path.read_bytes()).hexdigest(),
    }
    output_dir = tmp_path / "out"
    job = SlurmJob(
        "task-1",
        _make_task_type(gpus=True),
        _make_runner(),
        entities,
        str(output_dir),
        username="alice",
    )
    job._prepare_scratch_dir()
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_apptainer = fake_bin / "apptainer"
    fake_apptainer.write_text("#!/bin/bash\nsleep 1.1\n", encoding="utf-8")
    fake_apptainer.chmod(0o700)
    fake_nvidia_smi = fake_bin / "nvidia-smi"
    fake_nvidia_smi.write_text(
        '#!/bin/bash\n[[ "$*" == *"--id=0"* ]] || exit 2\nprintf "512, 73\\n"\n',
        encoding="utf-8",
    )
    fake_nvidia_smi.chmod(0o700)
    environment = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "SLURM_JOB_ID": "42",
        "SLURM_CPUS_PER_TASK": "2",
        "SLURM_NTASKS": "1",
        "CUDA_VISIBLE_DEVICES": "0",
    }

    result = subprocess.run(
        ["bash"],
        input=job._render_wrapper(),
        text=True,
        capture_output=True,
        env=environment,
        check=False,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    job._job_id = "42"
    job._stdout_lines = result.stdout.splitlines(keepends=True)
    job._save_output()
    resource = output_dir / "execution" / "slurm-alice-cpu_runner-task-1.resource.json"
    payload = json.loads(resource.read_text(encoding="utf-8"))
    assert payload["allocated_gpus_on_node"] == "1"
    assert payload["allocated_gpu_ids"] == "0"
    assert payload["visible_gpu_devices"] == "0"
    assert payload["gpu_memory_peak_mib"] == 512
    assert payload["gpu_utilization_peak_percent"] == 73


def _run_gpu_wrapper(tmp_path, *, env_gpus: dict[str, str]) -> dict:
    """Run the real wrapper for a GPU Task and return its published envelope.

    The wrapper is executed, not inspected: the claim under test is that the
    compute node's own report of how many accelerators it holds is a *count*, and
    that the receipt it writes and the envelope it publishes agree.
    """
    workspace = tmp_path / "workspace" / "task-1"
    inputs = workspace / "inputs"
    inputs.mkdir(parents=True, exist_ok=True)
    input_path = inputs / "input.fasta"
    input_path.write_text(">test\nACDE\n", encoding="utf-8")
    entities = _make_entities()
    entities[0] = {
        **entities[0],
        "snapshot_path": str(input_path),
        "snapshot_root": str(inputs),
        "hash": hashlib.sha256(input_path.read_bytes()).hexdigest(),
    }
    output_dir = tmp_path / "out"
    job = SlurmJob(
        "task-1",
        _make_task_type(gpus=True),
        _make_runner(),
        entities,
        str(output_dir),
        username="alice",
        resource_policy=_policy(gres="gpu:2", requires_gpu=True),
    )
    job._prepare_scratch_dir()
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir(exist_ok=True)
    fake_apptainer = fake_bin / "apptainer"
    fake_apptainer.write_text("#!/bin/bash\nexit 0\n", encoding="utf-8")
    fake_apptainer.chmod(0o700)
    fake_nvidia_smi = fake_bin / "nvidia-smi"
    fake_nvidia_smi.write_text('#!/bin/bash\nprintf "512, 73\\n"\n', encoding="utf-8")
    fake_nvidia_smi.chmod(0o700)
    environment = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "SLURM_JOB_ID": "4217",
        "SLURM_CPUS_PER_TASK": "2",
        "SLURM_NTASKS": "1",
        **env_gpus,
    }

    result = subprocess.run(
        ["bash"],
        input=job._render_wrapper(),
        text=True,
        capture_output=True,
        env=environment,
        check=False,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    job._job_id = "4217"
    job._stdout_lines = result.stdout.splitlines(keepends=True)
    job._save_output()
    payload = json.loads(
        (output_dir / "execution" / "slurm-alice-cpu_runner-task-1.resource.json").read_text(encoding="utf-8")
    )
    receipt = job.read_allocation_receipt()
    assert receipt is not None, "the wrapper must leave its compute-node receipt"
    return {"envelope": payload, "receipt": receipt}


def test_a_numeric_slurm_gpu_count_is_a_count_not_a_device_list(tmp_path):
    """The normal Slurm spelling is a number, and a number is the count.

    ``SLURM_GPUS_ON_NODE=2`` reaching the comma-list reader becomes 1, so a
    two-GPU receipt would persist a one-GPU allocation while the canonical start
    callback uses the requested count of two.
    """
    for value, expected in (("2", 2), ("1", 1), ("4", 4)):
        outcome = _run_gpu_wrapper(
            tmp_path / f"numeric-{value}",
            env_gpus={"SLURM_GPUS_ON_NODE": value},
        )
        assert outcome["receipt"]["gpus"] == expected
        assert outcome["envelope"]["allocated_gpus_on_node"] == str(expected)


def test_a_device_id_list_fallback_is_counted_by_its_members(tmp_path):
    """``SLURM_JOB_GPUS`` / ``CUDA_VISIBLE_DEVICES`` are device lists."""
    job_gpus = _run_gpu_wrapper(
        tmp_path / "job-gpus",
        env_gpus={"SLURM_JOB_GPUS": "0,1"},
    )
    assert job_gpus["receipt"]["gpus"] == 2
    assert job_gpus["envelope"]["allocated_gpus_on_node"] == "2"

    visible = _run_gpu_wrapper(
        tmp_path / "visible",
        env_gpus={"CUDA_VISIBLE_DEVICES": "0,1,2"},
    )
    assert visible["receipt"]["gpus"] == 3
    assert visible["envelope"]["allocated_gpus_on_node"] == "3"


def test_a_no_device_or_empty_value_reports_no_gpus(tmp_path):
    """The scheduler's sentinel means zero, and so does an absent spelling."""
    sentinel = _run_gpu_wrapper(
        tmp_path / "sentinel",
        env_gpus={"SLURM_GPUS_ON_NODE": "NoDevFiles"},
    )
    assert sentinel["receipt"]["gpus"] == 0

    empty = _run_gpu_wrapper(tmp_path / "empty", env_gpus={"SLURM_GPUS_ON_NODE": ""})
    assert empty["receipt"]["gpus"] == 0
    assert empty["envelope"]["allocated_gpus_on_node"] == ""


def test_a_malformed_gpu_value_never_invents_a_count(tmp_path):
    """A value that is neither a count nor a list is refused, and never exceeds
    the evidence: the numeric spelling is preferred, so a malformed one falls
    through rather than being read as a number."""
    outcome = _run_gpu_wrapper(
        tmp_path / "malformed",
        env_gpus={"SLURM_GPUS_ON_NODE": "0,,1", "SLURM_JOB_GPUS": "0"},
    )
    # The malformed numeric spelling is refused, so the valid list spelling is
    # used -- one device, never the two the malformed value might suggest.
    assert outcome["receipt"]["gpus"] == 1
    assert outcome["envelope"]["allocated_gpus_on_node"] == "1"


def test_resource_markers_start_a_line_after_output_without_a_trailing_newline(tmp_path):
    """Upstream that ends without a newline must not swallow the BEGIN marker.

    A trailing ANSI reset from a progress bar is the observed real case: the
    marker lands mid-line, ``_resource_capture_text`` cannot find it and
    ``accounting_available`` becomes False, failing an otherwise successful GPU
    Task with RESOURCE_OBSERVATION_FAILURE.
    """
    output_dir = tmp_path / "out"
    workspace = tmp_path / "workspace" / "task-1"
    inputs = workspace / "inputs"
    inputs.mkdir(parents=True)
    input_path = inputs / "input.fasta"
    input_path.write_text(">test\nACDE\n", encoding="utf-8")
    entities = _make_entities()
    entities[0] = {
        **entities[0],
        "snapshot_path": str(input_path),
        "snapshot_root": str(inputs),
        "hash": hashlib.sha256(input_path.read_bytes()).hexdigest(),
    }
    job = SlurmJob(
        "task-1",
        _make_task_type(),
        _make_runner(),
        entities,
        str(output_dir),
        username="alice",
    )
    job._prepare_scratch_dir()
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_apptainer = fake_bin / "apptainer"
    fake_apptainer.write_text('#!/bin/bash\nprintf "design done\\033[0m"\n', encoding="utf-8")
    fake_apptainer.chmod(0o700)
    environment = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "SLURM_JOB_ID": "42",
        "SLURM_CPUS_PER_TASK": "2",
        "SLURM_NTASKS": "1",
    }

    result = subprocess.run(
        ["bash"],
        input=job._render_wrapper(),
        text=True,
        capture_output=True,
        env=environment,
        check=False,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    job._job_id = "42"
    job._stdout_lines = result.stdout.splitlines(keepends=True)
    job._save_output()
    resource = output_dir / "execution" / "slurm-alice-cpu_runner-task-1.resource.json"
    assert resource.is_file()
    assert json.loads(resource.read_text(encoding="utf-8"))["job_id"] == "42"


def test_render_input_snapshot_is_verified_without_staging(tmp_path):
    job = SlurmJob("task-1", _make_task_type(), _make_runner(), _make_entities(), str(tmp_path / "out"))
    script = job._render_wrapper()
    assert "test -f '/srv/workspaces/tester/task-1/inputs/input.fasta'" in script
    assert "abc123  /srv/workspaces/tester/task-1/inputs/input.fasta" in script
    assert "sha256sum --check --status" in script
    assert "ln -f" not in script


# -- srun arguments -----------------------------------------------------------


def test_build_srun_args_includes_job_name(tmp_path):
    job = SlurmJob(
        "abcdef1234567890",
        _make_task_type(),
        _make_runner(),
        _make_entities(),
        str(tmp_path / "out"),
        username="testuser",
    )
    args = job._build_srun_args()
    job_name = next(a for a in args if a.startswith("--job-name="))
    assert "revocomput_testuser_cpu_runner_abcdef12" == job_name.split("=", 1)[1]


def test_build_srun_args_no_db_defaults(tmp_path):
    job = SlurmJob("task-1", _make_task_type(), _make_runner(), _make_entities(), str(tmp_path / "out"))
    args = job._build_srun_args()
    assert "--cpus-per-task=1" in args
    assert "--mem=4G" in args
    assert "--time=1-00:00:00" in args
    assert "--nodes=1" in args
    assert "--ntasks=1" in args
    assert f"--chdir={tmp_path / 'out'}" in args
    assert "--job-name=revocomput_unknown_cpu_runner_task-1" in args


def test_build_srun_args_gpu_task_reserves_one_gpu_by_default(tmp_path):
    job = SlurmJob(
        "task-1",
        _make_task_type(gpus=True),
        _make_runner(),
        _make_entities(),
        str(tmp_path / "out"),
    )

    assert "--gres=gpu:1" in job._build_srun_args()


def test_build_srun_args_gpu_task_uses_configured_gres(tmp_path):
    class _ManageDb:
        def resolve_task_resources(self, tool, *, requires_gpu, default_timeout_seconds):
            return ResolvedResources(
                cpus=1,
                memory="4G",
                max_runtime_seconds=3600,
                partition=None,
                gres="gpu:a100:1",
                nodes=1,
                ntasks=1,
                qos=None,
                account=None,
                constraint=None,
                exclusive=False,
                requires_gpu=True,
                sources={"gres": "task:slurm_gres"},
            )

    job = SlurmJob(
        "task-1",
        _make_task_type(gpus=True),
        _make_runner(),
        _make_entities(),
        str(tmp_path / "out"),
        manage_db=_ManageDb(),
    )
    args = job._build_srun_args()

    assert "--gres=gpu:a100:1" in args
    assert "--gres=gpu:1" not in args


# -- apptainer invocation -----------------------------------------------------


def test_render_apptainer_binds_and_env(tmp_path):
    job = SlurmJob(
        "task-1",
        _make_task_type(gpus=True),
        _make_runner(),
        _make_entities(),
        str(tmp_path / "out"),
    )
    script = job._render_wrapper()
    assert "apptainer exec --nv" in script
    assert "--bind" in script
    # Strong containment: task-backed /tmp and private $HOME, with no implicit
    # host environment or mounts.
    assert "--containall" in script
    assert "--cleanenv" in script
    assert "/workspace/inputs" in script
    assert "/workspace/outputs" in script
    assert "--bind '/srv/workspaces/tester/task-1/scratch':/tmp" in script
    assert "export APPTAINERENV_TASK_ID=" in script
    assert "export APPTAINERENV_TASK_TYPE=" in script
    assert "export APPTAINERENV_TASK_MANIFEST=" in script
    assert "export APPTAINERENV_CUDA_VISIBLE_DEVICES=" in script
    assert "-i '/workspace/inputs/task.json'" in script
    assert "/opt/images/cpu_runner_v1.sif" in script


def test_render_apptainer_omits_nvidia_flag_for_cpu_task(tmp_path):
    job = SlurmJob("task-1", _make_task_type(gpus=False), _make_runner(), _make_entities(), str(tmp_path / "out"))
    script = job._render_wrapper()
    assert "apptainer run --nv" not in script
    assert "APPTAINERENV_CUDA_VISIBLE_DEVICES" not in script
    assert "--containall --cleanenv" in script
    assert "--bind" in script


def test_render_apptainer_isolates_network_unless_declared(tmp_path):
    """--containall does not create a network namespace.  A Task that does not
    declare requires_network must not inherit the worker's host namespace,
    where the Redis broker and the gateway are reachable on loopback."""
    default = SlurmJob("task-1", _make_task_type(), _make_runner(), _make_entities(), str(tmp_path / "out"))
    assert "--net --network none" in default._render_wrapper()

    networked = SlurmJob(
        "task-1",
        _make_task_type(requires_network=True),
        _make_runner(),
        _make_entities(),
        str(tmp_path / "out"),
    )
    script = networked._render_wrapper()
    assert "--net --network none" not in script
    assert "--no-home" in script


def test_render_apptainer_keeps_parameters_in_typed_json_env(tmp_path):
    job = SlurmJob("task-1", _make_task_type(), _make_runner(), _make_entities(), str(tmp_path / "out"))
    script = job._render_wrapper()
    assert "-r 100" not in script
    assert "export APPTAINERENV_TASK_MANIFEST=" in script
    assert "-i '/workspace/inputs/task.json'" in script


def test_render_apptainer_ships_params_via_manifest(tmp_path):
    """APPTAINERENV_* forwarding collapses backslash runs (2, 4, and 8 all
    arrive as 1) — user-shaped data never travels through the environment.
    The wrapper exports only the backslash-free manifest path; params with
    backslashes live in the snapshot's task.json."""
    entities = _make_entities() + [
        {
            "name": "reaction_smiles",
            "type": "param",
            "value": "C=C(" + chr(92) + "C)",
            "verified_value": "C=C(" + chr(92) + "C)",
        }
    ]
    job = SlurmJob("task-1", _make_task_type(), _make_runner(), entities, str(tmp_path / "out"))
    script = job._render_wrapper()
    assert "export APPTAINERENV_TASK_MANIFEST=" in script
    assert "export APPTAINERENV_TASK_PARAMS=" not in script
    assert "export APPTAINERENV_TASK_PARAMS_FILE=" not in script
    assert "-i '/workspace/inputs/task.json'" in script
    # No param content (and no backslashes) anywhere in the wrapper.
    assert "reaction_smiles" not in script
    assert "C=C" not in script


def test_render_apptainer_passes_runtime_subcommand(tmp_path):
    task_type = _make_task_type(runner_args=("workspace_task",))
    job = SlurmJob("task-1", task_type, _make_runner(), _make_entities(), str(tmp_path / "out"))
    script = job._render_wrapper()
    assert "'/opt/images/cpu_runner_v1.sif' 'bash' '/app/run.sh' 'workspace_task' -i" in script


def test_render_apptainer_raises_without_sif_image(tmp_path):
    task_type = _make_task_type()
    task_type = replace(task_type, runtime=replace(task_type.runtime, slurm_image=""))
    job = SlurmJob("task-1", task_type, _make_runner(), _make_entities(), str(tmp_path / "out"))
    with pytest.raises(RuntimeError, match="slurm_image"):
        job._render_wrapper()


def test_render_apptainer_includes_runner_mounts(tmp_path):
    from revocompute.task_types import RunnerMount

    runner = _make_runner(mounts=(RunnerMount(host_path="/data/db", container_path="/opt/db", mode="ro"),))
    job = SlurmJob("task-1", _make_task_type(), runner, _make_entities(), str(tmp_path / "out"))
    script = job._render_wrapper()
    assert "--bind" in script
    assert "/data/db" in script
    assert "/opt/db" in script


def test_task_scratch_is_unique_and_outside_outputs(tmp_path):
    first_entities = _make_entities()
    second_entities = _make_entities()
    second_entities[0] = {
        **second_entities[0],
        "snapshot_path": "/srv/workspaces/tester/task-2/inputs/input.fasta",
        "snapshot_root": "/srv/workspaces/tester/task-2/inputs",
    }
    first = SlurmJob("task-1", _make_task_type(), _make_runner(), first_entities, str(tmp_path / "result-1"))
    second = SlurmJob("task-2", _make_task_type(), _make_runner(), second_entities, str(tmp_path / "result-2"))

    assert first.scratch_dir == "/srv/workspaces/tester/task-1/scratch"
    assert second.scratch_dir == "/srv/workspaces/tester/task-2/scratch"
    assert first.scratch_dir != second.scratch_dir
    assert not first.scratch_dir.startswith(first.output_dir)


def test_wrapper_is_outside_the_container_writable_view(tmp_path):
    """A container process must not be able to rewrite the running wrapper.

    Bash reads a script incrementally from its file offset, so a wrapper inside
    the writable ``output_dir`` bind (``/workspace/outputs``) lets a task append
    a tail that bash then runs on the host as the worker uid, outside Apptainer
    and outside ``--net --network none``.
    """
    workspace = tmp_path / "workspace" / "task-1"
    entities = _make_entities()
    entities[0] = {
        **entities[0],
        "snapshot_path": str(workspace / "inputs" / "input.fasta"),
        "snapshot_root": str(workspace / "inputs"),
    }
    (workspace / "inputs").mkdir(parents=True)
    output_dir = tmp_path / "out"
    job = SlurmJob("task-1", _make_task_type(), _make_runner(), entities, str(output_dir))

    path = Path(job._build_wrapper_script())

    assert path.is_file()
    assert path.stat().st_mode & 0o777 == 0o700
    assert not path.is_relative_to(output_dir)
    assert not path.is_relative_to(Path(job.scratch_path))
    rendered = job._render_wrapper()
    # The only host paths the container can write are outputs (rw), the runner
    # mounts, and /tmp scratch.  None is the wrapper's directory.
    writable_binds = [output_dir, Path(job.scratch_path)] + [
        Path(str(mount["source"])) for mount in job.execution_plan.mounts if mount.get("mode", "ro") == "rw"
    ]
    assert all(not path.is_relative_to(bind) for bind in writable_binds)
    # A same-named file inside the container-writable outputs tree is a
    # different file, so rewriting it cannot reach the host script bash reads.
    output_dir.mkdir(parents=True, exist_ok=True)
    sentinel = output_dir / f"_slurm_wrapper_{job.task_id[:8]}.sh"
    sentinel.write_text("#!/bin/bash\necho rewritten\n", encoding="utf-8")
    assert sentinel.resolve() != path.resolve()
    assert path.read_text(encoding="utf-8") == rendered
    # The container cannot see the allocation directory at all: it appears in no
    # --bind host side.
    assert "--bind" in rendered
    assert _sh_quote(str(path.parent)) not in rendered
    # srun --chdir must still resolve on the compute node.
    assert f"--chdir={output_dir}" in job._build_srun_args()


def test_submit_creates_private_task_scratch(tmp_path):
    workspace = tmp_path / "workspace" / "task-1"
    entities = _make_entities()
    entities[0] = {
        **entities[0],
        "snapshot_path": str(workspace / "inputs" / "input.fasta"),
        "snapshot_root": str(workspace / "inputs"),
    }
    (workspace / "inputs").mkdir(parents=True)
    (workspace / "scratch").mkdir()
    (workspace / "scratch" / "stale.bin").write_bytes(b"stale")
    job = SlurmJob("task-1", _make_task_type(), _make_runner(), entities, str(tmp_path / "out"))
    fake_proc = _FakeSrunProcess(stdout="REVODESIGN_JOB_ID=4217\n", returncode=0)

    with patch("subprocess.Popen", return_value=fake_proc):
        job.submit()

    scratch = workspace / "scratch"
    assert scratch.is_dir()
    assert scratch.stat().st_mode & 0o777 == 0o700
    assert not (scratch / "stale.bin").exists()


@pytest.mark.parametrize("failure", ["wrapper", "output", "resources", "popen"])
def test_submit_setup_failure_cleans_wrapper_and_disk_scratch(tmp_path, monkeypatch, failure):
    workspace = tmp_path / "workspace" / "task-1"
    entities = _make_entities()
    entities[0] = {
        **entities[0],
        "snapshot_path": str(workspace / "inputs" / "input.fasta"),
        "snapshot_root": str(workspace / "inputs"),
    }
    (workspace / "inputs").mkdir(parents=True)
    output = tmp_path / "out"
    job = SlurmJob("task-1", _make_task_type(), _make_runner(), entities, str(output))
    if failure == "wrapper":
        monkeypatch.setattr(job, "_build_wrapper_script", lambda: (_ for _ in ()).throw(RuntimeError("wrapper")))
    elif failure == "output":
        monkeypatch.setattr(os, "makedirs", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("output")))
    elif failure == "resources":
        monkeypatch.setattr(job, "_build_srun_args", lambda: (_ for _ in ()).throw(ValueError("resources")))
    else:
        monkeypatch.setattr(subprocess, "Popen", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("popen")))

    with pytest.raises((OSError, RuntimeError, ValueError)):
        job.submit()

    assert not (workspace / "scratch").exists()
    assert not list((tmp_path / "out.allocation").glob("_slurm_wrapper_*.sh"))
    assert not output.exists() or not list(output.glob("_slurm_wrapper_*.sh"))


def test_poll_cleans_disk_scratch(tmp_path):
    workspace = tmp_path / "workspace" / "task-1"
    entities = _make_entities()
    entities[0] = {
        **entities[0],
        "snapshot_path": str(workspace / "inputs" / "input.fasta"),
        "snapshot_root": str(workspace / "inputs"),
    }
    (workspace / "inputs").mkdir(parents=True)
    output = tmp_path / "out"
    job = SlurmJob("task-1", _make_task_type(), _make_runner(), entities, str(output))
    fake_proc = _FakeSrunProcess(stdout="REVODESIGN_JOB_ID=4217\n", returncode=0)

    with patch("subprocess.Popen", return_value=fake_proc):
        job.submit()
        output.joinpath("result.csv").write_text("score\n1\n")
        assert job.poll() == JobState.COMPLETED

    assert not (workspace / "scratch").exists()


def test_ram_scratch_uses_private_node_local_path_and_wrapper_cleanup(tmp_path):
    job = SlurmJob(
        "task-abcdef1234567890", _make_task_type(), _make_runner(), _make_entities(), str(tmp_path / "out"),
        scratch_backend="ram",
    )
    script = job._render_wrapper()
    assert job.scratch_path.startswith("/dev/shm/revocompute/task-abcdef1234567890-")
    assert f"mkdir -p '{job.scratch_path}'" in script
    assert f"chmod 700 '{job.scratch_path}'" in script
    assert "find /dev/shm/revocompute" in script and "-mmin +1440" in script
    assert 'if running=$(squeue -h -j "$stale_job_id"' in script
    assert 'grep -Fxq "$stale_job_id"' in script
    assert f"{job.scratch_path}/.slurm-job-id" in script
    assert f"rm -rf -- '{job.scratch_path}'" in script
    assert f"--bind '{job.scratch_path}':/tmp" in script
    assert f'trap "rm -rf -- {job.scratch_path}" EXIT' in script


def test_ram_scratch_names_do_not_collide_after_sanitizing(tmp_path):
    first = SlurmJob(
        "task/a", _make_task_type(), _make_runner(), _make_entities(), str(tmp_path / "one"), scratch_backend="ram"
    )
    second = SlurmJob(
        "task?a", _make_task_type(), _make_runner(), _make_entities(), str(tmp_path / "two"), scratch_backend="ram"
    )
    assert first.scratch_path != second.scratch_path


def test_invalid_scratch_backend_rejected(tmp_path):
    with pytest.raises(ValueError, match="scratch_backend"):
        SlurmJob(
            "task-1", _make_task_type(), _make_runner(), _make_entities(), str(tmp_path / "out"), scratch_backend="host"
        )


def test_render_apptainer_includes_runner_env(tmp_path):
    runner = _make_runner(env={"MY_VAR": "my_value"})
    job = SlurmJob("task-1", _make_task_type(), runner, _make_entities(), str(tmp_path / "out"))
    script = job._render_wrapper()
    assert "MY_VAR" in script
    assert "my_value" in script
    assert "export APPTAINERENV_" in script


def test_render_apptainer_quotes_paths_and_environment_values(tmp_path):
    from revocompute.task_types import RunnerMount

    entities = _make_entities()
    entities[0] = {
        **entities[0],
        "snapshot_path": "/srv/workspaces/alice's task/inputs/input file.fasta",
        "snapshot_root": "/srv/workspaces/alice's task/inputs",
        "workspace_key": "alice task",
    }
    task_type = _make_task_type(
        runtime=replace(_make_task_type().runtime, slurm_image="/opt/images/cpu_runner's image.sif")
    )
    runner = _make_runner(
        env={"GREMLIN_DB": "/data/db path/cpu_runner's db"},
        mounts=(
            RunnerMount(
                host_path="/data/db path/cpu_runner's db",
                container_path="/opt/db path/cpu_runner",
                mode="ro",
            ),
        ),
    )
    job = SlurmJob("task-1", task_type, runner, entities, str(tmp_path / "out dir"))
    script = job._render_wrapper()

    assert _sh_quote("/srv/workspaces/alice's task/inputs/input file.fasta") in script
    assert _sh_quote("/srv/workspaces/alice's task/inputs") in script
    assert _sh_quote("/data/db path/cpu_runner's db") in script
    assert _sh_quote("/opt/images/cpu_runner's image.sif") in script
    assert _sh_quote("/workspace/inputs/task.json") in script


# -- submit / poll / cancel (mocked Popen boundary) ---------------------------


def test_submit_invokes_srun_with_resource_args_and_wrapper(tmp_path):
    output_dir = tmp_path / "out with spaces"
    resources = _policy(
        cpus=8,
        memory="32G",
        max_runtime_seconds=90 * 60,
        partition="gpu",
        gres="gpu:a100:1",
        nodes=2,
        ntasks=1,
        qos="normal",
        account="lab",
        constraint="a100&nvme",
        exclusive=True,
        requires_gpu=True,
    )
    job = SlurmJob(
        "abcdef1234567890",
        _make_task_type(gpus=True),
        _make_runner(),
        _make_entities(),
        str(output_dir),
        username="alice@example.com",
        resource_policy=resources,
    )
    fake_proc = _FakeSrunProcess(stdout="REVODESIGN_JOB_ID=4217\n", returncode=0, pid=99)

    with patch("subprocess.Popen", return_value=fake_proc) as mock_popen:
        jid = job.submit()

    # The wrapper lives outside the output tree: ``output_dir`` is bind-mounted
    # writable as /workspace/outputs, and bash would execute a tail a container
    # process rewrote in place, on the host as the worker uid.
    wrapper = Path(job.allocation_dir) / "_slurm_wrapper_abcdef12.sh"
    assert jid == "4217"
    assert not wrapper.is_relative_to(output_dir)
    assert mock_popen.call_args.args[0] == [
        "srun",
        "-u",
        "--partition=gpu",
        "--cpus-per-task=8",
        "--gres=gpu:a100:1",
        "--mem=32G",
        "--time=01:30:00",
        "--nodes=2",
        "--ntasks=1",
        "--qos=normal",
        "--account=lab",
        "--constraint=a100&nvme",
        "--exclusive",
        f"--chdir={output_dir}",
        # Slurm's own per-job file, created at allocation: the only durable trace
        # of a job killed before the wrapper's first statement.  Only stderr is
        # redirected, so the wrapper's stdout protocol stays on its pipe.
        f"--error={Path(job.allocation_dir) / 'allocation-%j.err'}",
        "--job-name=revocomput_alice_example_com_cpu_runner_abcdef12",
        "/bin/bash",
        str(wrapper),
    ]
    assert mock_popen.call_args.kwargs == {"stdout": subprocess.PIPE, "stderr": subprocess.PIPE, "text": True}
    assert wrapper.is_file()
    assert wrapper.stat().st_mode & 0o777 == 0o700
    # ``srun --chdir`` must point at a directory that exists on the compute
    # node; submitting created it.
    assert output_dir.is_dir()


def test_gpu_allocation_release_gates_the_command_behind_the_allocation_report(tmp_path):
    output_dir = tmp_path / "out"
    starts = []
    finishes = []
    job = SlurmJob(
        "abcdef1234567890",
        _make_task_type(gpus=True),
        _make_runner(),
        _make_entities(),
        str(output_dir),
        resource_policy=_policy(gres="gpu:1", requires_gpu=True),
        allocation_started_callback=lambda job_id, at: starts.append((job_id, at)),
        allocation_finished_callback=lambda job_id, at: finishes.append((job_id, at)),
    )
    script = job._render_wrapper()
    fake_proc = _FakeSrunProcess(stdout="REVODESIGN_JOB_ID=4217\n", returncode=1)

    # Two gates: one to let the wrapper observe its allocation, one to let the
    # scientific command run.  The rendered script must contain both, and the
    # observation must consult the scheduler rather than the job identity.
    assert ".allocation-start-abcdef12" in script
    assert ".allocation-approved-abcdef12" in script
    assert "squeue" in script
    with patch("subprocess.Popen", return_value=fake_proc):
        assert job.submit() == "4217"
        # Submitting names the request and releases the observation gate only.
        # It does not start the allocation, and it does not grant the command.
        assert starts == []
        assert (output_dir / ".allocation-start-abcdef12").is_file()
        assert not (output_dir / ".allocation-approved-abcdef12").exists()
        assert job.poll() == JobState.FAILED

    # The wrapper ran on a compute node and wrote its resource envelope, so the
    # allocation is settled and the run released exactly once.
    assert starts[0][0] == "4217"
    assert finishes[0][0] == "4217"
    assert len(finishes) == 1
    assert not (output_dir / ".allocation-approved-abcdef12").exists()


def test_wrapper_observation_survives_a_crash_before_the_grant(tmp_path):
    """The wrapper's own stdout id line is persisted the moment it is read.

    This is the crash window the restart path has to survive: the wrapper is
    executing on a compute node, then it dies (or its process does) before any
    admission decision.  The dispatch callback is the durable-writer seam, so it
    must already have been called with ``wrapper_executed=True`` by the time the
    identity is known — not deferred to ``submit()``.
    """
    output_dir = tmp_path / "out"
    dispatches = []
    job = SlurmJob(
        "abcdef1234567890",
        _make_task_type(gpus=True),
        _make_runner(),
        _make_entities(),
        str(output_dir),
        resource_policy=_policy(gres="gpu:1", requires_gpu=True),
        allocation_dispatched_callback=lambda job_id, at, executed=False, receipt=None: dispatches.append(
            (job_id, executed)
        ),
        allocation_started_callback=lambda _job_id, _at: None,
    )
    stdout = StringIO("REVODESIGN_JOB_ID=4217\n")
    job._process = SimpleNamespace(stdout=stdout, stderr=StringIO(""))
    job._allocation_submitted_at = 1_000.0

    job._read_stdout()

    assert job.wrapper_executed is True
    assert dispatches == [("4217", True)]


def test_the_wrapper_receipt_precedes_its_stdout_line_and_parses(tmp_path):
    """The compute node's receipt is durable before anything else is emitted.

    Strict ordering is the point: recovery keys on the receipt, so it must exist
    before the stdout line that tells the worker anything, and it must be written
    into the host-only directory the container cannot reach.
    """
    output_dir = tmp_path / "out"
    job = SlurmJob(
        "abcdef1234567890",
        _make_task_type(gpus=True),
        _make_runner(),
        _make_entities(),
        str(output_dir),
        resource_policy=_policy(gres="gpu:1", requires_gpu=True),
    )
    script = job._render_wrapper()
    receipt_write = script.index("allocation.receipt")
    stdout_line = script.index(f'echo "{JOB_ID_PREFIX}')
    assert receipt_write < stdout_line
    # Atomic publication and a durable flush, so a kill cannot leave a partial
    # receipt that reads as a valid one.
    assert "sync " in script
    assert "mv -f -- " in script
    assert subprocess.run(["bash", "-n"], input=script, text=True, check=False).returncode == 0

    # The receipt lives beside the wrapper script, never inside the directory
    # that is bind-mounted read-write into the task's container.
    assert job.allocation_receipt_path.startswith(job.allocation_dir)
    assert not job.allocation_receipt_path.startswith(str(output_dir) + os.sep)

    # And it round-trips through the reader without being consumed: the file is
    # the only durable evidence a worker that dies before its own first write
    # leaves, so it survives until something durable has adopted the claim.
    os.makedirs(job.allocation_dir, exist_ok=True)
    Path(job.allocation_receipt_path).write_text(
        "schema_version=1\nslurm_job_id=4217\nobserved_at=1000\ncpus=2\ngpus=1\n", encoding="utf-8"
    )
    assert job.read_allocation_receipt() == {
        "slurm_job_id": "4217",
        "observed_at": 1000.0,
        "cpus": 2,
        "gpus": 1,
    }
    assert Path(job.allocation_receipt_path).exists()
    assert job.read_allocation_receipt() == {
        "slurm_job_id": "4217",
        "observed_at": 1000.0,
        "cpus": 2,
        "gpus": 1,
    }
    # Removal is a separate, explicit step that only callers with a durable
    # successor may take.  It is idempotent.
    job.discard_allocation_receipt()
    assert not Path(job.allocation_receipt_path).exists()
    job.discard_allocation_receipt()
    assert job.read_allocation_receipt() is None


def test_an_untrusted_receipt_is_treated_as_absent(tmp_path):
    """A receipt that is not exactly what the wrapper writes is not read.

    The reader is the boundary between a file on disk and a durable fact, so a
    truncated, mismatched, or unknown-schema receipt returns nothing rather than
    being coerced into a plausible allocation.  It is also never deleted: an
    anomalous durable observation stays inspectable instead of silently
    disappearing.
    """
    output_dir = tmp_path / "out"
    job = SlurmJob(
        "abcdef1234567890",
        _make_task_type(gpus=True),
        _make_runner(),
        _make_entities(),
        str(output_dir),
        resource_policy=_policy(gres="gpu:1", requires_gpu=True),
    )
    os.makedirs(job.allocation_dir, exist_ok=True)
    for payload in (
        "slurm_job_id=4217\nobserved_at=1000\n",  # no schema
        "schema_version=2\nslurm_job_id=4217\nobserved_at=1000\n",  # unknown schema
        "schema_version=1\nslurm_job_id=not-a-job\nobserved_at=1000\n",  # not an id
        "schema_version=1\nslurm_job_id=4217\nobserved_at=soon\n",  # unparsable stamp
        "schema_version=1\nslurm_job_id=4217\n",  # no stamp at all
    ):
        Path(job.allocation_receipt_path).write_text(payload, encoding="utf-8")
        assert job.read_allocation_receipt() is None
        assert Path(job.allocation_receipt_path).read_text(encoding="utf-8") == payload


def test_a_failed_observation_persist_is_never_swallowed(tmp_path):
    """A store failure on the wrapper's own id line must stop the run.

    The one durable transition that records "the wrapper executed" is the
    dispatch callback.  If it raises — a busy/locked database, a full disk — the
    reader must not swallow it: the wrapper is still ahead of its gate, so
    failing closed here is what keeps an allocation from running with no record.
    """
    output_dir = tmp_path / "out"
    attempts = []

    def failing(job_id, at, executed=False, receipt=None):
        attempts.append((job_id, executed))
        raise RuntimeError("database is locked")

    job = SlurmJob(
        "abcdef1234567890",
        _make_task_type(gpus=True),
        _make_runner(),
        _make_entities(),
        str(output_dir),
        resource_policy=_policy(gres="gpu:1", requires_gpu=True),
        allocation_dispatched_callback=failing,
        allocation_started_callback=lambda _job_id, _at: None,
    )
    job._process = SimpleNamespace(stdout=StringIO("REVODESIGN_JOB_ID=4217\n"), stderr=StringIO(""))
    job._allocation_submitted_at = 1_000.0

    with pytest.raises(RuntimeError, match="database is locked"):
        job._read_stdout()

    assert attempts == [("4217", True)]
    # The flag was cleared, so a later observation retries rather than treating
    # the request as dispatched with nothing written.
    assert job._dispatched_notified is False
    # The process-local fact alone never stands in for a durable one.
    assert job.wrapper_executed is True
    assert job.allocation_started is False


def _receipt_job(tmp_path, callback, *, task_id="abcdef1234567890"):
    output_dir = tmp_path / "out"
    job = SlurmJob(
        task_id,
        _make_task_type(gpus=True),
        _make_runner(),
        _make_entities(),
        str(output_dir),
        resource_policy=_policy(gres="gpu:1", requires_gpu=True),
        allocation_dispatched_callback=callback,
        allocation_started_callback=lambda _job_id, _at: None,
    )
    os.makedirs(job.allocation_dir, exist_ok=True)
    Path(job.allocation_receipt_path).write_text(
        "schema_version=1\nslurm_job_id=4217\nobserved_at=1000\ncpus=2\ngpus=1\n", encoding="utf-8"
    )
    job._process = SimpleNamespace(stdout=StringIO("REVODESIGN_JOB_ID=4217\n"), stderr=StringIO(""))
    job._allocation_submitted_at = 1_000.0
    return job


def test_a_death_before_the_durable_write_keeps_the_receipt(tmp_path):
    """Injection 1: killed after the file was read and before the DB commit.

    The whole point of the file is this instant.  If the callback never commits,
    the file has no durable successor and therefore must still be there — that is
    the difference between "reconciliation can still recover the allocation" and
    "a real allocation silently became zero".
    """
    attempts = []

    def failing(job_id, at, executed=False, receipt=None):
        attempts.append((job_id, executed, receipt))
        raise RuntimeError("database is locked")

    job = _receipt_job(tmp_path, failing)

    with pytest.raises(RuntimeError, match="database is locked"):
        job._read_stdout()

    assert attempts == [("4217", True, {"slurm_job_id": "4217", "observed_at": 1000.0, "cpus": 2, "gpus": 1})]
    assert job._dispatched_notified is False
    # The source receipt survives, so restart reconciliation can still adopt it.
    assert Path(job.allocation_receipt_path).read_text(encoding="utf-8").startswith("schema_version=1")
    assert job.read_allocation_receipt() is not None


def test_a_death_after_the_durable_write_removes_the_receipt(tmp_path):
    """Injection 2 and 3: the callback committed; the file is finally disposable.

    The runner removes the file only after the callback returns, so a kill
    anywhere inside the callback leaves it, and a successful callback leaves the
    claim in server-owned state with the file cleaned up.  There is never a
    moment with neither.
    """
    adopted = []

    def committing(job_id, at, executed=False, receipt=None):
        adopted.append((job_id, executed, receipt))

    job = _receipt_job(tmp_path, committing)
    job._read_stdout()

    assert adopted == [("4217", True, {"slurm_job_id": "4217", "observed_at": 1000.0, "cpus": 2, "gpus": 1})]
    assert job._dispatched_notified is True
    # The durable successor exists, so the source file is gone; a second read
    # finds nothing rather than reintroducing the claim.
    assert not Path(job.allocation_receipt_path).exists()
    assert job.read_allocation_receipt() is None


def test_poll_fails_closed_when_the_observation_was_never_persisted(tmp_path):
    """A wrapper that ran without a recorded fact fails rather than continues.

    When the process survives to ``poll()`` after a persist failure, the job must
    not settle as though the allocation had been observed.  There is no grant and
    no allocation fact, so running the scientific command would be an
    unaccounted allocation.
    """
    output_dir = tmp_path / "out"
    dispatches = []
    starts = []
    job = SlurmJob(
        "abcdef1234567890",
        _make_task_type(gpus=True),
        _make_runner(),
        _make_entities(),
        str(output_dir),
        resource_policy=_policy(gres="gpu:1", requires_gpu=True),
        allocation_dispatched_callback=lambda job_id, at, executed=False, receipt=None: dispatches.append(
            (job_id, executed)
        ),
        allocation_started_callback=lambda job_id, at: starts.append((job_id, at)),
    )
    job._process = _FakeSrunProcess(
        stdout="REVODESIGN_JOB_ID=4217\n", returncode=0
    )
    job._allocation_submitted_at = 1_000.0
    # The store rejected the observation and the reader path gave up.
    job._wrapper_started = True
    job._dispatch_error = "database is locked"

    assert job.poll() == JobState.FAILED
    # The allocation was never started, so the wrapper was never granted.
    assert starts == []
    assert not (output_dir / ".allocation-approved-abcdef12").exists()


def test_wrapper_observation_is_recorded_when_stderr_won_the_identity_race(tmp_path):
    """The stderr banner may supply the identity first; the wrapper still ran.

    A queued banner is not execution evidence, so the stdout id line must set the
    execution flag (and persist it) even when ``_slurm_job_id`` was already set
    from stderr — otherwise a host with no ``squeue`` would account nothing for an
    allocation that really ran.
    """
    output_dir = tmp_path / "out"
    dispatches = []
    job = SlurmJob(
        "abcdef1234567890",
        _make_task_type(gpus=True),
        _make_runner(),
        _make_entities(),
        str(output_dir),
        resource_policy=_policy(gres="gpu:1", requires_gpu=True),
        allocation_dispatched_callback=lambda job_id, at, executed=False, receipt=None: dispatches.append(
            (job_id, executed)
        ),
        allocation_started_callback=lambda _job_id, _at: None,
    )
    job._slurm_job_id, job._job_id_event = "4217", __import__("threading").Event()
    job._allocation_submitted_at = 1_000.0
    job._process = SimpleNamespace(stdout=StringIO("REVODESIGN_JOB_ID=4217\n"), stderr=StringIO(""))

    job._read_stdout()

    assert job.wrapper_executed is True
    assert dispatches == [("4217", True)]


def test_allocation_live_starts_accounting_and_releases_the_wrapper_once(tmp_path):
    output_dir = tmp_path / "out"
    starts = []
    finishes = []
    job = SlurmJob(
        "abcdef1234567890",
        _make_task_type(gpus=True),
        _make_runner(),
        _make_entities(),
        str(output_dir),
        resource_policy=_policy(gres="gpu:1", requires_gpu=True),
        allocation_started_callback=lambda job_id, at: starts.append((job_id, at)),
        allocation_finished_callback=lambda job_id, at: finishes.append((job_id, at)),
    )
    fake_proc = _FakeSrunProcess(
        stdout="REVODESIGN_JOB_ID=4217\nREVODESIGN_ALLOCATION_LIVE=4217\n",
        returncode=1,
    )

    with patch("subprocess.Popen", return_value=fake_proc):
        assert job.submit() == "4217"
        # The live line is the admission moment: the allocation is recorded and
        # the scientific command released as one decision, and it is recorded
        # once even though both the line and poll()'s exit could report it.
        assert job.poll() == JobState.FAILED

    assert [job_id for job_id, _at in starts] == ["4217"]
    assert [job_id for job_id, _at in finishes] == ["4217"]
    # The grant was written while the wrapper could still consume it, and the
    # wrapper's own run removed it before poll() cleaned up.
    assert not (output_dir / ".allocation-approved-abcdef12").exists()


def test_repeated_allocation_live_lines_start_accounting_exactly_once(tmp_path):
    starts = []
    job = SlurmJob(
        "task-1",
        _make_task_type(gpus=True),
        _make_runner(),
        _make_entities(),
        str(tmp_path / "out"),
        resource_policy=_policy(gres="gpu:1", requires_gpu=True),
        allocation_started_callback=lambda job_id, at: starts.append((job_id, at)),
    )
    stdout = StringIO(
        "REVODESIGN_JOB_ID=4154\n"
        "REVODESIGN_ALLOCATION_LIVE=4154\n"
        "REVODESIGN_ALLOCATION_LIVE=4154\n"
    )
    job._process = SimpleNamespace(stdout=stdout)

    job._read_stdout()

    assert [job_id for job_id, _at in starts] == ["4154"]


def test_a_queued_stderr_banner_never_claims_an_allocation(tmp_path):
    """A queued srun banner names the request; it is not an allocation.

    The stderr line ``srun: job N queued and waiting for resources`` is
    sufficient evidence of job identity, and that is all it may be treated as:
    no allocation is accounted and the wrapper is not released to run until the
    allocation is observed RUNNING.
    """
    output_dir = tmp_path / "out"
    starts = []
    dispatches = []
    job = SlurmJob(
        "task-1",
        _make_task_type(gpus=True),
        _make_runner(),
        _make_entities(),
        str(output_dir),
        resource_policy=_policy(gres="gpu:1", requires_gpu=True),
        allocation_dispatched_callback=lambda job_id, at, executed=False, receipt=None: dispatches.append(
            (job_id, at, executed)
        ),
        allocation_started_callback=lambda job_id, at: starts.append((job_id, at)),
    )
    fake_proc = _FakeSrunProcess(
        stderr="srun: job 4217 queued and waiting for resources\n", returncode=-15
    )

    with patch("subprocess.Popen", return_value=fake_proc):
        assert job.submit() == "4217"
        assert job.poll() == JobState.FAILED

    # Identity was announced as a dispatch and never as an allocation, and the
    # queued banner is not evidence the wrapper itself executed.
    assert [job_id for job_id, _at, _executed in dispatches] == ["4217"]
    assert [executed for _job_id, _at, executed in dispatches] == [False]
    assert starts == []
    assert job.allocation_started is False


def test_gpu_allocation_cancel_before_allocation_settles_nothing(tmp_path):
    output_dir = tmp_path / "out"
    finishes = []
    job = SlurmJob(
        "abcdef1234567890",
        _make_task_type(gpus=True),
        _make_runner(),
        _make_entities(),
        str(output_dir),
        resource_policy=_policy(gres="gpu:1", requires_gpu=True),
        allocation_started_callback=lambda _job_id, _at: None,
        allocation_finished_callback=lambda job_id, at: finishes.append((job_id, at)),
    )
    fake_proc = _FakeSrunProcess(stdout="REVODESIGN_JOB_ID=4217\n", returncode=None)

    with patch("subprocess.Popen", return_value=fake_proc):
        assert job.submit() == "4217"
        job.cancel()
        job.cancel()

    assert fake_proc.terminated is True
    # The cancellation itself settles nothing: the wrapper was never granted, so
    # no allocation accounting happened in this process.  The fact that the
    # wrapper ran stays durable for reconciliation to settle from evidence.
    assert finishes == []
    assert job.allocation_started is False


def test_gpu_allocation_cancel_after_allocation_reports_finish_once(tmp_path):
    output_dir = tmp_path / "out"
    finishes = []
    job = SlurmJob(
        "abcdef1234567890",
        _make_task_type(gpus=True),
        _make_runner(),
        _make_entities(),
        str(output_dir),
        resource_policy=_policy(gres="gpu:1", requires_gpu=True),
        allocation_started_callback=lambda _job_id, _at: None,
        allocation_finished_callback=lambda job_id, at: finishes.append((job_id, at)),
    )
    fake_proc = _FakeSrunProcess(
        stdout="REVODESIGN_JOB_ID=4217\nREVODESIGN_ALLOCATION_LIVE=4217\n", returncode=None
    )

    with patch("subprocess.Popen", return_value=fake_proc):
        # Drive the live line through the reader so the allocation is observed
        # before the cancellation.
        with patch.object(job, "_stdout_thread", None), patch.object(job, "_stderr_thread", None):
            assert job.submit() == "4217"
        job.cancel()
        job.cancel()

    assert fake_proc.terminated is True
    assert [job_id for job_id, _at in finishes] == ["4217"]


def test_gpu_allocation_denial_terminates_srun_and_fails_the_job(tmp_path):
    output_dir = tmp_path / "out"
    finishes = []

    def deny(_job_id, _started_at):
        raise RuntimeError("credit exhausted")

    job = SlurmJob(
        "abcdef1234567890",
        _make_task_type(gpus=True),
        _make_runner(),
        _make_entities(),
        str(output_dir),
        resource_policy=_policy(gres="gpu:1", requires_gpu=True),
        allocation_started_callback=deny,
        allocation_finished_callback=lambda job_id, at: finishes.append((job_id, at)),
    )
    fake_proc = _FakeSrunProcess(
        stdout="REVODESIGN_JOB_ID=4217\nREVODESIGN_ALLOCATION_LIVE=4217\n", returncode=1
    )

    with patch("subprocess.Popen", return_value=fake_proc):
        assert job.submit() == "4217"
        with pytest.raises(RuntimeError, match="credit exhausted"):
            job.poll()

    # A refused allocation is still an allocation: the fact the store was asked
    # to record exists (that is what the callback attempted before denying), so
    # it settles for the gate/termination interval.  The refusal is the grant,
    # not the fact.
    assert [job_id for job_id, _at in finishes] == ["4217"]
    assert job.allocation_started is False
    assert not (output_dir / ".allocation-approved-abcdef12").exists()


def test_submit_parses_job_id_from_srun_stderr_banner(tmp_path):
    job = SlurmJob("task-1", _make_task_type(), _make_runner(), _make_entities(), str(tmp_path / "out"))
    fake_proc = _FakeSrunProcess(stderr="srun: job 4217 queued and waiting for resources\n", returncode=0)

    with patch("subprocess.Popen", return_value=fake_proc):
        assert job.submit() == "4217"
    assert job.job_id == "4217"


def test_stderr_eof_cannot_fail_submit_before_stdout_identity_is_released(tmp_path):
    """One exhausted reader must leave the other reader authoritative."""
    stdout_ready = threading.Event()
    stdout_release = threading.Event()
    stderr_eof = threading.Event()
    job = SlurmJob("task-1", _make_task_type(), _make_runner(), _make_entities(), str(tmp_path / "out"))
    fake_proc = _FakeSrunProcess(returncode=None)
    fake_proc.stdout = _BarrierLineStream("REVODESIGN_JOB_ID=4217\n", stdout_ready, stdout_release)
    fake_proc.stderr = _EofSignalStream(stderr_eof)
    result: list[str] = []

    with patch("subprocess.Popen", return_value=fake_proc):
        submitter = threading.Thread(
            target=lambda: result.append(job.submit()),
            daemon=True,
        )
        submitter.start()
        assert stdout_ready.wait(timeout=1)
        assert stderr_eof.wait(timeout=1)
        assert submitter.is_alive()
        stdout_release.set()
        submitter.join(timeout=2)

    assert not submitter.is_alive()
    assert result == ["4217"]


def test_submit_rejects_unparseable_scheduler_id_and_terminates_srun(tmp_path):
    output_dir = tmp_path / "out"
    job = SlurmJob("task-1", _make_task_type(), _make_runner(), _make_entities(), str(output_dir))
    fake_proc = _FakeSrunProcess(
        stdout="tool started before SLURM_JOB_ID was exported\n", stderr="unexpected\n", returncode=None
    )

    with patch("subprocess.Popen", return_value=fake_proc):
        with pytest.raises(RuntimeError, match="did not return a scheduler job ID"):
            job.submit()
    assert job.job_id is None
    assert fake_proc.terminated is True
    assert not list(Path(job.allocation_dir).glob("_slurm_wrapper_*.sh"))


def test_submit_propagates_srun_launch_failure_and_removes_wrapper(tmp_path):
    output_dir = tmp_path / "out"
    job = SlurmJob("task-1", _make_task_type(), _make_runner(), _make_entities(), str(output_dir))

    with patch("subprocess.Popen", side_effect=FileNotFoundError("srun not found")):
        with pytest.raises(FileNotFoundError, match="srun not found"):
            job.submit()

    assert not list(Path(job.allocation_dir).glob("_slurm_wrapper_*.sh"))


def test_allocation_live_emits_first_stage_as_liveness_signal(tmp_path):
    stages_seen = []
    job = SlurmJob(
        "task-1",
        _make_task_type(),
        _make_runner(),
        _make_entities(),
        str(tmp_path / "out"),
        stage_callback=stages_seen.append,
    )
    stdout = StringIO(
        "REVODESIGN_JOB_ID=4154\n"
        "REVODESIGN_ALLOCATION_LIVE=4154\n"
        "REVODESIGN_STAGE:cpu_runner\n"
    )
    job._process = SimpleNamespace(stdout=stdout)

    job._read_stdout()

    assert job._slurm_job_id == "4154"
    assert job._job_id_event.is_set()
    # The first declared stage is the allocation's own liveness signal, emitted
    # when it starts running — never on the bare job identity.
    assert stages_seen == ["hhblits", "cpu_runner"]
    assert stdout.closed


def test_job_identity_alone_emits_no_stage(tmp_path):
    stages_seen = []
    job = SlurmJob(
        "task-1",
        _make_task_type(),
        _make_runner(),
        _make_entities(),
        str(tmp_path / "out"),
        stage_callback=stages_seen.append,
    )
    stdout = StringIO("REVODESIGN_JOB_ID=4154\n")
    job._process = SimpleNamespace(stdout=stdout)

    job._read_stdout()

    assert job._slurm_job_id == "4154"
    assert job._allocation_live is False
    assert stages_seen == []


def test_submit_poll_lifecycle_maps_exit_zero_with_result_to_completed(tmp_path):
    job = SlurmJob("task-1", _make_task_type(), _make_runner(), _make_entities(), str(tmp_path / "out"))
    fake_proc = _FakeSrunProcess(stdout="REVODESIGN_JOB_ID=4217\nREVODESIGN_STAGE:cpu_runner\n", returncode=0)

    with patch("subprocess.Popen", return_value=fake_proc):
        assert job.submit() == "4217"
        (tmp_path / "out" / "result.csv").write_text("score\n1.0\n")
        state = job.poll()
        assert state == JobState.COMPLETED
    assert not Path(job.allocation_dir).exists()


def test_submit_poll_emits_correlated_allocation_lifecycle(tmp_path, monkeypatch):
    from revocompute.job.runners import slurm_runner

    events = []
    monkeypatch.setattr(slurm_runner, "emit_event", lambda event, **fields: events.append((event, fields)))
    job = SlurmJob("task-1", _make_task_type(), _make_runner(), _make_entities(), str(tmp_path / "out"))
    fake_proc = _FakeSrunProcess(stdout="REVODESIGN_JOB_ID=4217\n", returncode=0)

    with patch("subprocess.Popen", return_value=fake_proc):
        assert job.submit() == "4217"
        (tmp_path / "out" / "result.csv").write_text("score\n1.0\n")
        assert job.poll() == JobState.COMPLETED

    assert [event for event, _fields in events] == [
        "slurm.allocation.requested",
        "slurm.allocation.granted",
        "slurm.allocation.finished",
    ]
    assert {fields["task_id"] for _event, fields in events} == {"task-1"}
    assert events[1][1]["slurm_job_id"] == events[2][1]["slurm_job_id"] == "4217"


def test_poll_returns_failed_on_exit_zero_without_result_artifact(tmp_path):
    job = SlurmJob("task-1", _make_task_type(), _make_runner(), _make_entities(), str(tmp_path / "out"))
    fake_proc = _FakeSrunProcess(stdout="REVODESIGN_JOB_ID=4217\n", returncode=0)

    with patch("subprocess.Popen", return_value=fake_proc):
        job.submit()
        (tmp_path / "out" / "task_finished").touch()
        state = job.poll()
        assert state == JobState.FAILED


def test_poll_maps_nonzero_srun_exit_to_failed_and_saves_scheduler_logs(tmp_path):
    job = SlurmJob("task-1", _make_task_type(), _make_runner(), _make_entities(), str(tmp_path / "out"), username="bob")
    fake_proc = _FakeSrunProcess(
        stdout="REVODESIGN_JOB_ID=4217\n",
        stderr="slurmstepd: error: task exited with exit code 1\n",
        returncode=1,
    )

    with patch("subprocess.Popen", return_value=fake_proc):
        job.submit()
        assert job.poll() == JobState.FAILED

    stderr = tmp_path / "out" / "execution" / "slurm-bob-cpu_runner-task-1.stderr.log"
    assert stderr.read_text() == "slurmstepd: error: task exited with exit code 1\n"


def test_poll_timeout_kills_srun_and_returns_failed(tmp_path):
    job = SlurmJob(
        "task-1",
        _make_task_type(),
        _make_runner(max_runtime_seconds=1),
        _make_entities(),
        str(tmp_path / "out"),
    )
    fake_proc = _FakeSrunProcess(stdout="REVODESIGN_JOB_ID=4217\n", returncode=None, timeout_once=True)

    with patch("subprocess.Popen", return_value=fake_proc):
        job.submit()
        assert job.poll() == JobState.FAILED

    assert fake_proc.killed is True
    assert fake_proc.wait_calls == 2


def test_slurm_output_is_named_previewable_execution_diagnostics(tmp_path):
    job = SlurmJob(
        "task-1",
        _make_task_type(),
        _make_runner(),
        _make_entities(),
        str(tmp_path / "out"),
        username="alice",
    )
    job._job_id = "srun-32"
    job._stdout_lines = ["REVODESIGN_STAGE:structure_runner\n"]
    job._stderr_lines = ["warning\n"]

    job._save_output()

    stdout = tmp_path / "out" / "execution" / "slurm-alice-cpu_runner-task-1.stdout.log"
    stderr = tmp_path / "out" / "execution" / "slurm-alice-cpu_runner-task-1.stderr.log"
    assert stdout.read_text() == "REVODESIGN_STAGE:structure_runner\n"
    assert stderr.read_text() == "warning\n"
    assert job._is_execution_log(str(stdout))


def test_slurm_resource_observation_is_bounded_diagnostic_not_scientific_output(tmp_path):
    workspace = tmp_path / "workspace" / "task-1"
    entities = _make_entities()
    entities[0] = {
        **entities[0],
        "snapshot_path": str(workspace / "inputs" / "input.fasta"),
        "snapshot_root": str(workspace / "inputs"),
    }
    (workspace / "inputs").mkdir(parents=True)
    job = SlurmJob(
        "task-1",
        _make_task_type(),
        _make_runner(),
        entities,
        str(tmp_path / "out"),
        username="alice",
    )
    resource_capture = Path(job._resource_capture_path)
    resource_capture.parent.mkdir()
    resource_capture.write_text(
        "schema_version=1\n"
        "source=allocation_wrapper\n"
        "job_id=42\n"
        "allocated_cpus_per_task=4\n"
        "allocated_tasks=1\n"
        "allocated_gpus_on_node=\n"
        "allocated_gpu_ids=\n"
        "visible_gpu_devices=\n"
        "exit_code=0\n"
        "elapsed_seconds=1.25\n"
        "user_cpu_seconds=0.75\n"
        "system_cpu_seconds=0.10\n"
        "max_rss_kib=2048\n",
        encoding="utf-8",
    )

    job._save_output()

    resource = tmp_path / "out" / "execution" / "slurm-alice-cpu_runner-task-1.resource.json"
    payload = json.loads(resource.read_text(encoding="utf-8"))
    assert payload["job_id"] == "42"
    assert payload["max_rss_kib"] == 2048
    assert job._is_execution_log(str(resource))
    assert job._has_result_artifact() is False


def test_slurm_resource_observation_uses_final_stdout_envelope_without_leaking_it(tmp_path):
    job = SlurmJob(
        "task-1",
        _make_task_type(),
        _make_runner(),
        _make_entities(),
        str(tmp_path / "out"),
        username="alice",
    )
    job._stdout_lines = [
        "REVODESIGN_JOB_ID=42\n",
        "REVODESIGN_RESOURCE_BEGIN\n",
        "REVODESIGN_RESOURCE:schema_version=1\n",
        "REVODESIGN_RESOURCE:source=allocation_wrapper\n",
        "REVODESIGN_RESOURCE:job_id=42\n",
        "REVODESIGN_RESOURCE:allocated_cpus_per_task=2\n",
        "REVODESIGN_RESOURCE:allocated_tasks=1\n",
        "REVODESIGN_RESOURCE:exit_code=0\n",
        "REVODESIGN_RESOURCE:elapsed_seconds=1.25\n",
        "REVODESIGN_RESOURCE:user_cpu_seconds=0.75\n",
        "REVODESIGN_RESOURCE:system_cpu_seconds=0.10\n",
        "REVODESIGN_RESOURCE:max_rss_kib=2048\n",
        "REVODESIGN_RESOURCE_END\n",
    ]

    job._save_output()

    resource = tmp_path / "out" / "execution" / "slurm-alice-cpu_runner-task-1.resource.json"
    stdout = tmp_path / "out" / "execution" / "slurm-alice-cpu_runner-task-1.stdout.log"
    assert json.loads(resource.read_text(encoding="utf-8"))["elapsed_seconds"] == 1.25
    assert stdout.read_text(encoding="utf-8") == "REVODESIGN_JOB_ID=42\n"


def test_slurm_resource_observation_preserves_bounded_gpu_metrics(tmp_path):
    job = SlurmJob(
        "task-1",
        _make_task_type(gpus=True),
        _make_runner(),
        _make_entities(),
        str(tmp_path / "out"),
        username="alice",
    )
    job._stdout_lines = [
        "REVODESIGN_RESOURCE_BEGIN\n",
        "REVODESIGN_RESOURCE:schema_version=1\n",
        "REVODESIGN_RESOURCE:source=allocation_wrapper\n",
        "REVODESIGN_RESOURCE:job_id=42\n",
        "REVODESIGN_RESOURCE:allocated_cpus_per_task=1\n",
        "REVODESIGN_RESOURCE:allocated_tasks=1\n",
        "REVODESIGN_RESOURCE:allocated_gpus_on_node=1\n",
        "REVODESIGN_RESOURCE:visible_gpu_devices=0\n",
        "REVODESIGN_RESOURCE:exit_code=0\n",
        "REVODESIGN_RESOURCE:elapsed_seconds=2.0\n",
        "REVODESIGN_RESOURCE:user_cpu_seconds=1.0\n",
        "REVODESIGN_RESOURCE:system_cpu_seconds=0.1\n",
        "REVODESIGN_RESOURCE:max_rss_kib=2048\n",
        "REVODESIGN_RESOURCE:gpu_memory_peak_mib=1024\n",
        "REVODESIGN_RESOURCE:gpu_utilization_peak_percent=75\n",
        "REVODESIGN_RESOURCE_END\n",
    ]

    job._save_output()

    resource = tmp_path / "out" / "execution" / "slurm-alice-cpu_runner-task-1.resource.json"
    payload = json.loads(resource.read_text(encoding="utf-8"))
    assert payload["gpu_memory_peak_mib"] == 1024
    assert payload["gpu_utilization_peak_percent"] == 75


def test_cancel_terminates_process(tmp_path):
    job = SlurmJob("task-1", _make_task_type(), _make_runner(), _make_entities(), str(tmp_path / "out"))
    fake_proc = _FakeSrunProcess(returncode=None, pid=99999)
    job._process = fake_proc
    job._job_id = "4217"

    job.cancel()

    assert fake_proc.terminated is True
    assert fake_proc.killed is False
    assert fake_proc.poll() == -15


def test_cancel_cleans_disk_scratch(tmp_path):
    workspace = tmp_path / "workspace" / "task-1"
    entities = _make_entities()
    entities[0] = {
        **entities[0],
        "snapshot_path": str(workspace / "inputs" / "input.fasta"),
        "snapshot_root": str(workspace / "inputs"),
    }
    (workspace / "inputs").mkdir(parents=True)
    job = SlurmJob("task-1", _make_task_type(), _make_runner(), entities, str(tmp_path / "out"))
    job._prepare_scratch_dir()
    job._process = _FakeSrunProcess(returncode=None)

    job.cancel()

    assert not (workspace / "scratch").exists()


def test_cancel_before_submit_is_noop(tmp_path):
    job = SlurmJob("task-1", _make_task_type(), _make_runner(), _make_entities(), str(tmp_path / "out"))
    job.cancel()  # should not raise


def test_fileless_job_uses_explicit_task_workspace(tmp_path):
    workspace = tmp_path / "workspace" / "task-1"
    workspace.mkdir(parents=True)
    job = SlurmJob(
        "task-1",
        _make_task_type(),
        _make_runner(),
        [{"type": "workspace", "workspace_root": str(workspace), "workspace_key": "user-key"}],
        str(tmp_path / "out"),
    )

    assert job.input_snapshot_root == str(workspace / "inputs")
    assert job.task_workspace_root == str(workspace)
    assert job.workspace_key == "user-key"
    assert f"--bind '{workspace / 'inputs'}':'/workspace/inputs':ro" in job._render_wrapper()


# -- shell quoting ------------------------------------------------------------


def test_sh_quote_plain():
    assert _sh_quote("hello") == "'hello'"


def test_sh_quote_with_single_quote():
    assert _sh_quote("it's") == "'it'\"'\"'s'"


def test_sh_quote_with_spaces():
    assert _sh_quote("a b") == "'a b'"


# -- name sanitization --------------------------------------------------------


def test_sanitize_name_alphanumeric():
    assert _sanitize_name("testuser") == "testuser"


def test_sanitize_name_with_special_chars():
    assert _sanitize_name("user@domain") == "user_domain"


def test_sanitize_name_empty():
    assert _sanitize_name("") == "unknown"


def test_finish_callback_failure_never_escapes_poll():
    """Accounting failure must not rewrite an already-finished scientific job."""
    job = SlurmJob.__new__(SlurmJob)
    job._allocation_finished_notified = False
    job._allocation_tracking_started = True
    job._slurm_job_id = "42"
    job._allocation_finished_callback = lambda *_args: (_ for _ in ()).throw(
        RuntimeError("accounting database is locked")
    )

    # No exception escapes: poll() keeps the real Runner exit state.
    job._notify_allocation_finished()

    assert job._allocation_finished_notified is True


# -- runner-protocol ingest ---------------------------------------------------


class _RecordingTaskStore:
    """Minimal task store: what the job persists from captured runner stdout."""

    def __init__(self) -> None:
        self.progress: list[tuple[str, dict | None, str | None]] = []
        self.observations: list[dict] = []

    def record_task_progress(self, task_id, *, progress=None, outcome=None):
        self.progress.append((task_id, progress, outcome))

    def record_resource_observation(self, row):
        self.observations.append(row)
        return len(self.observations)

    def get_task(self, task_id):
        return {"md5sum": task_id, "storage_key": "tester"}


def test_runner_protocol_lines_are_ingested_from_stdout(tmp_path):
    store = _RecordingTaskStore()
    job = SlurmJob(
        "task-1",
        _make_task_type(),
        _make_runner(),
        _make_entities(),
        str(tmp_path / "out"),
        username="alice",
        task_store=store,
    )
    observation = {
        "runner": "cpu_runner",
        "model_revision": "m1",
        "runtime_fingerprint": "fp",
        "device": {"vendor": "nvidia", "model": "A100-PCIE-40GB", "compute_capability": "8.0", "total_vram_mb": 40960},
        "features": {"runner": "cpu_runner", "model_revision": "m1", "runtime_fingerprint": "fp", "sequence_length": 100},
        "outcome": "oom",
        "baseline_mb": 100,
        "available_mb": 20000,
        "work_item": "p1",
        "attempt": 2,
    }
    job._stdout_lines = [
        "REVODESIGN_STAGE:cpu_runner\n",
        "REVODESIGN_PROGRESS:" + json.dumps({"total_items": 4, "completed_items": 2}) + "\n",
        "REVODESIGN_PROGRESS:" + json.dumps({"total_items": 4, "completed_items": 3}) + "\n",
        "REVODESIGN_OBSERVATION:" + json.dumps(observation) + "\n",
        "REVODESIGN_OBSERVATION:{malformed\n",
        "REVODESIGN_TASK_OUTCOME:PARTIAL_SUCCESS\n",
    ]

    job._ingest_runner_protocol()

    # The latest progress wins, and the outcome is recorded alongside it.
    assert store.progress == [
        ("task-1", {"total_items": 4, "completed_items": 3}, "PARTIAL_SUCCESS"),
    ]
    # A failed job's OOM row is exactly the evidence worth keeping.
    assert [row["attempt"] for row in store.observations] == [2]
    assert store.observations[0]["task_id"] == "task-1"


def test_ingest_is_skipped_without_a_task_store_and_failures_do_not_escape(tmp_path):
    job = SlurmJob(
        "task-1",
        _make_task_type(),
        _make_runner(),
        _make_entities(),
        str(tmp_path / "out"),
        username="alice",
    )
    job._stdout_lines = ["REVODESIGN_TASK_OUTCOME:SUCCESS\n"]
    job._ingest_runner_protocol()  # no store: nothing to write, nothing to raise

    class _BrokenStore(_RecordingTaskStore):
        def record_task_progress(self, *args, **kwargs):
            raise RuntimeError("database is locked")

        def record_resource_observation(self, row):
            raise RuntimeError("database is locked")

    broken = SlurmJob(
        "task-1",
        _make_task_type(),
        _make_runner(),
        _make_entities(),
        str(tmp_path / "out"),
        username="alice",
        task_store=_BrokenStore(),
    )
    broken._stdout_lines = job._stdout_lines
    broken._ingest_runner_protocol()


def test_a_hostile_stdout_line_never_skips_poll_cleanup(tmp_path):
    """Ingest runs from ``poll()``'s ``finally``; it must never skip settlement.

    A deeply nested JSON payload raises ``RecursionError`` — which is not a
    ``ValueError`` — and a ``finally`` that propagates it would leave the GPU
    allocation unsettled and the scratch directory on disk.
    """
    workspace = tmp_path / "workspace" / "task-1"
    entities = _make_entities()
    entities[0] = {
        **entities[0],
        "snapshot_path": str(workspace / "inputs" / "input.fasta"),
        "snapshot_root": str(workspace / "inputs"),
    }
    (workspace / "inputs").mkdir(parents=True)
    output = tmp_path / "out"
    finishes: list[tuple[str, float]] = []

    class _HostileStore(_RecordingTaskStore):
        def record_task_progress(self, *args, **kwargs):
            raise RecursionError("maximum recursion depth exceeded")

    job = SlurmJob(
        "task-1",
        _make_task_type(),
        _make_runner(),
        entities,
        str(output),
        task_store=_HostileStore(),
        allocation_started_callback=lambda _job_id, _at: None,
        allocation_finished_callback=lambda job_id, at: finishes.append((job_id, at)),
    )
    fake_proc = _FakeSrunProcess(stdout="REVODESIGN_JOB_ID=4217\n", returncode=0)

    with patch("subprocess.Popen", return_value=fake_proc):
        job.submit()
        job._stdout_lines = [
            "REVODESIGN_JOB_ID=4217\n",
            "REVODESIGN_PROGRESS:" + "[" * 20_000 + "\n",
            "REVODESIGN_OBSERVATION:" + "[" * 20_000 + "\n",
            "REVODESIGN_TASK_OUTCOME:PASSED\n",
        ]
        output.joinpath("result.csv").write_text("score\n1\n")
        assert job.poll() == JobState.COMPLETED

    assert [job_id for job_id, _at in finishes] == ["4217"], "the allocation must still be settled"
    assert not (workspace / "scratch").exists(), "scratch cleanup must still run"


# -- Runtime Bundle binding ---------------------------------------------------
#
# The bundle a task executes is pinned in its immutable task.json at submission.
# These prove the launch path binds that exact snapshot read-only, and that a
# bundle which no longer resolves fails closed instead of silently running a
# different one.


def _bundle_job(tmp_path, digest: str | None, *, family: str = "cpu_runner"):
    """A job whose input snapshot pins ``digest`` (or declares no bundle)."""
    store = tmp_path / "runtime-bundles"
    inputs = tmp_path / "workspace" / "task-1" / "inputs"
    inputs.mkdir(parents=True)
    manifest = {"task_id": "task-1", "params": {}}
    if digest is not None:
        manifest["runtime_bundle_sha256"] = digest
    (inputs / "task.json").write_text(json.dumps(manifest), encoding="utf-8")
    entities = _make_entities()
    entities[0] = {**entities[0], "snapshot_root": str(inputs)}
    return SlurmJob(
        "task-1",
        _make_task_type(),
        _make_runner(),
        entities,
        str(tmp_path / "out"),
        username="alice",
        runtime_bundle_root=str(store),
    )


def _materialized_bundle(tmp_path) -> tuple[str, Path]:
    from revocompute import runtime_bundle

    root = tmp_path / "runners" / "cpu_runner"
    root.mkdir(parents=True)
    (root / "run.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    os.chmod(root / "run.sh", 0o755)
    store = tmp_path / "runtime-bundles"
    digest, path = runtime_bundle.materialize(root.parent, ["cpu_runner/run.sh"], store)
    return digest, path


def test_runtime_bundle_is_bound_read_only_at_the_reserved_mount(tmp_path):
    digest, path = _materialized_bundle(tmp_path)
    job = _bundle_job(tmp_path, digest)

    script = job._render_wrapper()

    assert f"--bind '{path}':'/opt/revocompute/runtime':ro" in script
    assert "apptainer" in script
    assert subprocess.run(["bash", "-n"], input=script, text=True, check=False).returncode == 0


def test_absent_runtime_bundle_declaration_adds_no_runtime_mount(tmp_path):
    job = _bundle_job(tmp_path, None)

    script = job._render_wrapper()

    assert "/opt/revocompute/runtime" not in script


def test_unavailable_pinned_bundle_fails_closed(tmp_path):
    job = _bundle_job(tmp_path, "sha256:" + "0" * 64)

    with pytest.raises(RuntimeError, match="unavailable runtime bundle"):
        job._render_wrapper()


def test_capture_log_omits_protocol_lines_and_keeps_runner_diagnostics(tmp_path):
    job = SlurmJob(
        "task-1",
        _make_task_type(),
        _make_runner(),
        _make_entities(),
        str(tmp_path / "out"),
        username="alice",
    )
    job._job_id = "42"
    job._stdout_lines = [
        "REVODESIGN_JOB_ID=42\n",
        "model loaded\n",
        "REVODESIGN_PROGRESS:" + json.dumps({"total_items": 1}) + "\n",
        "REVODESIGN_OBSERVATION:" + json.dumps({"runner": "cpu_runner"}) + "\n",
        "REVODESIGN_TASK_OUTCOME:SUCCESS\n",
    ]

    job._save_output()

    stdout = tmp_path / "out" / "execution" / "slurm-alice-cpu_runner-task-1.stdout.log"
    assert stdout.read_text(encoding="utf-8") == "REVODESIGN_JOB_ID=42\nmodel loaded\n"
