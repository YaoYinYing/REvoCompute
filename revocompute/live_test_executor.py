# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Private worker-side live-test execution protocol."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from revocompute import task_runtime
from revocompute.live_tests import sha256_file


def _scheduler_user(job_id: str) -> str | None:
    if not re.fullmatch(r"[0-9]+", job_id):
        return None
    try:
        result = subprocess.run(
            ["scontrol", "show", "job", "-o", job_id],
            check=False, capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    match = re.search(r"(?:^| )UserId=([^ (]+)", result.stdout or "")
    return match.group(1) if match else None


def _evidence(task: dict[str, Any]) -> dict[str, Any]:
    try:
        workflow = json.loads(task.get("workflow_state") or "{}")
    except (TypeError, json.JSONDecodeError):
        workflow = {}
    jobs: list[dict[str, str | None]] = []
    if isinstance(workflow, dict):
        for stage, details in workflow.items():
            if isinstance(details, dict) and details.get("job_id"):
                job_id = str(details["job_id"])
                jobs.append({
                    "stage": str(stage), "job_id": job_id,
                    "state": str(details.get("status") or ""),
                    "scheduler_user": _scheduler_user(job_id),
                })
    job_id = str(task.get("slurm_job_id") or (jobs[-1]["job_id"] if jobs else ""))
    if job_id and not jobs:
        jobs.append({"stage": "main", "job_id": job_id, "state": str(task.get("status") or ""), "scheduler_user": _scheduler_user(job_id)})
    users = {job["scheduler_user"] for job in jobs}
    scheduler_user = next(iter(users)) if len(users) == 1 else None
    return {
        "execution_uid": os.getuid(), "execution_gid": os.getgid(),
        "scheduler_user": scheduler_user or (_scheduler_user(job_id) if not jobs else None), "slurm_job_id": job_id or None,
        "slurm_jobs": jobs,
    }


def execute(request_path: str | os.PathLike[str]) -> dict[str, Any]:
    request = json.loads(Path(request_path).read_text(encoding="utf-8"))
    if not isinstance(request, dict) or set(request) != {"task_id", "task_type", "result_path", "artifact_path", "artifact_sha256"}:
        raise ValueError("live-test request has an invalid schema")
    task_id, task_type, result_path = request["task_id"], request["task_type"], Path(request["result_path"])
    artifact_path = Path(request["artifact_path"])
    if not isinstance(task_id, str) or not re.fullmatch(r"[a-fA-F0-9]{32}", task_id):
        raise ValueError("live-test request task_id is invalid")
    if not isinstance(task_type, str) or not task_type:
        raise ValueError("live-test request task_type is invalid")
    image_root = os.environ.get("REVOCOMPUTE_IMAGE_DIR") or str(artifact_path.parent)
    if not image_root or not isinstance(request["artifact_sha256"], str):
        raise ValueError("live-test request artifact is invalid")
    try:
        artifact_path = artifact_path.resolve()
        if not artifact_path.is_relative_to(Path(image_root).resolve()) or not artifact_path.is_file():
            raise ValueError("live-test request artifact is outside the image directory")
    except OSError as exc:
        raise ValueError("live-test request artifact is invalid") from exc
    digest = sha256_file(artifact_path)
    if request["artifact_sha256"] not in {digest, digest.removeprefix("sha256:")}:
        raise ValueError("live-test request artifact hash does not match")
    for command in (("apptainer", "inspect", str(artifact_path)), ("apptainer", "test", str(artifact_path))):
        validation = subprocess.run(command, check=False, capture_output=True, text=True)
        if validation.returncode != 0:
            detail = (validation.stderr or validation.stdout or "Apptainer validation failed").strip()
            raise RuntimeError(detail[-2000:])
    task_runtime._execute_compute_task(task_id, task_type)
    task = task_runtime.task_store.get_task(task_id) or {}
    result = {"task_status": task.get("status"), "error": task.get("error"), **_evidence(task)}
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text(json.dumps(result, ensure_ascii=True, sort_keys=True) + "\n", encoding="utf-8")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m revocompute.live_test_executor")
    parser.add_argument("request")
    execute(parser.parse_args(argv).request)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
