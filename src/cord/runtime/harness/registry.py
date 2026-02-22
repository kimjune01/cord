"""Runtime adapter registry and defaults."""

from __future__ import annotations

from cord.runtime.harness.amp import AmpAdapter
from cord.runtime.harness.base import RuntimeAdapter
from cord.runtime.harness.claude import ClaudeAdapter
from cord.runtime.harness.codex_app_server import CodexAppServerAdapter


_DEFAULT_RUNTIME = "codex-app-server"
_ADAPTER_FACTORIES: dict[str, type[RuntimeAdapter]] = {
    "claude": ClaudeAdapter,
    "codex-app-server": CodexAppServerAdapter,
    "amp": AmpAdapter,
}


def runtime_names() -> tuple[str, ...]:
    return tuple(_ADAPTER_FACTORIES.keys())


def default_runtime() -> str:
    return _DEFAULT_RUNTIME


def create_adapter(runtime: str) -> RuntimeAdapter:
    factory = _ADAPTER_FACTORIES.get(runtime)
    if factory is None:
        supported = ", ".join(runtime_names())
        raise ValueError(f"Unsupported runtime: {runtime}. Expected one of: {supported}")
    return factory()


def default_model_for_runtime(runtime: str) -> str | None:
    adapter = create_adapter(runtime)
    return adapter.default_model

