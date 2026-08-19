#!/usr/bin/env python3
"""Exercise formatter setup, pipe progress, and descriptor ownership."""

import json
from pathlib import Path
import sys
import tempfile
import time

from lsp_test_client import Client


FOUR_MIB = 4 * 1024 * 1024
PIPE_PRESSURE_BYTES = 512 * 1024
MARKER_TIMEOUT_SECONDS = 15
RESPONSE_TIMEOUT_SECONDS = 15


STDOUT_AFTER_INPUT = r"""
import os
from pathlib import Path
import sys

sys.stdin.buffer.read()
Path(sys.argv[1]).write_text("input-read\n")
for _ in range(1024):
    os.write(1, b"O" * 4096)
Path(sys.argv[2]).write_text("stdout-written\n")
"""


STDERR_THEN_ECHO = r"""
import os
from pathlib import Path
import sys

Path(sys.argv[1]).write_text("stderr-started\n")
for _ in range(1024):
    os.write(2, b"E" * 4096)
Path(sys.argv[2]).write_text("stderr-written\n")
data = sys.stdin.buffer.read()
sys.stdout.buffer.write(data)
sys.stdout.buffer.flush()
"""


STDOUT_BEFORE_INPUT = r"""
import os
from pathlib import Path
import sys

Path(sys.argv[1]).write_text("stdout-started\n")
for _ in range(1024):
    os.write(1, b"P" * 4096)
Path(sys.argv[2]).write_text("stdout-written\n")
sys.stdin.buffer.read()
Path(sys.argv[3]).write_text("input-read\n")
"""


CROSS_INHERITED_STDIN = r"""
from pathlib import Path
import sys
import time

claim = Path(sys.argv[1])
try:
    claim.mkdir()
    role = "a"
except FileExistsError:
    role = "b"

started = Path(sys.argv[2] if role == "a" else sys.argv[3])
release = Path(sys.argv[4] if role == "a" else sys.argv[5])
started.write_text(role + "-started\n")
deadline = time.monotonic() + 15
while not release.exists():
    if time.monotonic() >= deadline:
        raise TimeoutError(role + " release gate was not opened")
    time.sleep(0.01)

sys.stdin.buffer.read()
sys.stdout.write(role.upper() + "-complete\n")
sys.stdout.flush()
"""


def formatter_config(command):
    return "--config=" + json.dumps({
        "formatting": {"command": command},
        "options": {},
    })


def python_formatter(script, *arguments):
    return [sys.executable, "-c", script, *(str(argument) for argument in arguments)]


def wait_for_file(path, expected, timeout=MARKER_TIMEOUT_SECONDS):
    deadline = time.monotonic() + timeout
    observed = None
    while time.monotonic() < deadline:
        try:
            contents = path.read_text()
        except FileNotFoundError:
            time.sleep(0.01)
            continue
        observed = contents
        if contents == expected:
            return
        time.sleep(0.01)
    raise TimeoutError(
        f"timed out waiting for marker {path.name}; "
        f"expected={expected!r}, observed={observed!r}"
    )


def send_formatting(client, request_id, uri):
    client.send({
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "textDocument/formatting",
        "params": {
            "textDocument": {"uri": uri},
            "options": {"tabSize": 2, "insertSpaces": True},
        },
    })


def wait_for_formatting(client, request_id, timeout=RESPONSE_TIMEOUT_SECONDS):
    return client.wait_for(
        lambda message: message.get("id") == request_id,
        timeout=timeout,
    )


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
                response = client.formatting(20, uri, timeout=30)
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


def exercise_stdout_after_input():
    with tempfile.TemporaryDirectory() as root:
        root_path = Path(root)
        input_read = root_path / "input-read"
        stdout_written = root_path / "stdout-written"
        command = python_formatter(
            STDOUT_AFTER_INPUT,
            input_read,
            stdout_written,
        )
        client = Client(args=(formatter_config(command),), cwd=root)
        try:
            client.initialize(root_path=root)
            client.initialized()
            uri = (root_path / "document.nix").as_uri()
            client.open_document(uri, "{ stdout = true; }\n")
            send_formatting(client, 20, uri)
            wait_for_file(input_read, "input-read\n")
            try:
                response = wait_for_formatting(client, 20)
            except TimeoutError as error:
                raise AssertionError(
                    "nixd waited for formatter exit before draining 4 MiB stdout"
                ) from error
            assert response == {
                "jsonrpc": "2.0",
                "id": 20,
                "result": [{
                    "range": {
                        "start": {"line": 0, "character": 0},
                        "end": {"line": 2147483647, "character": 2147483647},
                    },
                    "newText": "O" * FOUR_MIB,
                }],
            }, response
            wait_for_file(stdout_written, "stdout-written\n")
        finally:
            client.close()


def exercise_stderr_then_echo():
    with tempfile.TemporaryDirectory() as root:
        root_path = Path(root)
        stderr_started = root_path / "stderr-started"
        stderr_written = root_path / "stderr-written"
        command = python_formatter(
            STDERR_THEN_ECHO,
            stderr_started,
            stderr_written,
        )
        client = Client(args=(formatter_config(command),), cwd=root)
        try:
            client.initialize(root_path=root)
            client.initialized()
            uri = (root_path / "document.nix").as_uri()
            client.open_document(uri, "{ stderr = true; }\n")
            send_formatting(client, 20, uri)
            wait_for_file(stderr_started, "stderr-started\n")
            try:
                response = wait_for_formatting(client, 20)
            except TimeoutError as error:
                raise AssertionError(
                    "nixd did not drain 4 MiB formatter stderr before waiting"
                ) from error
            assert response == {"jsonrpc": "2.0", "id": 20, "result": []}, response
            wait_for_file(stderr_written, "stderr-written\n")
        finally:
            client.close()


def exercise_stdout_before_input():
    with tempfile.TemporaryDirectory() as root:
        root_path = Path(root)
        stdout_started = root_path / "stdout-started"
        stdout_written = root_path / "stdout-written"
        input_read = root_path / "input-read"
        command = python_formatter(
            STDOUT_BEFORE_INPUT,
            stdout_started,
            stdout_written,
            input_read,
        )
        client = Client(args=(formatter_config(command),), cwd=root)
        try:
            client.initialize(root_path=root)
            client.initialized()
            uri = (root_path / "document.nix").as_uri()
            client.open_document(uri, " " * PIPE_PRESSURE_BYTES)
            send_formatting(client, 20, uri)
            wait_for_file(stdout_started, "stdout-started\n")
            try:
                response = wait_for_formatting(client, 20)
            except TimeoutError as error:
                raise AssertionError(
                    "nixd serialized full stdin before draining 4 MiB stdout"
                ) from error
            assert response == {
                "jsonrpc": "2.0",
                "id": 20,
                "result": [{
                    "range": {
                        "start": {"line": 0, "character": 0},
                        "end": {"line": 2147483647, "character": 2147483647},
                    },
                    "newText": "P" * FOUR_MIB,
                }],
            }, response
            wait_for_file(stdout_written, "stdout-written\n")
            wait_for_file(input_read, "input-read\n")
        finally:
            client.close()


def exercise_cross_inherited_stdin_eof():
    with tempfile.TemporaryDirectory() as root:
        root_path = Path(root)
        claim = root_path / "first-formatter"
        a_started = root_path / "a-started"
        b_started = root_path / "b-started"
        release_a = root_path / "release-a"
        release_b = root_path / "release-b"
        command = python_formatter(
            CROSS_INHERITED_STDIN,
            claim,
            a_started,
            b_started,
            release_a,
            release_b,
        )
        client = Client(args=(formatter_config(command),), cwd=root)
        try:
            client.initialize(root_path=root)
            client.initialized()
            uri_a = (root_path / "a.nix").as_uri()
            uri_b = (root_path / "b.nix").as_uri()
            client.open_document(uri_a, " " * PIPE_PRESSURE_BYTES)
            client.open_document(uri_b, "{ b = true; }\n")

            send_formatting(client, 20, uri_a)
            wait_for_file(a_started, "a-started\n")
            send_formatting(client, 21, uri_b)
            wait_for_file(b_started, "b-started\n")
            assert not release_a.exists()
            assert not release_b.exists()

            release_a.write_text("release-a\n")
            try:
                response = wait_for_formatting(client, 20)
            except TimeoutError as error:
                raise AssertionError(
                    "request A did not receive stdin EOF while gated request B "
                    "kept an inherited writer open"
                ) from error
            assert response == {
                "jsonrpc": "2.0",
                "id": 20,
                "result": [{
                    "range": {
                        "start": {"line": 0, "character": 0},
                        "end": {"line": 2147483647, "character": 2147483647},
                    },
                    "newText": "A-complete\n",
                }],
            }, response
            assert b_started.read_text() == "b-started\n"
            assert not release_b.exists()
            assert client.proc.poll() is None, client.proc.returncode
        finally:
            release_a.write_text("release-a\n")
            release_b.write_text("release-b\n")
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


def exercise_ignored_sigpipe():
    with tempfile.TemporaryDirectory() as root:
        client = Client(
            args=(formatter_config(["sh", "-c", "exit 125"]),),
            cwd=root,
            restore_signals=False,
        )
        try:
            client.initialize(root_path=root)
            client.initialized()
            uri = (Path(root) / "document.nix").as_uri()
            client.open_document(uri, "x" * (2 * 1024 * 1024))
            response = client.formatting(20, uri)
            assert response["error"]["message"].startswith(
                "formatting sh command exited"
            ), response
            assert client.proc.poll() is None, client.proc.returncode
        finally:
            client.close()


if __name__ == "__main__":
    case = sys.argv[1]
    if case == "removed-root":
        exercise_removed_root()
    elif case == "stdout-after-input":
        exercise_stdout_after_input()
    elif case == "stderr-then-echo":
        exercise_stderr_then_echo()
    elif case == "stdout-before-input":
        exercise_stdout_before_input()
    elif case == "cross-inherited-stdin-eof":
        exercise_cross_inherited_stdin_eof()
    elif case == "descriptor-stability":
        exercise_descriptor_stability()
    elif case == "exec-failure":
        exercise_exec_failure()
    elif case == "ignored-sigpipe":
        exercise_ignored_sigpipe()
    else:
        raise AssertionError(f"unknown case: {case}")
    print(f"formatter process lifecycle case passed: {case}")
