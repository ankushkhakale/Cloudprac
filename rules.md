# CloudPrac — Engineering & Safety Rules

## 1. AWS Safety & Zero-Fabrication Mandate
- **No Secret Exposure**: Never log, print, commit, or request AWS credentials, keys, or session tokens. Rely exclusively on the ambient CloudShell credential provider.
- **Ambient Identity**: Always assume the user's current CloudShell environment credentials. Verify with `sts:GetCallerIdentity` during preflight without storing secrets.
- **Zero Resource Mutation in Initial Scaffolds**: Do not perform any real AWS infrastructure operations during scaffolding or Milestones 0–4.
- **Never Fabricate Outcomes**: Do not forge mock outputs as real AWS verification passes. Clearly state when tests run in mock/dry-run mode versus live cloud.
- **Cost Awareness**: Display resource creation plans and cost impact before any mutation. Warn students when billable services are involved.
- **Preserve Existing Resources**: Never delete, modify, or overwrite pre-existing AWS resources that were not created and tagged by the active CloudPrac run.

## 2. Practical Placeholders (P01–P08)
- P01–P08 must remain visibly marked as `NOT CONFIGURED` until official assignments are provided.
- Do NOT invent imaginary practicals or arbitrary AWS architectures.
- The execution engine MUST reject any attempt to run an unconfigured practical.

## 3. Engineering & Python Standards
- Python 3 with clean type annotations.
- Typer for CLI arguments, options, and commands.
- Rich for beautiful, clean terminal presentation with tables, banners, and spinners.
- Pydantic or Python dataclasses for structured validation of plans, configurations, manifests, and reports.
- Pytest for test suite; 100% of unit tests must run offline with mocked AWS calls.
- Pure standard-library or lightweight dependencies compatible with AWS CloudShell's resource constraints.

## 4. Git & GitHub Repository Rules
- Keep local repository synchronized with GitHub remote `origin/main`.
- Use conventional commits (`feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `chore:`).
- Verify tests pass before committing.
- Do not push or publish without explicit confirmation.
