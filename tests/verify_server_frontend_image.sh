#!/usr/bin/env bash

set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: $0 IMAGE" >&2
  exit 2
fi

docker run --rm --user 0 --entrypoint /bin/sh "$1" -eu -c '
  test -s /app/server/revocompute/static/vendor/molstar/molstar.js
  test -s /app/server/revocompute/static/vendor/molstar/molstar.css
  ! command -v node >/dev/null 2>&1
  ! command -v npm >/dev/null 2>&1
  ! command -v npx >/dev/null 2>&1
  test ! -e /app/server/frontend
  test ! -e /app/server/package.json
  test ! -e /app/server/package-lock.json
  test ! -e /root/.npm
  test -z "$(find / -xdev -type d -name node_modules -print -quit 2>/dev/null)"
  test -z "$(find / -xdev -type d -name .npm -print -quit 2>/dev/null)"
'
