"""Bounded real-process LSP client for nixd integration tests."""

import json
import os
import select
import shutil
import signal
import subprocess
import threading
import time

TIMEOUT_SECONDS = 30
SHUTDOWN_SECONDS = 3


class Client:
    def __init__(self, *, args=(), cwd=None, env=None):
        executable = os.environ.get("NIXD_BINARY") or shutil.which(
            "nixd", path=(env or os.environ).get("PATH")
        )
        if executable is None:
            raise RuntimeError("nixd is not available on PATH")
        self.received = []
        self._stdout = bytearray()
        self._stderr = bytearray()
        self._stderr_lock = threading.Lock()
        self._stderr_done = threading.Event()
        self._stderr_thread = None
        self._stderr_thread_started = False
        self._close_lock = threading.Lock()
        self._closed = False
        self.graceful_exit = False
        self.pre_initialize_configuration_requests = []
        self.first_workspace_configuration = None
        self.proc = subprocess.Popen(
            [executable, *args],
            cwd=cwd,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
            start_new_session=(os.name == "posix"),
        )
        try:
            os.set_blocking(self.proc.stdin.fileno(), False)
            self._stderr_thread = threading.Thread(
                target=self._drain_stderr, name="nixd-test-stderr", daemon=True
            )
            self._stderr_thread.start()
            self._stderr_thread_started = True
        except BaseException:
            self._cleanup_process(send_exit=False)
            self._closed = True
            raise

    def _drain_stderr(self):
        try:
            while True:
                chunk = os.read(self.proc.stderr.fileno(), 8192)
                if not chunk:
                    return
                with self._stderr_lock:
                    self._stderr.extend(chunk)
        finally:
            self._stderr_done.set()

    @property
    def stderr(self):
        with self._stderr_lock:
            return self._stderr.decode(errors="replace")

    def send(self, message, timeout=TIMEOUT_SECONDS):
        if self.proc.stdin is None or self.proc.stdin.closed:
            raise BrokenPipeError("nixd protocol input is closed")
        payload = json.dumps(message, separators=(",", ":")).encode()
        frame = memoryview(f"Content-Length: {len(payload)}\r\n\r\n".encode() + payload)
        descriptor = self.proc.stdin.fileno()
        deadline = time.monotonic() + timeout
        while frame:
            try:
                written = os.write(descriptor, frame)
            except InterruptedError:
                continue
            except BlockingIOError:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("timed out writing an LSP message")
                _, writable, _ = select.select([], [descriptor], [], remaining)
                if not writable:
                    raise TimeoutError("timed out writing an LSP message")
                continue
            if written == 0:
                raise BrokenPipeError("nixd closed its protocol input")
            frame = frame[written:]

    def _fill_stdout(self, deadline):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(
                f"timed out while reading an LSP message; stderr={self.stderr!r}"
            )
        readable, _, _ = select.select([self.proc.stdout], [], [], remaining)
        if not readable:
            raise TimeoutError(
                f"timed out while reading an LSP message; stderr={self.stderr!r}"
            )
        chunk = os.read(self.proc.stdout.fileno(), 8192)
        if not chunk:
            raise RuntimeError(
                f"nixd closed its protocol stream; stderr={self.stderr!r}"
            )
        self._stdout.extend(chunk)

    def receive(self, timeout=TIMEOUT_SECONDS):
        deadline = time.monotonic() + timeout
        separator = b"\r\n\r\n"
        while separator not in self._stdout:
            self._fill_stdout(deadline)
        header_end = self._stdout.index(separator)
        header_block = bytes(self._stdout[:header_end])
        headers = {}
        for line in header_block.split(b"\r\n"):
            key, value = line.decode().split(":", 1)
            headers[key.lower()] = value.strip()
        length = int(headers["content-length"])
        frame_end = header_end + len(separator) + length
        while len(self._stdout) < frame_end:
            self._fill_stdout(deadline)
        payload = bytes(self._stdout[header_end + len(separator) : frame_end])
        del self._stdout[:frame_end]
        message = json.loads(payload)
        self.received.append(message)
        return message

    def _has_complete_message(self):
        separator = b"\r\n\r\n"
        if separator not in self._stdout:
            return False
        header_end = self._stdout.index(separator)
        headers = {}
        for line in self._stdout[:header_end].split(b"\r\n"):
            key, value = line.decode().split(":", 1)
            headers[key.lower()] = value.strip()
        return len(self._stdout) >= (
            header_end + len(separator) + int(headers["content-length"])
        )

    def wait_for(self, predicate, timeout=TIMEOUT_SECONDS, unexpected_request=None):
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("timed out waiting for an LSP predicate")
            message = self.receive(remaining)
            if predicate(message):
                return message
            if "id" in message and "method" in message:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("timed out replying to an LSP request")
                if unexpected_request is None:
                    if message.get("method") == "workspace/configuration":
                        raise AssertionError(
                            "workspace/configuration must be received through "
                            f"workspace_request: {message}"
                        )
                    self.reply(message, result=None, timeout=remaining)
                else:
                    unexpected_request(message, remaining)

    def _reply_during_initialize(self, message, timeout):
        if message.get("method") == "workspace/configuration":
            self.pre_initialize_configuration_requests.append(message)
            raise AssertionError(
                "workspace/configuration arrived before initialize response: "
                f"{message}"
            )
        self.reply(message, result=None, timeout=timeout)

    def assert_no_message(self, predicate, timeout=0.25):
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            if not self._has_complete_message():
                readable, _, _ = select.select([self.proc.stdout], [], [], remaining)
                if not readable:
                    return
            message = self.receive(remaining)
            if predicate(message):
                raise AssertionError(f"unexpected LSP message: {message}")
            if "id" in message and "method" in message:
                if message.get("method") == "workspace/configuration":
                    raise AssertionError(
                        "workspace/configuration must be received through "
                        f"workspace_request: {message}"
                    )
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return
                self.reply(message, result=None, timeout=remaining)

    def read_stderr_until(self, predicate, timeout=TIMEOUT_SECONDS):
        deadline = time.monotonic() + timeout
        while True:
            text = self.stderr
            if predicate(text):
                return text
            if self._stderr_done.is_set():
                raise RuntimeError(f"nixd closed stderr before predicate: {text!r}")
            if time.monotonic() >= deadline:
                raise TimeoutError(f"stderr predicate not met: {text!r}")
            self._stderr_done.wait(0.01)

    def notify(self, method, params=None, timeout=TIMEOUT_SECONDS):
        self.send(
            {
                "jsonrpc": "2.0",
                "method": method,
                "params": {} if params is None else params,
            },
            timeout=timeout,
        )

    def reply(self, request, *, result=None, error=None, timeout=TIMEOUT_SECONDS):
        response = {"jsonrpc": "2.0", "id": request["id"]}
        if error is None:
            response["result"] = result
        else:
            response["error"] = error
        self.send(response, timeout=timeout)

    def initialize(
        self,
        *,
        root_uri=None,
        root_path=None,
        workspace_folders=None,
        capabilities=None,
        timeout=TIMEOUT_SECONDS,
    ):
        deadline = time.monotonic() + timeout
        params = {"processId": os.getpid(), "capabilities": capabilities or {}}
        if root_uri is not None:
            params["rootUri"] = root_uri
        if root_path is not None:
            params["rootPath"] = root_path
        if workspace_folders is not None:
            params["workspaceFolders"] = workspace_folders
        self.send(
            {
                "jsonrpc": "2.0",
                "id": 0,
                "method": "initialize",
                "params": params,
            },
            timeout=timeout,
        )
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("timed out waiting for initialize response")
        return self.wait_for(
            lambda message: message.get("id") == 0 and "method" not in message,
            timeout=remaining,
            unexpected_request=self._reply_during_initialize,
        )

    def initialized(self):
        self.notify("initialized")

    def open_document(self, uri, text, version=1):
        self.notify(
            "textDocument/didOpen",
            {
                "textDocument": {
                    "uri": uri,
                    "languageId": "nix",
                    "version": version,
                    "text": text,
                }
            },
        )

    def request(self, request_id, method, params, timeout=TIMEOUT_SECONDS):
        deadline = time.monotonic() + timeout
        self.send(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
                "params": params,
            },
            timeout=timeout,
        )
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("timed out waiting for an LSP response")
        return self.wait_for(
            lambda message: message.get("id") == request_id and "method" not in message,
            timeout=remaining,
        )

    def formatting(self, request_id, uri, timeout=TIMEOUT_SECONDS):
        return self.request(
            request_id,
            "textDocument/formatting",
            {
                "textDocument": {"uri": uri},
                "options": {"tabSize": 2, "insertSpaces": True},
            },
            timeout=timeout,
        )

    def workspace_request(self, timeout=TIMEOUT_SECONDS):
        request = self.wait_for(
            lambda message: message.get("method") == "workspace/configuration",
            timeout=timeout,
        )
        if self.first_workspace_configuration is None:
            self.first_workspace_configuration = request
        assert request["params"] == {"items": [{"section": "nixd"}]}, request
        return request

    def _unreaped_leader_state(self):
        try:
            result = os.waitid(
                os.P_PID,
                self.proc.pid,
                os.WEXITED | os.WNOHANG | os.WNOWAIT,
            )
        except ChildProcessError:
            return "reaped"
        return "exited" if result is not None else "running"

    def _wait_for_unreaped_leader(self, deadline):
        state = self._unreaped_leader_state()
        while state == "running":
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return state
            self._stderr_done.wait(min(0.01, remaining))
            state = self._unreaped_leader_state()
        return state

    def _signal_process_group(self, signum):
        try:
            os.killpg(self.proc.pid, signum)
        except (ProcessLookupError, PermissionError):
            pass

    def _cleanup_posix(self, deadline):
        started = time.monotonic()
        duration = max(0.0, deadline - started)
        graceful_deadline = started + duration / 2
        terminate_deadline = started + duration * 3 / 4
        state = self._wait_for_unreaped_leader(graceful_deadline)
        graceful = state != "running"
        if state == "running":
            self._signal_process_group(signal.SIGTERM)
            state = self._wait_for_unreaped_leader(terminate_deadline)
        if state != "reaped":
            # The leader remains an unreaped child here, so its process-group
            # identity cannot be recycled before this final descendant cleanup.
            # Do not probe killpg(PGID, 0) afterward: the zombie leader keeps
            # that probe true even when no live descendants remain.
            self._signal_process_group(signal.SIGKILL)
            if state == "running":
                self._wait_for_unreaped_leader(deadline)
        self.proc.wait(timeout=max(0.01, deadline - time.monotonic()))
        return graceful

    def _cleanup_non_posix(self, deadline):
        try:
            self.proc.wait(timeout=max(0.01, deadline - time.monotonic()))
            return True
        except subprocess.TimeoutExpired:
            self.proc.terminate()
        try:
            self.proc.wait(timeout=max(0.01, deadline - time.monotonic()))
            return False
        except subprocess.TimeoutExpired:
            self.proc.kill()
        self.proc.wait(timeout=max(0.01, deadline - time.monotonic()))
        return False

    def wait_for_graceful_exit(self, timeout=SHUTDOWN_SECONDS):
        deadline = time.monotonic() + timeout
        if os.name == "posix":
            state = self._wait_for_unreaped_leader(deadline)
            if state == "running":
                return False
            self.proc.wait(timeout=max(0.01, deadline - time.monotonic()))
        else:
            try:
                self.proc.wait(timeout=max(0.01, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                return False
        self.graceful_exit = True
        return True

    def _cleanup_process(self, *, send_exit):
        deadline = time.monotonic() + SHUTDOWN_SECONDS
        if send_exit:
            try:
                self.notify(
                    "exit",
                    timeout=min(
                        SHUTDOWN_SECONDS / 4,
                        max(0.0, deadline - time.monotonic()),
                    ),
                )
            except (BrokenPipeError, OSError, TimeoutError):
                pass
        if self.proc.stdin is not None and not self.proc.stdin.closed:
            self.proc.stdin.close()
        if os.name == "posix":
            graceful = self._cleanup_posix(deadline)
        else:
            graceful = self._cleanup_non_posix(deadline)
        self.graceful_exit = self.graceful_exit or (send_exit and graceful)

        if self._stderr_thread_started:
            self._stderr_done.wait(max(0.0, deadline - time.monotonic()))
            self._stderr_thread.join(timeout=max(0.0, deadline - time.monotonic()))
        for stream in (self.proc.stdout, self.proc.stderr):
            if stream is not None and not stream.closed:
                stream.close()

    def close(self):
        with self._close_lock:
            if not self._closed:
                try:
                    self._cleanup_process(send_exit=True)
                finally:
                    self._closed = True
            return self.stderr

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()


import errno
from pathlib import Path
import stat
import sys
import tempfile

sys.dont_write_bytecode = True


CAPABILITIES = {"workspace": {"configuration": True}}
NO_PROVIDERS = ("--nixpkgs-expr=", "--nixos-options-expr=")


def write_json(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


def write_script(path, body):
    path.write_text(
        f"#!{sys.executable}\n" f"{body}\n",
        encoding="utf-8",
    )
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def write_executable(path, body):
    write_script(
        path,
        "import os\n" "import sys\n" "sys.stdin.read()\n" f"{body}",
    )


def test_environment(bin_dir):
    env = os.environ.copy()
    env["PATH"] = os.pathsep.join((str(bin_dir), env.get("PATH", "")))
    return env


def write_formatter(bin_dir, name, marker=None):
    if marker is None:
        body = "sys.stdout.write(os.getcwd())"
    else:
        body = f"sys.stdout.write({marker!r})"
    write_executable(bin_dir / name, body)


def write_project(root, command):
    write_json(root / ".nixd.json", {"formatting": {"command": [command]}})


def formatted_text(client, request_id, uri, timeout=TIMEOUT_SECONDS):
    response = client.formatting(request_id, uri, timeout=timeout)
    assert "error" not in response, response
    edits = response["result"]
    return None if not edits else edits[0]["newText"]


def show_message(message):
    return message.get("method") == "window/showMessage"


def warning_messages(client):
    return [
        message["params"]["message"]
        for message in client.received
        if show_message(message)
    ]


def expect_startup_warning(client, expected):
    assert warning_messages(client) == [], client.received
    client.initialized()
    warning = client.wait_for(show_message)
    assert warning["params"] == {"type": 2, "message": expected}, warning
    assert warning_messages(client) == [expected], client.received


def assert_exact_warning_once(client, expected):
    client.read_stderr_until(lambda text: text.count(expected) >= 1)
    client.assert_no_message(show_message, timeout=0.5)
    assert warning_messages(client) == [expected], client.received
    assert client.stderr.count(expected) == 1, client.stderr


def editor_patch(command):
    return [{"formatting": {"command": [command]}}]


def request_editor_configuration(client):
    client.notify("workspace/didChangeConfiguration", {"settings": {}})
    return client.workspace_request()


def wait_for_formatted_text(client, uri, expected, request_id, timeout=TIMEOUT_SECONDS):
    deadline = time.monotonic() + timeout
    last = None
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        last = formatted_text(client, request_id, uri, timeout=remaining)
        request_id += 1
        if last == expected:
            return request_id
    raise AssertionError(f"formatter never produced {expected!r}; last={last!r}")


def completion_params(uri, character=13):
    return {
        "textDocument": {"uri": uri},
        "position": {"line": 0, "character": character},
        "context": {"triggerKind": 1},
    }


def completion(client, request_id, uri, timeout=TIMEOUT_SECONDS):
    return client.request(
        request_id,
        "textDocument/completion",
        completion_params(uri),
        timeout=timeout,
    )["result"]


def option_completion_params(uri):
    return completion_params(uri, character=6)


def option_completion(client, request_id, uri, timeout=TIMEOUT_SECONDS):
    return client.request(
        request_id,
        "textDocument/completion",
        option_completion_params(uri),
        timeout=timeout,
    )["result"]


def completion_labels(result):
    return {item.get("label") for item in (result or {}).get("items", ())}


def wait_for_endpoint(
    client,
    operation,
    predicate,
    request_id,
    description,
    timeout=TIMEOUT_SECONDS,
):
    deadline = time.monotonic() + timeout
    last = None
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        last = operation(client, request_id, remaining)
        request_id += 1
        if predicate(last):
            return last, request_id
    raise AssertionError(f"{description} never recovered; last={last!r}")


def send_request(client, request_id, method, params):
    client.send(
        {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}
    )


def wait_for_file(path, description, timeout=10):
    deadline = time.monotonic() + timeout
    while not path.exists():
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(f"timed out waiting for {description}: {path}")
        threading.Event().wait(min(0.01, remaining))


BLOCKING_ATTRSET_PROXY = r"""
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time


def read_message(stream):
    raw = bytearray()
    headers = {}
    while True:
        line = stream.readline()
        if not line:
            return None
        raw.extend(line)
        if line == b"\r\n":
            break
        key, value = line.decode().rstrip("\r\n").split(":", 1)
        headers[key.lower()] = value.strip()
    length = int(headers["content-length"])
    payload = stream.read(length)
    if len(payload) != length:
        raise RuntimeError("truncated attrset evaluator message")
    raw.extend(payload)
    return bytes(raw), json.loads(payload)


def main():
    child = subprocess.Popen(
        [os.environ["REAL_NIXD_ATTRSET_EVAL"]],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0,
    )
    token = os.environ["NIXD_TEST_BLOCK_TOKEN"]
    ready = Path(os.environ["NIXD_TEST_BLOCK_READY"])
    release = Path(os.environ["NIXD_TEST_BLOCK_RELEASE"])
    retired_path = os.environ.get("NIXD_TEST_RETIRED_MARKER")
    retired = Path(retired_path) if retired_path else None
    blocked_ids = set()
    blocked_lock = threading.Lock()
    block_this_worker = False
    track_retirement = False

    def forward_responses():
        while framed_message := read_message(child.stdout):
            framed, message = framed_message
            with blocked_lock:
                should_block = message.get("id") in blocked_ids
                blocked_ids.discard(message.get("id"))
            if should_block:
                ready.write_text("response withheld\n", encoding="utf-8")
                while not release.exists():
                    time.sleep(0.01)
            sys.stdout.buffer.write(framed)
            sys.stdout.buffer.flush()

    def forward_stderr():
        while chunk := child.stderr.read(8192):
            sys.stderr.buffer.write(chunk)
            sys.stderr.buffer.flush()

    responses = threading.Thread(target=forward_responses)
    stderr = threading.Thread(target=forward_stderr)
    responses.start()
    stderr.start()
    try:
        while framed_message := read_message(sys.stdin.buffer):
            framed, message = framed_message
            if message.get("method") == "attrset/evalExpr":
                block_this_worker = token in json.dumps(message.get("params"))
                track_retirement = block_this_worker
            elif block_this_worker and message.get("method") in {
                "attrset/attrpathComplete",
                "attrset/optionComplete",
            }:
                with blocked_lock:
                    blocked_ids.add(message["id"])
            child.stdin.write(framed)
            child.stdin.flush()
    finally:
        child.stdin.close()
        responses.join()
        stderr.join()
        child.wait()
        if track_retirement and retired:
            retired.write_text("retired\n", encoding="utf-8")


if __name__ == "__main__":
    main()
"""


def blocking_environment(bin_dir, proxy, token, ready, release, retired=None):
    env = test_environment(bin_dir)
    evaluator = env.get("NIXD_ATTRSET_EVAL")
    if not evaluator:
        raise RuntimeError("NIXD_ATTRSET_EVAL is required for provider recovery")
    env.update(
        {
            "REAL_NIXD_ATTRSET_EVAL": evaluator,
            "NIXD_ATTRSET_EVAL": str(proxy),
            "NIXD_TEST_BLOCK_TOKEN": token,
            "NIXD_TEST_BLOCK_READY": str(ready),
            "NIXD_TEST_BLOCK_RELEASE": str(release),
        }
    )
    if retired is not None:
        env["NIXD_TEST_RETIRED_MARKER"] = str(retired)
    return env


def exercise_empty_formatter():
    config = {
        "formatting": {"command": []},
        "nixpkgs": {"expr": ""},
        "options": {},
    }
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        bin_dir = root / "bin"
        bin_dir.mkdir()
        sentinel = root / "formatter-ran"
        write_script(
            bin_dir / "nixfmt",
            "from pathlib import Path\n"
            f"Path({str(sentinel)!r}).write_text('ran', encoding='utf-8')\n"
            "import sys\n"
            "sys.stdin.read()\n"
            "sys.stdout.write('formatter-ran')",
        )
        uri = (root / "empty-formatter.nix").as_uri()
        with Client(
            args=("--config=" + json.dumps(config),),
            cwd=root,
            env=test_environment(bin_dir),
        ) as client:
            client.initialize(root_path=str(root))
            client.open_document(uri, "{ value = 1; }\n")
            response = client.formatting(1, uri)
            assert response == {"jsonrpc": "2.0", "id": 1, "result": []}, response
        assert not sentinel.exists(), "empty formatter command launched nixfmt"

        write_script(bin_dir / "formatter-fails", "import sys\nsys.exit(23)")
        failed_config = {
            "formatting": {"command": ["formatter-fails"]},
            "nixpkgs": {"expr": ""},
            "options": {},
        }
        with Client(
            args=("--config=" + json.dumps(failed_config),),
            cwd=root,
            env=test_environment(bin_dir),
        ) as client:
            client.initialize(root_path=str(root))
            client.open_document(uri, "{ value = 1; }\n")
            response = client.formatting(2, uri)
            assert response["id"] == 2 and "error" in response, response
            assert response["error"]["message"].startswith(
                "formatting formatter-fails command exited with 23"
            ), response


def exercise_project_opt_in(base):
    root = base / "opt-in"
    bin_dir = root / "bin"
    bin_dir.mkdir(parents=True)
    write_formatter(bin_dir, "nixfmt", "default-formatter")
    write_formatter(bin_dir, "project-formatter", "project-formatter")
    write_project(root, "project-formatter")
    uri = (root / "opt-in.nix").as_uri()
    with Client(
        args=("--enable-project-config", *NO_PROVIDERS),
        cwd=root,
        env=test_environment(bin_dir),
    ) as client:
        client.initialize(root_uri=root.as_uri())
        client.open_document(uri, "{ value = 1; }\n")
        assert formatted_text(client, 10, uri) == "project-formatter"

    with Client(args=NO_PROVIDERS, cwd=root, env=test_environment(bin_dir)) as client:
        client.initialize(root_uri=root.as_uri())
        client.open_document(uri, "{ value = 1; }\n")
        assert formatted_text(client, 10, uri) == "default-formatter"


def exercise_explicit_config(base):
    root = base / "explicit-config"
    bin_dir = root / "bin"
    bin_dir.mkdir(parents=True)
    write_formatter(bin_dir, "nixfmt", "default-formatter")
    write_formatter(bin_dir, "cli-formatter", "cli-formatter")
    write_formatter(bin_dir, "project-formatter", "project-formatter")
    write_project(root, "project-formatter")
    config = {
        "formatting": {"command": ["cli-formatter"]},
        "nixpkgs": {"expr": '{ cliMarker.meta.description = "CLI configuration"; }'},
        "options": {"cli": {"expr": '{ nixdCliOption = { _type = "option"; }; }'}},
    }
    args = (
        "--enable-project-config",
        '--nixpkgs-expr={ legacyMarker.meta.description = "legacy"; }',
        "--nixos-options-expr=" '{ nixdLegacyOption = { _type = "option"; }; }',
        "--config=" + json.dumps(config),
    )
    format_uri = (root / "explicit-format.nix").as_uri()
    hover_uri = (root / "explicit-hover.nix").as_uri()
    options_uri = (root / "explicit-options.nix").as_uri()
    client = Client(args=args, cwd=root, env=test_environment(bin_dir))
    try:
        client.initialize(root_uri=root.as_uri())
        client.initialized()
        client.assert_no_message(show_message)
        client.open_document(format_uri, "{ value = 1; }\n")
        client.open_document(hover_uri, "pkgs.cliMarker\n")
        client.open_document(options_uri, "{ nixd }\n")
        assert formatted_text(client, 11, format_uri) == "cli-formatter"
        hover = client.request(
            12,
            "textDocument/hover",
            {
                "textDocument": {"uri": hover_uri},
                "position": {"line": 0, "character": 10},
            },
        )
        assert "CLI configuration" in json.dumps(hover["result"]), hover
        assert "legacy" not in json.dumps(hover["result"]), hover
        options, _ = wait_for_endpoint(
            client,
            lambda current, current_id, remaining: option_completion(
                current, current_id, options_uri, timeout=remaining
            ),
            lambda result: "nixdCliOption" in completion_labels(result),
            13,
            "explicit config options",
        )
        assert "nixdCliOption" in completion_labels(options), options
        assert "nixdLegacyOption" not in completion_labels(options), options
    finally:
        stderr = client.close()
    assert ".nixd.json" not in stderr, stderr

    empty_config = Client(
        args=("--enable-project-config", "--config={}", *NO_PROVIDERS),
        cwd=root,
        env=test_environment(bin_dir),
    )
    try:
        empty_config.initialize(root_uri=root.as_uri())
        empty_config.initialized()
        empty_config.assert_no_message(show_message)
        empty_config.open_document(format_uri, "{ value = 1; }\n")
        assert formatted_text(empty_config, 20, format_uri) == "default-formatter"
    finally:
        empty_stderr = empty_config.close()
    assert ".nixd.json" not in empty_stderr, empty_stderr

    unreadable = base / "empty-config-unreadable"
    unreadable.mkdir()
    (unreadable / ".nixd.json").symlink_to(".nixd.json")
    empty_config = Client(
        args=("--enable-project-config", "--config={}", *NO_PROVIDERS),
        cwd=unreadable,
        env=test_environment(bin_dir),
    )
    try:
        empty_config.initialize(root_uri=unreadable.as_uri())
        empty_config.initialized()
        empty_config.assert_no_message(show_message)
    finally:
        unreadable_stderr = empty_config.close()
    assert ".nixd.json" not in unreadable_stderr, unreadable_stderr


def exercise_root_precedence(base):
    bin_dir = base / "precedence-bin"
    bin_dir.mkdir()
    env = test_environment(bin_dir)
    roots = {}
    for name in ("root-uri", "root-path", "workspace", "launch"):
        root = base / name
        root.mkdir()
        command = f"{name}-formatter"
        write_formatter(bin_dir, command, name)
        write_project(root, command)
        roots[name] = root

    cases = (
        (
            {
                "root_uri": roots["root-uri"].as_uri(),
                "root_path": str(roots["root-path"]),
                "workspace_folders": [
                    {"uri": roots["workspace"].as_uri(), "name": "workspace"}
                ],
            },
            "root-uri",
        ),
        (
            {
                "root_path": str(roots["root-path"]),
                "workspace_folders": [
                    {"uri": roots["workspace"].as_uri(), "name": "workspace"}
                ],
            },
            "root-path",
        ),
        (
            {
                "root_path": "",
                "workspace_folders": [
                    {"uri": roots["workspace"].as_uri(), "name": "workspace"}
                ],
            },
            "workspace",
        ),
        ({"root_path": ""}, "launch"),
    )
    for index, (initialize, expected) in enumerate(cases, 20):
        root = roots[expected]
        uri = (root / f"{expected}.nix").as_uri()
        with Client(
            args=(*NO_PROVIDERS, "--enable-project-config"),
            cwd=roots["launch"],
            env=env,
        ) as client:
            client.initialize(**initialize)
            client.open_document(uri, "{ value = 1; }\n")
            assert formatted_text(client, index, uri) == expected


def exercise_empty_project_rebases(base):
    launch = base / "empty-launch"
    selected = base / "empty-selected"
    bin_dir = base / "empty-bin"
    launch.mkdir()
    selected.mkdir()
    bin_dir.mkdir()
    write_formatter(bin_dir, "nixfmt")
    write_json(selected / ".nixd.json", {})
    (selected / "nixpkgs.nix").write_text(
        '{ cwdMarker.meta.description = "selected evaluator cwd"; }\n',
        encoding="utf-8",
    )
    uri = (selected / "empty-project.nix").as_uri()
    with Client(
        args=(
            "--enable-project-config",
            "--nixpkgs-expr=import ./nixpkgs.nix",
            "--nixos-options-expr=",
        ),
        cwd=launch,
        env=test_environment(bin_dir),
    ) as client:
        client.initialize(root_uri=selected.as_uri())
        client.open_document(uri, "pkgs.cwdMarker\n")
        actual_cwd = formatted_text(client, 30, uri)
        assert Path(actual_cwd).resolve() == selected.resolve(), (
            actual_cwd,
            selected,
        )
        hover = client.request(
            31,
            "textDocument/hover",
            {
                "textDocument": {"uri": uri},
                "position": {"line": 0, "character": 9},
            },
        )
        assert "selected evaluator cwd" in json.dumps(hover["result"]), hover


def exercise_no_fallback_roots(base):
    launch = base / "fallback-launch"
    lower = base / "fallback-lower"
    bin_dir = base / "fallback-bin"
    launch.mkdir()
    lower.mkdir()
    bin_dir.mkdir()
    write_formatter(bin_dir, "nixfmt")
    write_formatter(bin_dir, "must-not-load", "must-not-load")
    write_project(lower, "must-not-load")
    env = test_environment(bin_dir)
    uri = (launch / "fallback.nix").as_uri()

    missing = base / "missing-root"
    with Client(
        args=(*NO_PROVIDERS, "--enable-project-config"), cwd=launch, env=env
    ) as client:
        client.initialize(root_uri=missing.as_uri(), root_path=str(lower))
        expected = (
            "cannot use rootUri as project configuration root "
            f"{missing}: {os.strerror(errno.ENOENT)}"
        )
        expect_startup_warning(client, expected)
        client.open_document(uri, "{ value = 1; }\n")
        assert Path(formatted_text(client, 40, uri)).resolve() == launch.resolve()
        assert_exact_warning_once(client, expected)

    missing_root_path = base / "missing-root-path"
    with Client(
        args=(*NO_PROVIDERS, "--enable-project-config"), cwd=launch, env=env
    ) as client:
        client.initialize(
            root_path=str(missing_root_path),
            workspace_folders=[
                {"uri": lower.as_uri(), "name": "must-not-fall-through"}
            ],
        )
        expected = (
            "cannot use rootPath as project configuration root "
            f"{missing_root_path}: {os.strerror(errno.ENOENT)}"
        )
        expect_startup_warning(client, expected)
        client.open_document(uri, "{ value = 1; }\n")
        assert Path(formatted_text(client, 41, uri)).resolve() == launch.resolve()
        assert_exact_warning_once(client, expected)

    missing_workspace = base / "missing-workspace"
    with Client(
        args=(*NO_PROVIDERS, "--enable-project-config"), cwd=launch, env=env
    ) as client:
        client.initialize(
            root_path="",
            workspace_folders=[{"uri": missing_workspace.as_uri(), "name": "missing"}],
        )
        expected = (
            "cannot use workspaceFolders[0] as project configuration root "
            f"{missing_workspace}: {os.strerror(errno.ENOENT)}"
        )
        expect_startup_warning(client, expected)
        client.open_document(uri, "{ value = 1; }\n")
        assert Path(formatted_text(client, 42, uri)).resolve() == launch.resolve()
        assert_exact_warning_once(client, expected)

    with Client(
        args=(*NO_PROVIDERS, "--enable-project-config"), cwd=launch, env=env
    ) as client:
        client.initialize(root_uri="https://example.test/root", root_path=str(lower))
        expected = (
            "cannot use rootUri as project configuration root: "
            "clangd only supports 'file' URI scheme for workspace files at "
            "(root).rootUri"
        )
        expect_startup_warning(client, expected)
        client.open_document(uri, "{ value = 1; }\n")
        assert Path(formatted_text(client, 43, uri)).resolve() == launch.resolve()
        assert_exact_warning_once(client, expected)

    with Client(
        args=(*NO_PROVIDERS, "--enable-project-config"), cwd=launch, env=env
    ) as client:
        client.initialize(
            root_uri=lower.as_uri(),
            workspace_folders=[
                {"uri": lower.as_uri(), "name": "valid"},
                {"uri": 42, "name": "malformed"},
            ],
        )
        expected = (
            "cannot load project configuration with multiple workspace "
            "folders (2 supplied)"
        )
        expect_startup_warning(client, expected)
        client.open_document(uri, "{ value = 1; }\n")
        assert Path(formatted_text(client, 44, uri)).resolve() == launch.resolve()
        assert_exact_warning_once(client, expected)


def exercise_no_ancestor_search(base):
    launch = base / "ancestor-launch"
    parent = base / "ancestor"
    child = parent / "child"
    bin_dir = base / "ancestor-bin"
    launch.mkdir()
    child.mkdir(parents=True)
    bin_dir.mkdir()
    write_formatter(bin_dir, "nixfmt")
    write_formatter(bin_dir, "ancestor-formatter", "ancestor")
    write_project(parent, "ancestor-formatter")
    uri = (child / "no-ancestor.nix").as_uri()
    with Client(
        args=(*NO_PROVIDERS, "--enable-project-config"),
        cwd=launch,
        env=test_environment(bin_dir),
    ) as client:
        client.initialize(root_uri=child.as_uri())
        client.initialized()
        client.assert_no_message(show_message)
        client.open_document(uri, "{ value = 1; }\n")
        assert Path(formatted_text(client, 50, uri)).resolve() == launch.resolve()


def exercise_source_selection():
    with tempfile.TemporaryDirectory() as temporary:
        base = Path(temporary)
        exercise_project_opt_in(base)
        exercise_explicit_config(base)
        exercise_root_precedence(base)
        exercise_empty_project_rebases(base)
        exercise_no_fallback_roots(base)
        exercise_no_ancestor_search(base)


def exercise_startup_case(base, kind, request_id):
    launch = base / f"{kind}-launch"
    selected = base / f"{kind}-selected"
    bin_dir = base / f"{kind}-bin"
    launch.mkdir()
    selected.mkdir()
    bin_dir.mkdir()
    write_formatter(bin_dir, "nixfmt")
    project_path = selected / ".nixd.json"
    if kind == "missing":
        expected = None
    elif kind == "invalid-json":
        project_path.write_text("{", encoding="utf-8")
        expected = (
            f"failed to load project configuration at {project_path}: "
            "JSON result cannot be parsed: [1:1, byte=1]: Expected object key"
        )
    elif kind == "invalid-schema":
        project_path.write_text('{"formatting":{"command":42}}', encoding="utf-8")
        expected = (
            f"failed to load project configuration at {project_path}: "
            "JSON schema mismatch: expected array at "
            "(root).formatting.command"
        )
    elif kind == "unreadable":
        project_path.symlink_to(project_path.name)
        expected = (
            f"failed to load project configuration at {project_path}: "
            f"{os.strerror(errno.ELOOP)}"
        )
    else:
        raise AssertionError(f"unknown startup case: {kind}")

    uri = (launch / f"{kind}.nix").as_uri()
    client = Client(
        args=(*NO_PROVIDERS, "--enable-project-config"),
        cwd=launch,
        env=test_environment(bin_dir),
    )
    try:
        client.initialize(root_uri=selected.as_uri())
        if expected is None:
            assert warning_messages(client) == []
            client.initialized()
            client.assert_no_message(show_message)
        else:
            logged = client.read_stderr_until(lambda text: expected in text)
            assert expected in logged, logged
            expect_startup_warning(client, expected)
        client.open_document(uri, "{ value = 1; }\n")
        assert (
            Path(formatted_text(client, request_id, uri)).resolve() == launch.resolve()
        )
        if expected is None:
            client.assert_no_message(show_message, timeout=0.5)
            assert warning_messages(client) == []
            assert ".nixd.json" not in client.stderr, client.stderr
        else:
            assert_exact_warning_once(client, expected)
    finally:
        client.close()


def exercise_startup_warnings():
    with tempfile.TemporaryDirectory() as temporary:
        base = Path(temporary)
        for request_id, kind in enumerate(
            ("missing", "invalid-json", "invalid-schema", "unreadable"), 60
        ):
            exercise_startup_case(base, kind, request_id)


def exercise_editor_overlays():
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        bin_dir = root / "bin"
        bin_dir.mkdir()
        for marker in (
            "base",
            "editor-one",
            "editor-two",
            "retained",
            "newer-success",
            "newer-failure",
            "failure-barrier",
            "stale-success",
        ):
            write_formatter(bin_dir, marker, marker)
        write_project(root, "base")
        uri = (root / "editor-overlays.nix").as_uri()
        client = Client(
            args=(*NO_PROVIDERS, "--enable-project-config"),
            cwd=root,
            env=test_environment(bin_dir),
        )
        request_id = 100
        try:
            client.initialize(root_uri=root.as_uri(), capabilities=CAPABILITIES)
            client.initialized()
            initial = client.workspace_request()
            client.reply(initial, result=[None])
            client.open_document(uri, "{ value = 1; }\n")
            request_id = wait_for_formatted_text(client, uri, "base", request_id)

            request = request_editor_configuration(client)
            client.reply(request, result=editor_patch("editor-one"))
            request_id = wait_for_formatted_text(client, uri, "editor-one", request_id)
            request = request_editor_configuration(client)
            client.reply(request, result=[None])
            request_id = wait_for_formatted_text(client, uri, "base", request_id)

            request = request_editor_configuration(client)
            client.reply(request, result=editor_patch("editor-two"))
            request_id = wait_for_formatted_text(client, uri, "editor-two", request_id)
            request = request_editor_configuration(client)
            client.reply(request, result=[{}])
            request_id = wait_for_formatted_text(client, uri, "base", request_id)

            request = request_editor_configuration(client)
            client.reply(request, result=editor_patch("retained"))
            request_id = wait_for_formatted_text(client, uri, "retained", request_id)

            invalid_responses = (
                (
                    [{"formatting": {"command": 42}}],
                    "workspace/configuration: parse error expected array at "
                    "(root).formatting.command",
                ),
                (
                    [{}, {}],
                    "workspace/configuration: expected exactly one array item",
                ),
                (
                    [],
                    "workspace/configuration: expected exactly one array item",
                ),
            )
            for result, error_text in invalid_responses:
                before = client.stderr.count(error_text)
                request = request_editor_configuration(client)
                client.reply(request, result=result)
                client.read_stderr_until(
                    lambda text, before=before, error_text=error_text: (
                        text.count(error_text) > before
                    )
                )
                assert formatted_text(client, request_id, uri) == "retained"
                request_id += 1

            response_error = "active workspace response failed"
            request = request_editor_configuration(client)
            client.reply(request, error={"code": -32603, "message": response_error})
            client.read_stderr_until(lambda text: response_error in text)
            assert formatted_text(client, request_id, uri) == "retained"
            request_id += 1

            older = request_editor_configuration(client)
            newer = request_editor_configuration(client)
            client.reply(newer, result=editor_patch("newer-success"))
            request_id = wait_for_formatted_text(
                client, uri, "newer-success", request_id
            )
            client.reply(older, result=editor_patch("stale-success"))
            barrier_error = "workspace/configuration: expected exactly one array item"
            before = client.stderr.count(barrier_error)
            barrier = request_editor_configuration(client)
            client.reply(barrier, result=[])
            client.read_stderr_until(lambda text: text.count(barrier_error) > before)
            assert formatted_text(client, request_id, uri) == "newer-success"
            request_id += 1

            older = request_editor_configuration(client)
            newer = request_editor_configuration(client)
            client.reply(newer, result=editor_patch("newer-failure"))
            request_id = wait_for_formatted_text(
                client, uri, "newer-failure", request_id
            )
            stale_error = "delayed stale response must not be reported"
            client.reply(older, error={"code": -32603, "message": stale_error})
            barrier = request_editor_configuration(client)
            client.reply(barrier, result=editor_patch("failure-barrier"))
            wait_for_formatted_text(client, uri, "failure-barrier", request_id)
            assert stale_error not in client.stderr, client.stderr
        finally:
            client.close()


def exercise_provider_recovery():
    token = "nixd-test-obsolete-provider"
    old_option_one = "nixdOldOptionOne"
    old_option_two = "nixdOldOptionTwo"
    current_option_one = "nixdCurrentOptionOne"
    current_option_two = "nixdCurrentOptionTwo"
    old_option_labels = {old_option_one, old_option_two}
    current_option_labels = {current_option_one, current_option_two}
    old_nix_label = "nixdOldPackage"
    current_nix_label = "nixdCurrentPackage"
    old_config = {
        "formatting": {"command": ["provider-old"]},
        "nixpkgs": {
            "expr": (
                f'let generation = "{token}"; in '
                f'{{ {old_nix_label} = {{ meta.description = "old"; }}; }}'
            )
        },
        "options": {
            "old-one": {
                "expr": (
                    f'let generation = "{token}"; in '
                    f'{{ {old_option_one} = {{ _type = "option"; }}; }}'
                )
            },
            "old-two": {
                "expr": (
                    f'let generation = "{token}"; in '
                    f'{{ {old_option_two} = {{ _type = "option"; }}; }}'
                )
            },
        },
    }
    current_config = {
        "formatting": {"command": ["provider-current"]},
        "nixpkgs": {
            "expr": f'{{ {current_nix_label} = {{ meta.description = "current"; }}; }}'
        },
        "options": {
            "current-one": {
                "expr": f'{{ {current_option_one} = {{ _type = "option"; }}; }}'
            },
            "current-two": {
                "expr": f'{{ {current_option_two} = {{ _type = "option"; }}; }}'
            },
        },
    }
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        bin_dir = root / "bin"
        bin_dir.mkdir()
        for marker in ("provider-old", "provider-current"):
            write_formatter(bin_dir, marker, marker)
        proxy = root / "blocking-attrset-proxy.py"
        write_script(proxy, BLOCKING_ATTRSET_PROXY)
        ready = root / "old-provider-response-ready"
        release = root / "release-old-provider-response"
        release.write_text("allow setup\n", encoding="utf-8")
        env = blocking_environment(bin_dir, proxy, token, ready, release)
        nix_uri = (root / "provider-nixpkgs.nix").as_uri()
        options_uri = (root / "provider-options.nix").as_uri()
        client = Client(
            args=("--config=" + json.dumps(old_config),),
            cwd=root,
            env=env,
        )
        request_id = 200
        try:
            client.initialize(root_uri=root.as_uri(), capabilities=CAPABILITIES)
            client.initialized()
            initial_request = client.workspace_request()
            client.reply(initial_request, result=[None])
            client.open_document(nix_uri, "with pkgs; [ nixd ]\n")
            client.open_document(options_uri, "{ nixd }\n")

            initial_options, request_id = wait_for_endpoint(
                client,
                lambda current, current_id, remaining: option_completion(
                    current, current_id, options_uri, timeout=remaining
                ),
                lambda result: old_option_labels <= completion_labels(result),
                request_id,
                "initial option fanout",
            )
            assert old_option_labels <= completion_labels(initial_options)
            initial_nixpkgs, request_id = wait_for_endpoint(
                client,
                lambda current, current_id, remaining: completion(
                    current, current_id, nix_uri, timeout=remaining
                ),
                lambda result: old_nix_label in completion_labels(result),
                request_id,
                "initial nixpkgs",
            )
            assert old_nix_label in completion_labels(initial_nixpkgs)

            ready.unlink(missing_ok=True)
            release.unlink()
            stale_options_id = request_id
            send_request(
                client,
                stale_options_id,
                "textDocument/completion",
                option_completion_params(options_uri),
            )
            request_id += 1
            wait_for_file(ready, "withheld old option response")
            current = request_editor_configuration(client)
            client.reply(current, result=[current_config])
            stale_options = client.wait_for(
                lambda message: message.get("id") == stale_options_id,
                timeout=10,
            )
            assert not (
                old_option_labels & completion_labels(stale_options.get("result"))
            ), stale_options
            release.write_text("release options\n", encoding="utf-8")
            request_id = wait_for_formatted_text(
                client, options_uri, "provider-current", request_id
            )
            current_options, request_id = wait_for_endpoint(
                client,
                lambda current, current_id, remaining: option_completion(
                    current, current_id, options_uri, timeout=remaining
                ),
                lambda result: current_option_labels <= completion_labels(result),
                request_id,
                "current option fanout",
            )
            assert current_option_labels <= completion_labels(current_options)

            ready.unlink(missing_ok=True)
            release.unlink()
            old = request_editor_configuration(client)
            client.reply(old, result=[old_config])
            request_id = wait_for_formatted_text(
                client, nix_uri, "provider-old", request_id
            )
            stale_nixpkgs_id = request_id
            send_request(
                client,
                stale_nixpkgs_id,
                "textDocument/completion",
                completion_params(nix_uri),
            )
            request_id += 1
            wait_for_file(ready, "withheld old nixpkgs response")
            current = request_editor_configuration(client)
            client.reply(current, result=[current_config])
            request_id = wait_for_formatted_text(
                client, nix_uri, "provider-current", request_id
            )
            release.write_text("release nixpkgs\n", encoding="utf-8")
            stale_nixpkgs = client.wait_for(
                lambda message: message.get("id") == stale_nixpkgs_id,
                timeout=10,
            )
            assert old_nix_label not in completion_labels(
                stale_nixpkgs.get("result")
            ), stale_nixpkgs
            current_nixpkgs, request_id = wait_for_endpoint(
                client,
                lambda current, current_id, remaining: completion(
                    current, current_id, nix_uri, timeout=remaining
                ),
                lambda result: current_nix_label in completion_labels(result),
                request_id,
                "current nixpkgs",
            )
            assert current_nix_label in completion_labels(current_nixpkgs)
        finally:
            release.write_text("cleanup\n", encoding="utf-8")
            client.close()


def exercise_provider_shutdown_drain():
    """A ready provider reply can finish during the bounded shutdown drain."""
    token = "nixd-test-provider-shutdown-drain"
    label = "nixdShutdownDrainOption"
    config = {
        "formatting": {"command": []},
        "nixpkgs": {"expr": ""},
        "options": {
            "drain": {
                "expr": (
                    f'let generation = "{token}"; in '
                    f'{{ {label} = {{ _type = "option"; }}; }}'
                )
            }
        },
    }
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        bin_dir = root / "bin"
        bin_dir.mkdir()
        proxy = root / "blocking-attrset-proxy.py"
        write_script(proxy, BLOCKING_ATTRSET_PROXY)
        ready = root / "provider-drain-response"
        release = root / "release-provider-drain-response"
        release.write_text("allow setup\n", encoding="utf-8")
        env = blocking_environment(bin_dir, proxy, token, ready, release)
        uri = (root / "provider-shutdown-drain.nix").as_uri()
        client = Client(args=("--config=" + json.dumps(config),), cwd=root, env=env)
        request_id = 710
        releaser = None
        try:
            client.initialize(root_uri=root.as_uri())
            client.open_document(uri, "{ nixd }\n")
            active, request_id = wait_for_endpoint(
                client,
                lambda current, current_id, remaining: option_completion(
                    current, current_id, uri, timeout=remaining
                ),
                lambda result: label in completion_labels(result),
                request_id,
                "provider before shutdown drain",
            )
            assert label in completion_labels(active), active

            ready.unlink(missing_ok=True)
            release.unlink()
            send_request(
                client,
                request_id,
                "textDocument/completion",
                option_completion_params(uri),
            )
            wait_for_file(ready, "provider reply awaiting shutdown drain")

            def release_during_drain():
                threading.Event().wait(0.05)
                release.write_text("release during drain\n", encoding="utf-8")

            releaser = threading.Thread(target=release_during_drain)
            releaser.start()
            client.notify("exit")
            client.proc.stdin.close()
            response = client.wait_for(
                lambda message: message.get("id") == request_id,
                timeout=5,
            )
            assert label in completion_labels(response.get("result")), response
            releaser.join()
            assert client.wait_for_graceful_exit(timeout=5), client.stderr
        finally:
            release.write_text("cleanup\n", encoding="utf-8")
            if releaser is not None:
                releaser.join()
            client.close()


def exercise_provider_shutdown_pending():
    """A blocked provider RPC cannot strand server destruction."""
    token = "nixd-test-provider-shutdown"
    config = {
        "formatting": {"command": []},
        "nixpkgs": {"expr": ""},
        "options": {
            "blocked": {
                "expr": (
                    f'let generation = "{token}"; in '
                    '{ blockedOption = { _type = "option"; }; }'
                )
            }
        },
    }
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        bin_dir = root / "bin"
        bin_dir.mkdir()
        proxy = root / "blocking-attrset-proxy.py"
        write_script(proxy, BLOCKING_ATTRSET_PROXY)
        ready = root / "blocked-provider-response"
        release = root / "release-provider-response"
        env = blocking_environment(bin_dir, proxy, token, ready, release)
        uri = (root / "provider-shutdown.nix").as_uri()
        client = Client(args=("--config=" + json.dumps(config),), cwd=root, env=env)
        try:
            client.initialize(root_uri=root.as_uri())
            client.open_document(uri, "{ block }\n")
            send_request(
                client,
                700,
                "textDocument/completion",
                option_completion_params(uri),
            )
            wait_for_file(ready, "blocked provider response")
            response = client.request(701, "shutdown", {}, timeout=5)
            assert response == {
                "jsonrpc": "2.0",
                "id": 701,
                "result": None,
            }, response
            client.notify("exit")
            client.proc.stdin.close()
            assert client.wait_for_graceful_exit(timeout=5), client.stderr
        finally:
            release.write_text("cleanup\n", encoding="utf-8")
            client.close()


def exercise_provider_retirement():
    """Removed option workers exit while replacement workers remain usable."""
    token = "nixd-test-retired-provider"
    old_config = {
        "formatting": {"command": []},
        "nixpkgs": {"expr": ""},
        "options": {
            "obsolete": {
                "expr": (
                    f'let generation = "{token}"; in '
                    '{ nixdObsoleteOption = { _type = "option"; }; }'
                )
            }
        },
    }
    current_config = {
        "formatting": {"command": []},
        "nixpkgs": {"expr": ""},
        "options": {
            "current": {"expr": '{ nixdCurrentOption = { _type = "option"; }; }'}
        },
    }
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        bin_dir = root / "bin"
        bin_dir.mkdir()
        proxy = root / "blocking-attrset-proxy.py"
        write_script(proxy, BLOCKING_ATTRSET_PROXY)
        ready = root / "provider-response"
        release = root / "release-provider-response"
        retired = root / "obsolete-provider-retired"
        release.write_text("allow replies\n", encoding="utf-8")
        env = blocking_environment(
            bin_dir, proxy, token, ready, release, retired=retired
        )
        uri = (root / "provider-retirement.nix").as_uri()
        client = Client(args=("--config=" + json.dumps(old_config),), cwd=root, env=env)
        request_id = 720
        try:
            client.initialize(root_uri=root.as_uri(), capabilities=CAPABILITIES)
            client.initialized()
            initial = client.workspace_request()
            client.reply(initial, result=[None])
            client.open_document(uri, "{ nixd }\n")
            old, request_id = wait_for_endpoint(
                client,
                lambda current, current_id, remaining: option_completion(
                    current, current_id, uri, timeout=remaining
                ),
                lambda result: "nixdObsoleteOption" in completion_labels(result),
                request_id,
                "obsolete option provider",
            )
            assert "nixdObsoleteOption" in completion_labels(old), old

            update = request_editor_configuration(client)
            client.reply(update, result=[current_config])
            current, request_id = wait_for_endpoint(
                client,
                lambda active, current_id, remaining: option_completion(
                    active, current_id, uri, timeout=remaining
                ),
                lambda result: "nixdCurrentOption" in completion_labels(result),
                request_id,
                "replacement option provider",
            )
            assert "nixdCurrentOption" in completion_labels(current), current
            wait_for_file(retired, "obsolete provider retirement", timeout=5)
            still_current = option_completion(client, request_id, uri, timeout=5)
            assert "nixdCurrentOption" in completion_labels(
                still_current
            ), still_current
        finally:
            client.close()


def exercise_formatter_shutdown_queue():
    """Queued formatting work cannot launch after shutdown acknowledgement."""
    request_count = 128
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        bin_dir = root / "bin"
        bin_dir.mkdir()
        launches = root / "formatter-launches"
        formatter = bin_dir / "queued-formatter"
        write_script(
            formatter,
            "from pathlib import Path\n"
            "import os\n"
            "import time\n"
            f"with Path({str(launches)!r}).open('a', encoding='utf-8') as stream:\n"
            "    stream.write(str(os.getpid()) + '\\n')\n"
            "while True:\n"
            "    time.sleep(1)",
        )
        config = {
            "formatting": {"command": [str(formatter)]},
            "nixpkgs": {"expr": ""},
            "options": {},
        }
        uri = (root / "formatter-queue.nix").as_uri()
        client = Client(
            args=("--config=" + json.dumps(config),),
            cwd=root,
            env=test_environment(bin_dir),
        )

        def launch_count():
            if not launches.exists():
                return 0
            return len(launches.read_text(encoding="utf-8").splitlines())

        try:
            client.initialize(root_uri=root.as_uri())
            client.open_document(uri, "{ value = 1; }\n")
            request_ids = set(range(800, 800 + request_count))
            for request_id in request_ids:
                send_request(
                    client,
                    request_id,
                    "textDocument/formatting",
                    {
                        "textDocument": {"uri": uri},
                        "options": {"tabSize": 2, "insertSpaces": True},
                    },
                )

            wait_for_file(launches, "active formatter launches")
            stable_count = -1
            stable_since = time.monotonic()
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                current_count = launch_count()
                if current_count != stable_count:
                    stable_count = current_count
                    stable_since = time.monotonic()
                elif time.monotonic() - stable_since >= 0.25:
                    break
                threading.Event().wait(0.01)
            assert 0 < stable_count < request_count, stable_count

            shutdown = client.request(950, "shutdown", {}, timeout=5)
            assert shutdown == {
                "jsonrpc": "2.0",
                "id": 950,
                "result": None,
            }, shutdown
            launches_at_shutdown = launch_count()

            responses = {
                message["id"]: message
                for message in client.received
                if message.get("id") in request_ids and "method" not in message
            }
            deadline = time.monotonic() + 15
            while len(responses) != request_count:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(
                        f"received {len(responses)}/{request_count} formatter replies"
                    )
                message = client.receive(remaining)
                if message.get("id") in request_ids and "method" not in message:
                    responses[message["id"]] = message

            unavailable = [
                response
                for response in responses.values()
                if "formatting is unavailable during shutdown"
                in response.get("error", {}).get("message", "")
            ]
            assert unavailable, "queued requests all launched before rejection"
            threading.Event().wait(0.25)
            assert launch_count() == launches_at_shutdown, (
                launches_at_shutdown,
                launch_count(),
            )
            client.notify("exit")
            client.proc.stdin.close()
            assert client.wait_for_graceful_exit(timeout=5), client.stderr
        finally:
            client.close()


def exercise_child_fork_stress():
    """Provider and formatter child setup can run concurrently without FD leaks."""
    iterations = 32
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        bin_dir = root / "bin"
        bin_dir.mkdir()
        formatter = bin_dir / "fork-stress-formatter"
        write_script(
            formatter,
            "import sys\n"
            "source = sys.stdin.read()\n"
            "sys.stdout.write(source + '# formatted\\n')",
        )
        config = {
            "formatting": {"command": [str(formatter)]},
            "nixpkgs": {"expr": ""},
            "options": {},
        }
        uri = (root / "child-fork-stress.nix").as_uri()
        client = Client(
            args=("--config=" + json.dumps(config),),
            cwd=root,
            env=test_environment(bin_dir),
        )
        request_ids = set(range(1000, 1000 + iterations))
        try:
            client.initialize(root_uri=root.as_uri(), capabilities=CAPABILITIES)
            client.initialized()
            initial = client.workspace_request()
            client.reply(initial, result=[None])
            client.open_document(uri, "{ nixd }\n")

            for iteration, request_id in enumerate(sorted(request_ids)):
                update = request_editor_configuration(client)
                send_request(
                    client,
                    request_id,
                    "textDocument/formatting",
                    {
                        "textDocument": {"uri": uri},
                        "options": {"tabSize": 2, "insertSpaces": True},
                    },
                )
                label = f"nixdStressOption{iteration}"
                client.reply(
                    update,
                    result=[
                        {
                            "options": {
                                f"stress-{iteration}": {
                                    "expr": f'{{ {label} = {{ _type = "option"; }}; }}'
                                }
                            }
                        }
                    ],
                )

            responses = {
                message["id"]: message
                for message in client.received
                if message.get("id") in request_ids and "method" not in message
            }
            deadline = time.monotonic() + 20
            while len(responses) != iterations:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(
                        f"received {len(responses)}/{iterations} formatter replies"
                    )
                message = client.receive(remaining)
                if "id" in message and "method" in message:
                    client.reply(message, result=None, timeout=remaining)
                elif message.get("id") in request_ids:
                    responses[message["id"]] = message

            for response in responses.values():
                assert "error" not in response, response
                assert response.get("result"), response

            current, _ = wait_for_endpoint(
                client,
                lambda active, current_id, remaining: option_completion(
                    active, current_id, uri, timeout=remaining
                ),
                lambda result: "nixdStressOption31" in completion_labels(result),
                1100,
                "latest provider after child-fork stress",
            )
            assert "nixdStressOption31" in completion_labels(current), current
        finally:
            client.close()


def exercise_shutdown_outbound():
    """Shutdown remains responsive while workspace/configuration is unanswered."""
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        client = Client(cwd=root)
        try:
            client.initialize(
                root_uri=root.as_uri(), capabilities=CAPABILITIES, timeout=5
            )
            client.initialized()
            outbound = client.workspace_request(timeout=5)
            assert outbound["params"] == {"items": [{"section": "nixd"}]}, outbound
            response = client.request(900, "shutdown", {}, timeout=5)
            assert response == {"jsonrpc": "2.0", "id": 900, "result": None}, response
            client.notify("exit")
            assert client.wait_for_graceful_exit(timeout=5), client.stderr
        finally:
            client.close()


SCENARIOS = {
    "empty-formatter": exercise_empty_formatter,
    "source-selection": exercise_source_selection,
    "startup-warnings": exercise_startup_warnings,
    "editor-overlays": exercise_editor_overlays,
    "provider-recovery": exercise_provider_recovery,
    "provider-shutdown-drain": exercise_provider_shutdown_drain,
    "provider-shutdown-pending": exercise_provider_shutdown_pending,
    "provider-retirement": exercise_provider_retirement,
    "formatter-shutdown-queue": exercise_formatter_shutdown_queue,
    "child-fork-stress": exercise_child_fork_stress,
    "shutdown-outbound": exercise_shutdown_outbound,
}


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in SCENARIOS:
        names = ", ".join(sorted(SCENARIOS))
        raise SystemExit(f"usage: {Path(sys.argv[0]).name} {{{names}}}")
    scenario = sys.argv[1]
    try:
        SCENARIOS[scenario]()
    except BaseException as error:
        raise SystemExit(f"{scenario}: {error}") from error


if __name__ == "__main__":
    main()
