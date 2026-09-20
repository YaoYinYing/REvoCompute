# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
from pathlib import Path

import pytest
from revocompute import task_types

ROOT = Path(__file__).resolve().parents[3]
FAMILY = ROOT / "docker" / "runners" / "ppiformer"


class _RegistryContext:
    def __enter__(self):
        self.manager = task_types._plugin_manager
        self.categories = dict(task_types._category_registry)
        return self

    def __exit__(self, *_):
        task_types._plugin_manager = self.manager
        task_types._category_registry.clear()
        task_types._category_registry.update(self.categories)


def _load_adapter():
    spec = importlib.util.spec_from_file_location("ppiformer_predict", FAMILY / "predict.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("value", ["", "A1V", "AA1J", "AA1V,", ";", "AA1V;bad"])
def test_ppiformer_mutation_parser_rejects_invalid_or_ambiguous_syntax(value: str):
    with pytest.raises(ValueError):
        _load_adapter().parse_mutations(value)


def test_ppiformer_mutation_parser_preserves_combined_variants():
    assert _load_adapter().parse_mutations("AA1V,GB2A; AA2G\nGB3A") == ["AA1V,GB2A", "AA2G", "GB3A"]


def test_ppiformer_wrapper_dispatches_both_modes_and_requires_artifacts(tmp_path: Path):
    fake = tmp_path / "fake.py"
    fake.write_text(
        """#!/usr/bin/env python3
import json
from pathlib import Path
import sys
args = sys.argv[1:]
out = Path(args[args.index('--output-dir') + 1]); out.mkdir(parents=True, exist_ok=True)
if args[0] == 'ddg':
    (out / 'ddg_predictions.csv').write_text('mutation,predicted_ddg_kcal_mol\\nAA1V,0.0\\n')
else:
    names = ('residue_embeddings.npy', 'interface_embedding.npy', 'residue_index.csv', 'embedding_summary.json')
    for name in names:
        (out / name).write_bytes(b'x')
(out / 'run_metadata.json').write_text(json.dumps({'mode': args[0]}))
Path(sys.argv[sys.argv.index('--scratch-dir') + 1], 'call.json').write_text(json.dumps(args))
""",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    pdb = ROOT / "tests" / "data" / "ppiformer" / "1abc_A_B.pdb"
    cases = (("ppiformer_ddg", {"mutations": "AA1V", "impute_missing": False}), ("ppiformer_embed", {}))
    for task_type, params in cases:
        manifest = tmp_path / f"{task_type}.json"
        manifest.write_text(
            json.dumps({"inputs": {"complex": [{"path": str(pdb)}]}, "params": params}), encoding="utf-8"
        )
        output = tmp_path / task_type
        completed = subprocess.run(
            ["bash", str(FAMILY / "run.sh"), "-i", str(manifest), "-o", str(output)],
            env={
                **os.environ,
                "TASK_TYPE": task_type,
                "TASK_CONTEXT_SRC": str(ROOT / "docker" / "runners" / "common" / "task_context.sh"),
                "PPIFORMER_PREDICT_SCRIPT": str(fake),
                "PPIFORMER_PYTHON": "python3",
            },
            text=True,
            capture_output=True,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr
        assert (output / "task_finished").is_file()
