#!/usr/bin/env python3
"""Request/response-synchronous LSP client for the editor overlay boundary."""

import json
import select
import subprocess
import sys
import time

TIMEOUT_SECONDS = 10


class Client:
    def __init__(self):
        config = {"formatting": {"command": ["sh", "-c", "printf cli"]}}
        self.proc = subprocess.Popen(
            ["nixd", "-config=" + json.dumps(config, separators=(",", ":"))],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            bufsize=0,
        )
        self.received = []

    def send(self, message):
        payload = json.dumps(message, separators=(",", ":")).encode()
        self.proc.stdin.write(
            f"Content-Length: {len(payload)}\r\n\r\n".encode() + payload
        )
        self.proc.stdin.flush()

    def receive(self):
        deadline = time.monotonic() + TIMEOUT_SECONDS
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

    def wait_for(self, predicate):
        while True:
            message = self.receive()
            if predicate(message):
                return message
            if "id" in message and "method" in message:
                self.send({"jsonrpc": "2.0", "id": message["id"], "result": None})

    def workspace_configuration(self):
        return self.wait_for(
            lambda message: message.get("method") == "workspace/configuration"
        )

    def close(self):
        if self.proc.poll() is None:
            self.send({"jsonrpc": "2.0", "method": "exit"})
            self.proc.stdin.close()
            try:
                self.proc.wait(timeout=TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        return self.proc.stderr.read().decode(errors="replace")


def formatting_params(request_id):
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "textDocument/formatting",
        "params": {
            "textDocument": {"uri": "file:///interactive-overlay.nix"},
            "options": {"tabSize": 2, "insertSpaces": True},
        },
    }


def main():
    client = Client()
    try:
        client.send({
            "jsonrpc": "2.0", "id": 0, "method": "initialize",
            "params": {
                "processId": 123, "rootPath": "",
                "capabilities": {"workspace": {"configuration": True}},
            },
        })
        client.wait_for(lambda message: message.get("id") == 0)
        client.send({"jsonrpc": "2.0", "method": "initialized", "params": {}})
        initial = client.workspace_configuration()
        client.send({"jsonrpc": "2.0", "id": initial["id"], "result": [None]})
        client.send({
            "jsonrpc": "2.0", "method": "textDocument/didOpen",
            "params": {"textDocument": {
                "uri": "file:///interactive-overlay.nix", "languageId": "nix",
                "version": 1, "text": "{ x = 1; }",
            }},
        })
        client.send({
            "jsonrpc": "2.0", "method": "workspace/didChangeConfiguration",
            "params": {"settings": {}},
        })
        override = client.workspace_configuration()
        client.send({
            "jsonrpc": "2.0", "id": override["id"],
            "result": [{"formatting": {"command": ["sh", "-c", "printf editor"]}}],
        })
        client.send(formatting_params(100))
        editor = client.wait_for(lambda message: message.get("id") == 100)
        assert editor["result"][0]["newText"] == "editor"
        client.send({
            "jsonrpc": "2.0", "method": "workspace/didChangeConfiguration",
            "params": {"settings": {}},
        })
        reset = client.workspace_configuration()
        client.send({"jsonrpc": "2.0", "id": reset["id"], "result": [None]})
        client.send(formatting_params(101))
        reset_reply = client.wait_for(lambda message: message.get("id") == 101)
        assert reset_reply["result"][0]["newText"] == "cli"
        print("interactive [null] reset: cli")
    except Exception as error:
        stderr = client.close()
        print(f"error: {error}", file=sys.stderr)
        print(f"received: {client.received}", file=sys.stderr)
        print(f"nixd stderr: {stderr}", file=sys.stderr)
        raise
    else:
        client.close()


if __name__ == "__main__":
    main()
