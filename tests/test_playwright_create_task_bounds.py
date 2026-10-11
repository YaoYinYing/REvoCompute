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

The same contract has a rendered half, so the last cases drive the built
application through ``tests/frontend_fixtures/``: a value on a declared exclusive
bound is refused at the field (the control is marked and the action is blocked),
and the validation panel states each admission blocker once and never claims the
form is ready while the status line reports a failure.

Only observable outcomes are asserted - a bound is carried or it is not, the
control carries its invalid state or it does not, a blocker is listed once, a
ready-flavoured row is present or it is not - and never a translated sentence,
class name, or pixel.
"""

from __future__ import annotations

from dataclasses import replace
import shutil
import subprocess
from pathlib import Path

from playwright.sync_api import Page, expect
import pytest

from frontend_fixtures import (
    ParameterSpec,
    PreflightAdmission,
    PreflightSpec,
    controlled_runner,
    mount_scenario,
    runner_scenario,
)

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
    """The validator refuses the values the declared bounds put out of range.

    ``0`` and ``1`` are the shipped values' own exclusive bounds, so they are the
    cases a value on the boundary produces: the server rejects a value *equal* to
    a declared exclusive bound, so the field must refuse it too rather than admit
    one the server will answer with a 400.
    """
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
                "lambda_l2": ["0", "0.01", "10", "10.1"],
                "epsilon": ["-1", "-1.0001"],
                "window": ["0", "0.5", "1"],
                "iterations": ["0", "1", "4", "5"],
            },
        },
    )

    assert accepted == {
        "lambda_l2": {"0": False, "0.01": True, "10": True, "10.1": False},
        "epsilon": {"-1": True, "-1.0001": False},
        "window": {"0": False, "0.5": True, "1": False},
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


# ---------------------------------------------------------------------------
# The same contract, rendered by the built application
# ---------------------------------------------------------------------------

BOUNDED_RUNNER = replace(controlled_runner(), parameters=(
    ParameterSpec.number("lambda_l2", default=0.01, has_default=True, exclusive_minimum=0.0, maximum=10.0),
    ParameterSpec.integer("iterations", default=2, has_default=True, minimum=1, maximum=4),
))
STATUS = ".ct-status"
ROWS = ".ct-validation-row"
# Every row that does not state a blocker: the non-blocking flavours the panel
# uses for a ready or in-progress form.
NON_ERROR_ROWS = ".ct-validation-row.ok, .ct-validation-row.info"


def _bounded_scenario(preflight: PreflightSpec | None = None):
    """The one-Runner CPU scenario with the bounded parameter contract.

    ``BOUNDED_RUNNER`` is the scenario's own Runner, so the served catalog entry,
    the detail, the parameter schema, and the Create Task route all describe the
    same contract.
    """
    scenario = runner_scenario(BOUNDED_RUNNER)
    return scenario if preflight is None else scenario.with_preflight(preflight)


def _open_bounded_create_task(page: Page) -> None:
    """Open Create Task on the bounded Runner and wait for its workbench."""
    page.goto(f"{ORIGIN}/compute/create_task?task_type={BOUNDED_RUNNER.name}")
    expect(page.locator(".ct-workbench")).to_be_visible()


def _field(page: Page, name: str):
    """The one rendered control a named parameter owns, by its bound role id."""
    return page.locator(f'[data-ct-parameter="{name}"]')


def _provide_sequence(page: Page) -> None:
    """Fill the Run's own local precondition, so nothing but the bound blocks."""
    page.locator("textarea[aria-label='Protein sequence']").fill(">sample\nACDEFG")


def _run(page: Page):
    return page.get_by_role("button", name="Run task", exact=True)


def test_a_value_on_a_declared_bound_is_refused_at_the_field(page: Page) -> None:
    """The served exclusive bound is a gate at the field, not only a spinner hint.

    ``lambda_l2`` declares ``exclusiveMinimum: 0``, so ``0`` is the value the
    server answers with a 400 and the field must refuse it; ``0.01`` is strictly
    inside the range and must be admitted.
    """
    mount_scenario(page, _bounded_scenario())
    _open_bounded_create_task(page)
    _provide_sequence(page)

    control = _field(page, "lambda_l2")
    # The declared bound is also the field's native range: the boundary the
    # validator enforces and the hint the spinner projects are the same number.
    expect(control).to_have_attribute("min", "0")
    expect(control).to_have_attribute("max", "10")
    control.fill("0")
    expect(control).to_have_attribute("aria-invalid", "")
    expect(_field(page, "iterations")).not_to_have_attribute("aria-invalid", "")
    expect(_run(page)).to_be_disabled()

    control.fill("0.01")
    expect(control).not_to_have_attribute("aria-invalid", "")
    expect(_run(page)).to_be_enabled()


@pytest.mark.parametrize(
    ("outcome", "refused_code", "admission"),
    [
        (
            "runner_not_ready",
            "admission_unavailable",
            PreflightAdmission(allowed=False, runner_ready=False, infrastructure_ready=True, infrastructure_status="READY"),
        ),
        (
            "infrastructure_not_ready",
            "infrastructure_unavailable",
            PreflightAdmission(allowed=False, runner_ready=True, infrastructure_ready=False, infrastructure_status="UNAVAILABLE"),
        ),
    ],
)
def test_an_admission_refusal_is_stated_once_and_counted_once(
    page: Page, outcome: str, refused_code: str, admission: PreflightAdmission,
) -> None:
    """A blocker the server already named is not appended a second time.

    This is the shape the server produces for an unavailable Runner or
    infrastructure: the refusal is a blocking finding *and* the same admission
    condition is clear, so the client's own row for that condition would state the
    one blocker twice. The panel must list one row per blocker and the summary
    count must equal the number of rows.
    """
    mount_scenario(page, _bounded_scenario(PreflightSpec(
        kind=outcome, errors=((refused_code, "Refused for the fixture."),), admission=admission,
    )))
    _open_bounded_create_task(page)
    _provide_sequence(page)
    _run(page).click()

    rows = page.locator(ROWS)
    expect(rows).to_have_count(1)
    expect(page.locator(f"{ROWS}.error")).to_have_count(1)
    expect(page.locator(".ct-validation-summary")).to_contain_text("1 issue")


def test_a_failed_action_never_reports_the_form_ready(page: Page) -> None:
    """A failed Run leaves no ready-flavoured row behind the failure status.

    The preflight request itself fails, so the form holds neither a preflight
    result nor a field error: nothing but the failure explains the panel, and the
    panel must not answer with a ready-flavoured row. Clear is the form's own next
    state; refilling the cleared input returns the row.
    """
    mount_scenario(page, _bounded_scenario())
    page.route(f"{ORIGIN}/compute/api/preflight/**", lambda route: route.fulfill(status=500, json={"error": "Refused for the fixture."}))
    _open_bounded_create_task(page)
    _provide_sequence(page)
    # With nothing to report the panel holds only its own non-blocker row.
    expect(page.locator(NON_ERROR_ROWS)).to_have_count(1)

    _run(page).click()
    # The failure is reported, the action stays available to retry...
    expect(page.locator(STATUS)).to_contain_text("Task checks failed")
    expect(_run(page)).to_be_enabled()
    # ...and no non-blocker row stands behind it, so the panel does not read ready
    # while the status line reports the failure.
    assert page.locator(NON_ERROR_ROWS).count() == 0

    page.get_by_role("button", name="Clear", exact=True).click()
    _provide_sequence(page)
    expect(page.locator(NON_ERROR_ROWS)).to_have_count(1)
