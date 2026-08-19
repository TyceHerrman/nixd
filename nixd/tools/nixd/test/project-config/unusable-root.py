#!/usr/bin/env python3
"""Prove unusable supplied roots warn and fall back without file loading."""

import errno
import json
import os
from pathlib import Path
import sys
import tempfile
import time

from lsp_test_client import Client


def show_message(message):
    return message.get("method") == "window/showMessage"


def make_executable(path, output):
    path.write_text(f"#!/bin/sh\nprintf '{output}'\n", encoding="utf-8")
    path.chmod(0o755)


def exercise(selector):
    evaluator_marker = f"{selector} launch evaluator fallback"
    formatter_marker = f"{selector} launch formatter fallback"
    with tempfile.TemporaryDirectory() as temporary:
        launch = Path(temporary) / "launch"
        launch.mkdir()
        unusable = Path(temporary) / "does-not-exist"
        inaccessible = selector == "root-path-inaccessible"
        if inaccessible:
            unusable.mkdir()
            unusable.chmod(0)

        (launch / "nixpkgs.nix").write_text(
            f'{{ marker.meta.description = "{evaluator_marker}"; }}\n',
            encoding="utf-8",
        )
        make_executable(launch / "nixfmt", formatter_marker)
        make_executable(launch / "project-formatter", "project file was loaded")
        (launch / ".nixd.json").write_text(json.dumps({
            "formatting": {"command": ["./project-formatter"]},
            "nixpkgs": {
                "expr": '{ marker.meta.description = "project file was loaded"; }'
            },
            "options": {},
        }), encoding="utf-8")

        env = os.environ.copy()
        env["PATH"] = f"{launch}{os.pathsep}{env['PATH']}"
        client = Client(
            args=("--enable-project-config", "--nixpkgs-expr=import ./nixpkgs.nix"),
            cwd=launch,
            env=env,
        )
        try:
            reason = os.strerror(errno.EACCES if inaccessible else errno.ENOENT)
            if selector == "root-uri":
                client.initialize(root_uri=unusable.as_uri(), root_path=str(launch))
            elif selector in {"root-path", "root-path-inaccessible"}:
                client.initialize(root_path=str(unusable))
            else:
                raise AssertionError(f"unknown selector: {selector}")

            logged = client.read_stderr_until(
                lambda stderr: "unusable workspace root" in stderr
                and str(unusable) in stderr
                and reason in stderr
            )
            assert "unusable workspace root" in logged, logged
            assert ".nixd.json" not in logged, logged
            client.assert_no_message(show_message)
            client.initialized()
            warning = client.wait_for(show_message)
            assert warning["params"]["type"] == 2, warning
            assert "unusable workspace root" in warning["params"]["message"], warning
            assert str(unusable) in warning["params"]["message"], warning
            assert reason in warning["params"]["message"], warning
            assert ".nixd.json" not in warning["params"]["message"], warning
            client.assert_no_message(show_message)

            uri = (launch / "document.nix").as_uri()
            client.open_document(uri, "pkgs.marker")
            deadline = time.monotonic() + 10
            request_id = 20
            while True:
                hover = client.hover(request_id, uri)
                value = (((hover.get("result") or {}).get("contents") or {}).get("value") or "")
                if evaluator_marker in value:
                    break
                if time.monotonic() >= deadline:
                    raise AssertionError(
                        f"evaluator did not use launch fallback; last response={hover}"
                    )
                request_id += 1
                time.sleep(0.05)

            formatted = client.formatting(100, uri)
            assert formatted["result"][0]["newText"] == formatter_marker, formatted
            assert "project file was loaded" not in str(client.received), client.received
        except Exception:
            stderr = client.close()
            print(f"received: {client.received}", file=sys.stderr)
            print(f"nixd stderr: {stderr}", file=sys.stderr)
            raise
        else:
            client.close()
        finally:
            if inaccessible:
                unusable.chmod(0o700)


if __name__ == "__main__":
    exercise(sys.argv[1])
    print(f"unusable root case passed: {sys.argv[1]}")
