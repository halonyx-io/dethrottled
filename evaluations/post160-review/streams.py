"""Real local HTTP download and WebSocket transfers during a concurrent rule change."""

import argparse
import asyncio
import base64
import hashlib
import json
import struct
import time
from urllib.parse import urlsplit

from dethrottled import adblock, adblock_proxy
from dethrottled.adblock_proxy import Gate


async def connection(gate):
    return await asyncio.open_connection("127.0.0.1", urlsplit(gate.url).port)


async def download():
    release = asyncio.Event()
    chunk = bytes(range(256)) * 256
    size = len(chunk) * 64

    async def origin(reader, writer):
        try:
            await reader.readuntil(b"\r\n\r\n")
            writer.write(f"HTTP/1.1 200 OK\r\nContent-Length: {size}\r\n\r\n".encode() + chunk)
            await writer.drain()
            await release.wait()
            for _ in range(63):
                writer.write(chunk)
                await writer.drain()
                await asyncio.sleep(0)
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        finally:
            writer.close()

    server = await asyncio.start_server(origin, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    direct = asyncio.open_connection
    adblock_proxy._connect = lambda host, ignored: direct("127.0.0.1", port)
    gate = Gate()
    await gate.start()
    started = time.perf_counter()
    try:
        reader, writer = await connection(gate)
        writer.write(b"GET http://content.example/file HTTP/1.1\r\nHost: content.example\r\n\r\n")
        await writer.drain()
        await reader.readuntil(b"\r\n\r\n")
        data = await reader.readexactly(len(chunk))
        adblock.FILTER.rules = frozenset({"content.example"})
        denied_reader, denied_writer = await connection(gate)
        denied_writer.write(
            b"CONNECT content.example:443 HTTP/1.1\r\nHost: content.example\r\n\r\n"
        )
        await denied_writer.drain()
        denial = await denied_reader.readuntil(b"\r\n\r\n")
        denied_writer.close()
        release.set()
        data += await asyncio.wait_for(reader.read(), 10)
        writer.close()
        return {
            "bytes_expected": size,
            "bytes_received": len(data),
            "hash_matches": hashlib.sha256(data).digest() == hashlib.sha256(chunk * 64).digest(),
            "new_connection_blocked": b" 451 " in denial,
            "seconds": time.perf_counter() - started,
        }
    finally:
        release.set()
        await gate.close()
        server.close()
        await server.wait_closed()


async def frame(reader):
    head = await reader.readexactly(2)
    length = head[1] & 127
    if length == 126:
        length = struct.unpack("!H", await reader.readexactly(2))[0]
    mask = await reader.readexactly(4) if head[1] & 128 else None
    payload = await reader.readexactly(length)
    return bytes(b ^ mask[i % 4] for i, b in enumerate(payload)) if mask else payload


async def websocket():
    async def origin(reader, writer):
        try:
            header = await reader.readuntil(b"\r\n\r\n")
            key = next(
                line.split(b":", 1)[1].strip()
                for line in header.split(b"\r\n")
                if line.lower().startswith(b"sec-websocket-key:")
            )
            accept = base64.b64encode(
                hashlib.sha1(key + b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11").digest()
            )
            writer.write(
                b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
                b"Connection: Upgrade\r\nSec-WebSocket-Accept: " + accept + b"\r\n\r\n"
            )
            await writer.drain()
            while True:
                payload = await frame(reader)
                writer.write(bytes([0x82, len(payload)]) + payload)
                await writer.drain()
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        finally:
            writer.close()

    server = await asyncio.start_server(origin, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    direct = asyncio.open_connection
    adblock_proxy._connect = lambda host, ignored: direct("127.0.0.1", port)
    gate = Gate()
    await gate.start()
    received = 0
    try:
        reader, writer = await connection(gate)
        writer.write(
            b"GET http://content.example/ws HTTP/1.1\r\nHost: content.example\r\n"
            b"Upgrade: websocket\r\nConnection: Upgrade\r\n"
            b"Sec-WebSocket-Version: 13\r\n"
            b"Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n\r\n"
        )
        await writer.drain()
        assert b" 101 " in await reader.readuntil(b"\r\n\r\n")
        for index in range(9):
            if index == 1:
                adblock.FILTER.rules = frozenset({"content.example"})
            payload = ("message-" + str(index)).encode()
            mask = b"ABCD"
            encoded = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
            writer.write(bytes([0x82, 128 + len(payload)]) + mask + encoded)
            await writer.drain()
            try:
                assert await asyncio.wait_for(frame(reader), 2) == payload
                received += 1
            except asyncio.IncompleteReadError:
                break
        writer.close()
        return {
            "frames_expected": 9,
            "frames_received": received,
            "post_update_frames_received": max(0, received - 1),
        }
    finally:
        await gate.close()
        server.close()
        await server.wait_closed()


async def run():
    adblock.FILTER = adblock.Filter()
    first = await download()
    adblock.FILTER.rules = frozenset()
    second = await websocket()
    return {"download": first, "websocket": second}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True)
    args = parser.parse_args()
    print(json.dumps({"label": args.label, **asyncio.run(run())}, indent=2))
