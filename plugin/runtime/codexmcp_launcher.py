"""Global launcher for GuDaStudio/codexmcp inside Antigravity plugin runtime.

Prepends the newest Codex Desktop bundled `codex.exe` directory to PATH
when `codex` is not already resolvable, without editing global Windows PATH
or patching the upstream `codexmcp` repository.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path


def _prepend_codex_bin_to_path() -> None:
    if shutil.which("codex"):
        return

    local_app_data = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    codex_bin_root = Path(local_app_data) / "OpenAI" / "Codex" / "bin"
    if not codex_bin_root.is_dir():
        return

    candidates = sorted(
        codex_bin_root.rglob("codex.exe"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if candidates:
        bin_dir = str(candidates[0].parent)
        os.environ["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")


def main() -> None:
    _prepend_codex_bin_to_path()
    from codexmcp.cli import main as codexmcp_main

    codexmcp_main()


if __name__ == "__main__":
    main()
