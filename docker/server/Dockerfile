FROM node:22-bookworm-slim AS frontend-builder

WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
COPY frontend/scripts/verify-lock.mjs ./scripts/verify-lock.mjs
RUN node scripts/verify-lock.mjs && npm ci
COPY frontend/ ./
RUN npm run typecheck && npm run test && npm run build

FROM python:3.12-slim

# propagate args from .env to docker compose
ARG RUNNER_UID
ARG RUNNER_GID

ARG RUNNER_USERNAME
ARG RUNNER_GROUP

ARG PORT

RUN groupadd -o -r ${RUNNER_GROUP} -g ${RUNNER_GID} && \
    useradd -o -r -g ${RUNNER_GROUP} -u ${RUNNER_UID} ${RUNNER_USERNAME}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_ROOT_USER_ACTION=ignore \
    REVOCOMPUTE_LOG_DIR=/var/log/revocompute

# System deps.  Pre-seed timezone to keep tzdata from prompting.
RUN ln -fs /usr/share/zoneinfo/Etc/UTC /etc/localtime && \
    echo "Etc/UTC" > /etc/timezone && \
    echo 'Acquire::Queue-Mode "access"; Acquire::Retries "3";' > /etc/apt/apt.conf.d/99-speed.conf && \
    DEBIAN_FRONTEND=noninteractive apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl procps \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p "${REVOCOMPUTE_LOG_DIR}"

WORKDIR /app

COPY --chown=${RUNNER_UID}:${RUNNER_GID} . /app/server
COPY --from=frontend-builder --chown=${RUNNER_UID}:${RUNNER_GID} \
    /build/frontend/dist/ \
    /app/server/revocompute/static/app/
RUN python -m pip install --no-cache-dir uv && \
    uv pip install --system --no-cache "/app/server[resend]" && \
    rm -rf /app/server/frontend /app/server/node_modules /app/server/package.json /app/server/package-lock.json /root/.npm


ENV PYTHONPATH=/app/server
# ponytail: WORKDIR must be /app/server, not /app/server/revocompute.
# When CWD is inside the package dir, Python's '' sys.path entry finds
# app.py as a top-level module, shadowing the revocompute package.
WORKDIR /app/server

ENV HTTP_PROXY="" HTTPS_PROXY="" ALL_PROXY="" \
    http_proxy="" https_proxy="" all_proxy="" NO_PROXY="" no_proxy=""

USER ${RUNNER_UID}:${RUNNER_GID}

# Trust X-Forwarded-Proto only from the internal gateway (compose bridge
# range). See docker-compose.yml for the full gunicorn command.
CMD ["sh", "-c", "exec gunicorn --preload --no-control-socket -w 2 --forwarded-allow-ips '127.0.0.1,172.16.0.0/12' -b 0.0.0.0:${PORT:-8080} revocompute.app:app"]
