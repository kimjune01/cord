"""Tests for CordDB."""

import pytest
from cord.db import CordDB


@pytest.fixture
def db():
    return CordDB(":memory:")


class TestCreateNode:
    def test_create_root(self, db):
        nid = db.create_node("goal", "Build something")
        assert nid == "#1"
        node = db.get_node(nid)
        assert node["node_type"] == "goal"
        assert node["goal"] == "Build something"
        assert node["status"] == "pending"
        assert node["parent_id"] is None

    def test_create_child(self, db):
        root = db.create_node("goal", "Root")
        child = db.create_node("task", "Child", parent_id=root)
        assert child == "#2"
        node = db.get_node(child)
        assert node["parent_id"] == root

    def test_create_with_needs(self, db):
        root = db.create_node("goal", "Root")
        a = db.create_node("task", "A", parent_id=root)
        b = db.create_node("task", "B", parent_id=root, needs=[a])
        node = db.get_node(b)
        assert node["needs"] == [a]

    def test_create_with_prompt(self, db):
        nid = db.create_node("task", "Task", prompt="Do the thing")
        node = db.get_node(nid)
        assert node["prompt"] == "Do the thing"

    def test_auto_increment_ids(self, db):
        a = db.create_node("goal", "A")
        b = db.create_node("task", "B")
        c = db.create_node("task", "C")
        assert a == "#1"
        assert b == "#2"
        assert c == "#3"


class TestUpdateStatus:
    def test_update_to_active(self, db):
        nid = db.create_node("goal", "Root")
        db.update_status(nid, "active")
        assert db.get_node(nid)["status"] == "active"

    def test_complete_node(self, db):
        nid = db.create_node("task", "Task")
        db.complete_node(nid, "Done!")
        node = db.get_node(nid)
        assert node["status"] == "complete"
        assert node["result"] == "Done!"


class TestGetTree:
    def test_tree_structure(self, db):
        root = db.create_node("goal", "Root")
        db.create_node("task", "A", parent_id=root)
        db.create_node("task", "B", parent_id=root)
        tree = db.get_tree()
        assert tree["node_id"] == root
        assert len(tree["children"]) == 2
        assert tree["children"][0]["goal"] == "A"
        assert tree["children"][1]["goal"] == "B"

    def test_nested_tree(self, db):
        root = db.create_node("goal", "Root")
        a = db.create_node("task", "A", parent_id=root)
        db.create_node("task", "A1", parent_id=a)
        tree = db.get_tree()
        assert len(tree["children"]) == 1
        assert len(tree["children"][0]["children"]) == 1
        assert tree["children"][0]["children"][0]["goal"] == "A1"


class TestFindReady:
    def test_no_deps_ready(self, db):
        root = db.create_node("goal", "Root", status="active")
        db.create_node("task", "A", parent_id=root)
        ready = db.find_ready_nodes()
        assert len(ready) == 1
        assert ready[0]["goal"] == "A"

    def test_blocked_not_ready(self, db):
        root = db.create_node("goal", "Root", status="active")
        a = db.create_node("task", "A", parent_id=root)
        db.create_node("task", "B", parent_id=root, needs=[a])
        ready = db.find_ready_nodes()
        assert len(ready) == 1
        assert ready[0]["goal"] == "A"

    def test_dep_complete_unblocks(self, db):
        root = db.create_node("goal", "Root", status="active")
        a = db.create_node("task", "A", parent_id=root)
        db.create_node("task", "B", parent_id=root, needs=[a])
        db.complete_node(a, "done")
        ready = db.find_ready_nodes()
        assert len(ready) == 1
        assert ready[0]["goal"] == "B"

    def test_multiple_needs(self, db):
        root = db.create_node("goal", "Root", status="active")
        a = db.create_node("task", "A", parent_id=root)
        b = db.create_node("task", "B", parent_id=root)
        db.create_node("task", "C", parent_id=root, needs=[a, b])
        # Only A complete — C not ready
        db.complete_node(a, "done")
        ready = db.find_ready_nodes()
        assert len(ready) == 1
        assert ready[0]["goal"] == "B"
        # Both complete — C ready
        db.complete_node(b, "done")
        ready = db.find_ready_nodes()
        assert len(ready) == 1
        assert ready[0]["goal"] == "C"


class TestTreeComplete:
    def test_not_complete(self, db):
        db.create_node("goal", "Root")
        assert not db.is_tree_complete()

    def test_all_complete(self, db):
        nid = db.create_node("goal", "Root")
        db.complete_node(nid, "done")
        assert db.is_tree_complete()

    def test_failed_is_terminal(self, db):
        nid = db.create_node("goal", "Root")
        db.update_status(nid, "failed")
        assert db.is_tree_complete()


class TestGoalChain:
    def test_root_chain(self, db):
        root = db.create_node("goal", "Root")
        chain = db.get_goal_chain(root)
        assert chain == [(root, "Root")]

    def test_nested_chain(self, db):
        root = db.create_node("goal", "Root")
        child = db.create_node("task", "Child", parent_id=root)
        chain = db.get_goal_chain(child)
        assert chain == [(root, "Root"), (child, "Child")]


class TestGetResults:
    def test_completed_results(self, db):
        a = db.create_node("task", "A")
        b = db.create_node("task", "B")
        db.complete_node(a, "result A")
        db.complete_node(b, "result B")
        results = db.get_completed_results([a, b])
        assert results == {a: "result A", b: "result B"}

    def test_incomplete_excluded(self, db):
        a = db.create_node("task", "A")
        b = db.create_node("task", "B")
        db.complete_node(a, "result A")
        results = db.get_completed_results([a, b])
        assert results == {a: "result A"}
