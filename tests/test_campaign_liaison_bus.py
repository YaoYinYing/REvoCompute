# Copyright (c) 2026 The REvoDesign Developers.
# Distributed under the terms of the GNU General Public License v3.0.
# SPDX-License-Identifier: GPL-3.0-only
"""Behavior coverage for the host-local liaison bus (tools/campaign_liaison_bus.py).

The bus is coordination-only and must stay small: an append-only mailbox per
logical agent, atomic appends under contention, a closed message vocabulary, and
tmux used strictly as a verified notification path. These tests drive the real
module and the real CLI, including a real multi-process append race.
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BUS_TOOL = ROOT / "tools" / "campaign_liaison_bus.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("campaign_liaison_bus", BUS_TOOL)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bus = _load_module()


# --------------------------------------------------------------------------- #
# Message shape and vocabulary
# --------------------------------------------------------------------------- #


def test_message_round_trips_through_a_mailbox(tmp_path):
    message = bus.build_message(
        sender="claude-pr69",
        recipient="commander",
        message_type="CHECKPOINT_READY",
        body="PR 69 head is ready for review",
        pr=69,
    )
    path = bus.append_message(message, tmp_path)
    assert path == tmp_path / "commander.jsonl"

    stored = bus.read_messages("commander", tmp_path)
    assert len(stored) == 1
    record = stored[0]
    assert record["from"] == "claude-pr69"
    assert record["to"] == "commander"
    assert record["pr"] == 69
    assert record["type"] == "CHECKPOINT_READY"
    assert record["message"] == "PR 69 head is ready for review"
    assert record["id"] == message["id"]
    assert record["reply_to"] is None


def test_reply_links_to_another_message(tmp_path):
    first = bus.build_message(sender="a1", recipient="b1", message_type="PLEASE_INSPECT", body="read the thread")
    bus.append_message(first, tmp_path)
    reply = bus.build_message(
        sender="b1", recipient="a1", message_type="ACK", body="seen", reply_to=first["id"]
    )
    bus.append_message(reply, tmp_path)
    assert bus.read_messages("a1", tmp_path)[-1]["reply_to"] == first["id"]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"message_type": "RUN_SHELL_COMMAND"},  # not in the vocabulary
        {"message_type": "checkpoint_ready"},  # case must match
        {"sender": "Bad Agent!"},
        {"recipient": "../../etc/passwd"},
        {"body": "line one\nline two"},
        {"body": "   "},
        {"body": "x" * (bus.MAX_MESSAGE_CHARS + 1)},
        {"pr": 0},
        {"pr": "69"},
        {"reply_to": "not-an-id"},
    ],
)
def test_bus_refuses_malformed_or_out_of_vocabulary_messages(kwargs):
    arguments = {
        "sender": "a1",
        "recipient": "b1",
        "message_type": "ACK",
        "body": "ok",
    }
    arguments.update(kwargs)
    with pytest.raises(bus.BusError):
        bus.build_message(**arguments)


def test_every_refused_body_is_never_written(tmp_path):
    with pytest.raises(bus.BusError):
        bus.build_message(sender="a1", recipient="b1", message_type="ACK", body="bad\nbody")
    assert bus.read_messages("b1", tmp_path) == []


def test_append_requires_the_required_keys(tmp_path):
    with pytest.raises(bus.BusError):
        bus.append_message({"from": "a1", "to": "b1"}, tmp_path)


def test_malformed_mailbox_line_is_reported_not_silently_skipped(tmp_path):
    (tmp_path / "b1.jsonl").write_text('{"id": "x"}\nnot json\n', encoding="utf-8")
    with pytest.raises(bus.BusError):
        bus.read_messages("b1", tmp_path)


def test_missing_mailbox_reads_as_empty(tmp_path):
    assert bus.read_messages("nobody", tmp_path) == []
    assert bus.peers(tmp_path) == {}


# --------------------------------------------------------------------------- #
# Atomic append under real contention
# --------------------------------------------------------------------------- #


def test_concurrent_append_loses_no_message(tmp_path):
    """Eight CLI processes append to one mailbox at once: every line must survive."""
    senders = 8
    payload = [
        [
            sys.executable,
            str(BUS_TOOL),
            "--bus-dir",
            str(tmp_path),
            "send",
            "--from",
            f"agent{i}",
            "--to",
            "commander",
            "--type",
            "CHECKPOINT_READY",
            "--message",
            f"checkpoint {i}",
            "--no-notify",
        ]
        for i in range(senders)
    ]
    processes = [subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE) for command in payload]
    for process in processes:
        process.communicate(timeout=30)
    assert all(process.returncode == 0 for process in processes)

    raw = (tmp_path / "commander.jsonl").read_text(encoding="utf-8")
    lines = [line for line in raw.splitlines() if line.strip()]
    assert len(lines) == senders
    records = [json.loads(line) for line in lines]
    assert {record["from"] for record in records} == {f"agent{i}" for i in range(senders)}
    assert len({record["id"] for record in records}) == senders


# --------------------------------------------------------------------------- #
# Peer registration
# --------------------------------------------------------------------------- #


def test_registration_records_the_pane_and_is_listed(tmp_path):
    registration = bus.build_message(
        sender="codex-pr67", recipient="codex-pr67", message_type="REGISTERED", body="codex online"
    )
    registration["tmux_target"] = "codex:0.0"
    bus.append_message(registration, tmp_path)
    bus.append_message(
        bus.build_message(sender="claude-pr69", recipient="claude-pr69", message_type="REGISTERED", body="claude online"),
        tmp_path,
    )

    assert bus.registered_target("codex-pr67", tmp_path) == "codex:0.0"
    assert bus.registered_target("claude-pr69", tmp_path) is None
    assert bus.peers(tmp_path) == {"claude-pr69": None, "codex-pr67": "codex:0.0"}


def test_a_later_registration_supersedes_an_earlier_pane(tmp_path):
    first = bus.build_message(sender="a1", recipient="a1", message_type="REGISTERED", body="online")
    first["tmux_target"] = "old:0.0"
    bus.append_message(first, tmp_path)
    second = bus.build_message(sender="a1", recipient="a1", message_type="REGISTERED", body="online again")
    second["tmux_target"] = "new:1.0"
    bus.append_message(second, tmp_path)
    assert bus.registered_target("a1", tmp_path) == "new:1.0"


# --------------------------------------------------------------------------- #
# tmux as a verified notification path only
# --------------------------------------------------------------------------- #


def _fake_tmux(monkeypatch, *, before: str, after: str):
    """Replace tmux with a deterministic stand-in for the delivery rule."""
    calls = []

    def fake_run(command, *args, **kwargs):
        calls.append(command)
        if "capture-pane" in command:
            # First capture is "before"; every later capture is "after".
            captured = before if calls.count(command) <= 1 else after
            return subprocess.CompletedProcess(command, 0, stdout=captured, stderr="")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(bus.subprocess, "run", fake_run)
    monkeypatch.setattr(bus.shutil, "which", lambda name: "/usr/bin/tmux")
    monkeypatch.setattr(bus.time, "sleep", lambda seconds: None)
    return calls


def test_delivery_requires_the_pane_to_change(monkeypatch):
    calls = _fake_tmux(monkeypatch, before="prompt $", after="prompt $")
    assert bus.notify_pane("sess:0.0", "Coordination message available in x.jsonl") == "unconfirmed-unchanged"
    typed = [c for c in calls if "send-keys" in c]
    assert typed, "the notice must still be typed"
    # Enter is a separate call, never combined with the text.
    assert any(c[:1] == ["tmux"] and c[-1] == "Enter" for c in typed)


def test_delivery_reports_success_when_the_pane_changed(monkeypatch):
    _fake_tmux(monkeypatch, before="prompt $", after="prompt $ bash: notice: command not found\nprompt $")
    assert bus.notify_pane("sess:0.0", "Coordination message available in x.jsonl") == "confirmed"


def test_text_still_on_the_input_line_is_unconfirmed(monkeypatch):
    notice = "Coordination message available in x.jsonl"
    _fake_tmux(monkeypatch, before="prompt $", after=f"prompt $ {notice}")
    assert bus.notify_pane("sess:0.0", notice) == "unconfirmed-on-input-line"


def test_notify_degrades_to_mailbox_only_without_tmux(tmp_path, monkeypatch):
    registration = bus.build_message(sender="a1", recipient="a1", message_type="REGISTERED", body="online")
    registration["tmux_target"] = "sess:0.0"
    bus.append_message(registration, tmp_path)
    monkeypatch.setattr(bus.shutil, "which", lambda name: None)
    assert bus.notify_message("a1", tmp_path) == "mailbox-only-tmux-absent"
    assert bus.list_panes() == {"available": False, "sessions": [], "panes": []}


def test_notify_without_a_registration_never_touches_tmux(tmp_path, monkeypatch):
    def explode(*args, **kwargs):
        raise AssertionError("tmux must not run for an unregistered agent")

    monkeypatch.setattr(bus.subprocess, "run", explode)
    assert bus.notify_message("ghost", tmp_path) == "mailbox-only-no-registration"


def test_pane_target_validation_rejects_injection(tmp_path):
    assert bus.notify_pane("sess; rm -rf /", "notice") == "invalid-target"
    assert bus.notify_pane("$(whoami)", "notice") == "invalid-target"


@pytest.mark.skipif(shutil.which("tmux") is None, reason="tmux is not installed")
def test_real_tmux_delivery_verification(tmp_path):
    """A real pane: the notice is delivered only when the pane visibly changes."""
    session = f"rc-bus-test-{os.getpid()}"
    created = subprocess.run(
        ["tmux", "new-session", "-d", "-s", session, "-x", "100", "-y", "30", "bash", "--norc", "-i"],
        capture_output=True,
        text=True,
    )
    if created.returncode != 0:
        pytest.skip(f"cannot start a tmux session here: {created.stderr.strip()}")
    try:
        target = f"{session}:0.0"
        # Wait for the shell to reach an interactive prompt.
        ready = False
        for _ in range(40):
            captured = subprocess.run(["tmux", "capture-pane", "-t", target, "-p"], capture_output=True, text=True)
            if captured.returncode == 0 and "$" in captured.stdout:
                ready = True
                break
            time.sleep(0.25)
        if not ready:
            pytest.skip("tmux pane never reached an interactive prompt")
        notice = "Coordination message available in .rc-agent-bus/commander.jsonl"
        outcome = bus.notify_pane(target, notice, settle_seconds=1.0)
        assert outcome == "confirmed", outcome
        final = subprocess.run(["tmux", "capture-pane", "-t", target, "-p"], capture_output=True, text=True).stdout
        assert notice not in final.splitlines()[-1]
    finally:
        subprocess.run(["tmux", "kill-session", "-t", session], capture_output=True, text=True)


# --------------------------------------------------------------------------- #
# CLI contract
# --------------------------------------------------------------------------- #


def test_cli_send_read_and_peers(tmp_path, capsys):
    code = bus.main(
        [
            "--bus-dir",
            str(tmp_path),
            "send",
            "--from",
            "claude-pr69",
            "--to",
            "commander",
            "--type",
            "DEPENDENCY_MERGED",
            "--pr",
            "65",
            "--message",
            "PR 65 merged; reconcile descendants",
            "--no-notify",
        ]
    )
    assert code == 0
    assert "notify=no-notify" in capsys.readouterr().out

    assert bus.main(["--bus-dir", str(tmp_path), "read", "--agent", "commander"]) == 0
    printed = json.loads(capsys.readouterr().out.strip().splitlines()[0])
    assert printed["type"] == "DEPENDENCY_MERGED"
    assert printed["pr"] == 65

    assert bus.main(["--bus-dir", str(tmp_path), "register", "--agent", "claude-pr69"]) == 0
    capsys.readouterr()
    assert bus.main(["--bus-dir", str(tmp_path), "peers"]) == 0
    assert "claude-pr69" in capsys.readouterr().out


def test_cli_refuses_an_out_of_vocabulary_type(tmp_path):
    code = bus.main(
        [
            "--bus-dir",
            str(tmp_path),
            "send",
            "--from",
            "a1",
            "--to",
            "b1",
            "--type",
            "EXECUTE_COMMAND",
            "--message",
            "rm -rf /",
            "--no-notify",
        ]
    )
    assert code == 2
    assert bus.read_messages("b1", tmp_path) == []
