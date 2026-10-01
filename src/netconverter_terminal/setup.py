"""Interactive connection setup; only non-secret preferences enter the workspace."""
import hashlib
import json
from pathlib import Path
from .api import Client, DEFAULT_BASE
from .credentials import get_secret, save_secret
from .providers import Provider
from .workspace import Workspace, WorkspaceError


def account(server):
    return 'server:' + hashlib.sha256(server.rstrip('/').encode()).hexdigest()[:24]


def load_settings(root):
    w = Workspace(root)
    p = w._inside(w.state_dir / 'connection.json')
    if not p.exists():
        return {}
    data = json.loads(p.read_text())
    if set(data) - {'server', 'provider', 'model'}:
        raise WorkspaceError('Invalid connection settings')
    return data


def configure(root, defaults=None, *, ask=input, secret=None):
    import getpass
    secret = secret or getpass.getpass
    settings = {**load_settings(root), **(defaults or {})}
    from rich.console import Console
    from .branding import banner
    Console().print(banner(Path(root).resolve()))
    print('Connection setup')
    print('Configuration files go directly to NetConverter. Model requests contain restricted intent only.')
    server = ask(f"NetConverter API URL [{settings.get('server', DEFAULT_BASE)}]: ").strip() or settings.get('server', DEFAULT_BASE)
    # Validate URL before asking for a credential. Never follow redirects.
    Client('', server).close()
    key = secret('NetConverter API key (hidden; blank uses saved key for this server): ').strip()
    key = key or get_secret(account(server), prompt=False)
    if not key:
        raise ValueError('A server API key is required')
    client = Client(key, server)
    try:
        caps = client.capabilities()
    except Exception:
        client.close()
        raise
    print(f"Connected: {caps['profile']} · remaining allowance: {caps.get('remaining', {})}")
    stored = save_secret(account(server), key)
    print('Server key saved in OS credential store.' if stored else 'OS credential store unavailable; key is held in memory for this session only.')
    provider = None
    try:
        name = ask(f"Model provider: none / ollama / anthropic / openai / gemini [{settings.get('provider') or 'none'}]: ").strip().lower() or settings.get('provider') or 'none'
        model = None
        if name != 'none':
            model = ask(f"Model name [{settings.get('model') or ''}]: ").strip() or settings.get('model')
            model_key = '' if name == 'ollama' else (secret(f'{name} API key (hidden; blank uses saved key): ').strip() or get_secret(name, prompt=False))
            provider = Provider(name, model, model_key)
            print('Testing the model tool protocol with a synthetic question…')
            try:
                compatible = provider.select('Find unused objects') == 'unused_objects'
            except Exception:
                compatible = False
            if not compatible:
                print('Model compatibility test failed. Guided conversion remains available; rerun setup to change the model.')
                provider.close()
                provider = None
                name, model = 'none', None
            elif name != 'ollama':
                save_secret(name, model_key)
            else:
                print('Local model connected; no hosted fallback.')
        w = Workspace(root)
        w._inside(w.state_dir).mkdir(mode=0o700, exist_ok=True)
        w._atomic_replace(w.state_dir / 'connection.json', json.dumps({'server': server, 'provider': None if name == 'none' else name, 'model': model}, indent=2).encode())
        return client, provider
    except BaseException:
        client.close()
        if provider:
            provider.close()
        raise
