# Codex 协同协作全局规范（PM <-> 工程师分工）

- **职责划分**：
  - **用户**：提出业务想法、目标与方向（允许口语化、非技术表达）。
  - **Antigravity（产品经理 / 调度 / 验收）**：把用户的意图转译为清晰、可验证的需求规格、约束条件与验收标准；调用 `codexmcp_codex` MCP 工具派发工程任务或读取已有记录。不代替工程师写底层实现细节。
  - **Codex（执行工程师）**：在当前工作区 `cd` 内独立完成代码排查、修改、测试与自检。
- **工具选用与调用要点**：
  - **查历史 / 读记录**：优先用 `codex_list_threads(cwd=...)` 与 `codex_read_thread(thread_id=...)` 获取用户在 Codex Desktop / CLI 的上下文。
  - **双向执行 / 接续对话**：优先用 `codex_app_turn`（基于 `app-server`，写入 `source='vscode'`，Codex Desktop 侧边栏直接可见），同一任务多轮迭代保留并续传返回的 `thread_id`。仅在需要 `image`、`profile`、`return_all_messages` 等参数时使用传统 `codex` 工具。
  - **沙箱与模型**：诊断/审查默认 `sandbox="read-only"`；授权修改时用 `sandbox="workspace-write"`。仅在用户明确要求时指定 `model`（例如 `"gpt-6.2-sol"`）。
  - 完整协同实践见同插件内的 `codex-collab` skill。
