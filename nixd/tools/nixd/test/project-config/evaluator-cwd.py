#!/usr/bin/env python3
"""Prove relative evaluator imports use the effective workspace root."""

import json
from pathlib import Path
import sys
import tempfile
import time

from lsp_test_client import Client


def write_project(root, marker):
    (root / ".nixd.json").write_text(json.dumps({
        "nixpkgs": {"expr": "import ./nixpkgs.nix"},
        "options": {},
    }), encoding="utf-8")
    (root / "nixpkgs.nix").write_text(
        f'{{ marker.meta.description = "{marker}"; }}\n', encoding="utf-8"
    )


def exercise(selector):
    marker = f"{selector} evaluator cwd"
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
            client.open_document(uri, "pkgs.marker")
            deadline = time.monotonic() + 10
            request_id = 20
            while True:
                response = client.hover(request_id, uri)
                value = (((response.get("result") or {}).get("contents") or {}).get("value") or "")
                if marker in value:
                    break
                if time.monotonic() >= deadline:
                    raise AssertionError(
                        f"evaluator never observed {marker!r}; last response={response}"
                    )
                request_id += 1
                time.sleep(0.05)
        finally:
            stderr = client.close()
        assert "error: getting status of" not in stderr, stderr


if __name__ == "__main__":
    exercise(sys.argv[1])
    print(f"evaluator cwd case passed: {sys.argv[1]}")
