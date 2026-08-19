#!/usr/bin/env python3
"""Exercise non-blocking reset and stale-response suppression."""

import json
import os
from pathlib import Path
import sys
import tempfile
import time

from lsp_test_client import Client


MARKER = "codexStaleMarker"
MARKER_DESCRIPTION = "outstanding stale marker"
MARKER_URI = "file:///codex-stale-generation.nix"
MARKER_VERSION = "outstanding-stale-version"
PROMPT_TIMEOUT_SECONDS = 2


def workspace_configuration(client):
    return client.wait_for(
        lambda message: message.get("method") == "workspace/configuration"
    )


def configure(client, response):
    client.send({
        "jsonrpc": "2.0",
        "method": "workspace/didChangeConfiguration",
        "params": {"settings": {}},
    })
    request = workspace_configuration(client)
    client.send({
        "jsonrpc": "2.0",
        "id": request["id"],
        "result": response,
    })


def send_request(client, request_id, method, params):
    client.send({
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
        "params": params,
    })


def wait_response(client, request_id, timeout=10):
    return client.wait_for(
        lambda message: message.get("id") == request_id,
        timeout=timeout,
    )


def wait_for_path(path, description):
    deadline = time.monotonic() + 10
    while not path.exists():
        if time.monotonic() >= deadline:
            raise TimeoutError(f"timed out waiting for {description}: {path}")
        time.sleep(0.01)


def completion_params(uri):
    return {
        "textDocument": {"uri": uri},
        "position": {
            "line": 0,
            "character": len("with pkgs; [ codexStale"),
        },
        "context": {"triggerKind": 1},
    }


def assert_neutral(case, response):
    result = response["result"]
    encoded = json.dumps(result)
    if case == "hover":
        assert result is None, response
    elif case == "completion":
        assert not any(
            item.get("label") == MARKER for item in result["items"]
        ), response
    elif case == "resolve":
        assert MARKER_DESCRIPTION not in encoded, response
    elif case == "definition":
        assert MARKER_URI not in encoded, response
    elif case == "inlay":
        assert MARKER_VERSION not in encoded, response
    else:
        raise AssertionError(f"unknown case: {case}")


def exercise(case):
    with tempfile.TemporaryDirectory() as root:
        root_path = Path(root)
        ready_path = root_path / "response-ready"
        release_path = root_path / "release-response"
        full_uri = (root_path / "full.nix").as_uri()
        completion_uri = (root_path / "completion.nix").as_uri()
        full_text = f"with pkgs; {MARKER}"
        completion_text = "with pkgs; [ codexStale ]"

        if case == "hover" or case == "resolve":
            expression = (
                '{ codexStaleMarker.meta.description = "'
                f'{MARKER_DESCRIPTION}"; }}'
            )
        elif case == "definition":
            expression = (
                '{ codexStaleMarker.meta.position = '
                '"/codex-stale-generation.nix:7"; }'
            )
        elif case == "inlay":
            expression = (
                '{ codexStaleMarker.version = '
                f'"{MARKER_VERSION}"; }}'
            )
        elif case == "completion":
            expression = "{ codexStaleMarker = 1; }"
        else:
            raise AssertionError(f"unknown case: {case}")

        base = {"formatting": {"command": ["nixfmt"]}}
        override = {"nixpkgs": {"expr": expression}}
        proxy = Path(__file__).with_name("blocking-attrset-proxy.py")
        env = os.environ.copy()
        env["REAL_NIXD_ATTRSET_EVAL"] = env["NIXD_ATTRSET_EVAL"]
        env["NIXD_ATTRSET_EVAL"] = str(proxy)
        env["BLOCK_RPC_METHOD"] = (
            "attrset/attrpathComplete"
            if case == "completion"
            else "attrset/attrpathInfo"
        )
        env["BLOCK_READY_PATH"] = str(ready_path)
        env["BLOCK_RELEASE_PATH"] = str(release_path)
        client = Client(
            args=("--config=" + json.dumps(base, separators=(",", ":")),),
            cwd=root,
            env=env,
        )
        try:
            client.initialize(
                root_path=root,
                capabilities={"workspace": {"configuration": True}},
            )
            client.initialized()
            initial = workspace_configuration(client)
            client.send({
                "jsonrpc": "2.0",
                "id": initial["id"],
                "result": [override],
            })
            client.open_document(full_uri, full_text)
            client.open_document(completion_uri, completion_text)

            if case == "hover":
                method = "textDocument/hover"
                params = {
                    "textDocument": {"uri": full_uri},
                    "position": {"line": 0, "character": 15},
                }
            elif case == "completion":
                method = "textDocument/completion"
                params = completion_params(completion_uri)
            elif case == "resolve":
                send_request(
                    client,
                    50,
                    "textDocument/completion",
                    completion_params(completion_uri),
                )
                completion = wait_response(client, 50)
                items = [
                    item
                    for item in completion["result"]["items"]
                    if item.get("label") == MARKER
                ]
                assert len(items) == 1, completion
                method = "completionItem/resolve"
                params = items[0]
            elif case == "definition":
                method = "textDocument/definition"
                params = {
                    "textDocument": {"uri": full_uri},
                    "position": {"line": 0, "character": 15},
                }
            else:
                method = "textDocument/inlayHint"
                params = {
                    "textDocument": {"uri": full_uri},
                    "range": {
                        "start": {"line": 0, "character": 0},
                        "end": {"line": 0, "character": len(full_text)},
                    },
                }

            send_request(client, 100, method, params)
            wait_for_path(ready_path, "withheld attrset response")

            configure(client, [None])
            send_request(client, 101, method, params)
            prompt_response = None
            try:
                prompt_response = wait_response(
                    client, 101, timeout=PROMPT_TIMEOUT_SECONDS
                )
            except TimeoutError:
                pass

            release_path.write_text("release\n", encoding="utf-8")

            stale_response = wait_response(client, 100)
            if prompt_response is None:
                wait_response(client, 101)

            assert prompt_response is not None, (
                f"{case} reset/inactive request blocked behind old provider RPC"
            )
            assert_neutral(case, prompt_response)
            assert_neutral(case, stale_response)
        except Exception as error:
            release_path.write_text("release after failure\n", encoding="utf-8")
            stderr = client.close()
            print(f"{case} error: {error}", file=sys.stderr)
            print(f"received: {client.received}", file=sys.stderr)
            print(f"nixd stderr: {stderr}", file=sys.stderr)
            raise
        else:
            client.close()


def main():
    cases = tuple(sys.argv[1:]) or (
        "hover",
        "completion",
        "resolve",
        "definition",
        "inlay",
    )
    for case in cases:
        exercise(case)
        print(f"nixpkgs reset liveness passed: {case}")


if __name__ == "__main__":
    main()
