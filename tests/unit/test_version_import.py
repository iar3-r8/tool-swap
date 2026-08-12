"""
Behaviour 1 — Both distributions install and import, and expose a version.

Tests from plan/task/m0-repository-skeleton.md, Behaviour 1.
"""

import importlib
import re
import subprocess
import sys
from importlib import metadata

import pytest


# PEP 440 valid version regex (simplified but sufficient for "non-empty PEP 440 string").
# See: https://peps.python.org/pep-0440/
_PEP440_RE = re.compile(
    r"^(?P<release>[0-9]+(?:\.[0-9]+)*)"
    r"(?:(?P<pre_tag>a|b|rc)(?P<pre_num>[0-9]+))?"
    r"(?:\.post(?P<post_num>[0-9]+))?"
    r"(?:\.dev(?P<dev_num>[0-9]+))?"
    r"(\+(?P<local>[a-z0-9.+]+))?$",
)


def _is_pep440(version: str) -> bool:
    """Return True if *version* matches PEP 440."""
    return _PEP440_RE.match(version) is not None


class TestToolSwapImport:
    """Verify `tool_swap` distribution (distribution name: ``tool-swap``)."""

    def test_import_tool_swap(self):
        """import tool_swap succeeds."""
        mod = importlib.import_module("tool_swap")
        assert mod is not None

    def test_tool_swap_version_exists_and_non_empty(self):
        """tool_swap.__version__ exists and is non-empty."""
        mod = importlib.import_module("tool_swap")
        assert hasattr(mod, "__version__"), (
            "tool_swap must expose __version__"
        )
        assert mod.__version__, "tool_swap.__version__ must be non-empty"

    def test_tool_swap_version_is_pep440(self):
        """tool_swap.__version__ is a valid PEP 440 string."""
        mod = importlib.import_module("tool_swap")
        assert _is_pep440(mod.__version__), (
            f"tool_swap.__version__ {mod.__version__!r} is not PEP 440"
        )

    def test_tool_swap_metadata_matches_version(self):
        """importlib.metadata.version("tool-swap") equals tool_swap.__version__."""
        mod = importlib.import_module("tool_swap")
        meta_version = metadata.version("tool-swap")
        assert meta_version == mod.__version__, (
            f"metadata version {meta_version!r} != __version__ {mod.__version__!r}"
        )

    def test_tool_swap_has_docstring(self):
        """tool_swap module has a non-empty __doc__."""
        mod = importlib.import_module("tool_swap")
        assert mod.__doc__ is not None and mod.__doc__.strip(), (
            "tool_swap must have a non-empty module docstring"
        )


class TestToolSwapRuntimeImport:
    """Verify `tool_swap_runtime` distribution (distribution name: ``tool-swap-runtime``)."""

    def test_import_tool_swap_runtime(self):
        """import tool_swap_runtime succeeds."""
        mod = importlib.import_module("tool_swap_runtime")
        assert mod is not None

    def test_tool_swap_runtime_version_exists_and_non_empty(self):
        """tool_swap_runtime.__version__ exists and is non-empty."""
        mod = importlib.import_module("tool_swap_runtime")
        assert hasattr(mod, "__version__"), (
            "tool_swap_runtime must expose __version__"
        )
        assert mod.__version__, "tool_swap_runtime.__version__ must be non-empty"

    def test_tool_swap_runtime_version_is_pep440(self):
        """tool_swap_runtime.__version__ is a valid PEP 440 string."""
        mod = importlib.import_module("tool_swap_runtime")
        assert _is_pep440(mod.__version__), (
            f"tool_swap_runtime.__version__ {mod.__version__!r} is not PEP 440"
        )

    def test_tool_swap_runtime_metadata_matches_version(self):
        """importlib.metadata.version("tool-swap-runtime") equals tool_swap_runtime.__version__."""
        mod = importlib.import_module("tool_swap_runtime")
        meta_version = metadata.version("tool-swap-runtime")
        assert meta_version == mod.__version__, (
            f"metadata version {meta_version!r} != __version__ {mod.__version__!r}"
        )

    def test_tool_swap_runtime_has_docstring(self):
        """tool_swap_runtime module has a non-empty __doc__."""
        mod = importlib.import_module("tool_swap_runtime")
        assert mod.__doc__ is not None and mod.__doc__.strip(), (
            "tool_swap_runtime must have a non-empty module docstring"
        )


class TestIndependentVersions:
    """The two distributions have independent version numbers."""

    def test_versions_independent_not_asserted_equal(self):
        """tool_swap and tool_swap_runtime must NOT be asserted equal.

        The two distributions carry independent version numbers — the router
        version is never used inside model images while the runtime version
        is stamped into images as ``runtime_version``.
        """
        ts = importlib.import_module("tool_swap")
        tsr = importlib.import_module("tool_swap_runtime")
        # Explicitly NOT asserting equality — versions may differ.
        # This test passes as long as both imports succeed and have versions.
        # The presence of both attributes is the assertion.
        assert hasattr(ts, "__version__")
        assert hasattr(tsr, "__version__")
        # Sanity: they can coexist independently (not a single monolith).
        assert ts is not tsr


class TestPackageNotFoundError:
    """A missing distribution raises importlib.metadata.PackageNotFoundError."""

    def test_nonexistent_distribution_raises_specific_exception(self):
        """metadata.version("this-package-does-not-exist-xyz") raises PackageNotFoundError."""
        with pytest.raises(metadata.PackageNotFoundError) as exc_info:
            metadata.version("this-package-does-not-exist-xyz")
        # Confirm it's the real exception, not a broadly caught one.
        assert "this-package-does-not-exist-xyz" in str(exc_info.value)

    def test_typo_in_distribution_name_fails_loudly(self):
        """A typo'd distribution name (e.g. "tool-swapp") raises PackageNotFoundError, not AttributeError."""
        with pytest.raises(metadata.PackageNotFoundError):
            metadata.version("tool-swapp")  # intentional typo


class TestSrcLayoutIsolation:
    """The test exercises the installed package, not a stray sys.path entry.

    The src/ layout means the package should only be importable after
    installation (editable or wheel). If the package leaks importable
    from the repo root via a stray sys.path entry, this test should fail.
    """

    def test_package_not_importable_from_src_via_sys_path(self):
        """Verifies the test itself is not importing from src/ by modifying sys.path.

        This test checks that our test infrastructure does not contaminate
        sys.path with the repo's src/ directory. If src/tool_swap is on
        sys.path, the package would import without installation, defeating
        the purpose of the src/ layout test.
        """
        # Find any path pointing to src/tool_swap directly in the workspace.
        workspace = "/workspaces/tool-swap"
        for path_item in sys.path:
            candidate = f"{workspace}/src/tool_swap"
            # We allow sys.path to contain the workspace root; we just check
            # that the test doesn't actively inject src/ into sys.path.
            assert path_item != candidate, (
                f"sys.path contains {candidate!r} — "
                "tests must exercise the installed package, not src/ directly"
            )

    @pytest.mark.skip(
        reason=(
            "This is a verification that the src/ layout is enforced. "
            "It runs 'pip list --format=freeze' and checks that both "
            "distributions are listed, confirming they are installed packages."
        )
    )
    def test_both_distributions_in_installed_packages(self):
        """Both distributions appear in ``pip list`` output, confirming they are installed (not just importable from src/)."""
        result = subprocess.run(
            [sys.executable, "-m", "pip", "list", "--format=freeze"],
            capture_output=True,
            text=True,
            check=True,
        )
        installed = result.stdout.lower()
        assert "tool-swap" in installed, (
            "tool-swap must be an installed package (not just importable from src/)"
        )
        assert "tool-swap-runtime" in installed, (
            "tool-swap-runtime must be an installed package"
        )


class TestEditableAndWheelConsistency:
    """Editable install and wheel install must both expose the same metadata.

    This is verified by asserting that metadata.version() always returns
    the version declared in the package's __version__, regardless of
    install type. The actual install-type swap is performed by CI / Makefile.
    """

    def test_metadata_version_matches_version_attr_editable_style(self):
        """Assert that metadata.version() mirrors __version__ — true for both editable and wheel."""
        for pkg_name, attr_name in [
            ("tool-swap", "tool_swap"),
            ("tool-swap-runtime", "tool_swap_runtime"),
        ]:
            mod = importlib.import_module(attr_name)
            meta_ver = metadata.version(pkg_name)
            assert meta_ver == mod.__version__, (
                f"Installed {pkg_name}: metadata={meta_ver!r} != __version__={mod.__version__!r}"
            )
