# Writing Documentation

This site is the single published source of truth for REvoCompute. This page
defines how it is organized, who owns what, and what a change must satisfy
before it merges.

## One owner per page

Every page belongs to exactly one audience section. The section is chosen by
*who needs the page*, not by which component it happens to describe:

| Section | Audience | Owns |
| --- | --- | --- |
| `user-guide/` | People submitting and reading tasks | Submission, task states, results, access |
| `operator-guide/` | People installing and running a server | Host preparation, configuration, deployment, readiness, recovery |
| `runner-guide/` | People authoring a runtime family | Family protocol, manifests, task contracts, weights, acceptance |
| `developer-guide/` | People changing Core | Architecture, execution model, plugins, result views, testing |
| `reference/` | Anyone looking something up | API routes, access-policy format, runtime families, security |
| `agents/` | Automated contributors | Architecture invariants, long-task protocol |

### What owns a fact

A fact has exactly one home, and the kind of fact decides the home.
Machine-owned facts are owned by machine-readable contracts; documentation
explains them and never copies their values.

| Fact | Owner |
| --- | --- |
| Scientific parameters, defaults, constraints | the owning `task.yaml`, projected through `/compute/api/task-parameters/{task_type}` |
| HTTP routes and request/response shapes | `revocompute/static/openapi.json` |
| Runner identity, runtime stack, task contributions | the family `plugin.yaml` and its `.def` |
| Machine-local mounts, environment, limits | the deployed `runner.yaml` |
| Deployment settings and secrets | the selected env file (`.env.example` documents the surface) |
| What a human must understand | exactly one page in this site |

When a page needs a parameter's default, link to
`/compute/api/task-parameters/{task_type}` or show a schematic example whose
values are clearly illustrative. A page that restates a machine-owned value is a
page that will be wrong later.

Within the site itself a fact still has exactly one page. If two pages need it,
keep the normative copy in the owning section and link to it rather than
restating it.

## Repository-root files are not documentation

Only these root files are maintained alongside the published site:

- `README.md` — orientation and quickstart for a new clone. It links into this
  site rather than duplicating it.
- `CLAUDE.md` / `AGENTS.md` — the normative agent contract, and the one
  deliberate exception to "`docs/` owns everything". Automated contributors read
  it directly, so it keeps its MUST-level rules. `AGENTS.md` is a symlink to
  `CLAUDE.md`; edit the target only.
  [Architecture Invariants](../agents/architecture-invariants.md) explains the
  rationale behind those rules instead of restating them.
- `LONG_TASK_HANDLING.md` — a symlink to
  [Long-task Handling](../agents/long-task-handling.md), kept so existing agent
  references to the root path keep working.
- `SECURITY.md` and `CODE_OF_CONDUCT.md` — symlinks into `reference/`, kept at
  the root because GitHub reads community-health files from there.
- `TODO.md`, `TODO_*.md`, `IMPLEMENTATION_STATE.md`, and `GOAL_GMX_MMPBSA.md` —
  the maintainer backlog and working notes. These are deliberately unpublished
  and may reference paths that no longer exist.

Any other root-level `*.md` guide is a defect. Move its content into the owning
section and delete it. When content must keep a stable root path for an existing
link, leave a symlink into `docs/` instead of a second copy. The documentation
workflow fails a pull request that adds an unlisted root-level guide, replaces a
compatibility symlink with a regular file, or repoints one away from its
canonical target.

## Page conventions

- One `#` H1 per page, matching the page's filename intent, not its nav label.
- Start with one short paragraph stating what the page covers and, when useful,
  what it deliberately does not.
- Use `##` for sections and `###` for subsections. Do not skip levels.
- Prefer relative links between pages so the navigation graph survives renames
  inside a section. Link to a section anchor when the reader only needs part of
  a page.
- Command examples use fenced `bash` blocks and `REVODESIGN_SERVER_ENV` as the
  env-file selector. Never include real credentials, tokens, or hostnames.
- State the owning component when describing a contract, for example
  "the owning `task.yaml` declares…". Documentation must not become a second
  source of truth for values that the server owns.

## Adding a page

1. Choose the owning section using the table above.
2. Create `docs/<section>/<page>.md` with an H1 and a one-paragraph introduction.
3. Add the page to `nav` in `mkdocs.yml` under that section. A page that is not
   in `nav` is not published and fails the documentation build.
4. Link the new page from its section index so it is reachable by browsing.
5. Run the local gate:

```bash
python -m pip install "mkdocs>=1.6,<2" "mkdocs-material>=9,<10"
mkdocs build --strict
```

The build fails on a broken relative link, an unlisted page, or a missing nav
target. Continuous integration runs the same command, so a page is not
documented until `mkdocs build --strict` passes.
