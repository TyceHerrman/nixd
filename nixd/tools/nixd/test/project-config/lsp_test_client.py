#!/usr/bin/env python3
"""Small predicate-based client for real nixd server behavior tests."""

import json
import os
import resource
import select
import subprocess
import time

TIMEOUT_SECONDS = 10


class Client:
    def __init__(self, *, args=(), cwd=None, env=None, fd_limit=None):
        def limit_open_files():
            _, hard_limit = resource.getrlimit(resource.RLIMIT_NOFILE)
            resource.setrlimit(
                resource.RLIMIT_NOFILE,
                (min(fd_limit, hard_limit), hard_limit),
            )

        self.proc = subprocess.Popen(
            ["nixd", *args],
            cwd=cwd,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
            preexec_fn=limit_open_files if fd_limit is not None else None,
        )
        self.received = []

    def send(self, message):
        payload = json.dumps(message, separators=(",", ":")).encode()
        self.proc.stdin.write(
            f"Content-Length: {len(payload)}\r\n\r\n".encode() + payload
        )
        self.proc.stdin.flush()

    def receive(self, timeout=TIMEOUT_SECONDS):
        deadline = time.monotonic() + timeout
        headers = {}
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("timed out while reading LSP headers")
            readable, _, _ = select.select([self.proc.stdout], [], [], remaining)
            if not readable:
                raise TimeoutError("timed out while reading LSP headers")
            line = self.proc.stdout.readline()
            if not line:
                raise RuntimeError("nixd closed its protocol stream")
            if line == b"\r\n":
                break
            key, value = line.decode().rstrip("\r\n").split(":", 1)
            headers[key.lower()] = value.strip()
        length = int(headers["content-length"])
        payload = bytearray()
        while len(payload) < length:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("timed out while reading an LSP payload")
            readable, _, _ = select.select([self.proc.stdout], [], [], remaining)
            if not readable:
                raise TimeoutError("timed out while reading an LSP payload")
            chunk = self.proc.stdout.read(length - len(payload))
            if not chunk:
                raise RuntimeError("nixd closed its protocol stream")
            payload.extend(chunk)
        message = json.loads(payload)
        self.received.append(message)
        return message

    def wait_for(self, predicate, timeout=TIMEOUT_SECONDS):
        deadline = time.monotonic() + timeout
        while True:
            message = self.receive(max(0, deadline - time.monotonic()))
            if predicate(message):
                return message
            if "id" in message and "method" in message:
                self.send({"jsonrpc": "2.0", "id": message["id"], "result": None})

    def assert_no_message(self, predicate, timeout=0.25):
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            readable, _, _ = select.select([self.proc.stdout], [], [], remaining)
            if not readable:
                return
            message = self.receive(remaining)
            if predicate(message):
                raise AssertionError(f"unexpected LSP message: {message}")
            if "id" in message and "method" in message:
                self.send({"jsonrpc": "2.0", "id": message["id"], "result": None})

    def read_stderr_until(self, predicate, timeout=TIMEOUT_SECONDS):
        deadline = time.monotonic() + timeout
        lines = []
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"stderr predicate not met; stderr={''.join(lines)!r}")
            readable, _, _ = select.select([self.proc.stderr], [], [], remaining)
            if not readable:
                raise TimeoutError(f"stderr predicate not met; stderr={''.join(lines)!r}")
            line = self.proc.stderr.readline().decode(errors="replace")
            if not line:
                raise RuntimeError(f"nixd closed stderr; stderr={''.join(lines)!r}")
            lines.append(line)
            if predicate("".join(lines)):
                return "".join(lines)

    def initialize(self, *, root_uri=None, root_path=None, capabilities=None):
        params = {
            "processId": os.getpid(),
            "capabilities": capabilities or {},
        }
        if root_uri is not None:
            params["rootUri"] = root_uri
        if root_path is not None:
            params["rootPath"] = root_path
        self.send({
            "jsonrpc": "2.0",
            "id": 0,
            "method": "initialize",
            "params": params,
        })
        return self.wait_for(lambda message: message.get("id") == 0)

    def initialized(self):
        self.send({"jsonrpc": "2.0", "method": "initialized", "params": {}})

    def open_document(self, uri, text):
        self.send({
            "jsonrpc": "2.0",
            "method": "textDocument/didOpen",
            "params": {"textDocument": {
                "uri": uri,
                "languageId": "nix",
                "version": 1,
                "text": text,
            }},
        })

    def formatting(self, request_id, uri):
        self.send({
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "textDocument/formatting",
            "params": {
                "textDocument": {"uri": uri},
                "options": {"tabSize": 2, "insertSpaces": True},
            },
        })
        return self.wait_for(lambda message: message.get("id") == request_id)

    def hover(self, request_id, uri, line=0, character=6):
        self.send({
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "textDocument/hover",
            "params": {
                "textDocument": {"uri": uri},
                "position": {"line": line, "character": character},
            },
        })
        return self.wait_for(lambda message: message.get("id") == request_id)

    def close(self):
        if self.proc.poll() is None:
            try:
                self.send({"jsonrpc": "2.0", "method": "exit"})
                self.proc.stdin.close()
            except (BrokenPipeError, OSError):
                pass
            try:
                self.proc.wait(timeout=TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=TIMEOUT_SECONDS)
        return self.proc.stderr.read().decode(errors="replace")
