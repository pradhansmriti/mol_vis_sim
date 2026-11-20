# Simulation agent project

## Goal

Build an evidence-grounded assistant that helps a researcher move from a natural-language simulation goal to a reviewable plan, supported checks and bounded readiness tests. The workspace remains responsible for validating inputs and executing simulations. A completed readiness test does not establish equilibration or production readiness.

## Initial decisions

- Keep the agent in a separate Python package in this repository while its interface with the workspace evolves. Reconsider a separate repository when the interface is stable and independent use justifies it.
- Expose constrained, typed tools and structured observations. Do not execute model-generated shell commands or simulation scripts.
- Preserve user choices, surface assumptions and missing inputs, and record evidence and artifact identifiers. Scientific choices require user review where the workspace cannot infer them.
- Begin with a mockable model interface and a narrow, testable workflow. Add model providers and execution capabilities only as their contracts and checks are verified.
- Work on framework robustness and the agent layer independently, then integrate and test them together.

## Progress

- 2026-11-20: Established two isolated worktrees from commit `7b529e0` for framework robustness and the initial agent layer. Integration and this record are maintained in the main workspace.
- 2026-11-20: Integrated a provider-neutral, bounded tool loop with in-memory conversation history and inspect/plan tools. The local workspace adapter returns structured observations, excludes atom coordinates from model observations, and does not run compatibility checks or simulations. See [agent documentation](simulation_agent/README.md).
- 2026-11-20: Added strict JSON number handling and machine-readable codes for selected API errors, preserving the existing `error` field. See [the API error contract](docs/api-errors.md). The agent adapter passes these codes through.

## To do

- [x] Review and integrate the framework robustness work.
- [x] Review and integrate the initial agent layer.
- [x] Verify the initial adapter contract with deterministic tests; record the socket-testing limitation below.
- [ ] Implement and evaluate a real model provider and an end-to-end user interaction.
- [ ] Design and implement persistent session/decision records and invalidation when inputs change.
- [ ] Expand evaluation cases to cover missing files, changed settings, failed checks and unsupported requests.
- [ ] Connect bounded readiness execution only after prerequisites and execution controls are tested.
- [ ] Add a workspace interface and an evidence-based portfolio demonstration after the core workflow is validated.

## Validation and limitations

The six agent tests and three API error tests pass. Full discovery ran 64 tests with 12 optional-dependency skips and one server test-class setup error: the sandbox denies the local socket bind. This same error occurred in the baseline before integration.

The agent has no real model provider, persistent session, compatibility tool, execution tool, or chat interface yet. Its final model prose is not automatically verified. Adapter tests use a mocked HTTP transport against the real planning function. The sandbox prevents binding a local socket, so live HTTP integration remains unverified here. The existing workspace supports bounded readiness testing, not production execution; the longest documented protein dynamics test is a single 4 ps ubiquitin readiness run. See [the workspace README](README.md) for the current scientific and operational limitations.
