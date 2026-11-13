"""Private, optional proxy transport settings for invoice browser sessions."""
import json
import os
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

PROXY_FILE = Path(__file__).resolve().parent.parent / '.local' / 'invoice-proxy.json'


def parse_proxy_url(value):
    """Accept a standard authenticated URL or Evomi's host-first format."""
    value = value.strip().replace('\\://', '://')
    if '://' not in value:
        value = 'http://' + value
    parsed = urlsplit(value)
    if parsed.scheme not in {'http', 'https', 'socks5'} or parsed.path not in {'', '/'} or parsed.query or parsed.fragment:
        raise ValueError('Invalid proxy configuration. Use a proxy URL without a path, query, or fragment.')
    if '@' not in parsed.netloc and parsed.netloc.count(':') >= 3:
        host, port, username, password = parsed.netloc.split(':', 3)
        server = f'{parsed.scheme}://{host}:{port}'
    else:
        host, port = parsed.hostname, parsed.port
        username, password = parsed.username, parsed.password
        server = f'{parsed.scheme}://{host}:{port}'
    if not host or not str(port).isdigit() or not 1 <= int(port) <= 65535:
        raise ValueError('Invalid proxy host or port.')
    result = {'server': server}
    if username is not None:
        result['username'] = unquote(username)
        result['password'] = unquote(password or '')
    return result


def load_proxy_settings():
    # An explicitly empty environment override disables the local configuration.
    if 'INVOICE_PROXY_URL' in os.environ:
        value = os.environ['INVOICE_PROXY_URL'].strip()
        return parse_proxy_url(value) if value else None
    if not PROXY_FILE.is_file():
        return None
    config = json.loads(PROXY_FILE.read_text(encoding='utf-8'))
    server = urlsplit(config['server'])
    if server.username or server.password:
        raise ValueError('Store proxy authentication in separate username/password settings.')
    result = parse_proxy_url(config['server'])
    result['username'] = config['username']
    result['password'] = config['password']
    session = config.get('evomi_locked_session')
    if session:
        if not re.fullmatch(r'[A-Za-z0-9]{6,10}', session):
            raise ValueError('Evomi session must have 6 to 10 alphanumeric characters.')
        if not server.hostname or not server.hostname.endswith('.evomi.com'):
            raise ValueError('Evomi session settings require an Evomi proxy host.')
        if re.search(r'_(?:session|hardsession|lockedsession)-', result['password']):
            raise ValueError('Configure the Evomi session once, not in both password and session setting.')
        result['password'] += '_lockedsession-' + session
    return result
