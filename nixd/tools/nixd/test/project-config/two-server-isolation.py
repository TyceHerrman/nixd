#!/usr/bin/env python3
"""Interleave two real nixd processes and prove root/config isolation."""

import json
from pathlib import Path
import tempfile
import time

from lsp_test_client import Client


def write_project(root, marker):
    (root / ".nixd.json").write_text(json.dumps({
        "formatting": {"command": ["./formatter"]},
        "nixpkgs": {"expr": "import ./nixpkgs.nix"},
        "options": {},
    }), encoding="utf-8")
    (root / "nixpkgs.nix").write_text(
        f'{{ marker.meta.description = "{marker} evaluator"; }}\n',
        encoding="utf-8",
    )
    formatter = root / "formatter"
    formatter.write_text(
        f"#!/bin/sh\nprintf '{marker} formatter'\n", encoding="utf-8"
    )
    formatter.chmod(0o755)


def wait_for_marker(client, uri, marker, request_id):
    deadline = time.monotonic() + 10
    while True:
        response = client.hover(request_id, uri)
        value = (((response.get("result") or {}).get("contents") or {}).get("value") or "")
        if marker in value:
            return value
        if time.monotonic() >= deadline:
            raise AssertionError(
                f"server never observed {marker!r}; last response={response}"
            )
        request_id += 1
        time.sleep(0.05)


def main():
    with tempfile.TemporaryDirectory() as temporary:
        base = Path(temporary)
        launch = base / "launch"
        first_root = base / "first"
        second_root = base / "second"
        for path in (launch, first_root, second_root):
            path.mkdir()
        write_project(first_root, "first project")
        write_project(second_root, "second project")

        first = Client(args=("--enable-project-config",), cwd=launch)
        second = Client(args=("--enable-project-config",), cwd=launch)
        try:
            first.initialize(root_uri=first_root.as_uri())
            second.initialize(root_path=str(second_root))
            first.initialized()
            second.initialized()

            first_uri = (first_root / "document.nix").as_uri()
            second_uri = (second_root / "document.nix").as_uri()
            first.open_document(first_uri, "pkgs.marker")
            second.open_document(second_uri, "pkgs.marker")

            second_hover = wait_for_marker(
                second, second_uri, "second project evaluator", 20
            )
            first_hover = wait_for_marker(
                first, first_uri, "first project evaluator", 40
            )
            assert "first project" not in second_hover, second_hover
            assert "second project" not in first_hover, first_hover

            first_format = first.formatting(100, first_uri)
            second_format = second.formatting(100, second_uri)
            assert first_format["result"][0]["newText"] == "first project formatter"
            assert second_format["result"][0]["newText"] == "second project formatter"
        finally:
            first.close()
            second.close()


if __name__ == "__main__":
    main()
    print("two server isolation passed")
