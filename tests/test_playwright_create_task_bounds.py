# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Browser behavior for the Create Task parameter projection and its validator.

The owning ``task.yaml`` declares numeric bounds the server enforces (a
``jsonschema`` Draft 2020-12 validator rejects a value equal to a declared
``exclusiveMinimum``). Create Task reads the same parameter schema, so the
parameter definition the form builds must carry every declared bound, and the
field label the server owns must reach every message frame for that parameter
unchanged.

The module under test (``frontend/src/features/create-task/parameter-controls``)
is pure parser/validator logic with no DOM entry point of its own, so the test
loads the real module into a browser through the project's own bundler (vite, the
pinned frontend dependency) and drives it with real controls. Nothing about the
module is re-implemented here: what it projects and what it refuses is what moves
these assertions.

Only observable outcomes are asserted - a bound is carried or it is not, and the
server-owned parameter label appears in a message frame or it does not. No
translated sentence, class name, or pixel is pinned.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from playwright.sync_api import Page
import pytest

pytestmark = pytest.mark.browser

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
VITE_ENTRY = FRONTEND / "node_modules" / "vite" / "dist" / "node" / "index.js"

# The module authors its message frames from the frontend locale layer, which
# reads a stored locale from `localStorage` when it first loads. A document
# served from a real origin has one; the `about:blank` scratch document does not,
# so the module is loaded into a routed page rather than a `set_content` body.
ORIGIN = "https://revocompute.example"
BLANK = "<!doctype html><html lang='en'><body></body></html>"

# One task.yaml-owned parameter schema in the shape the server serves from
# `/compute/api/task-parameters/<runner>`: exclusive bounds on each side, an
# exclusive pair with no inclusive bound, and an inclusive integer range.
# ``lambda_l2`` mirrors the shipped gremlin_lh_fit declaration
# (``exclusiveMinimum: 0``, ``maximum: 10``).
BOUNDS_SCHEMA: dict[str, object] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "lambda_l2": {"type": "number", "default": 0.01, "exclusiveMinimum": 0, "maximum": 10},
        "epsilon": {"type": "number", "minimum": -1, "exclusiveMaximum": 1},
        "window": {"type": "number", "exclusiveMinimum": 0, "exclusiveMaximum": 1},
        "iterations": {"type": "integer", "minimum": 1, "maximum": 4},
    },
}

# One choice-bearing parameter whose server-owned label carries an acronym, and
# one whose label the frontend derives from its name.
LABEL_SCHEMA: dict[str, object] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": ["use_msa", "regularization"],
    "properties": {
        "use_msa": {"type": "string", "title": "Use MSA", "enum": ["yes", "no"]},
        "regularization": {"type": "string", "enum": ["L2", "LH"]},
    },
}

# Bundles the real module - and the locale catalog it authors its frames from -
# with the project's own bundler and writes the bundle to stdout. `vite` resolves
# the module's imports; nothing about the module is stubbed.
BUNDLE_DRIVER = """
const [viteEntry, frontend, outDir] = process.argv.slice(1);
const { build } = await import(viteEntry);
await build({
  configFile: false,
  root: frontend,
  publicDir: false,
  logLevel: 'error',
  build: {
    lib: {
      entry: frontend + '/src/features/create-task/parameter-controls.ts',
      formats: ['iife'], name: '__ct', fileName: () => 'module.js',
    },
    outDir, emptyOutDir: true, minify: false, write: true,
  },
});
const fs = await import('node:fs');
process.stdout.write(fs.readFileSync(outDir + '/module.js', 'utf8'));
"""


def _install_module(page: Page, tmp_path: Path) -> None:
    """Bundle ``parameter-controls`` with vite and load it into a page."""
    node = shutil.which("node")
    assert node is not None, "node is required to bundle the Create Task module under test"
    assert VITE_ENTRY.is_file(), f"vite is not installed at {VITE_ENTRY}"
    completed = subprocess.run(
        [node, "--input-type=module", "-e", BUNDLE_DRIVER, str(VITE_ENTRY), str(FRONTEND), str(tmp_path / "module")],
        capture_output=True, text=True, timeout=300, check=False,
    )
    assert completed.returncode == 0, f"bundling parameter-controls failed:\n{completed.stdout}\n{completed.stderr}"
    assert completed.stdout.strip(), "the bundler produced no module"
    page.route(f"{ORIGIN}/**", lambda route: route.fulfill(status=200, content_type="text/html", body=BLANK))
    page.goto(f"{ORIGIN}/blank")
    page.add_script_tag(content=completed.stdout)
    assert page.evaluate("() => typeof globalThis.__ct?.parametersFromSchema") == "function"


def test_the_definition_carries_every_declared_numeric_bound(page: Page, tmp_path: Path) -> None:
    """A bound the server enforces is a bound the form's definition carries."""
    _install_module(page, tmp_path)
    projected = page.evaluate(
        """schema => Object.fromEntries(__ct.parametersFromSchema(schema).map(definition => [definition.name, {
             minimum: definition.minimum ?? null,
             maximum: definition.maximum ?? null,
             exclusiveMinimum: definition.exclusiveMinimum ?? null,
             exclusiveMaximum: definition.exclusiveMaximum ?? null,
           }]))""",
        BOUNDS_SCHEMA,
    )

    assert projected == {
        "lambda_l2": {"minimum": None, "maximum": 10, "exclusiveMinimum": 0, "exclusiveMaximum": None},
        "epsilon": {"minimum": -1, "maximum": None, "exclusiveMinimum": None, "exclusiveMaximum": 1},
        "window": {"minimum": None, "maximum": None, "exclusiveMinimum": 0, "exclusiveMaximum": 1},
        "iterations": {"minimum": 1, "maximum": 4, "exclusiveMinimum": None, "exclusiveMaximum": None},
    }


def test_a_value_beyond_a_declared_bound_is_refused(page: Page, tmp_path: Path) -> None:
    """The validator refuses the values the declared bounds put out of range."""
    _install_module(page, tmp_path)
    accepted = page.evaluate(
        """schema => {
          const byName = Object.fromEntries(__ct.parametersFromSchema(schema).map(definition => [definition.name, definition]));
          const enter = (name, value) => {
            const control = document.createElement('input');
            control.value = value;
            return __ct.validateParameter(byName[name], control) === null;
          };
          return Object.fromEntries(Object.entries(schema.__values).map(([name, values]) =>
            [name, Object.fromEntries(values.map(value => [value, enter(name, value)]))]));
        }""",
        {
            **BOUNDS_SCHEMA,
            "__values": {
                "lambda_l2": ["0.01", "10", "10.1"],
                "epsilon": ["-1", "-1.0001"],
                "window": ["0.5"],
                "iterations": ["0", "1", "4", "5"],
            },
        },
    )

    assert accepted == {
        "lambda_l2": {"0.01": True, "10": True, "10.1": False},
        "epsilon": {"-1": True, "-1.0001": False},
        "window": {"0.5": True},
        "iterations": {"0": False, "1": True, "4": True, "5": False},
    }


def test_every_parameter_message_names_the_parameter_as_its_field_label_does(page: Page, tmp_path: Path) -> None:
    """One parameter is named one way in every frame it appears in."""
    _install_module(page, tmp_path)
    frames = page.evaluate(
        """schema => {
          const built = {};
          for (const definition of __ct.parametersFromSchema(schema)) {
            const required = document.createElement('select');
            required.append(new Option('none', ''));
            const choice = document.createElement('select');
            choice.append(new Option('not listed', 'not-listed'));
            built[definition.name] = {
              label: definition.label,
              required: __ct.validateParameter(definition, required),
              choice: __ct.validateParameter(definition, choice),
            };
          }
          return built;
        }""",
        LABEL_SCHEMA,
    )

    assert frames["use_msa"]["label"] == "Use MSA"
    assert frames["regularization"]["label"] == "Regularization"
    for name, frame in frames.items():
        assert frame["required"] is not None and frame["choice"] is not None, name
        # The label is the server-owned parameter vocabulary and is interpolated
        # verbatim into every frontend-owned frame, so the parameter reads the
        # same in its field label and in each of its messages.
        assert frame["label"] in frame["required"], (name, frame)
        assert frame["label"] in frame["choice"], (name, frame)
