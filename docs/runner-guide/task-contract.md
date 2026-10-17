# Task Contract

A task manifest is the complete scientific API for one TaskType. Define its
input schema and validation, typed parameters and defaults, resource/network
requirements, runner arguments, execution stages, output files, and result
parser/artifact contract. Keep task-specific knowledge in the owning family;
Core should only orchestrate generic schemas and plans.

Under `parameters.properties`, declare every user-facing parameter's name,
JSON Schema type, default or required semantics, applicable enum/range/format
constraints, and a non-empty description of its actual scientific control.
The optional `x-ui-control: {kind: seed}` presentation hint is accepted only on
integer properties and asks browser clients to add concrete random-seed generation.
Its optional `random.minimum` and `random.maximum` define the browser-generation
domain separately from the API-valid range, so sentinels remain manually valid but
are never generated. The registry rejects invalid controls or generation bounds.
Do not generate descriptions mechanically from names. The server returns this
same Draft 2020-12 schema anonymously from
`GET /compute/api/task-parameters/<task-type>`. The TaskType detail links to
that canonical route with `parameters_url`; it does not embed a second copy. No
Python, JavaScript, Markdown, runner configuration, or shell adapter may become
a second parameter registry.
The stable `/skills.md` bootstrap guide directs agents to the dynamic Task APIs;
it does not list TaskTypes. Keep `summary`, `use_when`, input/output guidance,
and considerations accurate because `/compute/api/types/<name>` exposes that
semantic metadata after catalog selection.

Method citations are declared once, as an ordered `citations` list:

```yaml
citations:
- num: 1
  doi: 10.xxxx/xxxxx
  bibtex: >-
    @article{...}
```

Each entry carries exactly `num`, a bare canonical `doi`, and the original
`bibtex`. BibTeX is the authoritative bibliographic record — the display title
is parsed from it — and the DOI is the canonical external locator, so Core
derives `https://doi.org/<doi>` at load time. Core also strips Crossref inline
presentation markup (`<i>`, `<scp>`, `<sub>`, `<sup>`, ...) from that derived
display title while leaving the checked-in record untouched. Never declare a
separate title, URL, or aggregate BibTeX field: derived values are presentation
data, not a second stored contract. `citations.bib` is assembled from these same
records in `num` order. `tools/resolve_citations.py --check` validates the
contract locally with no network access; fetching or refreshing a record from
doi.org is an explicit authoring action (`--fill-missing`/`--refresh`).

Inputs are copied into an isolated task workspace and outputs are accepted only
when the declared artifact contract passes. Reject unknown or unsafe paths and
avoid implicit downloads in the execution step. Version contract changes and
update the family's required smoke cases; the changed identity invalidates
previous live receipts until revalidated.

## Input roles

Declare every input under `inputs` as a named role with a stable role ID, a
display title, a logical `type`, the formats it accepts, and its cardinality.
The role ID is the scientific name for the input, so Core, the API, the input
manifest, and Runner dispatch all address the same role rather than a file
position.

The logical `type` is what Core validates against, and a task may select a Core
dialect of a physical format when one serialization carries more than one
scientific language. A filename extension identifies serialization, not the
complete scientific meaning of an input: the same `.fasta` may be a protein
sequence or a richer entity specification. Standard protein FASTA stays strict
for every role that declares `protein_sequence`; a family whose upstream format
is a dialect declares that dialect's logical type instead. See
[Uploaded scientific inputs](../reference/security.md) for the available
profiles.

Keep transport safety, format parsing, logical-role validation, neutral
normalization, and Runner scientific preparation separate. Generic validation
must not silently protonate, assign charges, atom-type, minimize, or otherwise
alter scientific interpretation.

Cardinality counts files. One sequence FASTA may carry many records, and when a
family declares that each record is an independent work item, the Runner
normalizes them itself — see [Persistent Execution](persistent-execution.md).

## Demo inputs

A family may declare supported, scientist-facing **example inputs** beside a task
manifest: `tasks/<task-id>/demo/demos.yaml` plus a `files/` directory of
fixtures. A demo is a small redistributable fixture bound to named input roles
with typed parameter values, so a reader can fill the Create Task form in one
action. It is *not* the operator/CI acceptance contract — that stays `test.yaml`
and `tests/data` — and loading a demo never creates, reserves, submits, or
pre-authorizes a Task: it fills the same controls a reader fills by hand.

```yaml
demos:
- id: multi_record                # stable, unique per Task: [a-z][a-z0-9_]{0,63}
  title: Two short protein sequences
  purpose: One sentence on what this preset demonstrates.
  context: >-                    # optional scientific framing
    Both records are synthetic ten-residue peptides.
  source:                        # where the fixture came from
    name: REvoCompute Example Runner demo corpus
    url: https://example.org/corpus
  license:                       # why this deployment may redistribute it
    id: cc0-1.0
    name: CC0 1.0 Universal (public domain dedication)
    url: https://creativecommons.org/publicdomain/zero/1.0/
  inputs:                        # role ID -> declared fixture files
    sequence:
    - path: files/multi_record.fasta
      sha256: e2773b5a98b4b7531d5f06843e651aae83d2f33a2f92b279cfcad57776acd764
      media_type: text/x-fasta
  parameters:                    # typed parameter values, in the task's own grammar
    mass_precision: 2
```

Every declared role must be one the task's own `inputs` declares, cardinality is
enforced per role, and `parameters` is validated against the task's canonical
parameter schema — a demo is checked with the same parsers and grammar an
uploaded file and a typed parameter meet. `sha256` is the digest of the fixture
beside the manifest; a fixture may be at most a few MiB and must be a single
regular file. Fixtures live in Git only when they are genuinely small; keep PDB
structures, MSAs, and model weights out of the repository.

Provenance is required, not decorative: a demo is offered to anonymous callers,
so a family that cannot state a redistribution basis declares **no** demo rather
than declaring one under a placeholder licence. Declaring no demo is a supported
answer — the Create Task picker reports the absence.

The server publishes the catalog anonymously at
`GET /compute/api/types/<task-type>/demos` and serves each declared fixture at
`GET /compute/api/types/<task-type>/demos/<demo-id>/files/<path>`. The server
never fetches a remote dataset on a caller's behalf and never executes a demo
script: only fixtures the declaration already validated are served, by
allowlist membership.

