# Agents

This section holds the durable rules that automated contributors must follow
when changing REvoCompute. It is normative for agents and useful context for
human reviewers.

- [Architecture Invariants](architecture-invariants.md) — why the invariants
  exist, what they look like in practice, and where to read the surrounding
  design. It deliberately does not restate the rules.
- [Long-task Handling](long-task-handling.md) — the protocol for large
  refactors, migrations, and repository-wide redesigns.

Repository-root [`CLAUDE.md`](https://github.com/YaoYinYing/REvoCompute/blob/main/CLAUDE.md)
is the normative agent contract and the single owner of MUST-level rules;
`AGENTS.md` is a symlink to it. The pages here supply rationale and process, not
a second rulebook.
