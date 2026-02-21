"""Harness selection and construction."""

from __future__ import annotations

import shutil
from collections.abc import Callable
from typing import Literal

from cord.runtime.harness.amp import AmpHarness
from cord.runtime.harness.base import AgentHarness
from cord.runtime.harness.claude import ClaudeHarness


BackendName = Literal["claude", "amp"]


def select_backend(
    *,
    force_claude: bool = False,
    force_amp: bool = False,
    which: Callable[[str], str | None] = shutil.which,
) -> BackendName:
    """Resolve backend from explicit flags or local binary availability."""
    if force_claude and force_amp:
        raise ValueError("Invalid args: pass only one of --claude or --amp.")

    has_amp = which("amp") is not None
    has_claude = which("claude") is not None

    if force_amp:
        if not has_amp:
            raise ValueError(
                "Requested --amp but 'amp' binary was not found in PATH. "
                "Install Amp CLI or run with --claude."
            )
        return "amp"

    if force_claude:
        if not has_claude:
            raise ValueError(
                "Requested --claude but 'claude' binary was not found in PATH. "
                "Install Claude Code CLI or run with --amp."
            )
        return "claude"

    if has_amp:
        return "amp"
    if has_claude:
        return "claude"

    raise ValueError(
        "No supported agent CLI found in PATH. Install Amp CLI ('amp') or "
        "Claude Code CLI ('claude'), or pass --amp/--claude after install."
    )


def create_harness(backend: BackendName) -> AgentHarness:
    """Create a harness instance for a backend name."""
    if backend == "amp":
        return AmpHarness()
    return ClaudeHarness()


def resolve_harness(
    *,
    force_claude: bool = False,
    force_amp: bool = False,
    which: Callable[[str], str | None] = shutil.which,
) -> AgentHarness:
    """Resolve and construct harness from flags and environment."""
    backend = select_backend(
        force_claude=force_claude,
        force_amp=force_amp,
        which=which,
    )
    return create_harness(backend)
