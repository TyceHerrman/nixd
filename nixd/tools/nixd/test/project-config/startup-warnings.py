#!/usr/bin/env python3
"""Exercise project configuration warning timing against a real nixd."""

import errno
import os
from pathlib import Path
import sys
import tempfile

from lsp_test_client import Client


def show_message(message):
    return message.get("method") == "window/showMessage"


def exercise_missing():
    with tempfile.TemporaryDirectory() as root:
        client = Client(args=("--enable-project-config",), cwd=root)
        try:
            client.initialize(root_path=root)
            client.assert_no_message(show_message)
            client.initialized()
            client.assert_no_message(show_message)
        finally:
            stderr = client.close()
        assert ".nixd.json" not in stderr, stderr


def exercise_invalid(kind):
    with tempfile.TemporaryDirectory() as root:
        bin_dir = Path(root) / "bin"
        bin_dir.mkdir()
        formatter = bin_dir / "nixfmt"
        formatter.write_text(
            "#!/bin/sh\nprintf 'built-in formatter fallback'\n",
            encoding="utf-8",
        )
        formatter.chmod(0o755)
        env = os.environ.copy()
        env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"

        path = Path(root) / ".nixd.json"
        if kind == "io":
            path.symlink_to(path.name)
            reasons = (os.strerror(errno.ELOOP),)
        elif kind == "io-directory":
            path.mkdir()
            reasons = (os.strerror(errno.EISDIR),)
        elif kind == "json":
            path.write_text("{", encoding="utf-8")
            reasons = ("JSON result cannot be parsed", "Expected object key")
        elif kind == "schema":
            path.write_text('{"formatting":{"command":42}}', encoding="utf-8")
            reasons = (
                "JSON schema mismatch",
                "expected array at (root).formatting.command",
            )
        else:
            raise AssertionError(f"unknown invalid kind: {kind}")

        client = Client(args=("--enable-project-config",), cwd=root, env=env)
        try:
            client.initialize(root_path=root)
            logged = client.read_stderr_until(
                lambda stderr: str(path) in stderr
                and all(reason in stderr for reason in reasons)
            )
            assert str(path) in logged
            assert all(reason in logged for reason in reasons), logged
            client.assert_no_message(show_message)
            client.initialized()
            warning = client.wait_for(show_message)
            assert warning["params"]["type"] == 2, warning
            assert str(path) in warning["params"]["message"], warning
            assert all(
                reason in warning["params"]["message"] for reason in reasons
            ), warning
            client.assert_no_message(show_message)

            uri = "file:///startup-warning.nix"
            client.open_document(uri, "{ x = 1; }")
            response = client.formatting(20, uri)
            assert response["result"][0]["newText"] == (
                "built-in formatter fallback"
            ), response
        finally:
            client.close()


def exercise_invalid_cli():
    client = Client(args=("--config=",))
    try:
        client.initialize(root_path="")
        client.proc.wait(timeout=10)
    finally:
        stderr = client.close()
    assert client.proc.returncode != 0, client.proc.returncode
    assert "parse CLI config error" in stderr, stderr
    assert not any(show_message(message) for message in client.received), client.received


def main():
    case = sys.argv[1]
    if case == "missing":
        exercise_missing()
    elif case in {"io", "io-directory", "json", "schema"}:
        exercise_invalid(case)
    elif case == "invalid-cli":
        exercise_invalid_cli()
    else:
        raise AssertionError(f"unknown case: {case}")
    print(f"startup warning case passed: {case}")


if __name__ == "__main__":
    main()
