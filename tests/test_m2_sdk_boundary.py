"""M2 source guards for the mandatory harness boundary."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "syncinerary"
REPO_ROOT = ROOT.parent
BANNED_LLM_ROOTS = {"anthropic", "langchain_anthropic", "openai"}


def _import_roots(path: Path) -> set[str]:
    roots: set[str] = set()
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def test_agents_and_tools_do_not_import_an_llm_sdk_directly():
    offenders = {
        str(path.relative_to(ROOT)): sorted(_import_roots(path) & BANNED_LLM_ROOTS)
        for package in (ROOT / "agents", ROOT / "tools")
        for path in package.rglob("*.py")
        if _import_roots(path) & BANNED_LLM_ROOTS
    }

    assert offenders == {}


def test_existing_external_calls_are_routed_through_the_wrapper():
    explain = (ROOT / "agents" / "explain.py").read_text(encoding="utf-8")
    solver = (ROOT / "agents" / "solver" / "stage2_route.py").read_text(
        encoding="utf-8"
    )

    assert "call_llm(" in explain
    assert "run_tool(" in solver


def test_github_ci_has_the_direct_sdk_import_guard():
    workflow = REPO_ROOT / ".github" / "workflows" / "ci.yml"

    assert workflow.exists()
    contents = workflow.read_text(encoding="utf-8")
    assert "Reject direct LLM SDK imports" in contents
    assert "rg -n" in contents
    assert "syncinerary/agents syncinerary/tools" in contents
    assert "branches: [main]" not in contents
