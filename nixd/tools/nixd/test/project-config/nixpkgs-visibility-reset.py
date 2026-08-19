#!/usr/bin/env python3
"""Exercise nixpkgs provider visibility across editor configuration resets."""

import json
from pathlib import Path
import sys
import tempfile

from lsp_test_client import Client


MARKER = "codexStaleMarker"
MARKER_DESCRIPTION = "distinctive stale nixpkgs marker"
MARKER_URI = "file:///codex-stale-marker.nix"
MARKER_VERSION = "stale-marker-version"


def request(client, request_id, method, params):
    client.send({
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
        "params": params,
    })
    return client.wait_for(lambda message: message.get("id") == request_id)


def workspace_configuration(client):
    return client.wait_for(
        lambda message: message.get("method") == "workspace/configuration"
    )


def change_configuration(client, response):
    client.send({
        "jsonrpc": "2.0",
        "method": "workspace/didChangeConfiguration",
        "params": {"settings": {}},
    })
    configuration = workspace_configuration(client)
    client.send({
        "jsonrpc": "2.0",
        "id": configuration["id"],
        "result": response,
    })


def hover(client, request_id, uri):
    return client.hover(request_id, uri, line=0, character=15)


def marker_is_visible(response):
    return MARKER_DESCRIPTION in json.dumps(response.get("result"))


def main():
    base = {"formatting": {"command": ["nixfmt"]}}
    override = {
        "nixpkgs": {
            "expr": (
                "{ codexStaleMarker = {"
                ' meta.description = "distinctive stale nixpkgs marker";'
                ' meta.position = "/codex-stale-marker.nix:7";'
                ' version = "stale-marker-version";'
                " }; }"
            )
        }
    }

    with tempfile.TemporaryDirectory() as root:
        root_path = Path(root)
        hover_uri = (root_path / "hover.nix").as_uri()
        completion_uri = (root_path / "completion.nix").as_uri()
        hover_text = f"with pkgs; {MARKER}"
        completion_text = "with pkgs; [ codexStale ]"

        client = Client(
            args=("--config=" + json.dumps(base, separators=(",", ":")),),
            cwd=root,
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

            client.open_document(hover_uri, hover_text)
            client.open_document(completion_uri, completion_text)

            active_hover = hover(client, 10, hover_uri)
            assert marker_is_visible(active_hover), active_hover

            active_definition = request(client, 11, "textDocument/definition", {
                "textDocument": {"uri": hover_uri},
                "position": {"line": 0, "character": 15},
            })
            assert MARKER_URI in json.dumps(active_definition["result"]), (
                active_definition
            )

            active_hints = request(client, 12, "textDocument/inlayHint", {
                "textDocument": {"uri": hover_uri},
                "range": {
                    "start": {"line": 0, "character": 0},
                    "end": {"line": 0, "character": len(hover_text)},
                },
            })
            assert any(
                hint.get("label") == f": {MARKER_VERSION}"
                for hint in active_hints["result"]
            ), active_hints

            active_completion = request(
                client,
                13,
                "textDocument/completion",
                {
                    "textDocument": {"uri": completion_uri},
                    "position": {
                        "line": 0,
                        "character": len("with pkgs; [ codexStale"),
                    },
                    "context": {"triggerKind": 1},
                },
            )
            marker_items = [
                item
                for item in active_completion["result"]["items"]
                if item.get("label") == MARKER
            ]
            assert len(marker_items) == 1, active_completion
            marker_item = marker_items[0]

            change_configuration(client, [None])

            reset_hover = hover(client, 20, hover_uri)
            assert reset_hover["result"] is None, reset_hover

            reset_definition = request(client, 21, "textDocument/definition", {
                "textDocument": {"uri": hover_uri},
                "position": {"line": 0, "character": 15},
            })
            assert MARKER_URI not in json.dumps(reset_definition["result"]), (
                reset_definition
            )

            reset_hints = request(client, 22, "textDocument/inlayHint", {
                "textDocument": {"uri": hover_uri},
                "range": {
                    "start": {"line": 0, "character": 0},
                    "end": {"line": 0, "character": len(hover_text)},
                },
            })
            assert not any(
                hint.get("label") == f": {MARKER_VERSION}"
                for hint in reset_hints["result"]
            ), reset_hints

            reset_completion = request(
                client,
                23,
                "textDocument/completion",
                {
                    "textDocument": {"uri": completion_uri},
                    "position": {
                        "line": 0,
                        "character": len("with pkgs; [ codexStale"),
                    },
                    "context": {"triggerKind": 1},
                },
            )
            assert not any(
                item.get("label") == MARKER
                for item in reset_completion["result"]["items"]
            ), reset_completion

            resolved = request(
                client, 24, "completionItem/resolve", marker_item
            )
            assert MARKER_DESCRIPTION not in json.dumps(resolved["result"]), resolved
            assert MARKER_VERSION not in json.dumps(resolved["result"]), resolved

            change_configuration(
                client,
                [{"formatting": {"command": ["nixfmt"]}}],
            )
            omitted_hover = hover(client, 30, hover_uri)
            assert omitted_hover["result"] is None, omitted_hover

            change_configuration(client, [override])
            reactivated_hover = hover(client, 31, hover_uri)
            assert marker_is_visible(reactivated_hover), reactivated_hover

            change_configuration(client, [17])
            retained_hover = hover(client, 32, hover_uri)
            assert marker_is_visible(retained_hover), retained_hover
        except Exception as error:
            stderr = client.close()
            print(f"error: {error}", file=sys.stderr)
            print(f"received: {client.received}", file=sys.stderr)
            print(f"nixd stderr: {stderr}", file=sys.stderr)
            raise
        else:
            client.close()

    print("nixpkgs visibility reset passed")


if __name__ == "__main__":
    main()
