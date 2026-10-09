#!/usr/bin/env python3
"""Fail closed if Server collection reaches Runner-owned tests or testkit."""
from __future__ import annotations
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
server = [*(ROOT/'revocompute').rglob('*.py'), *(ROOT/'tests').rglob('*.py')]
violations=[]
for path in server:
    if '/tests/runners/' in str(path):
        continue
    text=path.read_text(errors='replace')
    for needle in ('tests.runners', 'tests/runners/', 'docker.runners'):
        if needle in text:
            violations.append((path.relative_to(ROOT), needle))
if violations:
    for p,n in violations: print(f'{p}: Server boundary import/reference {n!r}')
    raise SystemExit(1)
print(f'runner boundary clean: {len(server)} Server/Core files inspected; Runner-owned tests excluded')
