# Operational Events

REvoCompute writes privacy-safe JSON Lines to
`$LOG_DIR/operational-events.log`. Each event has a UTC `timestamp`, `level`,
and stable `event` name. Available correlation fields include `request_id`,
`task_id`, `celery_task_id`, `slurm_job_id`, and `stage_id`.

The web service accepts a safe `X-Request-ID` or generates one and returns it
on every response. Task submission stores that ID in server-owned Task context
and passes it to the Celery worker. User scientific content, uploaded filenames,
headers, credentials, email addresses, and internal filesystem paths are not
accepted event fields.

Use ordinary `jq` filters against the active log:

```bash
jq -c 'select(.request_id == "REQUEST_ID")' "$LOG_DIR/operational-events.log"
jq -c 'select(.task_id == "TASK_ID")' "$LOG_DIR/operational-events.log"
jq -c 'select(.celery_task_id == "CELERY_ID")' "$LOG_DIR/operational-events.log"
jq -c 'select(.slurm_job_id == "SLURM_ID")' "$LOG_DIR/operational-events.log"
jq -c 'select(.level == "ERROR")' "$LOG_DIR/operational-events.log"
```

Administrators can also select **Operational events** at `/compute/logs`.
The existing log-rotation policy includes this `.log` file.
No Loki, Grafana, or separate log service is required; those remain optional
deployment integrations.
