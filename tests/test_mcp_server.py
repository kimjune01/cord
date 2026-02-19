"""Tests for the MCP server (SQLite-backed)."""

import json
import pytest
from cord.db import CordDB


@pytest.fixture
def db(tmp_path):
    db_path = tmp_path / "test.db"
    return CordDB(db_path)


@pytest.fixture
def setup_server(db, tmp_path):
    """Set up the MCP server module globals."""
    import cord.mcp.server as server
    server.db_path = str(tmp_path / "test.db")
    root_id = db.create_node("goal", "Test goal", status="active")
    server.agent_id = root_id
    return server, root_id


class TestReadTree:
    def test_returns_json(self, setup_server, db):
        server, root_id = setup_server
        db.create_node("spawn", "Research", parent_id=root_id)
        db.create_node("spawn", "Writing", parent_id=root_id)
        data = json.loads(server.read_tree())
        assert data["id"] == root_id
        assert data["status"] == "active"
        assert len(data["children"]) == 2


class TestReadNode:
    def test_existing(self, setup_server, db):
        server, root_id = setup_server
        child = db.create_node("spawn", "Research", parent_id=root_id)
        data = json.loads(server.read_node(child))
        assert data["id"] == child
        assert data["goal"] == "Research"

    def test_missing(self, setup_server):
        server, _ = setup_server
        data = json.loads(server.read_node("#999"))
        assert "error" in data


class TestSpawn:
    def test_creates_child(self, setup_server, db):
        server, root_id = setup_server
        result = json.loads(server.spawn("New task", "Do stuff", "text"))
        assert "created" in result
        child = db.get_node(result["created"])
        assert child["goal"] == "New task"
        assert child["parent_id"] == root_id

    def test_blocked_by(self, setup_server, db):
        server, root_id = setup_server
        a = json.loads(server.spawn("A"))["created"]
        b = json.loads(server.spawn("B", blocked_by=[a]))["created"]
        node = db.get_node(b)
        assert a in node["blocked_by"]


class TestFork:
    def test_creates_fork(self, setup_server, db):
        server, root_id = setup_server
        dep = json.loads(server.spawn("Dep task"))["created"]
        result = json.loads(server.fork("Analysis", "Analyze", "structured", [dep]))
        child = db.get_node(result["created"])
        assert child["node_type"] == "fork"


class TestStop:
    def test_stop_own_child(self, setup_server, db):
        server, root_id = setup_server
        child = db.create_node("spawn", "A", parent_id=root_id)
        result = json.loads(server.stop(child))
        assert result["cancelled"] == child
        assert db.get_node(child)["status"] == "cancelled"

    def test_stop_own_grandchild(self, setup_server, db):
        server, root_id = setup_server
        child = db.create_node("spawn", "A", parent_id=root_id)
        grandchild = db.create_node("spawn", "B", parent_id=child)
        result = json.loads(server.stop(grandchild))
        assert result["cancelled"] == grandchild

    def test_stop_sibling_rejected(self, setup_server, db):
        server, root_id = setup_server
        # root_id is agent. Create a sibling subtree under a shared parent.
        parent = db.create_node("goal", "Parent", status="active")
        db.update_status(root_id, "active")
        # agent_id is root_id (#1). Create another branch not under #1.
        sibling = db.create_node("spawn", "Sibling", parent_id=parent)
        sibling_child = db.create_node("spawn", "Target", parent_id=sibling)
        result = json.loads(server.stop(sibling_child))
        assert "error" in result
        assert "not in your subtree" in result["error"]
        assert db.get_node(sibling_child)["status"] == "pending"

    def test_stop_nonexistent(self, setup_server):
        server, _ = setup_server
        result = json.loads(server.stop("#999"))
        assert "error" in result


class TestPause:
    def test_pause_active(self, setup_server, db):
        server, root_id = setup_server
        child = db.create_node("spawn", "A", parent_id=root_id, status="active")
        result = json.loads(server.pause(child))
        assert result["paused"] == child
        assert db.get_node(child)["status"] == "paused"

    def test_pause_pending_rejected(self, setup_server, db):
        server, root_id = setup_server
        child = db.create_node("spawn", "A", parent_id=root_id, status="pending")
        result = json.loads(server.pause(child))
        assert "error" in result
        assert "not active" in result["error"]

    def test_pause_sibling_rejected(self, setup_server, db):
        server, root_id = setup_server
        parent = db.create_node("goal", "Parent", status="active")
        sibling = db.create_node("spawn", "Sibling", parent_id=parent, status="active")
        result = json.loads(server.pause(sibling))
        assert "error" in result
        assert "not in your subtree" in result["error"]


class TestResume:
    def test_resume_paused(self, setup_server, db):
        server, root_id = setup_server
        child = db.create_node("spawn", "A", parent_id=root_id, status="paused")
        result = json.loads(server.resume(child))
        assert result["resumed"] == child
        assert db.get_node(child)["status"] == "pending"

    def test_resume_active_rejected(self, setup_server, db):
        server, root_id = setup_server
        child = db.create_node("spawn", "A", parent_id=root_id, status="active")
        result = json.loads(server.resume(child))
        assert "error" in result
        assert "not paused" in result["error"]


class TestModify:
    def test_modify_pending_goal(self, setup_server, db):
        server, root_id = setup_server
        child = db.create_node("spawn", "Old goal", parent_id=root_id, status="pending")
        result = json.loads(server.modify(child, goal="New goal"))
        assert result["modified"] == child
        assert result["goal"] == "New goal"
        assert db.get_node(child)["goal"] == "New goal"

    def test_modify_paused_prompt(self, setup_server, db):
        server, root_id = setup_server
        child = db.create_node("spawn", "A", parent_id=root_id, status="paused", prompt="old")
        result = json.loads(server.modify(child, prompt="new instructions"))
        assert result["modified"] == child
        assert db.get_node(child)["prompt"] == "new instructions"

    def test_modify_active_rejected(self, setup_server, db):
        server, root_id = setup_server
        child = db.create_node("spawn", "A", parent_id=root_id, status="active")
        result = json.loads(server.modify(child, goal="X"))
        assert "error" in result

    def test_modify_sibling_rejected(self, setup_server, db):
        server, root_id = setup_server
        parent = db.create_node("goal", "Parent", status="active")
        sibling = db.create_node("spawn", "Sibling", parent_id=parent, status="pending")
        result = json.loads(server.modify(sibling, goal="X"))
        assert "error" in result
        assert "not in your subtree" in result["error"]

    def test_modify_nothing_rejected(self, setup_server, db):
        server, root_id = setup_server
        child = db.create_node("spawn", "A", parent_id=root_id, status="pending")
        result = json.loads(server.modify(child))
        assert "error" in result
        assert "at least one" in result["error"]


class TestComplete:
    def test_complete(self, setup_server, db):
        server, root_id = setup_server
        result = json.loads(server.complete('["Stripe"]'))
        assert result["completed"] == root_id
        node = db.get_node(root_id)
        assert node["status"] == "complete"
        assert node["result"] == '["Stripe"]'
