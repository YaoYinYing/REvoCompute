#!/usr/bin/env bash

set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: $0 IMAGE" >&2
  exit 2
fi

docker run --rm --user 0 --entrypoint /usr/local/bin/python "$1" -c '
import json
from pathlib import Path

root = Path("/app/server/revocompute/static/app").resolve()
manifest = json.loads((root / ".vite/manifest.json").read_text(encoding="utf-8"))
assert isinstance(manifest, dict) and isinstance(manifest.get("index.html"), dict)
for key, item in manifest.items():
    assert isinstance(key, str) and isinstance(item, dict)
    for field in ("css", "imports", "dynamicImports"):
        assert isinstance(item.get(field, []), list)
    references = [item.get("file"), *item.get("css", [])]
    for relative in references:
        assert isinstance(relative, str) and relative and not relative.startswith("/") and "\\" not in relative
        assert all(part not in ("", ".", "..") for part in relative.split("/"))
        target = (root / relative).resolve()
        assert target.is_relative_to(root) and target.is_file() and target.stat().st_size > 0
    for imported in (*item.get("imports", []), *item.get("dynamicImports", [])):
        assert imported in manifest
'

docker run --rm --user 0 --entrypoint /bin/sh "$1" -eu -c '
  test -s /app/server/revocompute/static/app/index.html
  test -s /app/server/revocompute/static/app/.vite/manifest.json
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
