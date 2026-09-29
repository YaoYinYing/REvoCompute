#!/usr/bin/env bash

set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: $0 IMAGE" >&2
  exit 2
fi

docker run --rm --user 0 --entrypoint /bin/sh "$1" -eu -c '
  test -s /app/server/revocompute/static/app/index.html
  test -s /app/server/revocompute/static/app/.vite/manifest.json
  test -s /app/server/revocompute/static/app/assets/molecular-viewer.js
  test -s /app/server/revocompute/static/app/assets/molecular-viewer.css
  test -n "$(find /app/server/revocompute/static/app/assets -maxdepth 1 -type f -name "*.js" -size +0c -print -quit)"
  test -n "$(find /app/server/revocompute/static/app/assets -maxdepth 1 -type f -name "*.css" -size +0c -print -quit)"
  ! command -v node >/dev/null 2>&1
  ! command -v npm >/dev/null 2>&1
  ! command -v npx >/dev/null 2>&1
  test ! -e /app/server/frontend
  test ! -e /app/server/package.json
  test ! -e /app/server/package-lock.json
  test ! -e /app/server/revocompute/static/vendor/molstar
  test ! -e /root/.npm
  test -z "$(find / -xdev -type d -name node_modules -print -quit 2>/dev/null)"
  test -z "$(find / -xdev -type d -name .npm -print -quit 2>/dev/null)"
'
