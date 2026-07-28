#!/usr/bin/env python3
"""Fail-open launch wrapper for Process Lasso Game Mode."""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time

import psutil

from game_mode import MARKER_ENV, apply_launch_policy, socket_path


def _request(argv, profile=None):
    request = {"pid": os.getpid(), "start_time": psutil.Process().create_time(),
               "argv": argv, "profile": profile,
               "environment": {k: v for k, v in os.environ.items()
                               if k.startswith("Steam") or k.startswith("STEAM_")}}
    deadline = time.monotonic() + 5
    started = False
    while time.monotonic() < deadline:
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            client.connect(str(socket_path()))
            client.sendall(json.dumps(request).encode())
            client.shutdown(socket.SHUT_WR)
            return json.loads(client.recv(1024 * 1024).decode())
        except OSError:
            if not started:
                try:
                    subprocess.run(["systemctl", "--user", "start", "process-lasso.service"],
                                   check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                except OSError:
                    pass
                started = True
            time.sleep(.1)
        finally:
            client.close()
    return {"ok": False, "error": "Process Lasso IPC unavailable"}


def main(arguments=None):
    parser = argparse.ArgumentParser(prog="process-lasso-game")
    parser.add_argument("--profile")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(arguments)
    command = args.command
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        parser.error("COMMAND is required")
    response = _request(command, args.profile)
    if response.get("ok"):
        for error in apply_launch_policy(os.getpid(), response.get("policy", {})):
            print(f"process-lasso-game: {error}", file=sys.stderr)
        os.environ[MARKER_ENV] = response["token"]
    else:
        print(f"process-lasso-game: {response.get('error', 'activation failed')}; launching normally",
              file=sys.stderr)
    os.execvp(command[0], command)


if __name__ == "__main__":
    main()
