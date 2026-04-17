#
# Gramps - a GTK+/GNOME based genealogy program
#
# Copyright (C) 2026  Eduard Ralph
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
#

"""
Integration tests for the Form addon loader — covers
``gramps-project/gramps#11707`` (*ValueError: not enough values to
unpack* when a form's ``<section type='family'>`` title lacks the
``X/Y`` separator).

Scenarios covered:

* Malformed XML produces an ``ErrorDialog`` rather than a bare traceback.
* A partially-broken file still loads its well-formed ``<form>`` entries.
* The shipped built-in definition files load cleanly without any error
  dialogs being raised.
"""

# ------------------------
# Python modules
# ------------------------
import os
import sys
import textwrap

import pytest

# Imports below reach into Gramps via the Form addon; skip if unavailable.
pytest.importorskip("gi")
pytest.importorskip("gramps")


# ---------------------------------------------------------------------------
# Ensure GRAMPS_RESOURCES is set for Gramps' config machinery
# ---------------------------------------------------------------------------
if "GRAMPS_RESOURCES" not in os.environ:
    import gramps

    os.environ["GRAMPS_RESOURCES"] = os.path.dirname(
        os.path.dirname(gramps.__file__)
    )


# ---------------------------------------------------------------------------
# Make the addon importable
# ---------------------------------------------------------------------------
ADDON_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ADDON_DIR not in sys.path:
    sys.path.insert(0, ADDON_DIR)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def form_module(monkeypatch):
    """
    Import the Form addon's ``form`` module with ``ErrorDialog`` patched
    to record invocations instead of opening a GTK dialog.

    Yields a ``(module, shown)`` tuple where ``shown`` is a list of
    ``(title, body)`` pairs captured from each ``ErrorDialog`` call.
    """
    import form

    shown: list[tuple[str, str]] = []

    def _fake_error_dialog(title, body="", *args, **kwargs):
        shown.append((str(title), str(body)))

    monkeypatch.setattr(form, "ErrorDialog", _fake_error_dialog)
    yield form, shown


def _write(tmp_path, filename: str, content: str) -> None:
    (tmp_path / filename).write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# Error-dialog wiring
# ---------------------------------------------------------------------------
def test_malformed_xml_shows_error_dialog(form_module, tmp_path, monkeypatch):
    """XML syntax errors should raise an ErrorDialog, not a traceback."""
    form, shown = form_module

    _write(tmp_path, "custom.xml", "<forms><form id='F1'><unclosed></forms>")
    monkeypatch.setattr(form, "definition_files", ["custom.xml"])

    instance = form.Form(definition_dir=str(tmp_path))

    assert shown, "no ErrorDialog was displayed"
    title, body = shown[0]
    assert "XML syntax error" in title
    assert "custom.xml" in body
    assert list(instance.get_form_ids()) == []


def test_invalid_family_title_shows_error_dialog(
    form_module, tmp_path, monkeypatch
):
    """
    The exact condition from bug 11707 — a family section with a
    non-``X/Y`` title — must be surfaced as an ErrorDialog at load time
    rather than an unhandled exception when the user later opens the
    form.
    """
    form, shown = form_module

    _write(
        tmp_path,
        "custom.xml",
        textwrap.dedent("""\
            <forms>
                <form id='F1' type='Marriage' title='Bad Marriage'>
                    <section role='Family' type='family' title='Couple'/>
                </form>
            </forms>
        """),
    )
    monkeypatch.setattr(form, "definition_files", ["custom.xml"])

    form.Form(definition_dir=str(tmp_path))

    assert shown, "no ErrorDialog was displayed for invalid family title"
    title, body = shown[0]
    assert "Invalid Form definition file" in title
    assert "Name1/Name2" in body


def test_partially_broken_file_still_loads_valid_forms(
    form_module, tmp_path, monkeypatch
):
    """A broken <form> must not prevent sibling <form> elements from loading."""
    form, shown = form_module

    _write(
        tmp_path,
        "custom.xml",
        textwrap.dedent("""\
            <forms>
                <form id='GOOD' type='Census' title='Good Census'>
                    <section role='Primary' type='person'/>
                </form>
                <form id='BAD' type='Marriage' title='Bad Marriage'>
                    <section role='Family' type='family' title='Couple'/>
                </form>
            </forms>
        """),
    )
    monkeypatch.setattr(form, "definition_files", ["custom.xml"])

    instance = form.Form(definition_dir=str(tmp_path))
    loaded_ids = list(instance.get_form_ids())

    assert "GOOD" in loaded_ids, "valid form should still load"
    assert "BAD" not in loaded_ids, "invalid form should be skipped"
    assert shown, "the broken form should have been reported"


def test_missing_role_attribute_shows_error_dialog(
    form_module, tmp_path, monkeypatch
):
    """A section missing its ``role`` attribute should be reported clearly."""
    form, shown = form_module

    _write(
        tmp_path,
        "custom.xml",
        textwrap.dedent("""\
            <forms>
                <form id='F1' type='Census' title='x'>
                    <section type='person'/>
                </form>
            </forms>
        """),
    )
    monkeypatch.setattr(form, "definition_files", ["custom.xml"])

    form.Form(definition_dir=str(tmp_path))

    assert shown
    _, body = shown[0]
    assert "role" in body


def test_invalid_section_type_shows_error_dialog(
    form_module, tmp_path, monkeypatch
):
    """Unknown section types produce a clear error rather than a later crash."""
    form, shown = form_module

    _write(
        tmp_path,
        "custom.xml",
        textwrap.dedent("""\
            <forms>
                <form id='F1' type='Census' title='x'>
                    <section role='Primary' type='bogus'/>
                </form>
            </forms>
        """),
    )
    monkeypatch.setattr(form, "definition_files", ["custom.xml"])

    instance = form.Form(definition_dir=str(tmp_path))

    assert shown
    _, body = shown[0]
    assert "bogus" in body
    assert "F1" not in list(instance.get_form_ids())


# ---------------------------------------------------------------------------
# Shipped files load cleanly
# ---------------------------------------------------------------------------
def test_shipped_files_load_without_errors(form_module):
    """
    The built-in definition files that ship with the addon must load
    without triggering a single ErrorDialog, otherwise end users would
    see a popup every time they opened Gramps.
    """
    form, shown = form_module

    instance = form.Form()

    assert not shown, (
        "Built-in definition files triggered ErrorDialog calls:\n"
        + "\n".join(f"{t}: {b}" for t, b in shown)
    )
    # At least one form should have loaded from the built-ins.
    assert list(instance.get_form_ids())
