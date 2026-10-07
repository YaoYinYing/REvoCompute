# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only

"""Deployment host views for the shared Runner control plane.

The Runner readiness/control core runs in three places that must agree: the
``revocompute_ctl`` deployment CLI, the read-only web process, and the Admin
API. They hold their host paths and environment differently — the CLI reads a
deployment env file, the web process reads its own configuration — so the core
takes this narrow protocol instead of importing either one.

``revocompute_ctl.env.EnvState`` satisfies it as-is.  A server-side view is a
small adapter over the server configuration.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from revocompute.server_root import SERVER_ROOT


@runtime_checkable
class HostPaths(Protocol):
    """The host locations and environment a control-plane evaluation needs."""

    def get(self, key: str, default: str = "") -> str:
        """Return one deployment setting."""
        ...

    def server_dir(self) -> str:
        """The deployment data tree (``SERVER_DIR``)."""
        ...

    def config_dir(self) -> str:
        """The operator configuration tree (``CONFIG_DIR``)."""
        ...

    def server_root(self) -> str:
        """The server checkout (Compose/build root)."""
        ...

    def exported(self) -> dict[str, str]:
        """The environment a started subprocess should receive."""
        ...

    def use_slurm(self) -> bool:
        """Whether this deployment executes through the scheduler."""
        ...


@dataclass
class ServerHostPaths:
    """A ``HostPaths`` view over already-resolved server settings.

    The web process already holds these values; it must not read a deployment
    env file to derive them.
    """

    server: str
    config: str
    root: str
    settings: dict[str, str] = field(default_factory=dict)
    executor: str = "slurm"

    def get(self, key: str, default: str = "") -> str:
        return self.settings.get(key) or os.environ.get(key, default)

    def server_dir(self) -> str:
        return self.server

    def config_dir(self) -> str:
        return self.config

    def server_root(self) -> str:
        return self.root

    def exported(self) -> dict[str, str]:
        return dict(os.environ)

    def use_slurm(self) -> bool:
        return self.executor.strip().lower() == "slurm"


def build_server_host(config) -> ServerHostPaths:
    """Build the web process's host view from its resolved server configuration.

    Discovery in this process already honors ``ENABLED_TASKRUNNERS`` by filtering
    the registry, so no enabled-family override is projected here: the families
    the active registry holds are exactly the enabled ones.
    """
    return ServerHostPaths(
        server=config.server_dir,
        config=os.environ.get("CONFIG_DIR") or os.path.join(config.server_dir, "config"),
        root=str(SERVER_ROOT),
        settings={
            "RUNTIME_BUNDLE_DIR": config.runtime_bundle_root,
            "SLURM_ALLOWED_QUEUES": ",".join(config.slurm_allowed_queues),
            "MANAGE_DB_PATH": config.manage_db_path,
        },
        executor=config.job_executor,
    )


__all__ = ["HostPaths", "ServerHostPaths", "build_server_host"]
