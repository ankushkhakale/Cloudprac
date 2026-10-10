# CloudPrac Workspace Instructions

This workspace builds CloudPrac, a Python CLI/TUI that will run eight college Cloud Computing practicals on AWS CloudShell. Read and follow `goals.md`, `design.md`, `agent.md`, and `rules.md` before planning or editing code. `PROMPT.md` contains the initial implementation prompt.

The eight practical instructions have not been supplied yet. Do not invent them. P01–P08 must remain visibly `NOT CONFIGURED` and non-executable until the user provides the exact requirements.

First milestone: create a lightweight package and CLI foundation, safe inspection/preflight, registry slots, state/log/report path handling, and unit tests with mocked AWS clients. Do not create, modify, or delete AWS resources in this milestone. Do not publish packages, push repositories, or run real cloud operations without explicit user approval.

Follow the security, cost, verification, and testing requirements in `rules.md`. Prefer small, testable changes and report the exact checks you ran.
