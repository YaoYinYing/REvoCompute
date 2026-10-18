# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import os
from functools import partial
from pathlib import Path
from typing import NamedTuple

from runner_protocol import ROOT, run_with_manifest

ESM_RUNNER_SCRIPT = ROOT / "docker/runners/esm/run.sh"
ESM_TASK_CONTEXT = ROOT / "docker/runners/common/runtime/task_context.sh"
PARAM_LOG_VARIABLE = "ESM_PARAM_LOG"

_run_with_manifest = partial(run_with_manifest, role="sequence")


class EsmInput(NamedTuple):
    """One Task's named input role, as its owning ``task.yaml`` declares it."""

    name: str
    formats: tuple[str, ...]


#: The resolved Runner inputs for every ESM Task: the named input role, its
#: declared format, and the parameter set the Server materializes into the
#: dispatched ``task.json``.
#:
#: This is a fixture rather than a Server projection, deliberately: this is a
#: Runner unit lane observing the adapter's own reads, so it owns the inputs it
#: drives the adapter with and no Server schema or discovery change can fail it
#: before an adapter defect exists.  The owning ``task.yaml`` remains the single
#: source of the vocabulary, and the Server's projection of it has its own
#: coverage off this lane.
ESM_TASKS: dict[str, tuple[EsmInput, dict[str, object]]] = {
    "esm_1v": (EsmInput("sequence", ("fasta",)), {}),
    "esm_extract": (
        EsmInput("sequence", ("fasta",)),
        {
            "model": "esm2_t33_650M_UR50D",
            "repr_layers": "33",
            "include": "mean per_tok",
            "toks_per_batch": 4096,
            "truncation_seq_length": 1022,
        },
    ),
    "esm_if1": (EsmInput("structure", ("pdb",)), {"temperature": 1.0, "num_samples": 1, "chain": "A"}),
    "esm_msa": (EsmInput("alignment", ("a3m",)), {"msa_samples": 32}),
}

#: Every parameter name any ESM Task declares.
ESM_DECLARED_PARAMETERS: frozenset[str] = frozenset(
    name for _input_role, params in ESM_TASKS.values() for name in params
)

# ``_parse_param`` is total: an undeclared name silently resolves to its default,
# so the only way to observe which names an adapter asks for is to wrap the real
# implementation.  The adapter sources this stand-in in place of the shipped
# ``task_context.sh``, so every recorded name is a genuine read by ``run.sh``
# rather than a pattern matched in its text.
_RECORDER_TEMPLATE = """#!/usr/bin/env bash
source "__TASK_CONTEXT__"
eval "$(declare -f _parse_param | sed 's/^_parse_param/_real_parse_param/')"
_parse_param() {
  printf '%s\\n' "$1" >> "$__PARAM_LOG_VARIABLE__"
  _real_parse_param "$@"
}
"""


def test_esm_extract_scopes_cache_and_temporary_files_to_scratch(tmp_path):
    input_file = tmp_path / "input.fasta"
    output_dir = tmp_path / "outputs"
    bin_dir = tmp_path / "bin"
    capture = tmp_path / "esm.env"
    scratch = tmp_path / "scratch"
    checkpoints = tmp_path / "provisioned" / "checkpoints"
    input_file.write_text(">test\nACDE\n", encoding="utf-8")
    bin_dir.mkdir()
    scratch.mkdir()
    checkpoints.mkdir(parents=True)
    (checkpoints / "esm2_t6_8M_UR50D.pt").write_bytes(b"model")
    (checkpoints / "esm2_t6_8M_UR50D-contact-regression.pt").write_bytes(b"regression")
    executable = bin_dir / "esm2-extract"
    executable.write_text(
        "#!/bin/bash\n"
        "set -e\n"
        "test -f \"$TORCH_HOME/hub/checkpoints/${1}.pt\"\n"
        "test -f \"$TORCH_HOME/hub/checkpoints/${1}-contact-regression.pt\"\n"
        "printf '%s\\n' \"$TMPDIR\" \"$XDG_CACHE_HOME\" \"$TORCH_HOME\" \"$(readlink -f \"$TORCH_HOME/hub/checkpoints\")\" > \"$ESM_ENV_CAPTURE\"\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:{env['PATH']}",
            "TMPDIR": str(scratch),
            "ESM_ENV_CAPTURE": str(capture),
            "ESM_CHECKPOINT_DIR": str(checkpoints),
            "TASK_TYPE": "esm_extract",
            "http_proxy": "http://127.0.0.1:1",
            "https_proxy": "http://127.0.0.1:1",
        }
    )

    completed = _run_with_manifest(
        ESM_RUNNER_SCRIPT,
        input_file,
        output_dir,
        env,
        params={
            "model": "esm2_t6_8M_UR50D",
            "repr_layers": "6",
            "include": "mean",
            "toks_per_batch": 128,
            "truncation_seq_length": 64,
        },
    )

    assert completed.returncode == 0, completed.stderr
    locations = capture.read_text(encoding="utf-8").splitlines()
    assert all(path.startswith(str(scratch / "revodesign-esm.")) for path in locations[:3])
    assert locations[3] == str(checkpoints)
    assert not any(path.startswith(str(output_dir)) for path in locations[:3])
    assert (output_dir / "task_finished").is_file()


#: A key every ESM ``task.yaml`` carries as JSON Schema structure and every input
#: role carries as a field, but no Task declares as a parameter.  A read of it is
#: a control the user was never offered, and the case a text scan of those files
#: cannot see.
UNDECLARED_PROBE_PARAMETER = "type"


def test_esm_reads_only_parameters_its_tasks_declare(tmp_path):
    """No adapter read may name a parameter no esm TaskType declares.

    A read naming a parameter no Task declares is a control the user was
    never offered — what caught the write-only ``num_recycles``,
    ``max_tokens_per_batch`` and ``chunk_size`` reads.  The reads are observed by
    running the adapter for every ESM Task, each over the resolved Runner inputs
    the Server would project for it.
    """
    reads: set[str] = set()
    for task_type, (input_role, params) in sorted(ESM_TASKS.items()):
        reads |= _esm_reads(ESM_RUNNER_SCRIPT, task_type, input_role, params, tmp_path / task_type)

    assert reads, "the adapter reads no parameters at all"
    undeclared = reads - ESM_DECLARED_PARAMETERS
    assert not undeclared, f"adapter reads undeclared parameters: {sorted(undeclared)}"


def test_esm_parameter_probe_flags_a_read_no_task_declares(tmp_path):
    """The read observation must separate a declared name from a metadata key.

    The probe adapter differs from ``run.sh`` only in the names it asks for, so an
    adapter reading ``UNDECLARED_PROBE_PARAMETER`` is reported while the declared
    name it reads alongside is not.
    """
    task_type, (input_role, params) = sorted(ESM_TASKS.items())[0]
    probe = tmp_path / "probe_adapter.sh"
    probe.write_text(
        "#!/usr/bin/env bash\n"
        'source "$TASK_CONTEXT_SRC"\n'
        'printf \'%s\\n\' "$(_parse_param model)"\n'
        f'printf \'%s\\n\' "$(_parse_param {UNDECLARED_PROBE_PARAMETER})"\n',
        encoding="utf-8",
    )

    reads = _esm_reads(probe, task_type, input_role, params, tmp_path / "probe")

    assert reads == {"model", UNDECLARED_PROBE_PARAMETER}
    assert reads - ESM_DECLARED_PARAMETERS == {UNDECLARED_PROBE_PARAMETER}


def _write_recorder(directory: Path) -> Path:
    """Install the ``_parse_param`` recorder an adapter sources."""
    recorder = directory / "param_recorder.sh"
    recorder.write_text(
        _RECORDER_TEMPLATE.replace("__TASK_CONTEXT__", str(ESM_TASK_CONTEXT)).replace(
            "__PARAM_LOG_VARIABLE__", PARAM_LOG_VARIABLE
        ),
        encoding="utf-8",
    )
    return recorder


def _esm_reads(script: Path, task_type: str, input_role: EsmInput, params: dict, case: Path) -> set[str]:
    """Run one adapter for one Task and return the parameter names it read.

    The model executables are stubs: this observes the adapter's parameter
    contract, so the stub input needs only the role's declared format, never
    valid scientific content.
    """
    case.mkdir(parents=True, exist_ok=True)
    bin_dir = case / "bin"
    bin_dir.mkdir()
    for executable_name in ("python", "esm2-extract"):
        stub = bin_dir / executable_name
        stub.write_text("#!/bin/bash\nexit 0\n", encoding="utf-8")
        stub.chmod(0o755)
    checkpoints = case / "checkpoints"
    checkpoints.mkdir()
    input_file = case / f"input.{input_role.formats[0]}"
    input_file.write_text(">test\nACDE\n", encoding="utf-8")
    param_log = case / "params.log"
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:{env['PATH']}",
            "TASK_TYPE": task_type,
            "TASK_CONTEXT_SRC": str(_write_recorder(case)),
            PARAM_LOG_VARIABLE: str(param_log),
            "ESM_CHECKPOINT_DIR": str(checkpoints),
            "http_proxy": "http://127.0.0.1:1",
            "https_proxy": "http://127.0.0.1:1",
        }
    )

    completed = run_with_manifest(script, input_file, case / "outputs", env, params=params, role=input_role.name)

    assert completed.returncode == 0, completed.stderr
    return set(param_log.read_text(encoding="utf-8").split())
