# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import os
from functools import partial

from runner_protocol import ROOT, run_with_manifest

ESM_RUNNER_SCRIPT = ROOT / "docker/runners/esm/run.sh"
_run_with_manifest = partial(run_with_manifest, role="sequence")

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
