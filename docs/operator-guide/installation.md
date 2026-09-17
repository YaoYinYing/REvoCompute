# Installation and Host Preparation

Provision the deployment host before configuring the server. This page
covers host packages, the service account, and how runner-specific
reference databases are owned.

## Host prerequisites

Install the following on the deployment host:

- Docker Engine 24+ with Compose plugin
- Enough disk space for logs, uncompressed task results, and any
  runner-specific reference databases you choose to enable

Ubuntu example:

```bash
sudo apt-get update
sudo apt-get install -y docker.io docker-compose-plugin
```

## Runner-specific databases

REvoCompute itself requires no reference database. A Runner family that depends
on one owns its acquisition, layout, and validation procedure next to its code
under `docker/runners/<family>/README.md`; the operator provisions that data
only when enabling that family.

Databases are always deployment-owned, read-only mounts declared in the family's
`runner.yaml` — never copied into an image or a task workspace. Server
installation and deployment do not depend on any of them, and a server that
disables every database-backed family needs none of them.

For the PSSM-GREMLIN family, follow
[pssm_gremlin/README.md](https://github.com/YaoYinYing/REvoCompute/blob/main/docker/runners/pssm_gremlin/README.md).
Its UniRef preparation needs `aria2c` and NCBI BLAST+ (`makeblastdb`) on the
deployment host:

```bash
sudo apt-get install -y ncbi-blast+ aria2
makeblastdb -version
```

## Service account

Use a dedicated non-root account for operations.

Ubuntu example:

```bash
sudo adduser --system --group --no-create-home --shell /usr/sbin/nologin revodesign
sudo usermod -aG docker revodesign

sudo mkdir -p /srv/revodesign/server
sudo mkdir -p /srv/revodesign/auth
sudo mkdir -p /srv/revodesign/logs

# grant full and recurse access to this user
sudo chown -R revodesign:revodesign /srv/revodesign
```

Notes:

- Never run a scheduled Runner as root.
- Configure non-root runner identity via `RUNNER_UID`/`RUNNER_GID` or `RUNNER_USERNAME`/`RUNNER_GROUP`.
  
User IDs can be found with `id <username>`. eg:

```bash
id revodesign
> uid=129(revodesign) gid=137(revodesign) groups=137(revodesign),998(docker)
```
