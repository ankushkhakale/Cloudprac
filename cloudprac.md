---
trigger: always_on
description: Always apply CloudPrac product, AWS safety, testing, and no-fabrication rules.
---

- Build CloudPrac for AWS CloudShell, AWS only, using Python and a CLI-first interface with an optional TUI.
- Read `goals.md`, `design.md`, `agent.md`, and `rules.md` before substantial changes.
- P01–P08 are placeholders until real practical instructions are supplied. Do not invent their names, resource operations, postconditions, or evidence requirements; prevent unconfigured modules from executing.
- Read-only commands must never mutate AWS resources. No cloud mutation during the initial scaffold.
- Require visible plans and confirmation for costly/destructive operations. Cleanup is separate and scoped to resources tracked in a run manifest.
- Use the current CloudShell identity; never hard-code credentials, dump environment variables, or log secrets.
- Unit tests use mocked AWS clients and must not create real resources. Integration tests are opt-in.
- Verify actual AWS state against explicit assignment requirements. Never fabricate a success or report a mock as a real AWS pass.
- Do not publish, push, or mutate AWS without explicit user approval. Report tests and limitations honestly.
