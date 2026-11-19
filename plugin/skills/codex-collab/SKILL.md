---
name: codex-collab
description: Use when delegating engineering diagnosis, code review, bug fixes, or implementation tasks to OpenAI Codex via the `codex` MCP tool across any Antigravity workspace. Enforces the PM-to-Engineer workflow, safe sandbox selection, `SESSION_ID` multi-turn reuse, and objective verification.
---

# Codex MCP Global Collaboration Best Practices

This skill defines how Antigravity acts as **Product Manager / Dispatcher / Reviewer** while delegating technical execution to the **Codex Engineer** through the `codex` MCP server (`GuDaStudio/codexmcp`).

---

## 1. Role Split (PM <-> Engineer)

1. **Translate user intent, do not micromanage code:**
   - Convert informal or oral user ideas into structured specifications: **Goal**, **Scope**, **Constraints / Non-goals**, and **Acceptance Criteria**.
   - Avoid writing implementation code yourself before delegating when the user asked Codex to handle engineering work independently.
2. **Independent verification before reporting:**
   - Never treat Codex's reply alone as final proof without verifying `success: true`, checking modified files or running the stated test/dry-run check if needed, and inspecting any edge cases.
   - Maintain a skeptical, evidence-first review mindset (adapted from `GuDaStudio/codexmcp` best practices): verify paths, commands, and test outputs directly.

---

## 2. `codex` MCP Tool Parameters & Rules

Tool name: `codex` (exposed by `mcpServers.codex` via `mcp_config.json`).

| Parameter | Required | Default | Guidance |
| :--- | :--- | :--- | :--- |
| `PROMPT` | Yes | — | Clear, structured task brief (goals, constraints, expected output/checks). |
| `cd` | Yes | — | Absolute path to the active workspace root (must exist, or tool fails silently). |
| `sandbox` | No | `"read-only"` | Use `"read-only"` for diagnosis, architecture planning, and code review. Use `"workspace-write"` only when code edits/tests are authorized. Avoid `"danger-full-access"` / `yolo=true` unless explicitly required. |
| `SESSION_ID` | No | `""` | Leave empty to start a fresh thread. **Always save and pass back `SESSION_ID`** to continue the same engineering task with preserved context. |
| `skip_git_repo_check` | No | `true` | Keep `true` so Codex works smoothly in workspaces without `.git`. |
| `return_all_messages` | No | `false` | Keep `false` normally; set `true` only when diagnosing missing replies or inspecting tool/reasoning traces. |
| `image` | No | `[]` | Attach screenshot/diagram paths for UI or visual bug analysis. |
| `model` | No | `""` | Leave empty to use `~/.codex/config.toml` default, OR pass exact requested model slug (e.g., `"gpt-6.1-sol"`). |
| `profile` | No | `""` | Leave empty unless user explicitly requests a named profile in `~/.codex/config.toml`. |

---

## 3. Standard Dispatch Workflows

### A. Diagnosis / Second-Opinion / Code Review (`read-only`)
1. Call `codex` with `sandbox="read-only"`, exact workspace `cd`, and ask for:
   - Exact file paths + line numbers + symbol evidence;
   - Root cause + edge cases;
   - Minimal change plan without editing files.
2. Save the returned `SESSION_ID`. If follow-up questions arise, continue in the same `SESSION_ID`.

### B. Feature Implementation / Bug Fix (`workspace-write`)
1. Brief Codex on **what** must work and **what must NOT break** (constraints, backwards compatibility, dry-run/safety rules), leaving exact refactoring/implementation choices to Codex.
2. Let Codex edit files and run its own unit tests / `--dry-run` / linters inside `cd`.
3. After `codex` returns `success: true`, inspect the diff/changed files and re-verify key acceptance checks before reporting to the user.

---

## 4. Known Windows & Protocol Caveats

- **Network inside Windows sandbox**: Under `read-only` (and restricted sandboxes) on Windows, Codex subprocesses cannot open outbound sockets (`WinError 10013`). If an engineering task requires external API data (e.g., platform API responses), fetch read-only JSON outside first and pass the saved file path or payload to Codex.
- **Session list visibility**: `codexmcp` runs `codex exec` (`source='exec'` in `~/.codex/state_5.sqlite`). Sessions persist on disk and resume seamlessly via `SESSION_ID`, though they appear under CLI exec history rather than the Codex Desktop sidebar (`source='vscode'`).
- **Prompt formatting on Windows**: Keep `PROMPT` clean plain text/markdown without raw unescaped control anomalies; `codexmcp` handles Windows argument escaping automatically.
