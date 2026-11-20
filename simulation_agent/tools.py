"""Narrow planning tools; structure data comes from trusted application context."""
from dataclasses import dataclass
from typing import Any, Mapping
import json
import math
import urllib.error
import urllib.request


@dataclass(frozen=True)
class WorkspaceContext:
    pdb: str
    psf: str | None = None


@dataclass(frozen=True)
class ToolResult:
    status: str
    data: Mapping[str, Any]

    def as_dict(self):
        return {'status': self.status, 'data': dict(self.data)}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class WorkspaceClient:
    """Call only the fixed loopback plan endpoint, without compatibility or execution."""
    def __init__(self, port: int = 8765, timeout: float = 10):
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            raise ValueError('port must be an integer from 1 to 65535')
        if timeout <= 0:
            raise ValueError('timeout must be positive')
        self.url = f'http://127.0.0.1:{port}/api/plan'
        self.timeout = timeout

    def plan(self, context: WorkspaceContext, settings: dict) -> dict:
        payload = {'pdb': context.pdb, 'settings': settings, 'check_compatibility': False}
        if context.psf is not None:
            payload['psf'] = context.psf
        request = urllib.request.Request(self.url, data=json.dumps(payload, allow_nan=False).encode(),
                                         headers={'Content-Type': 'application/json'}, method='POST')
        try:
            with urllib.request.build_opener(_NoRedirect()).open(request, timeout=self.timeout) as response:
                result = json.load(response)
        except urllib.error.HTTPError as exc:
            try:
                details = json.loads(exc.read(4096))
                error = details.get('error', 'Workspace rejected the request.')
                code = details.get('code', 'workspace_rejected')
                if not isinstance(code, str):
                    code = 'workspace_rejected'
            except (ValueError, AttributeError):
                error = 'Workspace rejected the request.'
                code = 'workspace_rejected'
            raise WorkspaceError(code, str(error)) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise WorkspaceError('workspace_unavailable', 'Could not reach the local workspace.') from exc
        except (ValueError, UnicodeError) as exc:
            raise WorkspaceError('invalid_workspace_response', 'Workspace returned an invalid response.') from exc
        if not isinstance(result, dict) or not isinstance(result.get('structure'), dict):
            raise WorkspaceError('invalid_workspace_response', 'Workspace returned an invalid plan.')
        return result


class WorkspaceError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


# Deliberately limited to settings already supported by planning. Chemistry, files,
# compatibility flags and arbitrary endpoint names cannot be supplied by a model.
ALLOWED_SETTINGS = {'temperature_k', 'duration_ps', 'equilibration_ps', 'timestep_fs',
                    'solvent_model', 'salt_molar', 'padding_nm'}


class PlanningTools:
    def __init__(self, client, context: WorkspaceContext):
        self.client = client
        self.context = context

    def call(self, name: str, arguments: Any) -> ToolResult:
        if name not in ('inspect_structure', 'propose_workflow'):
            return ToolResult('error', {'code': 'unknown_tool', 'message': 'Tool is not available.'})
        if not isinstance(arguments, dict):
            return ToolResult('error', {'code': 'invalid_arguments', 'message': 'Arguments must be an object.'})
        if name == 'inspect_structure':
            if arguments:
                return ToolResult('error', {'code': 'invalid_arguments', 'message': 'inspect_structure takes no arguments.'})
            settings = {}
        else:
            if set(arguments) - {'settings'} or not isinstance(arguments.get('settings', {}), dict):
                return ToolResult('error', {'code': 'invalid_arguments', 'message': 'Provide a settings object only.'})
            settings = arguments.get('settings', {})
            if set(settings) - ALLOWED_SETTINGS:
                return ToolResult('error', {'code': 'invalid_arguments', 'message': 'Unsupported setting.'})
            for key, value in settings.items():
                if key == 'solvent_model':
                    valid = value in ('deferred', 'vacuum', 'obc2', 'gbn2', 'charmm_tip3p') if isinstance(value, str) else False
                else:
                    valid = isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
                if not valid:
                    return ToolResult('error', {'code': 'invalid_arguments', 'message': f'Invalid value for {key}.'})
        try:
            plan = self.client.plan(self.context, settings)
        except WorkspaceError as exc:
            return ToolResult('error', {'code': exc.code, 'message': str(exc)})
        structure = plan['structure']
        summary = {k: structure.get(k) for k in ('atom_count', 'residue_count', 'chains', 'heterogens', 'sha256')}
        if name == 'inspect_structure':
            return ToolResult('ok', {'structure': summary,
                'note': 'Parsing does not establish structure completeness or scientific validity.'})
        return ToolResult('ok', {'structure': summary, 'settings': plan.get('settings'),
            'compatibility': plan.get('compatibility'), 'steps': plan.get('steps'),
            'decisions': plan.get('decisions'), 'run_information': plan.get('run_information'),
            'note': 'This is a proposal. Production execution is not connected; compatibility has not been checked.'})
