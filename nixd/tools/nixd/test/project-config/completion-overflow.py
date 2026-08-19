#!/usr/bin/env python3
"""Exercise completion overflow preservation across provider generations."""

import json
import os
from pathlib import Path
import sys
import tempfile
import time

from lsp_test_client import Client


STATIC_PREFIX = "overflowStatic"
PROVIDER_PREFIX = "overflowProvider"
QUERY_PREFIX = "overflow"
EXPECTED_STATIC_LABELS = [
    "overflowStatic00",
    "overflowStatic01",
    "overflowStatic02",
    "overflowStatic03",
    "overflowStatic04",
    "overflowStatic05",
    "overflowStatic06",
    "overflowStatic07",
    "overflowStatic08",
    "overflowStatic09",
    "overflowStatic10",
    "overflowStatic11",
    "overflowStatic12",
    "overflowStatic13",
    "overflowStatic14",
    "overflowStatic15",
    "overflowStatic16",
    "overflowStatic17",
    "overflowStatic18",
    "overflowStatic19",
    "overflowStatic20",
    "overflowStatic21",
    "overflowStatic22",
    "overflowStatic23",
    "overflowStatic24",
    "overflowStatic25",
    "overflowStatic26",
    "overflowStatic27",
    "overflowStatic28",
    "overflowStatic29",
]
EXPECTED_PROVIDER_LABELS = [
    "overflowProvider00",
    "overflowProvider01",
    "overflowProvider02",
    "overflowProvider03",
    "overflowProvider04",
    "overflowProvider05",
    "overflowProvider06",
    "overflowProvider07",
    "overflowProvider08",
    "overflowProvider09",
    "overflowProvider10",
    "overflowProvider11",
    "overflowProvider12",
    "overflowProvider13",
    "overflowProvider14",
    "overflowProvider15",
    "overflowProvider16",
    "overflowProvider17",
    "overflowProvider18",
    "overflowProvider19",
    "overflowProvider20",
    "overflowProvider21",
    "overflowProvider22",
    "overflowProvider23",
    "overflowProvider24",
    "overflowProvider25",
    "overflowProvider26",
    "overflowProvider27",
    "overflowProvider28",
    "overflowProvider29",
]


def attrset_expression(prefix, count=35):
    fields = " ".join(f"{prefix}{index:02d} = {index};" for index in range(count))
    return "{ " + fields + " }"


def static_document(count, body):
    bindings = "\n".join(
        f"  {STATIC_PREFIX}{index:02d} = {index};" for index in range(count)
    )
    return f"let\n{bindings}\nin {body}"


def completion_params(uri, text):
    query_start = text.rfind(QUERY_PREFIX)
    assert query_start >= 0, text
    line_start = text.rfind("\n", 0, query_start) + 1
    return {
        "textDocument": {"uri": uri},
        "position": {
            "line": text.count("\n", 0, query_start),
            "character": query_start - line_start + len(QUERY_PREFIX),
        },
        "context": {"triggerKind": 1},
    }


def send_completion(client, request_id, uri, text):
    client.send({
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "textDocument/completion",
        "params": completion_params(uri, text),
    })


def wait_response(client, request_id, timeout=10):
    return client.wait_for(
        lambda message: message.get("id") == request_id,
        timeout=timeout,
    )


def assert_completion(response, labels, incomplete):
    result = response["result"]
    assert [item["label"] for item in result["items"]] == labels, response
    assert result["isIncomplete"] is incomplete, response


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


def wait_for_path(path, description):
    deadline = time.monotonic() + 10
    while not path.exists():
        if time.monotonic() >= deadline:
            raise TimeoutError(f"timed out waiting for {description}: {path}")
        time.sleep(0.01)


def exercise_inactive_static():
    base = {"formatting": {"command": ["nixfmt"]}}
    text = static_document(35, QUERY_PREFIX)
    with tempfile.TemporaryDirectory() as root:
        uri = (Path(root) / "inactive-static.nix").as_uri()
        client = Client(
            args=("--config=" + json.dumps(base, separators=(",", ":")),),
            cwd=root,
        )
        try:
            client.initialize(root_path=root)
            client.initialized()
            client.open_document(uri, text)
            send_completion(client, 10, uri, text)
            assert_completion(
                wait_response(client, 10), EXPECTED_STATIC_LABELS, True
            )
        except Exception as error:
            stderr = client.close()
            print(f"inactive-static error: {error}", file=sys.stderr)
            print(f"received: {client.received}", file=sys.stderr)
            print(f"nixd stderr: {stderr}", file=sys.stderr)
            raise
        else:
            client.close()


def exercise_current_provider():
    base = {
        "formatting": {"command": ["nixfmt"]},
        "nixpkgs": {"expr": attrset_expression(PROVIDER_PREFIX)},
    }
    text = f"with pkgs; [ {QUERY_PREFIX} ]"
    with tempfile.TemporaryDirectory() as root:
        uri = (Path(root) / "current-provider.nix").as_uri()
        client = Client(
            args=("--config=" + json.dumps(base, separators=(",", ":")),),
            cwd=root,
        )
        try:
            client.initialize(root_path=root)
            client.initialized()
            client.open_document(uri, text)
            send_completion(client, 20, uri, text)
            assert_completion(
                wait_response(client, 20), EXPECTED_PROVIDER_LABELS, True
            )
        except Exception as error:
            stderr = client.close()
            print(f"current-provider error: {error}", file=sys.stderr)
            print(f"received: {client.received}", file=sys.stderr)
            print(f"nixd stderr: {stderr}", file=sys.stderr)
            raise
        else:
            client.close()


def exercise_truncated_static_short_circuit():
    with tempfile.TemporaryDirectory() as root:
        root_path = Path(root)
        ready_path = root_path / "response-ready"
        release_path = root_path / "release-response"
        text = static_document(35, f"with pkgs; [ {QUERY_PREFIX} ]")
        uri = (root_path / "truncated-static.nix").as_uri()
        base = {
            "formatting": {"command": ["nixfmt"]},
            "nixpkgs": {"expr": attrset_expression(PROVIDER_PREFIX)},
        }
        proxy = Path(__file__).with_name("blocking-attrset-proxy.py")
        env = os.environ.copy()
        env["REAL_NIXD_ATTRSET_EVAL"] = env["NIXD_ATTRSET_EVAL"]
        env["NIXD_ATTRSET_EVAL"] = str(proxy)
        env["BLOCK_RPC_METHOD"] = "attrset/attrpathComplete"
        env["BLOCK_READY_PATH"] = str(ready_path)
        env["BLOCK_RELEASE_PATH"] = str(release_path)
        client = Client(
            args=("--config=" + json.dumps(base, separators=(",", ":")),),
            cwd=root,
            env=env,
        )
        try:
            client.initialize(root_path=root)
            client.initialized()
            client.open_document(uri, text)
            send_completion(client, 30, uri, text)
            assert_completion(
                wait_response(client, 30, timeout=2), EXPECTED_STATIC_LABELS, True
            )
            assert not ready_path.exists(), "provider RPC unexpectedly reached proxy"
        except Exception as error:
            release_path.write_text("release after failure\n", encoding="utf-8")
            stderr = client.close()
            print(f"truncated-static error: {error}", file=sys.stderr)
            print(f"proxy reached: {ready_path.exists()}", file=sys.stderr)
            print(f"received: {client.received}", file=sys.stderr)
            print(f"nixd stderr: {stderr}", file=sys.stderr)
            raise
        else:
            client.close()


def exercise_exact_static_cap_queries_provider():
    with tempfile.TemporaryDirectory() as root:
        root_path = Path(root)
        ready_path = root_path / "response-ready"
        release_path = root_path / "release-response"
        text = static_document(30, f"with pkgs; [ {QUERY_PREFIX} ]")
        uri = (root_path / "exact-static-cap.nix").as_uri()
        base = {
            "formatting": {"command": ["nixfmt"]},
            "nixpkgs": {"expr": attrset_expression(PROVIDER_PREFIX, count=1)},
        }
        proxy = Path(__file__).with_name("blocking-attrset-proxy.py")
        env = os.environ.copy()
        env["REAL_NIXD_ATTRSET_EVAL"] = env["NIXD_ATTRSET_EVAL"]
        env["NIXD_ATTRSET_EVAL"] = str(proxy)
        env["BLOCK_RPC_METHOD"] = "attrset/attrpathComplete"
        env["BLOCK_READY_PATH"] = str(ready_path)
        env["BLOCK_RELEASE_PATH"] = str(release_path)
        client = Client(
            args=("--config=" + json.dumps(base, separators=(",", ":")),),
            cwd=root,
            env=env,
        )
        try:
            client.initialize(root_path=root)
            client.initialized()
            client.open_document(uri, text)
            send_completion(client, 40, uri, text)
            wait_for_path(ready_path, "exact-cap provider completion request")
            release_path.write_text("release\n", encoding="utf-8")
            assert_completion(
                wait_response(client, 40), EXPECTED_STATIC_LABELS, True
            )
        except Exception as error:
            release_path.write_text("release after failure\n", encoding="utf-8")
            stderr = client.close()
            print(f"exact-static-cap error: {error}", file=sys.stderr)
            print(f"received: {client.received}", file=sys.stderr)
            print(f"nixd stderr: {stderr}", file=sys.stderr)
            raise
        else:
            client.close()


def exercise_stale_provider(static_count, expected_labels, incomplete):
    with tempfile.TemporaryDirectory() as root:
        root_path = Path(root)
        ready_path = root_path / "response-ready"
        release_path = root_path / "release-response"
        text = static_document(static_count, f"with pkgs; [ {QUERY_PREFIX} ]")
        uri = (root_path / f"stale-provider-{static_count}.nix").as_uri()
        base = {"formatting": {"command": ["nixfmt"]}}
        override = {
            "nixpkgs": {"expr": attrset_expression(PROVIDER_PREFIX)}
        }
        proxy = Path(__file__).with_name("blocking-attrset-proxy.py")
        env = os.environ.copy()
        env["REAL_NIXD_ATTRSET_EVAL"] = env["NIXD_ATTRSET_EVAL"]
        env["NIXD_ATTRSET_EVAL"] = str(proxy)
        env["BLOCK_RPC_METHOD"] = "attrset/attrpathComplete"
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
            client.open_document(uri, text)

            send_completion(client, 100, uri, text)
            wait_for_path(ready_path, "withheld oversized completion response")

            configure(client, [None])
            send_completion(client, 101, uri, text)
            assert_completion(
                wait_response(client, 101), expected_labels, incomplete
            )

            release_path.write_text("release\n", encoding="utf-8")
            assert_completion(
                wait_response(client, 100), expected_labels, incomplete
            )
        except Exception as error:
            release_path.write_text("release after failure\n", encoding="utf-8")
            stderr = client.close()
            print(f"stale-provider-{static_count} error: {error}", file=sys.stderr)
            print(f"received: {client.received}", file=sys.stderr)
            print(f"nixd stderr: {stderr}", file=sys.stderr)
            raise
        else:
            client.close()


def exercise_stale_provider_matrix():
    exercise_stale_provider(20, EXPECTED_STATIC_LABELS[:20], False)


def main():
    cases = {
        "inactive-static": exercise_inactive_static,
        "current-provider": exercise_current_provider,
        "truncated-static": exercise_truncated_static_short_circuit,
        "exact-static-cap": exercise_exact_static_cap_queries_provider,
        "stale-provider": exercise_stale_provider_matrix,
    }
    selected = sys.argv[1:] or tuple(cases)
    for case in selected:
        cases[case]()
        print(f"completion overflow case passed: {case}")


if __name__ == "__main__":
    main()
