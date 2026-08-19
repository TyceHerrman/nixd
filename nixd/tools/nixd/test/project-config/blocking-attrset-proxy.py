#!/usr/bin/env python3
"""Proxy a real attrset evaluator while withholding one selected response."""

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


def write_message(stream, framed):
    stream.write(framed)
    stream.flush()


def main():
    real_worker = os.environ["REAL_NIXD_ATTRSET_EVAL"]
    block_method = os.environ["BLOCK_RPC_METHOD"]
    ready_path = Path(os.environ["BLOCK_READY_PATH"])
    release_path = Path(os.environ["BLOCK_RELEASE_PATH"])
    child = subprocess.Popen(
        [real_worker],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0,
    )
    blocked_ids = set()
    blocked_ids_lock = threading.Lock()

    def forward_responses():
        while framed_message := read_message(child.stdout):
            framed, message = framed_message
            with blocked_ids_lock:
                should_block = message.get("id") in blocked_ids
                if should_block:
                    blocked_ids.remove(message["id"])
            if should_block:
                ready_path.write_text("response withheld\n", encoding="utf-8")
                while not release_path.exists():
                    time.sleep(0.01)
            write_message(sys.stdout.buffer, framed)

    def forward_stderr():
        while chunk := child.stderr.read(4096):
            sys.stderr.buffer.write(chunk)
            sys.stderr.buffer.flush()

    responses = threading.Thread(target=forward_responses)
    stderr = threading.Thread(target=forward_stderr)
    responses.start()
    stderr.start()
    try:
        while framed_message := read_message(sys.stdin.buffer):
            framed, message = framed_message
            if message.get("method") == block_method:
                with blocked_ids_lock:
                    blocked_ids.add(message["id"])
            write_message(child.stdin, framed)
    finally:
        child.stdin.close()
        responses.join()
        stderr.join()
        child.wait()


if __name__ == "__main__":
    main()
