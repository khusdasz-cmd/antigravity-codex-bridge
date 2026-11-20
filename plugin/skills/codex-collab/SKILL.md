---
name: codex-collab
description: Use when delegating engineering tasks to OpenAI Codex, inspecting existing Codex Desktop/CLI conversation history for a workspace, or continuing a shared Codex thread via `codex_app_turn`, `codex_list_threads`, `codex_read_thread`, or `codex` MCP tools.
---

# Codex Collaboration Workflow

Collaborate with OpenAI Codex as **PM / Dispatcher / Reviewer** (Antigravity) while delegating technical investigation and implementation to the **Codex Engineer** via the `codexmcp_codex` MCP server.

## 1. Tool Selection

Choose the right tool for the task:

| Goal | Tool | Key Behavior |
| :--- | :--- | :--- |
| **Find past Codex Desktop/CLI chats** | `codex_list_threads` | Filter by `cwd`, `search`, or `source_kinds` (`vscode`, `cli`, `appServer`, `exec`). |
| **Read a Codex conversation** | `codex_read_thread` | Pass `thread_id` (`include_turns=true` for messages + concise tool summaries). |
| **Run or resume shared Codex thread** | `codex_app_turn` | **Preferred for execution.** Uses `app-server` (`source='vscode'`), visible in Codex Desktop sidebar and resumable via `codex resume <thread_id>`. |
| **Legacy / flag-specific exec** | `codex` | Use only when you need `image`, `profile`, `return_all_messages`, `yolo`, or `SESSION_ID` (`codex exec`). |

## 2. Standard Workflows

### A. Inspect & Continue a User's Codex Session
1. Call `codex_list_threads(cwd="<workspace_abs_path>", limit=10)` to find the target `thread_id`.
2. Call `codex_read_thread(thread_id="<uuid>", include_turns=true)` to load context.
3. If continuing the work, call `codex_app_turn(prompt=..., cd=..., thread_id="<uuid>", sandbox=...)`.

### B. Diagnosis / Review (`read-only`)
1. Call `codex_app_turn` with `sandbox="read-only"` and structured brief (**Goal**, **Scope**, **Expected Output**).
2. Ask for exact file paths, line numbers, root causes, and a minimal plan without modifying files.
3. Save the returned `thread_id` for follow-ups.

### C. Implementation / Bug Fix (`workspace-write`)
1. Brief Codex on **what** must work, **constraints**, and **acceptance checks**; leave implementation details to Codex.
2. Call `codex_app_turn` with `sandbox="workspace-write"` (on Windows, if AppX sandbox blocks writes, confirm before using `danger-full-access` within scoped paths).
3. Independently verify changed files and run tests before reporting completion.

## 3. Rules & Guardrails

- **Role split**: Translate user intent into clear specs; do not micromanage or pre-write the implementation before delegating.
- **Model override**: Leave `model` empty (`""`) unless the user explicitly asks for a specific model (e.g., `"gpt-6.2-sol"`).
- **Timeout budget (3m MCP limit)**: Break large implementations into focused steps (< 2m each) and pass the same `thread_id` across turns.
- **Windows network caveat**: Under `read-only`, Codex subprocesses cannot open outbound sockets (`WinError 10013`); fetch external data outside first if needed.
