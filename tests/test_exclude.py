"""Regression tests for Debian bug #167277: exclude patterns which
embed a slash matched nothing.

The rcfile parser classified only patterns *beginning* with a slash
as path patterns; `exclude stats/*' and `exclude stats/index.html'
were matched against the file's base name, which can never contain a
slash, so they silently excluded nothing.  The bare name (exclude
stats) and leading-slash (exclude /stats) forms always worked and are
guarded here too.

These tests exercise the local directory scan only (--list after
--initialize), so no server is needed.  The behaviour during
--update and --fetch, which use the same pattern lists, is tested
against real servers in server_tests.py.
"""

import re

import pytest

from common import run_sitecopy
from conftest import make_sitecopy_env

ADDED_RE = re.compile(
    r"^\* These items have been added since the last update:\n(.*)$",
    re.MULTILINE)


def excl_site(tmp_path, patterns):
    """A site environment with the given exclude patterns, using the
    ftp protocol, which the local scan never contacts."""
    config = "  remote /\n  protocol ftp\n" + "".join(
        "  exclude %s\n" % pattern for pattern in patterns)
    return make_sitecopy_env(tmp_path, config)


def build_tree(root):
    """The corpus of Debian bug #167277: a stats/ directory holding
    index.html and friends alongside the site root index.html."""
    (root / "index.html").write_text("root index\n")
    (root / "images.html").write_text("images\n")
    stats = root / "stats"
    stats.mkdir()
    (stats / "index.html").write_text("stats index\n")
    (stats / "ctry.html").write_text("ctry\n")
    (stats / "usage.html").write_text("usage\n")


def added_items(senv):
    """Files reported as locally added by --list, as a set of tokens
    ('dir:stats' for directories)."""
    res = run_sitecopy(senv, ["--initialize", "testsite"])
    assert res.returncode == 0, res.stdout + res.stderr
    res = run_sitecopy(senv, ["--list", "testsite"])
    assert res.returncode == 1, res.stdout + res.stderr
    match = ADDED_RE.search(res.stdout)
    assert match, res.stdout
    return {item.strip() for item in match.group(1).split(",")}


def test_exclude_directory_name(tmp_path):
    # A bare directory name excludes the directory and everything
    # beneath it (man page, "Excluding Files").
    senv = excl_site(tmp_path, ["stats"])
    build_tree(senv["local"])
    assert added_items(senv) == {"index.html", "images.html"}


def test_exclude_leading_slash(tmp_path):
    # The leading-slash form was always classified as a path pattern;
    # guard that behaviour.
    senv = excl_site(tmp_path, ["/stats"])
    build_tree(senv["local"])
    assert added_items(senv) == {"index.html", "images.html"}


def test_exclude_directory_contents_pattern(tmp_path):
    # Debian bug #167277: `stats/*' matched nothing, leaking the
    # whole stats/ tree into the file list.
    senv = excl_site(tmp_path, ["stats/*"])
    build_tree(senv["local"])
    assert added_items(senv) == {"index.html", "images.html", "dir:stats"}


def test_exclude_file_within_directory(tmp_path):
    # Debian bug #167277: `stats/index.html' matched nothing, so the
    # stats index could not be excluded without also excluding the
    # root index.html.
    senv = excl_site(tmp_path, ["stats/index.html"])
    build_tree(senv["local"])
    items = added_items(senv)
    assert "stats/index.html" not in items
    assert "stats/ctry.html" in items
    assert "index.html" in items


@pytest.mark.parametrize("patterns", [["stats/*", "ctry*"], ["ctry*", "stats/*"]],
                         ids=["dir_then_file", "file_then_dir"])
def test_exclude_multiple_patterns(tmp_path, patterns):
    # A whole directory and a file pattern must both take effect, in
    # either order.
    senv = excl_site(tmp_path, patterns)
    build_tree(senv["local"])
    assert added_items(senv) == {"index.html", "images.html", "dir:stats"}
