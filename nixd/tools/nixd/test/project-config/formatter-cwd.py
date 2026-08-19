#!/usr/bin/env python3
"""Prove relative formatter executables use the effective workspace root."""

import json
from pathlib import Path
import sys
import tempfile

from lsp_test_client import Client


def write_project(root, marker):
    (root / ".nixd.json").write_text(json.dumps({
        "formatting": {"command": ["./formatter"]},
        "options": {},
    }), encoding="utf-8")
    formatter = root / "formatter"
    formatter.write_text(f"#!/bin/sh\nprintf '{marker}'\n", encoding="utf-8")
    formatter.chmod(0o755)


def exercise(selector):
    if selector == "exit-125":
        with tempfile.TemporaryDirectory() as root:
            config = json.dumps({
                "formatting": {"command": ["sh", "-c", "exit 125"]},
                "options": {},
            })
            client = Client(args=("--config=" + config,), cwd=root)
            try:
                client.initialize(root_path=root)
                client.initialized()
                uri = (Path(root) / "document.nix").as_uri()
                client.open_document(uri, " " * (512 * 1024))
                try:
                    response = client.formatting(20, uri)
                except RuntimeError as error:
                    stderr = client.close()
                    raise AssertionError(
                        f"nixd terminated during exit-125 formatting: "
                        f"{client.proc.returncode}; stderr={stderr!r}"
                    ) from error
                assert response["error"]["message"].startswith(
                    "formatting sh command exited"
                ), response
                assert client.proc.poll() is None, client.proc.returncode
            finally:
                client.close()
        return

    marker = f"{selector} formatter cwd"
    with tempfile.TemporaryDirectory() as temporary:
        base = Path(temporary)
        launch = base / "launch"
        selected = base / "selected"
        launch.mkdir()
        selected.mkdir()
        root = launch if selector == "launch" else selected
        write_project(root, marker)

        client = Client(args=("--enable-project-config",), cwd=launch)
        try:
            if selector == "root-uri":
                client.initialize(root_uri=selected.as_uri(), root_path=str(launch))
            elif selector == "root-path":
                client.initialize(root_path=str(selected))
            elif selector == "launch":
                client.initialize(root_path="")
            else:
                raise AssertionError(f"unknown selector: {selector}")
            client.initialized()

            uri = (root / "document.nix").as_uri()
            client.open_document(uri, "{ x = 1; }")
            response = client.formatting(20, uri)
            assert response["result"][0]["newText"] == marker, response
        finally:
            client.close()


if __name__ == "__main__":
    exercise(sys.argv[1])
    print(f"formatter cwd case passed: {sys.argv[1]}")
