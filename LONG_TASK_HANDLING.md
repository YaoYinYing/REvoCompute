## Long-running Refactor Protocol

For large architectural refactors, migrations, repository-wide redesigns, or other work that cannot be completed reliably as a single local patch, do not treat the task as a normal feature implementation.

The agent must maintain three separate sources of truth:

```text
DESIGN / TODO
    architectural truth

IMPLEMENTATION_STATE.md
    current execution/progress truth

tests / acceptance commands
    machine-verifiable truth
```

### 1. Read the design before editing

When the user or repository identifies a design document such as:

```text
TODO.md
DESIGN.md
MIGRATION.md
RFC.md
```

read it completely before making architectural changes.

Do not infer completion merely because some requested classes, modules, abstractions, or tests already exist.

For refactors, completion means the intended dependency direction and ownership model are actually in production use.

---

### 2. Convert the design into a persistent execution checklist

Before starting a large refactor, create or update:

```text
IMPLEMENTATION_STATE.md
```

Translate every important `MUST`, required migration step, acceptance criterion, and architectural invariant from the design into explicit checklist items.

Example:

```markdown
## Completion checklist

- [ ] Move authoritative task definitions out of the central registry
- [ ] Switch production discovery to plugin-owned manifests
- [ ] Remove the old production registry path
- [ ] Migrate one real implementation end-to-end
- [ ] Add zero-plugin startup coverage
- [ ] Add architecture boundary tests
- [ ] Run final acceptance commands
```

Do not use the checklist merely as documentation.

It is the persistent execution state for the current refactor.

---

### 3. Keep progress durable

After every major milestone, update `IMPLEMENTATION_STATE.md` with:

```text
completed items
current phase
files/components migrated
verification performed
known failures
remaining blockers
next concrete action
```

Do this before moving to the next major phase.

The execution state must be sufficient for another agent session to resume the work without reconstructing the migration from git history alone.

---

### 4. Recover state after context loss or session restart

After any of the following:

```text
context compaction
new agent session
long interruption
major test/debug cycle
uncertainty about the current migration state
```

re-read:

```text
repository instructions
the active design/TODO document
IMPLEMENTATION_STATE.md
```

before deciding what to do next.

Do not rely solely on conversation memory or a compacted context summary.

Repository files are the durable project memory.

---

### 5. Architecture ownership outranks minimum diff

For ordinary bugs, prefer small and focused changes.

For an explicitly requested architectural migration, minimum-diff heuristics must not preserve an architecture that the design requires removing.

Before adding a special case, ask:

```text
Who owns this knowledge?
```

If the knowledge belongs to a plugin, task, runner, adapter, backend, or another domain module, move the validation/configuration/behavior to that owner instead of hardcoding it into generic Core code.

A two-line fix is not preferable when it violates the target dependency direction.

---

### 6. Do not stop at scaffolding

The following do not by themselves count as completion:

```text
a new manager class exists
a new interface exists
a new schema exists
a doctor command exists
new tests for the new abstraction pass
```

For a migration, the new architecture must replace the old production path.

Always distinguish:

```text
new abstraction exists
```

from:

```text
production now depends on the new abstraction
```

The latter is required.

---

### 7. Avoid dual sources of truth

During a migration, temporary compatibility code may be used only when necessary to perform the transition.

By the end of the refactor, there must not be two authoritative representations of the same concept.

Examples of forbidden final states:

```text
new plugin registry + old central task registry

new schema + legacy validation table

new execution plan + production still constructing jobs directly

distributed manifests + central fallback manifest
```

If the design requires ownership inversion, the old authoritative path must be retired after its information has been migrated.

---

### 8. Migrate information before deleting its old container

When retiring a centralized file or registry, do not interpret "delete" literally before understanding what it contains.

Use this migration sequence:

```text
inventory
→ classify ownership
→ migrate
→ switch consumers
→ verify semantic preservation
→ remove old source of truth
```

For every important migrated field, know:

```text
old location
semantic meaning
new owner
new location
verification evidence
```

A deleted centralized file with lost behavior or metadata is a failed migration.

---

### 9. Prefer vertical-slice migration

When possible, migrate one complete real implementation end-to-end before bulk-moving every implementation.

For example:

```text
discovery
→ configuration/schema
→ runtime
→ output
→ presentation
→ doctor
→ tests
```

for one real component.

Use that implementation as the reference architecture for subsequent migrations.

Do not validate a repository-wide design only with synthetic fixtures.

Synthetic fixtures are useful for protocol tests but do not replace one real production integration.

---

### 10. Make acceptance criteria executable

Whenever possible, turn architectural requirements into commands or tests.

Prefer:

```text
pytest tests/test_zero_plugin_startup.py
pytest tests/test_plugin_discovery.py
python scripts/check_architecture.py
```

over subjective criteria such as:

```text
architecture looks clean
plugin system appears integrated
```

Add architecture tests for important dependency rules.

Examples:

```text
Core starts with zero plugins

adding a test plugin requires no Core changes

old centralized registry is absent

production does not call deprecated discovery code

generic modules contain no known domain-specific branches
```

A failing executable acceptance gate means the refactor is not complete.

---

### 11. Self-authored tests are not sufficient evidence

Tests added during the refactor often prove only that newly added abstractions work in isolation.

Before completion, also test the negative condition:

```text
the old architecture is no longer required
```

and the integration condition:

```text
the real production path uses the new architecture
```

For architectural migrations, explicitly test dependency removal, not only feature addition.

---

### 12. Maintain explicit phases

Large refactors should be tracked in phases such as:

```text
Phase 1 — inventory and design validation
Phase 2 — generic contracts
Phase 3 — reference implementation migration
Phase 4 — production dependency switch
Phase 5 — bulk migration
Phase 6 — old architecture removal
Phase 7 — doctor / architecture validation
Phase 8 — full regression verification
```

Record the active phase in `IMPLEMENTATION_STATE.md`.

Do not jump to cleanup/removal before the migrated path is operational.

---

### 13. Do not declare completion with unchecked checklist items

A final response is allowed only when:

```text
all required checklist items are complete
```

or an actual external blocker prevents further work.

An external blocker means something the agent cannot fix in the repository, such as:

```text
missing credentials
unavailable external service
required proprietary dependency unavailable
missing user decision on genuinely ambiguous product behavior
```

Large scope, failing tests, architectural complexity, or a long diff are not blockers.

Continue working.

---

### 14. Before finalizing, perform an architecture audit

For large refactors, explicitly search for remnants of the old architecture.

Examples:

```text
deprecated file names
old loader functions
old registries
legacy configuration keys
known domain identifiers in generic modules
special-case branches
compatibility fallbacks
duplicate sources of truth
```

Review each remaining occurrence.

Do not blindly remove matches, but require a reason for every intentional remainder.

---

### 15. Final acceptance report

Before completing a major refactor, update `IMPLEMENTATION_STATE.md` and report:

```text
what architecture changed
what old sources of truth were retired
where migrated information now lives
which real implementation proves the design
which production dependency paths changed
which acceptance tests prove the migration
which commands were run
which tests passed or failed
what intentional architecture debt remains
```

Do not describe scaffolding as finished migration.

---

### 16. Repository-level definition of done for architectural refactors

A large refactor is complete only when all three are true:

```text
DESIGN TRUTH
The repository structure and dependency direction match the intended architecture.

EXECUTION TRUTH
IMPLEMENTATION_STATE.md has no unresolved required migration items.

MACHINE TRUTH
The defined acceptance tests and architecture gates pass.
```

If one of these is false, continue the refactor.
