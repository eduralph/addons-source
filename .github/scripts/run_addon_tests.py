#!/usr/bin/env python3
"""Run per-addon unit tests with a GI bootstrap and honest skip accounting.

Replaces a bare ``python -m unittest <modules>`` in CI. It does two things that
plain unittest does not:

1. **GI version bootstrap.** Before any test imports a ``gramps.gui`` module, it
   calls ``gi.require_version`` for Pango/PangoCairo/Gtk — the same set the
   Gramps GUI launcher (``gramps/gui/grampsgui.py``) pins at startup. A direct
   test import never runs that launcher, so without this the first
   ``from gi.repository import Gtk`` (in gramps core, e.g. ``gramps.gui.dialog``)
   warns and risks loading the wrong GTK on a host where GTK 4 is the default.

2. **Honest skip accounting.** unittest/xmlrunner exit 0 when every test SKIPS,
   so a wholly-skipped module reads as a pass. This runner FAILS a module whose
   tests all skipped — UNLESS the addon's declared system deps are not available
   on this platform (e.g. goocanvas/osm-gps-map are not on conda-forge), in which
   case the skip is expected and tolerated. The map of what is available per
   platform lives in ``addon_system_deps.py``.

Usage::

    run_addon_tests.py --platform apt   Addon.tests.test_x  Other.tests.test_y
    run_addon_tests.py --platform conda Addon.tests.test_x

Exit code is non-zero if any module is a hard failure (test failure/error, or an
unexpected all-skip on a platform where the addon's deps ARE available).
"""

# ------------------------
# Python modules
# ------------------------
from __future__ import annotations

import argparse
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import addon_system_deps as deps  # noqa: E402


def _bootstrap_gi() -> None:
    """Pin the GI versions the Gramps GUI launcher pins, before tests import."""
    try:
        import gi
    except ImportError:
        return
    for namespace, version in (("Pango", "1.0"), ("PangoCairo", "1.0"), ("Gtk", "3.0")):
        try:
            gi.require_version(namespace, version)
        except (ValueError, AttributeError):
            # Namespace/version not present here; leave it. A test that truly
            # needs it will surface that itself.
            pass


def _run_module(modname: str) -> unittest.TestResult:
    suite = unittest.defaultTestLoader.loadTestsFromName(modname)
    return unittest.TextTestRunner(verbosity=2).run(suite)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", required=True, choices=deps.PLATFORMS)
    parser.add_argument(
        "--root",
        default=".",
        help="addons-source root holding the <Addon>/ dirs (default: cwd)",
    )
    parser.add_argument("modules", nargs="*", help="dotted test modules to run")
    args = parser.parse_args(argv)

    if not args.modules:
        print("No per-addon unit test modules found")
        return 0

    _bootstrap_gi()

    hard_failures: list[str] = []
    summary: list[str] = []

    for modname in args.modules:
        addon = modname.split(".", 1)[0]
        addon_dir = os.path.join(args.root, addon)
        satisfiable = deps.addon_satisfiable_on(addon_dir, args.platform)

        try:
            result = _run_module(modname)
        except Exception as exc:  # import-time failure (loadTestsFromName)
            if satisfiable:
                hard_failures.append(modname)
                summary.append(f"  FAIL  {modname} — load error: {exc!r}")
            else:
                summary.append(
                    f"  skip  {modname} — not loadable on {args.platform} "
                    f"(addon system deps unavailable here)"
                )
            continue

        ran = result.testsRun
        skipped = len(result.skipped)
        broke = len(result.failures) + len(result.errors)

        if broke:
            hard_failures.append(modname)
            summary.append(f"  FAIL  {modname} — {broke} failed/errored")
        elif ran > 0 and skipped == ran:
            if satisfiable:
                hard_failures.append(modname)
                summary.append(
                    f"  FAIL  {modname} — all {ran} tests skipped "
                    f"(degraded coverage; deps ARE available on {args.platform})"
                )
            else:
                summary.append(
                    f"  skip  {modname} — all {ran} skipped, expected "
                    f"(addon system deps unavailable on {args.platform})"
                )
        elif skipped:
            summary.append(f"  ok    {modname} — {ran} tests, {skipped} skipped")
        else:
            summary.append(f"  ok    {modname} — {ran} tests")

    print("\n=== addon test summary ===")
    for line in summary:
        print(line)

    if hard_failures:
        print(f"\n{len(hard_failures)} module(s) failed: {hard_failures}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
