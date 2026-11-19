"""Project history and interactive turns for the MCP tools."""

from __future__ import annotations

import asyncio
from contextlib import closing
import json
import ntpath
import os
from pathlib import Path
import sqlite3
from typing import Literal
from uuid import UUID
from weakref import WeakValueDictionary

from .app_server import AppServer, AppServerError


SandboxMode = Literal["read-only", "workspace-write", "danger-full-access"]
SOURCE_KINDS = {
    "cli", "vscode", "exec", "mcp", "appServer", "subAgent", "subAgentReview",
    "subAgentCompact", "subAgentThreadSpawn", "subAgentOther", "unknown",
}
TURN_TIMEOUT = 600
THREAD_LOCKS: WeakValueDictionary[str, asyncio.Lock] = WeakValueDictionary()


def normalized_cwd(value: str) -> str:
    if os.name == "nt" or ntpath.splitdrive(value)[0] or "\\" in value:
        value = value.replace("/", "\\")
        if value.lower().startswith("\\\\?\\unc\\"):
            value = "\\\\" + value[8:]
        elif value.startswith("\\\\?\\"):
            value = value[4:]
        return ntpath.normcase(ntpath.normpath(value))
    return os.path.abspath(value)


def source_kinds(source: str | dict) -> set[str]:
    if isinstance(source, str):
        return {"mcp", "appServer"} if source == "mcp" else {source}
    if "custom" in source:
        return {"appServer"}
    if "subagent" in source:
        subagent = source["subagent"]
        kind = next(iter(subagent), "other") if isinstance(subagent, dict) else subagent
        detail = {"review": "subAgentReview", "compact": "subAgentCompact",
                  "thread_spawn": "subAgentThreadSpawn"}
        return {"subAgent", detail.get(kind, "subAgentOther")}
    return {"unknown"}


def metadata(thread: dict) -> dict:
    source = thread["source"]
    if isinstance(source, str) and source.startswith(("{", '"')):
        try:
            source = json.loads(source)
        except ValueError:
            pass
    return {
        "id": thread["id"], "title": thread.get("name") or thread.get("title") or thread.get("preview") or "",
        "cwd": thread["cwd"], "source": source, "originator": thread.get("originator"),
        "created_at": thread.get("created_at", thread.get("createdAt")),
        "updated_at": thread.get("updated_at", thread.get("updatedAt")),
        "archived": bool(thread.get("archived")),
    }


def indexed_threads(cwd: str, limit: int, search: str, kinds: set[str]) -> list[dict]:
    codex_home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex").expanduser()
    sqlite_home = Path(os.environ.get("CODEX_SQLITE_HOME") or codex_home).expanduser()
    uri = (sqlite_home / "state_5.sqlite").absolute().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as db:
        db.row_factory = sqlite3.Row
        db.create_function("normalized_cwd", 1, normalized_cwd, deterministic=True)
        columns = {row["name"] for row in db.execute("PRAGMA table_info(threads)")}
        fields = ["id", "title", "cwd", "source", "created_at", "updated_at"]
        fields += [field for field in ("originator", "archived", "name", "preview") if field in columns]
        conditions = " WHERE normalized_cwd(cwd) = ?" if cwd else ""
        args = (normalized_cwd(cwd),) if cwd else ()
        sort = "COALESCE(updated_at_ms, updated_at * 1000)" if "updated_at_ms" in columns else "updated_at"
        matches = []
        for row in db.execute(f"SELECT {', '.join(fields)} FROM threads{conditions} ORDER BY {sort} DESC, id DESC", args):
            thread = metadata(dict(row))
            if search.casefold() not in thread["title"].casefold():
                continue
            if kinds and not kinds.intersection(source_kinds(thread["source"])):
                continue
            matches.append(thread)
            if len(matches) == limit:
                break
        return matches


async def list_threads(cwd: str, limit: int, search: str, kinds: list[str]) -> list[dict]:
    if limit <= 0:
        raise ValueError("limit must be positive")
    requested = set(kinds)
    if unknown := requested - SOURCE_KINDS:
        raise ValueError(f"Unknown source kinds: {', '.join(sorted(unknown))}")
    try:
        return await asyncio.to_thread(indexed_threads, cwd, limit, search, requested)
    except sqlite3.Error:
        pass
    matches = []
    async with AppServer.connect() as app:
        for archived in (False, True):
            params = {"limit": min(max(limit, 20), 100), "sortKey": "updated_at", "archived": archived,
                      "modelProviders": [], "sourceKinds": sorted(SOURCE_KINDS - {"mcp"})}
            cursor = None
            count = 0
            while count < limit:
                result = await app.request("thread/list", {**params, "cursor": cursor})
                for entry in result["data"]:
                    thread = metadata({**entry, "archived": archived})
                    if cwd and normalized_cwd(thread["cwd"]) != normalized_cwd(cwd):
                        continue
                    if search.casefold() not in thread["title"].casefold():
                        continue
                    if requested and not requested.intersection(source_kinds(thread["source"])):
                        continue
                    matches.append(thread)
                    count += 1
                    if count == limit:
                        break
                next_cursor = result.get("nextCursor")
                if not next_cursor or next_cursor == cursor:
                    break
                cursor = next_cursor
    return sorted(matches, key=lambda thread: (thread["updated_at"], thread["id"]), reverse=True)[:limit]


def summarize_item(item: dict) -> dict | None:
    kind = item["type"]
    if kind == "userMessage":
        content = []
        for part in item["content"]:
            attachment = {key: part[key] for key in ("type", "text", "path", "name", "fileId") if key in part}
            if part.get("url") and not part["url"].startswith("data:"):
                attachment["url"] = part["url"]
            content.append(attachment)
        return {"role": "user", "content": content}
    if kind == "agentMessage":
        return {"role": "assistant", "text": item["text"], "phase": item.get("phase")}
    fields = {
        "commandExecution": ("command", "cwd", "status", "exitCode"),
        "mcpToolCall": ("server", "tool", "status"),
        "dynamicToolCall": ("namespace", "tool", "success", "status"),
        "fileChange": ("status",), "webSearch": ("query",),
        "collabAgentToolCall": ("tool", "status"),
        "functionCallOutput": ("name", "namespace"),
    }
    if kind in fields:
        summary = {"role": "tool", "type": kind, **{key: item[key] for key in fields[kind] if key in item}}
        if kind == "fileChange":
            summary["paths"] = [change["path"] for change in item.get("changes", [])]
        return summary
    if kind == "plan":
        return {"role": "assistant", "type": "plan", "text": item["text"]}
    return None


async def read_thread(thread_id: str, include_turns: bool) -> dict:
    thread_id = str(UUID(thread_id))
    async with AppServer.connect() as app:
        thread = (await app.request("thread/read", {
            "threadId": thread_id, "includeTurns": False,
        }))["thread"]
        if include_turns:
            turns = await read_turns(app, thread_id, thread.get("historyMode"))
    result = metadata(thread)
    result.pop("archived")
    if include_turns:
        result["turns"] = [{
            "id": turn["id"], "status": turn["status"],
            "items": [summary for item in turn["items"] if (summary := summarize_item(item)) is not None],
        } for turn in turns]
    return result


async def read_turns(app: AppServer, thread_id: str, history_mode: str | None) -> list[dict]:
    if history_mode == "paginated":
        turns = []
        cursor = None
        try:
            while True:
                page = await app.request("thread/turns/list", {
                    "threadId": thread_id, "cursor": cursor, "limit": 5,
                    "sortDirection": "asc", "itemsView": "full",
                })
                turns.extend(page["data"])
                next_cursor = page.get("nextCursor")
                if not next_cursor:
                    return turns
                if next_cursor == cursor:
                    raise AppServerError("Codex repeated a thread history pagination cursor.")
                cursor = next_cursor
        except AppServerError as exc:
            if exc.code != -32601:
                raise
    return (await app.request("thread/read", {"threadId": thread_id, "includeTurns": True}))["thread"]["turns"]


async def app_turn(prompt: str, cd: str, thread_id: str, sandbox: SandboxMode, model: str) -> dict:
    if not prompt.strip():
        raise ValueError("prompt must not be empty")
    if not cd.strip() or not Path(cd).is_dir():
        raise ValueError("cd must be an existing directory")
    options = {"cwd": str(Path(cd).resolve()), "sandbox": sandbox, "approvalPolicy": "never"}
    if model.strip():
        options["model"] = model.strip()
    active_id = str(UUID(thread_id)) if thread_id else ""
    if active_id:
        lock = THREAD_LOCKS.setdefault(active_id, asyncio.Lock())
        async with lock:
            return await run_turn(prompt, active_id, options)
    return await run_turn(prompt, active_id, options)


async def run_turn(prompt: str, active_id: str, options: dict) -> dict:
    turn_id = ""
    try:
        async with AppServer.connect(TURN_TIMEOUT) as app:
            if active_id:
                result = await app.request("thread/resume", {**options, "threadId": active_id, "excludeTurns": True})
            else:
                result = await app.request("thread/start", {**options, "ephemeral": False})
            active_id = result["thread"]["id"]
            turn = (await app.request("turn/start", {
                "threadId": active_id, "input": [{"type": "text", "text": prompt}],
            }, capture_turn=True))["turn"]
            turn_id = turn["id"]
            completed, events = await app.completed_turn(active_id, turn_id)
            items = [item for item in completed.get("items", []) if item["type"] == "agentMessage"]
            messages = {item["id"]: item for item in events + items}
            finals = [item["text"] for item in messages.values() if item.get("phase") == "final_answer"]
            candidates = [item["text"] for item in messages.values() if item.get("phase") != "commentary"]
            response = {"thread_id": active_id, "turn_id": turn_id, "status": completed["status"],
                        "reply": (finals or candidates or [""])[-1]}
            if completed["status"] != "completed":
                response["error"] = (completed.get("error") or {}).get("message") or completed["status"]
            return response
    except (AppServerError, OSError) as exc:
        return {"thread_id": active_id, "turn_id": turn_id, "status": "failed", "reply": "", "error": str(exc)}
