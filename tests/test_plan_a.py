"""Plan A unit and integration tests (no live LLM required)."""
import asyncio
import os
import unittest
from unittest.mock import patch

from http_client import default_headers, parse_allowlist, url_allowed
from orchestrator.executor import _deps_done, resume_state
from orchestrator.graph import Graph, Step
from orchestrator.state import RunState, StepState, Status
from research_graph.commentary import add_commentary
from research_graph.models import Claim, ClaimStatus, ResearchGraph


class HttpClientTests(unittest.TestCase):
    def test_default_headers_include_user_agent(self):
        headers = default_headers()
        self.assertIn("User-Agent", headers)
        self.assertIn("AutonomousResearcher", headers["User-Agent"])

    def test_allowlist_blocks_unknown_host(self):
        allow = {"example.com", "docs.python.org"}
        self.assertTrue(url_allowed("https://docs.python.org/3/", allow))
        self.assertFalse(url_allowed("https://evil.example.net/", allow))

    def test_empty_allowlist_allows_all(self):
        with patch.dict(os.environ, {"RESEARCH_URL_ALLOWLIST": ""}, clear=False):
            self.assertEqual(parse_allowlist(), set())
            self.assertTrue(url_allowed("https://anywhere.test/page"))


class ExecutorTests(unittest.TestCase):
    def test_skipped_dep_allows_downstream(self):
        def noop(_state):
            return {}

        graph = Graph(
            [
                Step("a", noop),
                Step("b", noop, deps=["a"], on_failure="skip"),
                Step("c", noop, deps=["b"]),
            ],
            order=["a", "b", "c"],
        )
        state = RunState(run_id="t", goal="test")
        state.steps["a"] = StepState(name="a", status=Status.DONE)
        state.steps["b"] = StepState(name="b", status=Status.SKIPPED)
        state.steps["c"] = StepState(name="c", status=Status.PENDING)
        self.assertTrue(_deps_done(graph, state, "c"))

    def test_resume_resets_errored_skip(self):
        def noop(_state):
            return {}

        graph = Graph([Step("critique", noop, on_failure="skip")], order=["critique"])
        state = RunState(run_id="t", goal="test")
        state.steps["critique"] = StepState(
            name="critique",
            status=Status.SKIPPED,
            error="NameError",
            output={"degraded": True},
        )
        resume_state(graph, state)
        self.assertEqual(state.steps["critique"].status, Status.PENDING)
        self.assertIsNone(state.steps["critique"].error)


class CommentaryTests(unittest.TestCase):
    def test_add_commentary_marks_unsupported(self):
        graph = ResearchGraph(
            run_id="r1",
            question="q",
            claims=[
                Claim(id="C1", text="x", status=ClaimStatus.UNSUPPORTED),
            ],
        )
        out = add_commentary(graph)
        self.assertIn("insufficient evidence", out.claims[0].commentary or "")


class ResearchEngineTests(unittest.TestCase):
    def test_run_id_parameter_exists(self):
        import inspect

        from research_engine import run_research_plan

        self.assertIn("run_id", inspect.signature(run_research_plan).parameters)


if __name__ == "__main__":
    unittest.main()
