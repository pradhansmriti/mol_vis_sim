"""Small local CLI for trying the agent before a workspace chat interface exists."""
import argparse
import os
import sys
from pathlib import Path

from .orchestrator import Agent, Session
from .providers import ModelProvider, ProviderConfig, ProviderError
from .tools import PlanningTools, WorkspaceClient, WorkspaceContext


def main():
    parser = argparse.ArgumentParser(description='Check your model and chat with the planning agent.')
    parser.add_argument('--provider', choices=['openai', 'openrouter', 'anthropic', 'custom'], required=True)
    parser.add_argument('--model', required=True)
    parser.add_argument('--base-url', default='', help='Custom OpenAI-compatible API base URL, including /v1 if needed')
    parser.add_argument('--pdb', required=True, help='Local PDB file')
    parser.add_argument('--psf', help='Optional matching local PSF file')
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    key_env = {'openai': 'OPENAI_API_KEY', 'openrouter': 'OPENROUTER_API_KEY',
               'anthropic': 'ANTHROPIC_API_KEY', 'custom': 'SIMULATION_AGENT_API_KEY'}[args.provider]
    try:
        config = ProviderConfig(args.provider, args.model, os.environ.get(key_env, ''), args.base_url)
        context = WorkspaceContext(Path(args.pdb).read_text(), Path(args.psf).read_text() if args.psf else None)
        provider = ModelProvider(config)
        print(f'Checking tool support at {config.endpoint} with model {config.model}. This sends a test request to the provider.', flush=True)
        provider.check_compatibility()
        print('Tool check passed. Messages and structure summaries will be sent to this endpoint. Type /quit to exit.')
        agent = Agent(provider, PlanningTools(WorkspaceClient(args.port), context))
        session = Session()
        while True:
            try:
                prompt = input('\nYou: ')
            except EOFError:
                break
            if prompt.strip() == '/quit':
                break
            if not prompt.strip():
                continue
            result = agent.turn(session, prompt)
            print(f'Agent: {result.text}')
    except (ProviderError, ValueError, OSError) as exc:
        print(f'Cannot continue: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
