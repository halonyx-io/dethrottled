"""Actual local sockets: byte-preserving tunnels, refusals, chaining and cleanup."""

import asyncio

import pytest

from dethrottled import adblock, adblock_proxy
from dethrottled.adblock_proxy import Gate


@pytest.fixture(autouse=True)
def policy(tmp_path, monkeypatch):
    monkeypatch.setenv("DETHROTTLED_ADBLOCK", "1")
    manager = adblock.Filter(tmp_path)
    manager.rules = frozenset({"ads.example"})
    monkeypatch.setattr(adblock, "FILTER", manager)
    monkeypatch.setattr(manager, "start", lambda: None)
    return manager


async def connect(gate, host):
    port = gate.server.sockets[0].getsockname()[1]
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(("CONNECT " + host + " HTTP/1.1\r\nHost: " + host + "\r\n\r\n").encode())
    await writer.drain()
    response = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 2)
    return reader, writer, response


def test_blocked_connect_never_resolves_or_dials(monkeypatch):
    async def run():
        async def forbidden(*args):
            pytest.fail("blocked origin dialled")

        monkeypatch.setattr(adblock_proxy, "_connect", forbidden)
        gate = Gate()
        await gate.start()
        try:
            reader, writer, response = await connect(gate, "sub.ads.example:443")
            assert response.startswith(b"HTTP/1.1 451")
            assert b"adblock_blocked:ads.example" in await reader.read()
            writer.close()
            assert len(gate.events) == 1
        finally:
            await gate.close()

    asyncio.run(run())


def test_tunnel_preserves_bytes_across_update_and_blocks_new_connect(policy, monkeypatch):
    async def run():
        received = []

        async def echo(reader, writer):
            try:
                while chunk := await reader.read(65536):
                    received.append(chunk)
                    writer.write(chunk)
                    await writer.drain()
            finally:
                writer.close()

        server = await asyncio.start_server(echo, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        original = asyncio.open_connection

        async def local(host, port):
            return await original("127.0.0.1", port)

        monkeypatch.setattr(adblock_proxy, "_connect", local)
        gate = Gate()
        await gate.start()
        try:
            reader, writer, response = await connect(gate, "content.example:" + str(port))
            assert b" 200 " in response
            payload = bytes(range(256)) * 100
            writer.write(payload)
            await writer.drain()
            assert await reader.readexactly(len(payload)) == payload
            policy.rules = frozenset({"content.example"})
            writer.write(b"admitted stream survives update")
            await writer.drain()
            assert await reader.readexactly(31) == b"admitted stream survives update"
            denied_reader, denied_writer, denial = await connect(
                gate, "content.example:" + str(port))
            assert b" 451 " in denial
            denied_writer.close()
            writer.close()
        finally:
            await gate.close()
            server.close()
            await server.wait_closed()

    asyncio.run(run())


def test_upstream_refusal_is_preserved_without_direct_retry(monkeypatch):
    async def run():
        requests, dials = [], []

        async def upstream(reader, writer):
            requests.append(await reader.readuntil(b"\r\n\r\n"))
            writer.write(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n")
            await writer.drain()
            writer.close()

        server = await asyncio.start_server(upstream, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        original = asyncio.open_connection

        async def dial(host, port):
            dials.append((host, port))
            return await original(host, port)

        monkeypatch.setattr(adblock_proxy, "_connect", dial)
        gate = Gate({"server": f"http://127.0.0.1:{port}"})
        await gate.start()
        try:
            reader, writer, response = await connect(gate, "content.example:443")
            assert b"403 Forbidden" in response
            assert dials == [("127.0.0.1", port)]
            assert requests[0].startswith(b"CONNECT content.example:443")
            writer.close()
        finally:
            await gate.close()
            server.close()
            await server.wait_closed()

    asyncio.run(run())


def test_closing_context_gate_cancels_waiting_connections():
    async def run():
        gate = Gate()
        await gate.start()
        reader, writer = await asyncio.open_connection(
            "127.0.0.1", gate.server.sockets[0].getsockname()[1]
        )
        await asyncio.sleep(0.01)
        await asyncio.wait_for(gate.close(), 2)
        assert not gate.tasks and not gate.writers
        assert await reader.read() == b""
        writer.close()

    asyncio.run(run())


def test_unsupported_upstream_proxy_is_explicit():
    with pytest.raises(ValueError, match="adblock_upstream_proxy_requires_http"):
        Gate({"server": "socks5://proxy.example:1080"})


def test_plain_http_post_preserves_body_and_rejects_invalid_target():
    async def run():
        observed = []

        async def origin(reader, writer):
            headers = await reader.readuntil(b"\r\n\r\n")
            body = await reader.readexactly(7)
            observed.append((headers, body))
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 7\r\n\r\n" + body)
            await writer.drain()
            writer.close()

        server = await asyncio.start_server(origin, "127.0.0.1", 0)
        gate = Gate()
        await gate.start()
        try:
            reader, writer = await asyncio.open_connection(
                "127.0.0.1", gate.server.sockets[0].getsockname()[1]
            )
            port = server.sockets[0].getsockname()[1]
            writer.write(
                (
                    f"POST http://127.0.0.1:{port}/form?q=1 HTTP/1.1\r\n"
                    "Host: localhost\r\nContent-Length: 7\r\n\r\nkey=123"
                ).encode()
            )
            await writer.drain()
            assert (await asyncio.wait_for(reader.read(), 2)).endswith(b"key=123")
            assert observed[0][0].startswith(b"POST /form?q=1 HTTP/1.1")
            assert observed[0][1] == b"key=123"
            writer.close()
            reader, writer, response = await connect(gate, "user@content.example:443")
            assert b"400 Bad Request" in response
            assert b"X-Dethrottled-Blocked" not in response
            writer.close()
        finally:
            await gate.close()
            server.close()
            await server.wait_closed()

    asyncio.run(run())


def test_large_download_and_websocket_survive_refresh_but_new_connections_refuse(monkeypatch):
    import importlib.util
    from pathlib import Path
    path = Path(__file__).resolve().parents[1] / 'evaluations/post160-review/streams.py'
    spec = importlib.util.spec_from_file_location('stream_regressions', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(adblock, 'FILTER', adblock.Filter())
    monkeypatch.setattr(adblock_proxy, '_connect', adblock_proxy._connect)
    result = asyncio.run(module.run())
    assert result['download']['hash_matches']
    assert result['download']['bytes_received'] == 4194304
    assert result['download']['new_connection_blocked']
    assert result['websocket']['frames_received'] == 9


def test_redirect_target_new_connection_observes_updated_rules(policy, monkeypatch):
    async def run():
        dials = []
        async def origin(reader, writer):
            await reader.readuntil(b'\r\n\r\n')
            writer.write(b'HTTP/1.1 302 Found\r\nLocation: https://newblocked.example/\r\n'
                         b'Content-Length: 0\r\n\r\n')
            await writer.drain()
            writer.close()
        server = await asyncio.start_server(origin, '127.0.0.1', 0)
        port = server.sockets[0].getsockname()[1]
        original = asyncio.open_connection
        async def local(host, _):
            dials.append(host)
            return await original('127.0.0.1', port)
        monkeypatch.setattr(adblock_proxy, '_connect', local)
        gate = Gate()
        await gate.start()
        try:
            reader, writer = await original('127.0.0.1', gate.server.sockets[0].getsockname()[1])
            writer.write(b'GET http://content.example/ HTTP/1.1\r\nHost: content.example\r\n\r\n')
            await writer.drain()
            assert b'Location: https://newblocked.example/' in await reader.readuntil(b'\r\n\r\n')
            writer.close()
            policy.rules = frozenset({'newblocked.example'})
            _, rejected, response = await connect(gate, 'newblocked.example:443')
            assert b' 451 ' in response and dials == ['content.example']
            rejected.close()
        finally:
            await gate.close()
            server.close()
            await server.wait_closed()
    asyncio.run(run())
