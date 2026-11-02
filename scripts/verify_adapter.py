"""Exercise the packaged MCP transport on loopback, without a backend or Internet."""
import asyncio
import hashlib
import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
from dethrottled_version import __version__
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


async def verify(url, token, registry):
    headers = {"Authorization": "Bearer " + token}
    async with httpx.AsyncClient(base_url=url) as http:
        health = (await http.get('/health')).json()
        assert health['version'] == __version__
        assert health['sdk_version'] == '1.30.0'
        assert (await http.post('/mcp', json={})).status_code == 401
        async with streamablehttp_client(url + '/mcp', headers=headers) as (read, write, _):
            async with ClientSession(read, write) as client:
                init = await client.initialize()
                assert init.serverInfo.version == __version__, init.serverInfo
                assert init.instructions and 'read_document' in init.instructions
                listing = await client.list_tools()
                assert len(listing.tools) == 20
                drive = next(t for t in listing.tools if t.name == 'drive')
                assert all(s in json.dumps(drive.inputSchema) for s in
                           ['scroll', 'read_state', 'expand_details'])
                extra = await client.call_tool('capabilities', {'unexpected': True})
                assert extra.isError and 'extra' in str(extra.content).lower()
                private = await client.call_tool('fetch', {'urls': ['http://127.0.0.1/']})
                assert private.isError
                assert "public HTTP(S) URLs are required" in str(private.content)
        # Replacing the registry must revoke a previously accepted identity.
        replacement = registry.with_suffix('.new')
        replacement.write_text(json.dumps({'tokens': []}))
        replacement.replace(registry)
        revoked = await http.post('/mcp', headers=headers, json={})
        assert revoked.status_code == 401
        print(json.dumps({'passed': True, 'application_version': __version__,
                          'sdk_version': health['sdk_version'], 'tools': len(listing.tools),
                          'strict_arguments': True, 'private_targets_rejected': True,
                          'authentication_and_revocation': True}))


def main():
    with tempfile.TemporaryDirectory(prefix='adapter-verification-') as directory:
        root = Path(directory)
        token = secrets.token_urlsafe(32)
        registry = root / 'tokens.json'
        registry.write_text(json.dumps({'tokens': [{
            'sha256': hashlib.sha256(token.encode()).hexdigest(),
            'scopes': ['web', 'drive', 'corpus']}]}))
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        url = f'http://127.0.0.1:{port}'
        env = dict(os.environ, DETHROTTLED_TOKEN_REGISTRY=str(registry),
                   DETHROTTLED_ADMISSION_DB=str(root / 'admission.sqlite'),
                   MCP_BACKEND_URL='http://127.0.0.1:1',
                   MCP_ALLOWED_HOSTS='127.0.0.1:*,localhost:*')
        with (root / 'server.log').open('w+') as log:
            process = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'server:app',
                                        '--host', '127.0.0.1', '--port', str(port)],
                                       env=env, stdout=log, stderr=log)
            try:
                for _ in range(100):
                    try:
                        if httpx.get(url + '/health', timeout=1).status_code == 200:
                            break
                    except httpx.HTTPError:
                        pass
                    if process.poll() is not None:
                        raise RuntimeError('adapter exited before readiness')
                    time.sleep(.1)
                else:
                    raise RuntimeError('adapter readiness timeout')
                asyncio.run(verify(url, token, registry))
            except BaseException:
                log.seek(0)
                print(log.read(), file=sys.stderr)
                raise
            finally:
                process.terminate()
                process.wait(timeout=15)


if __name__ == '__main__':
    main()
