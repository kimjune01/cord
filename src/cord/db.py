"""SQLite-backed coordination state for cord."""

from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path


SCHEMA = """
CREATE TABLE IF NOT EXISTS nodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    node_type TEXT NOT NULL CHECK(node_type IN ('goal', 'spawn', 'fork', 'serial', 'ask')),
    goal TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK(status IN ('pending', 'active', 'paused', 'complete', 'failed', 'cancelled')),
    parent_id INTEGER REFERENCES nodes(id),
    prompt TEXT,
    returns TEXT DEFAULT 'text',
    result TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS dependencies (
    node_id INTEGER NOT NULL REFERENCES nodes(id),
    depends_on INTEGER NOT NULL REFERENCES nodes(id),
    PRIMARY KEY (node_id, depends_on)
);

CREATE INDEX IF NOT EXISTS idx_nodes_parent ON nodes(parent_id);
CREATE INDEX IF NOT EXISTS idx_nodes_status ON nodes(status);
"""


def _node_id(row_id: int) -> str:
    return f"#{row_id}"


def _row_id(node_id: str) -> int:
    return int(node_id.lstrip("#"))


class CordDB:
    """Thread-safe SQLite coordination store."""

    def __init__(self, db_path: Path | str = ":memory:"):
        self.db_path = str(db_path)
        self._local = threading.local()
        self._init_schema()

    @property
    def _conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn"):
            conn = sqlite3.connect(self.db_path, timeout=10)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            self._local.conn = conn
        return self._local.conn

    def _init_schema(self) -> None:
        self._conn.executescript(SCHEMA)

    def create_node(
        self,
        node_type: str,
        goal: str,
        parent_id: str | None = None,
        prompt: str | None = None,
        returns: str = "text",
        blocked_by: list[str] | None = None,
        status: str = "pending",
    ) -> str:
        now = time.time()
        pid = _row_id(parent_id) if parent_id else None

        cursor = self._conn.execute(
            """INSERT INTO nodes (node_type, goal, status, parent_id, prompt, returns, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (node_type, goal, status, pid, prompt, returns, now, now),
        )
        row_id = cursor.lastrowid

        if blocked_by:
            for dep in blocked_by:
                self._conn.execute(
                    "INSERT INTO dependencies (node_id, depends_on) VALUES (?, ?)",
                    (row_id, _row_id(dep)),
                )

        self._conn.commit()
        return _node_id(row_id)

    def update_status(self, node_id: str, status: str) -> None:
        self._conn.execute(
            "UPDATE nodes SET status = ?, updated_at = ? WHERE id = ?",
            (status, time.time(), _row_id(node_id)),
        )
        self._conn.commit()

    def modify_node(self, node_id: str, goal: str | None = None, prompt: str | None = None) -> None:
        updates = []
        params: list = []
        if goal is not None:
            updates.append("goal = ?")
            params.append(goal)
        if prompt is not None:
            updates.append("prompt = ?")
            params.append(prompt)
        if not updates:
            return
        updates.append("updated_at = ?")
        params.append(time.time())
        params.append(_row_id(node_id))
        self._conn.execute(
            f"UPDATE nodes SET {', '.join(updates)} WHERE id = ?", params
        )
        self._conn.commit()

    def complete_node(self, node_id: str, result: str = "") -> None:
        self._conn.execute(
            "UPDATE nodes SET status = 'complete', result = ?, updated_at = ? WHERE id = ?",
            (result, time.time(), _row_id(node_id)),
        )
        self._conn.commit()

    def get_node(self, node_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM nodes WHERE id = ?", (_row_id(node_id),)
        ).fetchone()
        if not row:
            return None
        return self._row_to_dict(row)

    def get_children(self, node_id: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM nodes WHERE parent_id = ? ORDER BY id",
            (_row_id(node_id),),
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def get_blocked_by(self, node_id: str) -> list[str]:
        rows = self._conn.execute(
            "SELECT depends_on FROM dependencies WHERE node_id = ?",
            (_row_id(node_id),),
        ).fetchall()
        return [_node_id(r["depends_on"]) for r in rows]

    def get_root(self) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM nodes WHERE parent_id IS NULL ORDER BY id LIMIT 1"
        ).fetchone()
        if not row:
            return None
        return self._row_to_dict(row)

    def get_tree(self) -> dict | None:
        root = self.get_root()
        if not root:
            return None
        self._attach_children(root)
        return root

    def find_ready_nodes(self) -> list[dict]:
        """Find pending nodes whose dependencies are all complete."""
        rows = self._conn.execute(
            """SELECT n.* FROM nodes n
               WHERE n.status = 'pending'
               AND NOT EXISTS (
                   SELECT 1 FROM dependencies d
                   JOIN nodes dep ON dep.id = d.depends_on
                   WHERE d.node_id = n.id AND dep.status != 'complete'
               )
               ORDER BY n.id""",
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def is_tree_complete(self) -> bool:
        row = self._conn.execute(
            "SELECT COUNT(*) as c FROM nodes WHERE status NOT IN ('complete', 'failed', 'cancelled')"
        ).fetchone()
        return row["c"] == 0

    def get_completed_results(self, node_ids: list[str]) -> dict[str, str]:
        results = {}
        for nid in node_ids:
            node = self.get_node(nid)
            if node and node["status"] == "complete" and node["result"]:
                results[nid] = node["result"]
        return results

    def get_goal_chain(self, node_id: str) -> list[tuple[str, str]]:
        chain = []
        current = self.get_node(node_id)
        while current:
            chain.append((current["node_id"], current["goal"]))
            if current["parent_id"]:
                current = self.get_node(current["parent_id"])
            else:
                current = None
        chain.reverse()
        return chain

    def all_nodes(self) -> list[dict]:
        rows = self._conn.execute("SELECT * FROM nodes ORDER BY id").fetchall()
        return [self._row_to_dict(r) for r in rows]

    def _attach_children(self, node: dict) -> None:
        children = self.get_children(node["node_id"])
        node["children"] = children
        for child in children:
            self._attach_children(child)

    def _row_to_dict(self, row: sqlite3.Row) -> dict:
        d = dict(row)
        d["node_id"] = _node_id(d["id"])
        d["parent_id"] = _node_id(d["parent_id"]) if d["parent_id"] else None
        d["blocked_by"] = self.get_blocked_by(d["node_id"])
        return d
