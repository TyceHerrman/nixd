#!/usr/bin/env python3
"""Exercise formatter setup failure and descriptor ownership."""

import json
from pathlib import Path
import sys
import tempfile

from lsp_test_client import Client


def formatter_config(command):
    return "--config=" + json.dumps({
        "formatting": {"command": command},
        "options": {},
    })


def exercise_removed_root():
    with tempfile.TemporaryDirectory() as temporary:
        launch = Path(temporary)
        root = launch / "selected"
        root.mkdir()
        client = Client(args=(formatter_config(["cat"]),), cwd=launch)
        try:
            client.initialize(root_path=str(root))
            client.initialized()
            root.rmdir()

            uri = (root / "document.nix").as_uri()
            client.open_document(uri, "x" * (2 * 1024 * 1024))
            try:
                response = client.formatting(20, uri)
            except RuntimeError as error:
                client.proc.wait(timeout=10)
                raise AssertionError(
                    f"nixd terminated during formatting: {client.proc.returncode}"
                ) from error
            assert response["error"]["message"] == (
                f"failed to change formatter working directory to {root}"
            ), response
            assert client.proc.poll() is None, client.proc.returncode
        finally:
            client.close()


def exercise_descriptor_stability():
    with tempfile.TemporaryDirectory() as root:
        client = Client(
            args=(formatter_config(["cat"]),),
            cwd=root,
            fd_limit=32,
        )
        try:
            client.initialize(root_path=root)
            client.initialized()
            uri = (Path(root) / "document.nix").as_uri()
            client.open_document(uri, "{ x = 1; }")
            for request_id in range(20, 32):
                try:
                    response = client.formatting(request_id, uri)
                except RuntimeError as error:
                    raise AssertionError(
                        f"nixd failed on formatting request {request_id}"
                    ) from error
                assert response["result"] == [], response
            assert client.proc.poll() is None, client.proc.returncode
        finally:
            client.close()


def exercise_exec_failure():
    command = "nixd-test-formatter-that-does-not-exist"
    with tempfile.TemporaryDirectory() as root:
        client = Client(args=(formatter_config([command]),), cwd=root)
        try:
            client.initialize(root_path=root)
            client.initialized()
            uri = (Path(root) / "document.nix").as_uri()
            client.open_document(uri, "x" * (2 * 1024 * 1024))
            response = client.formatting(20, uri)
            assert response["error"]["message"].startswith(
                f"formatting {command} command exited"
            ), response
            assert client.proc.poll() is None, client.proc.returncode
        finally:
            client.close()


if __name__ == "__main__":
    case = sys.argv[1]
    if case == "removed-root":
        exercise_removed_root()
    elif case == "descriptor-stability":
        exercise_descriptor_stability()
    elif case == "exec-failure":
        exercise_exec_failure()
    else:
        raise AssertionError(f"unknown case: {case}")
    print(f"formatter process lifecycle case passed: {case}")
