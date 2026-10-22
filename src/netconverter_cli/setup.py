"""Connection setup; credentials never enter workspace preferences."""
import hashlib
import json
from pathlib import Path
from .api import Client, DEFAULT_BASE
from .backend import open_client
from .credentials import get_secret, load_secret, save_secret
from .providers import Provider, ProviderError
from .workspace import Workspace, WorkspaceError


def account(server):
    return 'server:' + hashlib.sha256(server.rstrip('/').encode()).hexdigest()[:24]


def load_settings(root):
    w = Workspace(root)
    p = w._inside(w.state_dir / 'connection.json')
    if not p.exists():
        return {}
    data = json.loads(p.read_text())
    if set(data) - {'server', 'provider', 'model', 'auth'} or data.get('auth') not in (None, 'key', 'clerk'):
        raise WorkspaceError('Invalid connection settings')
    return data


def store_settings(root, settings):
    w = Workspace(root)
    w._inside(w.state_dir).mkdir(mode=0o700, exist_ok=True)
    w._atomic_replace(w.state_dir / 'connection.json', json.dumps(settings, indent=2).encode())


def connect_model(name, model, key=''):
    """Probe only synthetic intent; failure closes the candidate, not the old model."""
    if name == 'none':
        return None
    if name not in {'openai','anthropic','gemini','ollama'} or not model:
        raise ProviderError('configuration')
    if name != 'ollama':
        key = key.strip() or get_secret(name, prompt=False)
        if not key:
            raise ProviderError('missing_key')
    try:
        provider = Provider(name, (model or '').strip(), key)
    except ValueError:
        raise ProviderError('configuration') from None
    try:
        if provider.select('Find unused objects') != 'unused_objects':
            raise ProviderError('protocol')
    except BaseException:
        provider.close()
        raise
    return provider


def save_model(root, provider):
    settings = load_settings(root)
    settings.update(provider=provider.name if provider else None, model=provider.model if provider else None)
    store_settings(root, settings)
    if provider and provider.name != 'ollama':
        return save_secret(provider.name, provider.key)
    return True


class AccountSignIn:
    """The NetConverter account sign-in as first-run setup sees it (the cli's trust rules)."""

    def allowed(self, server):
        from . import cli
        return cli.clerk_allowed(server)

    def session(self):
        from . import cli
        return cli._clerk_session()

    def login(self):
        from .clerk import ClerkError, login
        try:
            login(notify=print)
        except ClerkError as exc:
            print(str(exc))
            return None
        return self.session()


def connect_credential(server, signin, ask, secret):
    """A stored key, the existing sign-in, or the user's choice of signing in or pasting a key."""
    # Keyring only: a key from the environment must neither skip the sign-in nor be copied into the keyring.
    saved = load_secret(account(server))
    if not saved and signin.allowed(server):
        session = signin.session()
        if session is not None:
            print('Using your NetConverter sign-in.')
            return session
        while True:
            choice = ask('Connect with 1 = your NetConverter account (browser sign-in), 2 = an API key [1]: ').strip() or '1'
            if choice in ('1', '2'):
                break
            print('Enter 1 or 2.')
        if choice == '1':
            session = signin.login()
            if session is None:
                raise ValueError('Sign-in did not complete; run `netconverter login --clerk` and try again')
            return session
    key = secret('NetConverter API key (hidden; paste here, then Enter; blank uses saved key): ').strip()
    key = key or saved
    if not key:
        raise ValueError('A server API key is required')
    return key


def configure(root, defaults=None, *, ask=None, secret=None, signin=None):
    import getpass
    from rich.console import Console
    from .branding import banner
    ask = ask or input
    secret = secret or getpass.getpass
    signin = signin or AccountSignIn()
    settings = {**load_settings(root), **(defaults or {})}
    Console().print(banner(Path(root).resolve()))
    print('\n1 / 2  Connect to NetConverter')
    print('Press Enter for the production URL. A key, if you use one, goes only in the hidden prompt.')
    while True:
        server = ask(f"Server URL [{settings.get('server') or DEFAULT_BASE}]: ").strip() or settings.get('server') or DEFAULT_BASE
        if server.startswith(('nck_', 'sk-')):
            print('That looks like an API key, not a URL. It was entered in a visible field; replace it if exposed. Press Enter below for the server address.')
            continue
        try:
            Client('', server).close()
            break
        except ValueError:
            print('Enter an HTTPS server URL, or press Enter to accept the displayed address.')
    credential = connect_credential(server, signin, ask, secret)
    client, kind = open_client(credential, server)
    print('Connected: ' + ('full API — every supported vendor' if kind == 'external'
                           else 'pilot key — ASA → Palo Alto'))
    if isinstance(credential, str):
        stored = save_secret(account(server), credential)
        print('Server key saved in OS credential store.' if stored else 'Credential store unavailable; server key is in memory for this session only.')
    else:
        print('Signed in with your NetConverter account; no key is stored.')
    provider = None
    try:
        print('\n2 / 2  Connect a model (optional)')
        print('A model chooses operations only. Configurations and detailed results stay out of model requests.')
        name_default = settings.get('provider') or 'none'
        while True:
            name = ask(f'Model provider: none / ollama / anthropic / openai / gemini [{name_default}]: ').strip().lower() or name_default
            if name not in {'none','ollama','anthropic','openai','gemini'}:
                print('Choose one of the listed providers.')
                continue
            if name == 'none':
                print('Guided commands selected. Use /model inside the terminal to connect later.')
                break
            model_default = settings.get('model') if name == settings.get('provider') else ''
            model = ask(f'Exact API model ID [{model_default or ""}]: ').strip() or model_default
            key = '' if name == 'ollama' else secret(f'{name} API key (hidden; blank uses saved key): ').strip()
            print('Testing a synthetic tool call…')
            try:
                provider = connect_model(name, model, key)
            except Exception as exc:
                print(str(exc) if isinstance(exc, ProviderError) else ProviderError.MESSAGES['protocol'])
                choice = ask('Retry model setup or continue without a model? [retry / guided]: ').strip().lower()
                if choice == 'guided':
                    print('Guided commands selected. Use /model to retry later.')
                    break
                name_default = name
                continue
            print(f'Model connected: {provider.name} / {provider.model}')
            break
        store_settings(root, {'server':server, 'provider':None, 'model':None})
        stored = save_model(root, provider)
        if not stored:
            print('Model key is in memory only; enter it again after restarting.')
        return client, provider
    except BaseException:
        client.close()
        if provider:
            provider.close()
        raise
