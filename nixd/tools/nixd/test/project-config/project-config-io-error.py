#!/usr/bin/env python3
"""Run the inaccessible project-file fixture with failure-safe cleanup."""

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def main():
    source = Path(sys.argv[1])
    root = Path(sys.argv[2])
    if root.exists():
        root.chmod(0o700)
        shutil.rmtree(root)
    root.mkdir()
    project_file = root / ".nixd.json"
    project_file.touch()
    project_file.chmod(0)
    try:
        transcript = source.read_text(encoding="utf-8").replace("ROOT", str(root))
        transcript = transcript.replace(
            '"processId": 123', f'"processId": {os.getpid()}'
        )
        with tempfile.TemporaryFile() as input_file:
            input_file.write(transcript.encode())
            input_file.seek(0)
            completed = subprocess.run(
                ["nixd", "--enable-project-config", "--lit-test"],
                stdin=input_file,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
        sys.stdout.buffer.write(completed.stdout)
        if completed.returncode != 0 or not completed.stdout:
            sys.stderr.buffer.write(completed.stderr)
            raise SystemExit(completed.returncode or 1)
    finally:
        project_file.chmod(0o600)
        root.chmod(0o700)
        shutil.rmtree(root)


if __name__ == "__main__":
    main()
