from __future__ import annotations

import re
from pathlib import Path

import yaml

from revocompute.task_types import _load_runner_config


DOC = Path(__file__).resolve().parents[1] / "docs" / "runner-guide" / "model-resources.md"


def test_model_resource_runner_yaml_examples_match_runner_config(tmp_path):
    text = DOC.read_text(encoding="utf-8")
    snippets = re.findall(r"```yaml\n(.*?)```", text, flags=re.DOTALL)
    assert snippets, "model-resource guide must contain a YAML mount example"

    for index, snippet in enumerate(snippets):
        data = yaml.safe_load(snippet)
        assert isinstance(data, dict) and isinstance(data.get("mounts"), list)
        assert data["mounts"]
        for mount in data["mounts"]:
            assert set(mount) >= {"host_path", "container_path", "mode"}
            assert "source" not in mount and "target" not in mount
        path = tmp_path / f"runner-{index}.yaml"
        path.write_text(snippet, encoding="utf-8")
        config = _load_runner_config(str(path))
        assert config.mounts
        assert all(mount.mode == "ro" for mount in config.mounts)
