"""Track and manage agent subprocess lifecycle."""

from __future__ import annotations

import os
import signal
import subprocess
from dataclasses import dataclass, field


@dataclass
class ProcessInfo:
    node_id: str
    process: subprocess.Popen[str]
    stdout_lines: list[str] = field(default_factory=list)


class ProcessManager:
    """Manages subprocesses for active nodes."""

    def __init__(self) -> None:
        self._processes: dict[str, ProcessInfo] = {}

    def register(self, node_id: str, process: subprocess.Popen[str]) -> None:
        """Register a subprocess for a node."""
        self._processes[node_id] = ProcessInfo(node_id=node_id, process=process)

    def poll_completions(self) -> list[tuple[str, int, str, str]]:
        """Poll all registered processes for completions.

        Returns list of (node_id, return_code, stdout, stderr) for completed processes.
        """
        completed = []
        for node_id, info in list(self._processes.items()):
            rc = info.process.poll()
            if rc is not None:
                stdout = ""
                stderr = ""
                if info.process.stdout:
                    stdout = info.process.stdout.read() or ""
                if info.process.stderr:
                    stderr = info.process.stderr.read() or ""
                completed.append((node_id, rc, stdout, stderr))
                del self._processes[node_id]
        return completed

    def cancel(self, node_id: str) -> bool:
        """Send SIGTERM to a node's process. Returns True if signal was sent."""
        info = self._processes.get(node_id)
        if info is None:
            return False
        try:
            os.kill(info.process.pid, signal.SIGTERM)
            return True
        except ProcessLookupError:
            return False

    def cancel_all(self) -> None:
        """Cancel all running processes."""
        for node_id in list(self._processes.keys()):
            self.cancel(node_id)

    @property
    def active_count(self) -> int:
        return len(self._processes)

    @property
    def active_node_ids(self) -> set[str]:
        return set(self._processes.keys())
