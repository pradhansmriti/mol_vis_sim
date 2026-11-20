# Simulation agent: planning foundation

This is an experimental tool loop for inspecting the active structure and proposing a workflow through the existing local workspace API. It supports OpenAI, OpenRouter, Anthropic and custom OpenAI-compatible endpoints. It does **not** yet include a workspace chat panel, persistent session storage, scientific compatibility checks, or simulation execution. A plan is not scientific validation. Production dynamics remain unavailable.

`WorkspaceContext` is supplied by the application, not the model: the model cannot choose file paths or replace the active PDB/PSF. `PlanningTools` exposes only `inspect_structure` and `propose_workflow`; it rejects other tools and settings. The adapter sends requests only to `http://127.0.0.1:<port>/api/plan` and disables compatibility checks. The workspace supplies defaults for omitted settings; the returned settings must be presented as a proposal and reviewed, not assumed to be the user's choices. Explicit water currently adds no ions or neutralization.

The agent returns structured observations with structure counts, hashes, plan settings, decisions, and compatibility status, omitting atom coordinates. Parsing does not establish structure completeness. No generated scripts or arbitrary commands are executed. `Agent` caps tool calls per turn and records messages and results in the in-memory `Session`.

## Integration

Start the workspace as described in the main README. Application code constructs a `WorkspaceContext(pdb=..., psf=...)`, a `PlanningTools(WorkspaceClient(port=8765), context)`, and an `Agent(provider, tools)`. Supply a provider implementing `respond(system=..., messages=..., tools=...)` that returns a `ModelResponse`; tool calls use `ToolCall(id, name, arguments)`. Invoke `agent.turn(session, user_text)`. The provider must translate the neutral message/tool format to its own API and treat tool observations as untrusted data. This package deliberately sends no PDB coordinates or PSF contents to the provider, although the user text and summary observations are sent through it. Do not connect sensitive requests to an external provider without making that data flow clear to users.

The current session is held in memory only. Provider exceptions propagate to the caller; applications should surface them and decide whether to retry. This foundation does not enforce the truth of the model's final prose; applications need evaluation and user-visible evidence before relying on its explanations.

Run the deterministic tests without a model, network, or OpenMM:

```sh
python3 -m unittest discover -s tests/agent -v
```

The adapter test exercises the actual planning function with a mocked HTTP transport. It is not a live socket integration test.

## Try the command-line preview

Start the workspace server following the main README, then set the relevant environment variable (`OPENAI_API_KEY`, `OPENROUTER_API_KEY`, `ANTHROPIC_API_KEY`, or, optionally for custom endpoints, `SIMULATION_AGENT_API_KEY`). Do not put credentials in command arguments. For example:

```sh
python3 -m simulation_agent --provider openrouter --model PROVIDER/MODEL --pdb /path/to/structure.pdb
```

For a custom OpenAI-compatible endpoint use `--provider custom --base-url http://localhost:11434/v1 --model MODEL`. Remote endpoints require HTTPS; local loopback endpoints may use HTTP. Add `--psf /path/to/prepared.psf` when applicable. Type `/quit` to exit. The CLI holds the session only in memory and prints the agent's response; structured tool observations remain available in the session for application integration.

Before allowing a conversation, the adapter sends a small test request to the chosen provider and checks a tool call and a subsequent tool-result response. Failure blocks the session; changing provider configuration requires a new check. This tests a basic protocol round trip, not the model's scientific accuracy or reliability. The probe can incur provider charges. User messages and structure summaries are sent to the configured endpoint; PDB coordinates and PSF contents are not sent to the model provider. No live provider has yet been verified in this environment.
