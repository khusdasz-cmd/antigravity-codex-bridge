"""Opt-in integration checks against local history and an isolated Codex home."""

import argparse
import asyncio
from contextlib import closing
import os
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from unittest.mock import patch

from codexmcp.server import codex_app_turn, codex_list_threads, codex_read_thread, mcp
from codexmcp.threads import normalized_cwd


def snapshot(source: Path, target: Path) -> None:
    with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as original:
        with closing(sqlite3.connect(target)) as copy:
            original.backup(copy)


async def verify(project: str, config: str) -> None:
    assert {tool.name for tool in await mcp.list_tools()} == {
        "codex", "codex_list_threads", "codex_read_thread", "codex_app_turn",
    }
    base = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex").resolve()
    state = Path(os.environ.get("CODEX_SQLITE_HOME") or base).resolve()
    assert normalized_cwd(r"\\?\D:\AI_VIDEO_YANZHI") == normalized_cwd("d:/ai_video_yanzhi/")
    with TemporaryDirectory(prefix="codexmcp-check-", dir=Path.cwd()) as temporary:
        workspace = Path(temporary)
        history = workspace / "history"
        home = workspace / "home"
        history.mkdir()
        home.mkdir()
        for filename in ("state_5.sqlite", "thread_history_1.sqlite"):
            if (state / filename).exists():
                snapshot(state / filename, history / filename)
        (history / "config.toml").write_text(config, encoding="utf-8")
        (home / "config.toml").write_text(config, encoding="utf-8")
        with patch.dict(os.environ, {"CODEX_HOME": str(history), "CODEX_SQLITE_HOME": str(history)}):
            rows = await codex_list_threads(project, limit=10, source_kinds=["vscode"])
            assert rows and all(normalized_cwd(row["cwd"]) == normalized_cwd(project) for row in rows)
            print(f"project filter OK: {len(rows)} vscode threads", flush=True)
            thread = await codex_read_thread(rows[0]["id"])
            roles = {item["role"] for turn in thread["turns"] for item in turn["items"]}
            assert {"user", "assistant"} <= roles
            assert "turns" not in await codex_read_thread(rows[0]["id"], include_turns=False)
            print(f"real thread read OK: {len(thread['turns'])} turns, {', '.join(sorted(roles))}", flush=True)
        with patch.dict(os.environ, {"CODEX_HOME": str(home), "CODEX_SQLITE_HOME": str(home)}):
            first = await codex_app_turn("Reply only BRIDGE-TEST-2026. Do not use tools.", str(workspace))
            assert first["status"] == "completed" and first["reply"] == "BRIDGE-TEST-2026", first
            thread_id = first["thread_id"]
            second = await codex_app_turn(
                "Repeat your previous reply, adding -RESUMED. Do not use tools.", str(workspace), thread_id,
            )
            assert second["status"] == "completed" and second["thread_id"] == thread_id, second
            assert second["reply"] == "BRIDGE-TEST-2026-RESUMED", second
            assert len((await codex_read_thread(thread_id))["turns"]) == 2
            print(f"start and resume OK: {first['reply']} -> {second['reply']}", flush=True)
            uri = (home / "state_5.sqlite").as_uri() + "?mode=ro"
            with closing(sqlite3.connect(uri, uri=True)) as db:
                source, originator = db.execute("SELECT source, originator FROM threads WHERE id = ?", (thread_id,)).fetchone()
            listed = await codex_list_threads(str(workspace), limit=1, search="BRIDGE-TEST")
            assert listed and listed[0]["id"] == thread_id
            assert (listed[0]["source"], listed[0]["originator"]) == (source, originator)
            print(f"SQLite persistence OK: source={source}, originator={originator}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default=r"d:\ai_video_yanzhi")
    parser.add_argument("--test-config", type=Path, required=True,
                        help="Minimal Codex config.toml with a working model/provider and no startup hooks.")
    args = parser.parse_args()
    asyncio.run(verify(args.project, args.test_config.read_text(encoding="utf-8")))
