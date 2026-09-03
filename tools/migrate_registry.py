from pathlib import Path
import yaml

source = Path("config/task_types.yaml")
doc = yaml.safe_load(source.read_text(encoding="utf-8"))
root = Path("docker/runners")
for family, runtime in doc["runtime_families"].items():
    dirname = "pssm_gremlin" if family == "gremlin" else family
    target = root / dirname
    target.mkdir(parents=True, exist_ok=True)
    legacy_runner = Path("config/runners") / f"{family}.yaml"
    if legacy_runner.is_file():
        (target / "runner.yaml").write_text(legacy_runner.read_text(encoding="utf-8"), encoding="utf-8")
    manifest = {"api_version": 1, "id": family, "version": "1", "runtime": {"image": runtime.get("slurm_image") or runtime.get("docker_image", family), "definition": runtime.get("definition", f"{family}.def"), "dockerfile": runtime.get("dockerfile", "Dockerfile"), "entrypoint": runtime.get("entrypoint", [])}, "tasks": []}
    for task_id, task in doc["task_types"].items():
        if task.get("runtime_family") != family: continue
        task_dir = target / "tasks" / task_id
        task_dir.mkdir(parents=True, exist_ok=True)
        out = dict(task)
        out.pop("runtime_family", None)
        out["id"] = task_id
        params = out.pop("params", [])
        properties = {}
        required = []
        for param in params:
            p = {"type": {"str":"string", "int":"integer", "float":"number", "bool":"boolean"}.get(param.get("type", "str"), "string")}
            for key in ("default", "minimum", "maximum"): 
                if param.get(key) is not None: p[key] = param[key]
            if param.get("choices"): p["enum"] = param["choices"]
            properties[param["name"]] = p
            if param.get("required") and param.get("default") is None: required.append(param["name"])
        out["parameters"] = {"$schema":"https://json-schema.org/draft/2020-12/schema", "type":"object", "additionalProperties":False, "properties":properties}
        if required: out["parameters"]["required"] = required
        path = task_dir / "task.yaml"
        path.write_text(yaml.safe_dump(out, sort_keys=False), encoding="utf-8")
        manifest["tasks"].append(str(path.relative_to(target)))
    (target / "plugin.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
