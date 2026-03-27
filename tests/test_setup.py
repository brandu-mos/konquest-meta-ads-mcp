"""
Tests for setup readiness checker.

Tests registration, output structure, readiness logic, and
fix instruction generation without Meta API calls.
"""
import pytest
import os


class TestRunSetupCheckRegistration:

    def test_function_exists(self):
        from meta_ads_mcp.core.setup import run_setup_check
        assert callable(run_setup_check)

    def test_tool_is_registered(self):
        import inspect
        from meta_ads_mcp.core import setup
        source = inspect.getsource(setup)
        lines = source.split("\n")
        for i, line in enumerate(lines):
            if "def run_setup_check(" in line:
                for j in range(max(0, i - 3), i):
                    if "@mcp.tool()" in lines[j] and not lines[j].strip().startswith("#"):
                        return
                pytest.fail("run_setup_check is not registered with @mcp.tool()")


class TestReadinessLogic:

    def test_missing_token_returns_not_ready(self):
        """Without META_ACCESS_TOKEN, result must be not_ready."""
        old = os.environ.pop("META_ACCESS_TOKEN", None)
        try:
            from meta_ads_mcp.core.setup import run_setup_check
            result = run_setup_check()
            assert result["overall_status"] == "not_ready"
            assert result["summary"]["fail"] > 0
            assert any(c["name"] == "token_exists" and c["status"] == "fail" for c in result["checks"])
        finally:
            if old is not None:
                os.environ["META_ACCESS_TOKEN"] = old

    def test_missing_token_has_fix_instructions(self):
        old = os.environ.pop("META_ACCESS_TOKEN", None)
        try:
            from meta_ads_mcp.core.setup import run_setup_check
            result = run_setup_check()
            assert result["fix_instructions"] is not None
            assert len(result["fix_instructions"]) > 0
            assert "System User" in result["fix_instructions"][0]
        finally:
            if old is not None:
                os.environ["META_ACCESS_TOKEN"] = old


class TestOutputStructure:

    def test_result_has_required_fields(self):
        """Result must have all required top-level fields."""
        old = os.environ.pop("META_ACCESS_TOKEN", None)
        try:
            from meta_ads_mcp.core.setup import run_setup_check
            result = run_setup_check()
            assert "overall_status" in result
            assert "summary" in result
            assert "checks" in result
            assert "ready_accounts" in result
            assert "not_ready_accounts" in result
            assert result["overall_status"] in ("ready", "ready_with_warnings", "not_ready")
        finally:
            if old is not None:
                os.environ["META_ACCESS_TOKEN"] = old

    def test_summary_has_counts(self):
        old = os.environ.pop("META_ACCESS_TOKEN", None)
        try:
            from meta_ads_mcp.core.setup import run_setup_check
            result = run_setup_check()
            summary = result["summary"]
            assert "pass" in summary
            assert "warn" in summary
            assert "fail" in summary
            assert "total_checks" in summary
            assert summary["total_checks"] == summary["pass"] + summary["warn"] + summary["fail"]
        finally:
            if old is not None:
                os.environ["META_ACCESS_TOKEN"] = old

    def test_checks_are_structured(self):
        old = os.environ.pop("META_ACCESS_TOKEN", None)
        try:
            from meta_ads_mcp.core.setup import run_setup_check
            result = run_setup_check()
            for check in result["checks"]:
                assert "name" in check
                assert "status" in check
                assert "detail" in check
                assert "scope" in check
                assert check["status"] in ("pass", "warn", "fail")
        finally:
            if old is not None:
                os.environ["META_ACCESS_TOKEN"] = old


class TestWarningVsBlocker:

    def test_warn_only_checks_do_not_hard_fail(self):
        """If only warnings exist (no fails), status should be ready_with_warnings, not not_ready."""
        from meta_ads_mcp.core.setup import _build_result
        checks = [
            {"name": "token", "status": "pass", "detail": "ok", "scope": "global"},
            {"name": "vault", "status": "warn", "detail": "not set", "scope": "global"},
            {"name": "secret", "status": "warn", "detail": "not set", "scope": "global"},
        ]
        result = _build_result(checks, [], [], [])
        assert result["overall_status"] == "ready_with_warnings"

    def test_all_pass_returns_ready(self):
        from meta_ads_mcp.core.setup import _build_result
        checks = [
            {"name": "token", "status": "pass", "detail": "ok", "scope": "global"},
            {"name": "accounts", "status": "pass", "detail": "ok", "scope": "global"},
        ]
        result = _build_result(checks, [], [{"id": "act_123"}], [])
        assert result["overall_status"] == "ready"

    def test_any_fail_returns_not_ready(self):
        from meta_ads_mcp.core.setup import _build_result
        checks = [
            {"name": "token", "status": "pass", "detail": "ok", "scope": "global"},
            {"name": "permissions", "status": "fail", "detail": "missing", "scope": "global"},
        ]
        result = _build_result(checks, ["Fix permissions"], [], [])
        assert result["overall_status"] == "not_ready"

    def test_fix_instructions_none_when_empty(self):
        from meta_ads_mcp.core.setup import _build_result
        result = _build_result([], [], [], [])
        assert result["fix_instructions"] is None


class TestPermissionClassification:

    def test_critical_vs_warn_permissions_in_source(self):
        """Verify that permission classification exists in source."""
        import inspect
        from meta_ads_mcp.core import setup
        source = inspect.getsource(setup.run_setup_check)
        assert "ads_management" in source
        assert "ads_read" in source
        assert "business_management" in source
        assert "pages_read_engagement" in source
        assert "pages_manage_ads" in source
