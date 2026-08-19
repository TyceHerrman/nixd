#!/usr/bin/env python3
"""Prove editor patches always rebuild from the project-file base."""

from pathlib import Path

from lsp_test_client import Client


def reply_to_configuration(client, result):
    request = client.wait_for(
        lambda message: message.get("method") == "workspace/configuration"
    )
    client.send({
        "jsonrpc": "2.0",
        "id": request["id"],
        "result": result,
    })


def change_configuration(client, result):
    client.send({
        "jsonrpc": "2.0",
        "method": "workspace/didChangeConfiguration",
        "params": {"settings": {}},
    })
    reply_to_configuration(client, result)


def main():
    root = Path(__file__).parent / "fixtures" / "project"
    client = Client(args=("--enable-project-config",), cwd=root)
    try:
        client.initialize(
            root_uri=root.as_uri(),
            capabilities={"workspace": {"configuration": True}},
        )
        client.initialized()
        reply_to_configuration(client, [None])

        uri = (root / "file-editor-overlay.nix").as_uri()
        client.open_document(uri, "{ x = 1; }")
        project = client.formatting(100, uri)
        assert project["result"][0]["newText"] == "project-format", project

        change_configuration(client, [{
            "formatting": {"command": ["sh", "-c", "printf editor-format"]},
        }])
        editor = client.formatting(101, uri)
        assert editor["result"][0]["newText"] == "editor-format", editor

        change_configuration(client, [{}])
        reset = client.formatting(102, uri)
        assert reset["result"][0]["newText"] == "project-format", reset
        print("interactive file overlay reset: project-format")
    finally:
        client.close()


if __name__ == "__main__":
    main()
