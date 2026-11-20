# Simulation agent: planning foundation

This is an experimental, provider-independent tool loop for inspecting the active structure and proposing a workflow through the existing local workspace API. It does **not** yet include a model provider, chat interface, persistent session storage, compatibility checks, or simulation execution. A plan is not scientific validation. Production dynamics remain unavailable.

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
