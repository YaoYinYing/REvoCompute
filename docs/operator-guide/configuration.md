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

## Granting state-directory access

Use POSIX ACLs when both the deployment operator and the configured service
account must manage a private server-state tree. Here `SERVER_ROLE` names the
Unix **service account** (for example, the account selected by
`RUNNER_USERNAME`), not a Unix group or an application authorization role.
Install the host package that provides `getfacl` and `setfacl`, and confirm that
the backing filesystem supports ACLs before proceeding.

Stop or quiesce writers, replace the example state path with the exact absolute
host path, and verify all three values before running the privileged block:

```bash
OPERATOR=operator
SERVER_ROLE=revodesign
SERVER_STATE=/path/to/the/server/state/storage/directory

getent passwd "$OPERATOR"
getent passwd "$SERVER_ROLE"
sudo test -d "$SERVER_STATE"
sudo find "$SERVER_STATE" -xdev -maxdepth 0 -printf '%p\n'
```

Create a private ACL backup, remove group/other mode access, grant the two
accounts access to existing entries, and set inheritable ACLs on every existing
directory:

```bash
umask 077
sudo getfacl -R -p "$SERVER_STATE" > /tmp/revocompute-acl.before
sudo chmod -R go-rwx "$SERVER_STATE"
sudo setfacl -R -m u:"$SERVER_ROLE":rwX,u:"$OPERATOR":rwX,m::rwx "$SERVER_STATE"
sudo find "$SERVER_STATE" -type d -exec \
  setfacl -m d:u::rwx,d:u:"$SERVER_ROLE":rwx,d:u:"$OPERATOR":rwx,d:g::---,d:m::rwx,d:o::--- {} +
```

This intentionally changes every existing entry below `SERVER_STATE`. The
uppercase `X` avoids making ordinary files executable: it grants traversal on
directories and execution only where it already exists. Default ACLs affect
newly created children, while the recursive access ACL covers existing content.
Do not broaden `SERVER_STATE` to a parent that contains unrelated data, and keep
the backup private because it records the complete state-tree layout.

Verify representative directories and files as both identities before
resuming writes:

```bash
sudo getfacl -p "$SERVER_STATE"
sudo -u "$SERVER_ROLE" test -r "$SERVER_STATE" -a -w "$SERVER_STATE" -a -x "$SERVER_STATE"
sudo -u "$OPERATOR" test -r "$SERVER_STATE" -a -w "$SERVER_STATE" -a -x "$SERVER_STATE"
```

To roll back, keep writers stopped and restore the saved modes and ACLs from
the same host and unchanged path tree:

```bash
sudo setfacl --restore=/tmp/revocompute-acl.before
```

Inspect the restored root with `sudo getfacl -p "$SERVER_STATE"`, then securely
remove or archive the ACL backup according to the host's operations policy.
