"""In-memory chat session controller for an eventual workspace interface."""
from dataclasses import dataclass, field
import secrets
import threading

from .orchestrator import Agent, Session
from .providers import ModelProvider, ProviderConfig, ProviderError
from .tools import PlanningTools, WorkspaceContext


class LocalPlanningClient:
    """Use the workspace planner in-process, without a self-directed HTTP request."""
    def plan(self, context, settings):
        from molvis.planning import create_plan
        from .tools import WorkspaceError
        payload = {'pdb': context.pdb, 'settings': settings, 'check_compatibility': False}
        if context.psf is not None:
            payload['psf'] = context.psf
        try:
            return create_plan(payload)
        except (ValueError, TypeError) as exc:
            raise WorkspaceError('invalid_request', str(exc)) from exc


@dataclass
class ChatSession:
    provider: object
    context: WorkspaceContext
    history: Session = field(default_factory=Session)
    lock: object = field(default_factory=threading.Lock)


class ChatController:
    """Keep credentials and sessions in memory; publish a token only after a probe passes."""
    def __init__(self, provider_factory=ModelProvider, client=None, max_sessions=16):
        self.provider_factory = provider_factory
        self.client = client or LocalPlanningClient()
        self.max_sessions = max_sessions
        self._sessions = {}
        self._lock = threading.Lock()

    def start(self, config: ProviderConfig, context: WorkspaceContext):
        if not isinstance(context.pdb, str) or not context.pdb.strip():
            raise ValueError('Load a PDB structure before starting a conversation.')
        provider = self.provider_factory(config)
        provider.check_compatibility()
        with self._lock:
            if len(self._sessions) >= self.max_sessions:
                raise ValueError('Too many active agent sessions. Close a session before starting another.')
            token = secrets.token_urlsafe(32)
            self._sessions[token] = ChatSession(provider, context)
        return token

    def turn(self, token, message):
        with self._lock:
            session = self._sessions.get(token)
        if session is None:
            raise ValueError('Agent session not found. Check the provider and start again.')
        if not session.lock.acquire(blocking=False):
            raise ValueError('An agent response is already in progress.')
        try:
            prior = len(session.history.messages)
            agent = Agent(session.provider, PlanningTools(self.client, session.context))
            try:
                result = agent.turn(session.history, message)
            except Exception:
                # Avoid retaining a partial tool exchange after a provider failure.
                del session.history.messages[prior:]
                raise
            observations = [item for item in session.history.messages[prior:] if item['role'] == 'tool']
            return {'status': result.status, 'text': result.text, 'observations': observations}
        finally:
            session.lock.release()

    def close(self, token):
        with self._lock:
            self._sessions.pop(token, None)
