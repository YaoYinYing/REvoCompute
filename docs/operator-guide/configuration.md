# Configuration and Service Identity

Configuration has three deliberate owners. The selected environment file
(`REVODESIGN_SERVER_ENV`) owns host paths, Compose settings, credentials, and
the configured service identity. A family `plugin.yaml` owns task and runtime
contracts. A machine-local `runner.yaml` owns mounts, environment, limits, and
defaults. Do not copy these values into JavaScript or a second YAML registry.

## Identity contract

The deployment operator may be different from the service identity. The
configured `RUNNER_USERNAME` and `RUNNER_GROUP` must resolve on the target host;
explicit `RUNNER_UID` and `RUNNER_GID`, when supplied, must equal those account
records. Root and silent numeric fallbacks are rejected. Validate the effective
UID/GID in web, worker, and a real Slurm smoke job before lifting maintenance.

## Safe configuration workflow

```bash
cp .env.example .env.production.example-slurm
chmod 0600 .env.production.example-slurm
export REVODESIGN_SERVER_ENV=.env.production.example-slurm
git check-ignore -v "$REVODESIGN_SERVER_ENV"
```

Keep secrets in mode-0600 files or the deployment secret store. Print only an
allowlist of paths when diagnosing configuration; never dump an environment
file, credentials, or scheduler tokens into logs or receipts. Run Doctor after
changing any identity, mount, resource, task, or access-policy setting.
