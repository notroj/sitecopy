"""Tests run against each server, imported into test_dav.py and
test_vsftpd.py, which select the server with a protocol marker.  Each
test takes the site fixture and is run once per valid combination of
the rcfile option axes named by its axes marker (see siteconfig.py).
"""

import pytest

from common import *

def test_update_cycle(site):
    check_update_cycle(site)

# -- Moves --------------------------------------------------------------
#
# Each test is run with no move handling, with `checkmoved' and with
# `checkmoved renames'.  A file moved to a different directory under
# the same name is moved on the server with either form of checkmoved,
# a file moved and renamed only with `checkmoved renames'; otherwise
# the file is deleted and uploaded again.  In every case the remote
# tree must end up matching the local tree.

MOVE_TREE = {
    "a.txt": "File a\n",
    "b.txt": "File b, which is longer\n",
    "old/": None,
    "old/c.txt": "File c, in a directory\n",
    "keep/": None,
    "keep/d.txt": "File d, staying put\n",
}

@pytest.mark.axes("state", "moves")
def test_move_into_new_dir(site):
    # A directory is created, then an existing file is moved into it:
    # the directory must be created on the server before the move.
    setup_site(site, MOVE_TREE)
    local = site["local"]
    (local / "new").mkdir()
    (local / "a.txt").rename(local / "new/a.txt")
    res = update_and_check(site)
    assert_moved(res, "a.txt", "new/a.txt", moves_detected(site))

@pytest.mark.axes("state", "moves")
def test_move_into_nested_new_dirs(site):
    setup_site(site, MOVE_TREE)
    local = site["local"]
    (local / "x/y/z").mkdir(parents=True)
    (local / "a.txt").rename(local / "x/y/z/a.txt")
    res = update_and_check(site)
    assert_moved(res, "a.txt", "x/y/z/a.txt", moves_detected(site))

@pytest.mark.axes("state", "moves")
def test_move_into_existing_dir(site):
    setup_site(site, MOVE_TREE)
    local = site["local"]
    (local / "b.txt").rename(local / "keep/b.txt")
    res = update_and_check(site)
    assert_moved(res, "b.txt", "keep/b.txt", moves_detected(site))

@pytest.mark.axes("state", "moves")
def test_move_and_rename_into_new_dir(site):
    setup_site(site, MOVE_TREE)
    local = site["local"]
    (local / "new").mkdir()
    (local / "a.txt").rename(local / "new/renamed.txt")
    res = update_and_check(site)
    assert_moved(res, "a.txt", "new/renamed.txt", renames_detected(site))

@pytest.mark.axes("state", "moves")
def test_move_out_of_removed_dir(site):
    # The only file in a directory is moved out of it and the
    # directory is removed: the move must happen before the directory
    # is deleted on the server.
    setup_site(site, MOVE_TREE)
    local = site["local"]
    (local / "old/c.txt").rename(local / "c.txt")
    (local / "old").rmdir()
    res = update_and_check(site)
    assert_moved(res, "old/c.txt", "c.txt", moves_detected(site))
