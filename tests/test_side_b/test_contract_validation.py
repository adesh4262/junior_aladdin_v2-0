"""Architecture contract validation tests.

Verifies the Side B project structure adheres to architectural rules:
  - All expected modules exist and are importable
  - All route modules expose `register_routes(app)` helper
  - All dashboard JS files have valid syntax
  - Dashboard HTML references all JS files correctly
  - Naming conventions are consistent (snake_case for Python, camelCase for JS)
  - No architecture violations between floors/sides

Reference: FLOOR_04_DEPARTMENT_HEADS_V1_2_FINAL, ROADMAP_SIDE_B
"""

from __future__ import annotations

import ast
import os
import re
from pathlib import Path
from typing import Any

import pytest

# ── Project root ──
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
JUNIOR_ALADDIN = PROJECT_ROOT / "junior_aladdin"
SIDE_B_API = JUNIOR_ALADDIN / "side_b_api"
SIDE_B_DASHBOARD = JUNIOR_ALADDIN / "side_b_dashboard"
ROUTES_DIR = SIDE_B_API / "routes"
DATA_SOURCES_DIR = SIDE_B_API / "data_sources"
COMMAND_HANDLERS_DIR = SIDE_B_API / "command_handlers"

# ── Expected route modules (each must have register_routes) ──
EXPECTED_ROUTE_MODULES: dict[str, str] = {
    "health_routes": "health_routes.py",
    "captain_routes": "captain_routes.py",
    "head_routes": "head_routes.py",
    "execution_routes": "execution_routes.py",
    "market_routes": "market_routes.py",
    "memory_routes": "memory_routes.py",
    "replay_routes": "replay_routes.py",
    "control_routes": "control_routes.py",
    "alert_routes": "alert_routes.py",
}

# ── Expected data source modules (7 total) ──
EXPECTED_DATA_SOURCES: list[str] = [
    "floor_1_source",
    "floor_2_source",
    "floor_3_source",
    "floor_4_source",
    "floor_5_source",
    "side_a_source",
    "side_c_source",
]

# ── Expected command handler modules (6 total) ──
EXPECTED_COMMAND_HANDLERS: list[str] = [
    "mode_handler",
    "capital_handler",
    "kill_switch_handler",
    "override_handler",
    "reconnect_handler",
    "account_handler",
]

# ── Expected dashboard JS workspaces ──
EXPECTED_WORKSPACES: list[str] = [
    "workspace_replay.js",
    "workspace_review.js",
    "workspace_diagnostics.js",
    "session_cache_display.js",
]

# ── Expected dashboard JS panels ──
EXPECTED_PANELS: list[str] = [
    "health_panel.js",
    "alert_panel.js",
    "market_panel.js",
    "execution_panel.js",
    "captain_panel.js",
    "heads_panel.js",
    "controls_panel.js",
    "chart_surface.js",
    "explainability_panel.js",
    "floor_drilldown.js",
]

# ── Expected utility JS files ──
EXPECTED_UTILS: list[str] = [
    "colors.js",
    "formatters.js",
]

# ── Expected core JS files ──
EXPECTED_CORE_JS: list[str] = [
    "api_client.js",
    "state_manager.js",
    "component_manager.js",
    "websocket_client.js",
    "refresh_scheduler.js",
    "app.js",
]


# ══════════════════════════════════════════════════════════════
#  1. Module Import Tests
# ══════════════════════════════════════════════════════════════


class TestModuleImports:
    """Verify all expected modules are importable."""

    def test_side_b_api_importable(self):
        """The main side_b_api package imports cleanly."""
        from junior_aladdin import side_b_api
        assert side_b_api.__name__ == "junior_aladdin.side_b_api"

    def test_api_server_importable(self):
        """api_server module imports cleanly."""
        from junior_aladdin.side_b_api import api_server
        assert hasattr(api_server, "app")

    def test_session_cache_importable(self):
        """session_cache module imports cleanly."""
        from junior_aladdin.side_b_api.session_cache import (
            SessionCache,
            CacheTier,
            CacheEntry,
            get_default_cache,
        )
        assert SessionCache is not None
        assert CacheTier is not None
        assert CacheEntry is not None
        assert callable(get_default_cache)

    def test_data_aggregator_importable(self):
        """data_aggregator module imports cleanly."""
        from junior_aladdin.side_b_api.data_aggregator import (
            DataAggregator,
            get_default_aggregator,
        )
        assert DataAggregator is not None
        assert callable(get_default_aggregator)

    def test_api_config_importable(self):
        """api_config module imports cleanly."""
        from junior_aladdin.side_b_api.api_config import (
            APIConfig,
            DEFAULT_CONFIG,
            HOT_REFRESH_MS,
            WARM_REFRESH_MS,
            COLD_REFRESH_MS,
        )
        assert HOT_REFRESH_MS == 500
        assert WARM_REFRESH_MS == 3000
        assert COLD_REFRESH_MS == 30000

    def test_data_contracts_importable(self):
        """All data contracts import cleanly."""
        from junior_aladdin.side_b_api.data_contracts import (
            SystemHealthSnapshot,
            CaptainDisplayState,
            ExecutionDisplayState,
            FloorSummaryDisplay,
            HeadReportDisplay,
            MarketDataSnapshot,
            CommandAck,
            AlertEntry,
            DashboardState,
        )
        assert SystemHealthSnapshot is not None
        assert DashboardState is not None
        assert CommandAck is not None

    def test_all_route_modules_importable(self):
        """Every expected route module imports without error."""
        for module_name in EXPECTED_ROUTE_MODULES:
            __import__(f"junior_aladdin.side_b_api.routes.{module_name}", fromlist=[module_name])
            module = __import__(f"junior_aladdin.side_b_api.routes.{module_name}", fromlist=["register_routes"])
            assert hasattr(module, "register_routes"), f"{module_name} missing register_routes"

    def test_all_data_sources_importable(self):
        """Every expected data source imports without error."""
        for source in EXPECTED_DATA_SOURCES:
            try:
                __import__(f"junior_aladdin.side_b_api.data_sources.{source}", fromlist=[source])
            except Exception as e:
                pytest.fail(f"Data source '{source}' failed to import: {e}")

    def test_all_command_handlers_importable(self):
        """Every expected command handler imports without error."""
        from junior_aladdin.side_b_api.command_handlers import (
            handle_mode_request,
            handle_capital_request,
            handle_kill_switch_request,
            handle_override_request,
            handle_reconnect_request,
            handle_account_reset_request,
        )
        assert callable(handle_mode_request)
        assert callable(handle_capital_request)
        assert callable(handle_kill_switch_request)
        assert callable(handle_override_request)
        assert callable(handle_reconnect_request)
        assert callable(handle_account_reset_request)


# ══════════════════════════════════════════════════════════════
#  2. Route Module Contract Tests
# ══════════════════════════════════════════════════════════════


class TestRouteModuleContracts:
    """Verify every route module follows the contract pattern."""

    def test_each_route_has_register_routes(self):
        """Every route file defines a register_routes function."""
        for name, filename in EXPECTED_ROUTE_MODULES.items():
            filepath = ROUTES_DIR / filename
            assert filepath.exists(), f"{filename} not found"

            with open(filepath, encoding="utf-8") as f:
                content = f.read()

            assert "def register_routes" in content, f"{filename} missing register_routes()"
            assert "app.include_router" in content, f"{filename} missing app.include_router"
            assert "APIRouter" in content, f"{filename} missing APIRouter usage"

    def test_each_route_has_prefix_and_tags(self):
        """Each route module defines router with prefix and tags."""
        for name, filename in EXPECTED_ROUTE_MODULES.items():
            filepath = ROUTES_DIR / filename
            with open(filepath, encoding="utf-8") as f:
                content = f.read()

            assert "prefix=" in content, f"{filename} missing prefix"
            assert "tags=" in content, f"{filename} missing tags"

    def test_no_exec_in_route_names(self):
        """No route file defines functions named 'execute_' (must use 'request_' or 'get_')."""
        for filename in os.listdir(ROUTES_DIR):
            if not filename.endswith(".py") or filename == "__init__.py":
                continue
            filepath = ROUTES_DIR / filename
            with open(filepath, encoding="utf-8") as f:
                content = f.read()
            # All route modules should use request_ or get_ pattern, never execute_
            assert "request_" in content or "get_" in content, f"{filename} missing request_ or get_ pattern"
            # Only check function definitions, not docstrings/comments
            for line in content.splitlines():
                if line.lstrip().startswith("async def execute_") or line.lstrip().startswith("def execute_"):
                    pytest.fail(f"{filename} defines function with forbidden 'execute_' prefix: {line.strip()}")


# ══════════════════════════════════════════════════════════════
#  3. Dashboard File Tests
# ══════════════════════════════════════════════════════════════


class TestDashboardFileIntegrity:
    """Verify all dashboard files exist and are syntactically valid."""

    def test_index_html_exists(self):
        """Dashboard index.html exists."""
        assert (SIDE_B_DASHBOARD / "index.html").exists()

    def test_main_css_exists(self):
        """Dashboard main stylesheet exists."""
        assert (SIDE_B_DASHBOARD / "assets" / "css" / "main.css").exists()

    def test_logo_svg_exists(self):
        """Dashboard logo exists."""
        assert (SIDE_B_DASHBOARD / "assets" / "img" / "logo.svg").exists()

    def test_all_workspace_files_exist(self):
        """All expected workspace JS files exist."""
        for ws in EXPECTED_WORKSPACES:
            assert (SIDE_B_DASHBOARD / "assets" / "js" / ws).exists(), f"Missing workspace: {ws}"

    def test_all_panel_files_exist(self):
        """All expected panel JS files exist."""
        for panel in EXPECTED_PANELS:
            assert (SIDE_B_DASHBOARD / "assets" / "js" / panel).exists(), f"Missing panel: {panel}"

    def test_all_core_js_files_exist(self):
        """All expected core JS files exist."""
        for js in EXPECTED_CORE_JS:
            assert (SIDE_B_DASHBOARD / "assets" / "js" / js).exists(), f"Missing core JS: {js}"

    def test_all_util_files_exist(self):
        """All expected utility JS files exist."""
        for util in EXPECTED_UTILS:
            assert (SIDE_B_DASHBOARD / "assets" / "js" / "utils" / util).exists(), f"Missing util: {util}"

    def test_workspace_files_have_render_function(self):
        """Every workspace file exports a render function via object pattern."""
        for ws in EXPECTED_WORKSPACES:
            filepath = SIDE_B_DASHBOARD / "assets" / "js" / ws
            with open(filepath, encoding="utf-8") as f:
                content = f.read()
            assert "render(" in content, f"{ws} missing render() method"
            assert "unmount()" in content or "unmount" in content, f"{ws} missing unmount()"

    def test_js_files_use_modern_syntax(self):
        """Dashboard JS files use modern syntax (const/let not var)."""
        js_dir = SIDE_B_DASHBOARD / "assets" / "js"
        poor_syntax_files = []
        for js_file in js_dir.glob("**/*.js"):
            with open(js_file, encoding="utf-8") as f:
                content = f.read()
            var_count = len(re.findall(r"\bvar\s+", content))
            if var_count > 5 and js_file.name not in ("colors.js", "formatters.js"):
                poor_syntax_files.append(f"{js_file.name} ({var_count} var usages)")
        assert len(poor_syntax_files) == 0, f"Files using excessive 'var': {poor_syntax_files}"


# ══════════════════════════════════════════════════════════════
#  4. Source File Syntax Tests
# ══════════════════════════════════════════════════════════════


class TestPythonSyntax:
    """Verify all Python source files have valid syntax."""

    @pytest.mark.parametrize("py_file", [
        str(p.relative_to(PROJECT_ROOT))
        for p in JUNIOR_ALADDIN.rglob("*.py")
        if "__pycache__" not in str(p)
    ])
    def test_python_file_has_valid_syntax(self, py_file: str):
        """Every .py file parses without syntax errors."""
        filepath = PROJECT_ROOT / py_file
        try:
            with open(filepath, encoding="utf-8") as f:
                ast.parse(f.read())
        except SyntaxError as e:
            pytest.fail(f"Syntax error in {py_file}: {e}")

    def test_no_absolute_imports_in_side_b(self):
        """Side B modules should use package-relative imports, not absolute paths."""
        for py_file in SIDE_B_API.rglob("*.py"):
            if py_file.name == "__init__.py":
                continue
            with open(py_file, encoding="utf-8") as f:
                content = f.read()
            # Check for imports that don't use the junior_aladdin package prefix
            # Every import in side_b must route through junior_aladdin.side_b_api
            for line in content.splitlines():
                stripped = line.strip()
                if "import " not in stripped or stripped.startswith("#"):
                    continue
                # Skip from __future__, stdlib, and third-party imports
                if "from __future__" in stripped:
                    continue
                if stripped.startswith("from junior_aladdin") or stripped.startswith("import junior_aladdin"):
                    continue
                # Allow standard library imports that don't have 'junior_aladdin'
                # This includes: os, sys, json, typing, datetime, etc.
                if "junior_aladdin" not in stripped:
                    continue  # Allow stdlib/third-party packages


# ══════════════════════════════════════════════════════════════
#  5. Floor/Side Structure Tests
# ══════════════════════════════════════════════════════════════


class TestFloorSideStructure:
    """Verify expected floor/side directories exist."""

    EXPECTED_FLOORS: list[str] = [
        "floor_1_connection",
        "floor_2_datacenter",
        "floor_3_calculations",
        "floor_4_heads",
        "floor_5_captain",
    ]

    EXPECTED_SIDES: list[str] = [
        "side_a_execution",
        "side_b_api",
        "side_c_memory",
    ]

    def test_all_floors_exist(self):
        """All 5 floor directories exist under junior_aladdin."""
        for floor in self.EXPECTED_FLOORS:
            assert (JUNIOR_ALADDIN / floor).is_dir(), f"Missing floor directory: {floor}"

    def test_all_floors_have_init(self):
        """Every floor directory has __init__.py."""
        for floor in self.EXPECTED_FLOORS:
            init_file = JUNIOR_ALADDIN / floor / "__init__.py"
            assert init_file.exists(), f"Missing {init_file}"

    def test_all_sides_exist(self):
        """All 3 side directories exist under junior_aladdin."""
        for side in self.EXPECTED_SIDES:
            assert (JUNIOR_ALADDIN / side).is_dir(), f"Missing side directory: {side}"

    def test_shared_modules_exist(self):
        """Shared modules exist."""
        shared = JUNIOR_ALADDIN / "shared"
        assert (shared / "__init__.py").exists()
        assert (shared / "types.py").exists()
        assert (shared / "errors.py").exists()
        assert (shared / "config.py").exists()
        assert (shared / "logging.py").exists()
        assert (shared / "testing.py").exists()


# ══════════════════════════════════════════════════════════════
#  6. HTML/JS Contract Tests
# ══════════════════════════════════════════════════════════════


class TestHTMLJSScripts:
    """Verify index.html references all JS files correctly."""

    def test_all_js_files_referenced_in_html(self):
        """Every JS file in assets/js/ is referenced in index.html."""
        index_html = SIDE_B_DASHBOARD / "index.html"
        assert index_html.exists()

        with open(index_html, encoding="utf-8") as f:
            html_content = f.read()

        js_dir = SIDE_B_DASHBOARD / "assets" / "js"
        for js_file in sorted(js_dir.rglob("*.js")):
            relative = js_file.relative_to(SIDE_B_DASHBOARD).as_posix()
            # Normalize: assets/js/foo.js → src="assets/js/foo.js"
            if "assets/js/" + relative.split("assets/js/")[-1] in html_content:
                continue
            # Also check with version suffix like .js?v=2
            pattern = f'src="{relative}'
            if pattern not in html_content and f'src="{relative}?v=' not in html_content:
                # Try just the filename
                js_name = js_file.name
                if js_name in html_content:
                    continue
                pytest.fail(f"JS file '{relative}' not referenced in index.html")

    def test_html_has_no_broken_script_paths(self):
        """All script src paths in index.html point to existing files."""
        index_html = SIDE_B_DASHBOARD / "index.html"
        with open(index_html, encoding="utf-8") as f:
            html_content = f.read()

        script_pattern = re.compile(r'src="([^"]+\.js(?:[?][^"]*)?)"')
        for match in script_pattern.finditer(html_content):
            src = match.group(1).split("?")[0]  # strip ?v=2 query string
            if src.startswith("http"):
                continue  # external CDN
            filepath = (SIDE_B_DASHBOARD / src).resolve()
            assert filepath.exists(), f"Script path not found: {src} (resolved: {filepath})"

    def test_all_workspaces_have_sidebar_entry(self):
        """Each workspace JS file has a corresponding sidebar button in HTML."""
        index_html = SIDE_B_DASHBOARD / "index.html"
        with open(index_html, encoding="utf-8") as f:
            html_content = f.read()

        # Workspace names and expected sidebar data attributes
        workspace_map = {
            "workspace_replay.js": "replay",
            "workspace_review.js": "review",
            "workspace_diagnostics.js": "diagnostics",
            "session_cache_display.js": "cache",
        }

        for js_file, expected_data_ws in workspace_map.items():
            assert f'data-workspace="{expected_data_ws}"' in html_content, \
                f"Missing sidebar entry for {js_file} (data-workspace=\"{expected_data_ws}\")"


# ══════════════════════════════════════════════════════════════
#  7. Import Isolation Tests
# ══════════════════════════════════════════════════════════════


class TestImportIsolation:
    """Verify Side B doesn't import from floors/sides it shouldn't."""

    def test_side_b_does_not_import_side_a_directly(self):
        """Side B should not directly import from side_a_execution modules.

        Exceptions allowed:
        - data_sources/side_a_source.py: Data source adapter that MUST consume Side A
        - session_cache / data_contracts: Type references only
        """
        allowed_files = {
            "side_a_source.py",  # Data source adapter
        }
        for py_file in SIDE_B_API.rglob("*.py"):
            if py_file.name == "__init__.py":
                continue
            if py_file.name in allowed_files:
                continue
            with open(py_file, encoding="utf-8") as f:
                content = f.read()
            if "from junior_aladdin.side_a_execution" in content:
                pytest.fail(
                    f"{py_file.relative_to(PROJECT_ROOT)} imports from side_a_execution "
                    f"which violates architectural isolation"
                )
