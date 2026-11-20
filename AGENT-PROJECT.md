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
- 2026-11-20: Added user-configured OpenAI-compatible and Anthropic adapters and a command-line preview. A model must pass a tool-call and tool-result probe before the adapter permits planning; changing its configuration requires another check. Tests use mocked providers; no live model has been verified.
- 2026-11-20: Added a tested in-memory chat session controller for a future workspace panel. Sessions are created only after the provider probe succeeds; observations are available to the interface, and failed turns roll back their partial history.
- 2026-11-20: Connected the controller to local HTTP endpoints for starting, using, and closing a session. API keys are read from the server's environment, and agent requests require the local Origin and JSON content. Socketless endpoint tests pass; the browser panel and live integration remain outstanding.
- 2026-11-20: Added an experimental workspace panel for provider configuration, model checks, planning conversations and tool observations. Changing provider details or prepared structure disconnects the session. The user will check the visual result locally; live provider and browser integration remain unverified.
- 2026-11-20: Moved the assistant panel to the top of the full workspace, above the simulation setup. Connecting still requires a prepared structure; the guided example keeps its existing focused layout.

## To do

- [x] Review and integrate the framework robustness work.
- [x] Review and integrate the initial agent layer.
- [x] Verify the initial adapter contract with deterministic tests; record the socket-testing limitation below.
- [ ] Verify provider adapters with live accounts and evaluate end-to-end planning conversations across models. A basic tool protocol check is not a scientific evaluation.
- [ ] Design and implement persistent session/decision records and invalidation when inputs change.
- [ ] Expand evaluation cases to cover missing files, changed settings, failed checks and unsupported requests.
- [ ] Connect bounded readiness execution only after prerequisites and execution controls are tested.
- [ ] Verify the workspace chat interface and a real provider end to end, and create an evidence-based portfolio demonstration after the core workflow is validated.
- [ ] Run the workspace outside the restricted socket environment and capture and inspect the required fresh README screenshot when the visible interface changes.

## Validation and limitations

The six agent tests and three API error tests pass. Full discovery ran 64 tests with 12 optional-dependency skips and one server test-class setup error: the sandbox denies the local socket bind. This same error occurred in the baseline before integration.

After adding providers and the session controller, all 15 agent tests and four socketless agent API tests pass using mock providers. The current sandbox still rejects the server's local socket bind, preventing a running-app screenshot.

The provider adapters have only been tested with mocked responses. The agent has no persistent session, scientific compatibility tool, or execution tool yet. The new workspace panel has not been visually or end-to-end verified. Its final model prose is not automatically verified. Workspace adapter tests use a mocked HTTP transport against the real planning function. The sandbox prevents binding a local socket, so live HTTP integration remains unverified here. The existing workspace supports bounded readiness testing, not production execution; the longest documented protein dynamics test is a single 4 ps ubiquitin readiness run. See [the workspace README](README.md) for the current scientific and operational limitations.
