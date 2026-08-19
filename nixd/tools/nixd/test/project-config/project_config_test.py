#!/usr/bin/env python3
"""Real-process project-configuration scenarios selected by command-line mode."""

import errno
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from lsp_test_client import Client


CAPABILITIES = {"workspace": {"configuration": True}}
MARKER = "editorMarker"
MARKER_DESCRIPTION = "editor nixpkgs marker"


def write_json(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


def write_project(root, *, formatter="project-format", modern=False):
    config = {
        "formatting": {"command": ["sh", "-c", f"printf {formatter}"]},
    }
    if modern:
        config.update({
            "nixpkgs": {
                "expr": '{ project.meta.description = "project nixpkgs"; }',
            },
            "options": {
                "project": {
                    "expr": '{ project.option = { _type = "option"; }; }',
                },
            },
            "diagnostic": {
                "suppress": ["sema-unused-def-lambda-noarg-formal"],
            },
        })
    write_json(root / ".nixd.json", config)


def formatted_text(client, request_id, uri, forbidden=None):
    response = client.formatting(request_id, uri, forbidden=forbidden)
    return response["result"][0]["newText"]


def workspace_request(client):
    return client.wait_for(
        lambda message: message.get("method") == "workspace/configuration"
    )


def reply(client, *, result=None, error=None):
    request = workspace_request(client)
    response = {"jsonrpc": "2.0", "id": request["id"]}
    if error is None:
        response["result"] = result
    else:
        response["error"] = error
    client.send(response)


def change(client, *, result=None, error=None):
    client.send({
        "jsonrpc": "2.0",
        "method": "workspace/didChangeConfiguration",
        "params": {"settings": {}},
    })
    reply(client, result=result, error=error)


def show_message(message):
    return message.get("method") == "window/showMessage"


def assert_warning_count(client, expected):
    actual = sum(show_message(message) for message in client.received)
    assert actual == expected, client.received


def exercise_disabled(root):
    write_project(root, formatter="project-format")
    client = Client(cwd=root)
    uri = (root / "disabled.nix").as_uri()
    try:
        client.initialize(root_uri=root.as_uri())
        client.open_document(uri, "{ x = 1; }")
        response = client.formatting(1, uri)
        assert "project-format" not in json.dumps(response), response
    finally:
        client.close()


def exercise_root_uri(root):
    write_project(root, formatter="root-uri-format")
    client = Client(args=("--enable-project-config",), cwd=root)
    uri = (root / "root-uri.nix").as_uri()
    try:
        client.initialize(
            root_uri=root.as_uri(), root_path="/definitely-not-the-project-root"
        )
        client.open_document(uri, "{ x = 1; }")
        assert formatted_text(client, 2, uri) == "root-uri-format"
    finally:
        client.close()


def exercise_root_path(root):
    write_project(root, formatter="root-path-format")
    client = Client(args=("--enable-project-config",), cwd=root)
    uri = (root / "root-path.nix").as_uri()
    try:
        client.initialize(root_uri="", root_path=str(root))
        client.open_document(uri, "{ x = 1; }")
        assert formatted_text(client, 3, uri) == "root-path-format"
    finally:
        client.close()


def exercise_launch_directory(root):
    write_project(root, formatter="launch-format")
    client = Client(args=("--enable-project-config",), cwd=root)
    uri = (root / "launch.nix").as_uri()
    try:
        client.initialize(root_path="")
        client.open_document(uri, "{ x = 1; }")
        assert formatted_text(client, 4, uri) == "launch-format"
    finally:
        client.close()


def exercise_no_ancestor(root):
    parent = root / "ancestor"
    child = parent / "child"
    child.mkdir(parents=True)
    write_project(parent, formatter="ancestor-format")
    client = Client(args=("--enable-project-config",), cwd=root)
    uri = (child / "no-ancestor.nix").as_uri()
    try:
        client.initialize(root_path=str(child))
        client.open_document(uri, "{ x = 1; }")
        response = client.formatting(5, uri)
        assert "ancestor-format" not in json.dumps(response), response
    finally:
        client.close()


def exercise_cli_precedence(root):
    write_project(root, formatter="project-format")
    cli = {"formatting": {"command": ["sh", "-c", "printf cli-format"]}}
    client = Client(
        args=("--enable-project-config", "--config=" + json.dumps(cli)), cwd=root
    )
    uri = (root / "precedence.nix").as_uri()
    try:
        client.initialize(root_uri=root.as_uri())
        client.open_document(uri, "{ x = 1; }")
        client.send({
            "jsonrpc": "2.0",
            "method": "workspace/didChangeConfiguration",
            "params": {"settings": {}},
        })
        assert formatted_text(client, 6, uri) == "cli-format"
    finally:
        client.close()


def exercise_empty_cli_config():
    request = json.dumps({
        "jsonrpc": "2.0",
        "id": 0,
        "method": "initialize",
        "params": {"processId": 123, "rootPath": "", "capabilities": {}},
    }, separators=(",", ":")).encode()
    transcript = (
        f"Content-Length: {len(request)}\r\n\r\n".encode() + request
    )
    process = subprocess.Popen(
        ["nixd", "--config="],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        process.stdin.write(transcript)
        process.stdin.flush()
        process.wait(timeout=10)
    except subprocess.TimeoutExpired as error:
        process.kill()
        raise AssertionError("empty CLI configuration did not fail") from error
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)
    assert process.returncode != 0, process.stderr.read().decode(errors="replace")


def exercise_help_warning():
    result = subprocess.run(
        ["nixd", "--help"], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        check=False, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert any(
        "--enable-project-config" in line
        and "trusted project configuration may evaluate Nix and execute formatter commands" in line
        for line in result.stdout.splitlines()
    ), result.stdout


def exercise_selection():
    with tempfile.TemporaryDirectory() as temporary:
        base = Path(temporary)
        for name, scenario in (
            ("disabled", exercise_disabled),
            ("root-uri", exercise_root_uri),
            ("root-path", exercise_root_path),
            ("launch", exercise_launch_directory),
            ("no-ancestor", exercise_no_ancestor),
            ("precedence", exercise_cli_precedence),
        ):
            root = base / name
            root.mkdir()
            scenario(root)
    exercise_empty_cli_config()
    exercise_help_warning()


def exercise_modern_fields():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        write_project(root, modern=True)
        client = Client(args=("--enable-project-config",), cwd=root)
        diagnostic_uri = (root / "modern-diagnostic.nix").as_uri()
        nixpkgs_uri = (root / "modern-nixpkgs.nix").as_uri()
        options_uri = (root / "modern-options.nix").as_uri()
        try:
            client.initialize(root_uri=root.as_uri())
            client.open_document(diagnostic_uri, "{x, y}: x + 1")
            diagnostic = client.wait_for(
                lambda message: message.get("method") == "textDocument/publishDiagnostics"
                and message.get("params", {}).get("uri") == diagnostic_uri
            )
            assert diagnostic["params"]["diagnostics"] == [], diagnostic
            client.open_document(nixpkgs_uri, "pkgs.project")
            hover = client.hover(10, nixpkgs_uri)
            assert hover["result"]["contents"]["value"] == (
                "## Description\n\nproject nixpkgs\n\n"
            ), hover
            client.open_document(options_uri, "{ pro }")
            completion = client.request(11, "textDocument/completion", {
                "textDocument": {"uri": options_uri},
                "position": {"line": 0, "character": 5},
                "context": {"triggerKind": 1},
            })
            assert any(
                item.get("label") == "project" and item.get("detail") == "project"
                for item in completion["result"]["items"]
            ), completion
            assert formatted_text(client, 12, options_uri) == "project-format"
        finally:
            client.close()


def hover(client, request_id, uri, character):
    return client.request(request_id, "textDocument/hover", {
        "textDocument": {"uri": uri},
        "position": {"line": 0, "character": character},
    })


def exercise_cli_base(root):
    cli = {"formatting": {"command": ["sh", "-c", "printf cli-format"]}}
    client = Client(args=("--config=" + json.dumps(cli),), cwd=root)
    uri = (root / "cli-overlay.nix").as_uri()
    try:
        client.initialize(root_path=str(root), capabilities=CAPABILITIES)
        client.initialized()
        reply(client, result=[None])
        client.open_document(uri, "{ x = 1; }")
        assert formatted_text(client, 20, uri) == "cli-format"
        change(client, result=[{
            "formatting": {"command": ["sh", "-c", "printf editor-format"]},
        }])
        assert formatted_text(client, 21, uri) == "editor-format"
        change(client, result=[None])
        assert formatted_text(client, 22, uri) == "cli-format"
        client.send({
            "jsonrpc": "2.0",
            "method": "workspace/didChangeConfiguration",
            "params": {"settings": {}},
        })
        older_request = workspace_request(client)
        client.send({
            "jsonrpc": "2.0",
            "method": "workspace/didChangeConfiguration",
            "params": {"settings": {}},
        })
        newer_request = workspace_request(client)
        assert older_request["id"] != newer_request["id"]
        client.send({
            "jsonrpc": "2.0",
            "id": newer_request["id"],
            "result": [{
                "formatting": {
                    "command": ["sh", "-c", "printf newer-format"],
                },
            }],
        })
        assert formatted_text(client, 23, uri) == "newer-format"
        client.send({
            "jsonrpc": "2.0",
            "id": older_request["id"],
            "error": {"code": -32603, "message": "stale request failed"},
        })
        active = formatted_text(client, 24, uri)
        assert active == "newer-format", active
    finally:
        client.close()


def exercise_project_base(root):
    write_project(root, modern=True)
    client = Client(args=("--enable-project-config",), cwd=root)
    format_uri = (root / "file-overlay.nix").as_uri()
    options_uri = (root / "options-overlay.nix").as_uri()
    hover_uri = (root / "nixpkgs-overlay.nix").as_uri()
    try:
        client.initialize(root_uri=root.as_uri(), capabilities=CAPABILITIES)
        client.initialized()
        reply(client, result=[None])
        client.open_document(format_uri, "{ x = 1; }")
        client.open_document(options_uri, "{ ed }")
        client.open_document(hover_uri, f"pkgs.{MARKER}")
        assert formatted_text(client, 30, format_uri) == "project-format"
        change(client, result=[{"diagnostic": {}}])
        assert formatted_text(client, 31, format_uri) == "project-format"
        change(client, result=[{
            "formatting": {"command": ["sh", "-c", "printf editor-format"]},
        }])
        assert formatted_text(client, 32, format_uri) == "editor-format"
        change(client, result=[{}])
        assert formatted_text(client, 33, format_uri) == "project-format"
        change(client, result=[{
            "options": {"editor": {
                "expr": '{ editor.option = { _type = "option"; }; }',
            }},
        }])
        completion = client.request(34, "textDocument/completion", {
            "textDocument": {"uri": options_uri},
            "position": {"line": 0, "character": 4},
            "context": {"triggerKind": 1},
        })
        labels = [item.get("label") for item in completion["result"]["items"]]
        assert "editor" in labels, completion
        assert "project" not in labels, completion
        change(client, result=[{
            "nixpkgs": {"expr": (
                '{ editorMarker.meta.description = "editor nixpkgs marker"; }'
            )},
        }])
        active = hover(client, 35, hover_uri, len("pkgs.editor"))
        assert MARKER_DESCRIPTION in json.dumps(active["result"]), active
        change(client, result=[None])
        reset = hover(client, 36, hover_uri, len("pkgs.editor"))
        assert MARKER_DESCRIPTION not in json.dumps(reset["result"]), reset
        change(client, result=[{
            "formatting": {"command": ["sh", "-c", "printf retained-format"]},
        }])
        assert formatted_text(client, 37, format_uri) == "retained-format"
        change(client, result=[{"formatting": {"command": 42}}])
        assert formatted_text(client, 38, format_uri) == "retained-format"
        change(client, result=[17])
        assert formatted_text(client, 39, format_uri) == "retained-format"
        change(client, error={"code": -32603, "message": "request failed"})
        assert formatted_text(client, 40, format_uri) == "retained-format"
        change(client, result=[])
        assert formatted_text(client, 41, format_uri) == "retained-format"
    finally:
        client.close()


def exercise_workspace_overlay():
    with tempfile.TemporaryDirectory() as temporary:
        base = Path(temporary)
        cli_root = base / "cli"
        project_root = base / "project"
        cli_root.mkdir()
        project_root.mkdir()
        exercise_cli_base(cli_root)
        exercise_project_base(project_root)


def exercise_missing_warning():
    with tempfile.TemporaryDirectory() as root:
        client = Client(args=("--enable-project-config",), cwd=root)
        try:
            client.initialize(root_path=root)
            assert_warning_count(client, 0)
            client.assert_no_message(show_message)
            client.initialized()
            uri = (Path(root) / "missing-project-config.nix").as_uri()
            client.open_document(uri, "{ x = 1; }")
            client.formatting(49, uri, forbidden=show_message)
            assert_warning_count(client, 0)
        finally:
            stderr = client.close()
        assert ".nixd.json" not in stderr, stderr


def exercise_invalid_warning(kind):
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        bin_dir = root / "bin"
        bin_dir.mkdir()
        formatter = bin_dir / "nixfmt"
        formatter.write_text(
            "#!/bin/sh\nprintf 'built-in formatter fallback'\n", encoding="utf-8"
        )
        formatter.chmod(0o755)
        env = os.environ.copy()
        env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
        path = root / ".nixd.json"
        if kind == "io":
            path.symlink_to(path.name)
            reasons = (os.strerror(errno.ELOOP),)
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
            client.initialize(root_path=str(root))
            assert_warning_count(client, 0)
            logged = client.read_stderr_until(
                lambda stderr: str(path) in stderr
                and all(reason in stderr for reason in reasons)
            )
            assert str(path) in logged and all(reason in logged for reason in reasons)
            client.assert_no_message(show_message)
            client.initialized()
            warning = client.wait_for(show_message)
            assert warning["params"]["type"] == 2, warning
            assert str(path) in warning["params"]["message"], warning
            assert all(
                reason in warning["params"]["message"] for reason in reasons
            ), warning
            assert_warning_count(client, 1)
            uri = (root / "startup-warning.nix").as_uri()
            client.open_document(uri, "{ x = 1; }")
            assert formatted_text(
                client, 50, uri, forbidden=show_message
            ) == "built-in formatter fallback"
            assert_warning_count(client, 1)
        finally:
            client.close()


def exercise_startup_warnings():
    exercise_missing_warning()
    for kind in ("io", "json", "schema"):
        exercise_invalid_warning(kind)


def executable(path, output):
    path.write_text(f"#!/bin/sh\nprintf '{output}'\n", encoding="utf-8")
    path.chmod(0o755)


def write_relative_project(root, evaluator_marker, formatter_marker):
    write_json(root / ".nixd.json", {
        "formatting": {"command": ["./formatter"]},
        "nixpkgs": {"expr": "import ./nixpkgs.nix"},
        "options": {},
    })
    (root / "nixpkgs.nix").write_text(
        f'{{ marker.meta.description = "{evaluator_marker}"; }}\n', encoding="utf-8"
    )
    executable(root / "formatter", formatter_marker)


def wait_for_hover(client, uri, marker, request_id=60):
    deadline = time.monotonic() + 10
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise AssertionError(f"evaluator never observed {marker!r}")
        response = client.hover(request_id, uri, timeout=remaining)
        if marker in json.dumps(response.get("result")):
            return
        if time.monotonic() >= deadline:
            raise AssertionError(
                f"evaluator never observed {marker!r}; last response={response}"
            )
        request_id += 1
        time.sleep(0.05)


def exercise_selected_root(selector):
    evaluator_marker = f"{selector} evaluator cwd"
    formatter_marker = f"{selector} formatter cwd"
    with tempfile.TemporaryDirectory() as temporary:
        base = Path(temporary)
        launch = base / "launch"
        selected = base / "selected"
        launch.mkdir()
        selected.mkdir()
        root = launch if selector == "launch" else selected
        write_relative_project(root, evaluator_marker, formatter_marker)
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
            wait_for_hover(client, uri, evaluator_marker)
            assert formatted_text(client, 70, uri) == formatter_marker
        finally:
            stderr = client.close()
        assert "error: getting status of" not in stderr, stderr


def exercise_unusable_root():
    evaluator_marker = "launch evaluator fallback"
    formatter_marker = "launch formatter fallback"
    with tempfile.TemporaryDirectory() as temporary:
        base = Path(temporary)
        launch = base / "launch"
        launch.mkdir()
        unusable = base / "does-not-exist"
        (launch / "nixpkgs.nix").write_text(
            f'{{ marker.meta.description = "{evaluator_marker}"; }}\n', encoding="utf-8"
        )
        executable(launch / "nixfmt", formatter_marker)
        executable(launch / "project-formatter", "project file was loaded")
        write_json(launch / ".nixd.json", {
            "formatting": {"command": ["./project-formatter"]},
            "nixpkgs": {
                "expr": '{ marker.meta.description = "project file was loaded"; }',
            },
            "options": {},
        })
        env = os.environ.copy()
        env["PATH"] = f"{launch}{os.pathsep}{env['PATH']}"
        client = Client(
            args=("--enable-project-config", "--nixpkgs-expr=import ./nixpkgs.nix"),
            cwd=launch, env=env,
        )
        try:
            client.initialize(root_uri=unusable.as_uri(), root_path=str(launch))
            assert_warning_count(client, 0)
            reason = os.strerror(errno.ENOENT)
            logged = client.read_stderr_until(
                lambda text: "unusable workspace root" in text
                and str(unusable) in text and reason in text
            )
            assert ".nixd.json" not in logged, logged
            client.assert_no_message(show_message)
            client.initialized()
            warning = client.wait_for(show_message)
            assert warning["params"]["type"] == 2, warning
            assert str(unusable) in warning["params"]["message"], warning
            assert reason in warning["params"]["message"], warning
            assert_warning_count(client, 1)
            uri = (launch / "document.nix").as_uri()
            client.open_document(uri, "pkgs.marker")
            wait_for_hover(client, uri, evaluator_marker)
            assert formatted_text(
                client, 80, uri, forbidden=show_message
            ) == formatter_marker
            assert_warning_count(client, 1)
            assert "project file was loaded" not in str(client.received)
        finally:
            client.close()


def exercise_relative_execution():
    for selector in ("root-uri", "root-path", "launch"):
        exercise_selected_root(selector)
    exercise_unusable_root()


SCENARIOS = {
    "selection": exercise_selection,
    "modern-fields": exercise_modern_fields,
    "workspace-overlay": exercise_workspace_overlay,
    "startup-warnings": exercise_startup_warnings,
    "relative-execution": exercise_relative_execution,
}


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in SCENARIOS:
        raise SystemExit(f"usage: {Path(sys.argv[0]).name} {{{', '.join(SCENARIOS)}}}")
    SCENARIOS[sys.argv[1]]()


if __name__ == "__main__":
    main()
