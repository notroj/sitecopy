"""Tests run against each server, imported into test_dav.py and
test_vsftpd.py, which select the server with a protocol marker.  Each
test takes the site fixture and is run once per valid combination of
the rcfile option axes named by its axes marker (see siteconfig.py).
"""

import shutil
import time

import pytest

from common import *

@pytest.mark.axes("delete", "overwrite", "safe", "tempupload", "lowercase")
def test_update_cycle(site):
    check_update_cycle(site)

# -- Moves --------------------------------------------------------------
#
# Each test is run with no move handling, with `checkmoved' and with
# `checkmoved renames', with and without `nodelete'.  A file moved to a different directory under
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

@pytest.mark.axes("state", "moves", "delete")
def test_move_into_new_dir(site):
    # A directory is created, then an existing file is moved into it:
    # the directory must be created on the server before the move.
    setup_site(site, MOVE_TREE)
    local = site["local"]
    (local / "new").mkdir()
    (local / "a.txt").rename(local / "new/a.txt")
    move_and_check(site, "a.txt", "new/a.txt", moves_detected(site))

@pytest.mark.axes("state", "moves", "delete")
def test_move_into_nested_new_dirs(site):
    setup_site(site, MOVE_TREE)
    local = site["local"]
    (local / "x/y/z").mkdir(parents=True)
    (local / "a.txt").rename(local / "x/y/z/a.txt")
    move_and_check(site, "a.txt", "x/y/z/a.txt", moves_detected(site))

@pytest.mark.axes("state", "moves", "delete")
def test_move_into_existing_dir(site):
    setup_site(site, MOVE_TREE)
    local = site["local"]
    (local / "b.txt").rename(local / "keep/b.txt")
    move_and_check(site, "b.txt", "keep/b.txt", moves_detected(site))

@pytest.mark.axes("state", "moves", "delete")
def test_move_and_rename_into_new_dir(site):
    setup_site(site, MOVE_TREE)
    local = site["local"]
    (local / "new").mkdir()
    (local / "a.txt").rename(local / "new/renamed.txt")
    move_and_check(site, "a.txt", "new/renamed.txt", renames_detected(site))

@pytest.mark.axes("state", "moves", "delete")
def test_move_out_of_removed_dir(site):
    # The only file in a directory is moved out of it and the
    # directory is removed: the move must happen before the directory
    # is deleted on the server.
    setup_site(site, MOVE_TREE)
    local = site["local"]
    (local / "old/c.txt").rename(local / "c.txt")
    (local / "old").rmdir()
    move_and_check(site, "old/c.txt", "c.txt", moves_detected(site))

# -- Safe mode ------------------------------------------------------------

@pytest.mark.axes("safe")
def test_remote_change(site):
    # A file changed on the server by someone else since it was
    # uploaded is not overwritten in safe mode, and is otherwise.
    setup_site(site, {"page.txt": "Original\n"})
    remote_before = remote_tree(site)["page.txt"]
    change_remote_later(site, "page.txt", "Changed on the server\n")
    changed = remote_tree(site)["page.txt"]
    assert changed != remote_before
    (site["local"] / "page.txt").write_text("Changed locally, again\n")

    res = run_sitecopy(site, ["--update", "testsite"])
    if "safe" in site["config"]:
        for _ in range(2):
            assert res.returncode == 1, res.stdout + res.stderr
            assert ("Remote file has been modified - not overwriting"
                    in res.stdout), res.stdout
            assert remote_tree(site)["page.txt"] == changed
            # The file is not marked as updated, so a later update
            # fails in the same way.
            res = run_sitecopy(site, ["--update", "testsite"])
    else:
        assert res.returncode == 0, res.stdout + res.stderr
        assert_trees_match(site)

@pytest.mark.site_lines("safe")
def test_safe_unchanged_remote(site):
    # A file changed only locally is uploaded in safe mode, however
    # long after the last update.
    setup_site(site, {"page.txt": "Original\n"})
    time.sleep(2)
    (site["local"] / "page.txt").write_text("Changed locally\n")
    update_and_check(site)

@pytest.mark.xfail(strict=True, reason="the stored state reader carries "
                   "the server modification time of one file over to the "
                   "next file which has none")
def test_safe_enabled_later(site):
    # Files uploaded before safe mode was enabled have no recorded
    # server modification time, so are uploaded unconditionally.
    setup_site(site, {"a.txt": "A\n", "b.txt": "B\n"})
    add_site_lines(site, "safe")
    # Records the server time of a.txt, but not b.txt.
    (site["local"] / "a.txt").write_text("A, changed\n")
    update_and_check(site)

    # Make b.txt's time on the server later than a.txt's.
    change_remote_later(site, "b.txt", "B\n")
    (site["local"] / "b.txt").write_text("B, changed\n")
    update_and_check(site)

# -- Temporary uploads ----------------------------------------------------

@pytest.mark.axes("tempupload")
def test_tempupload(site):
    # With tempupload, files are uploaded under a temporary ".in."
    # name and then moved into place.  The names are unique to each
    # test, since the server log is shared by every test.
    token = site["config"].id
    setup_site(site, {"top-%s.txt" % token: "Top\n",
                      "dir/": None,
                      "dir/nested-%s.txt" % token: "Nested\n"})
    for name in ("top-%s.txt" % token, "nested-%s.txt" % token):
        lines = server_log_lines(site, name)
        assert lines
        temp = any(".in." + name in line for line in lines)
        assert temp == ("tempupload" in site["config"]), lines

# -- Deletes and overwrites ----------------------------------------------

@pytest.mark.site_lines("nodelete")
def test_nodelete(site):
    setup_site(site, {"a.txt": "A\n", "dir/": None, "dir/b.txt": "B\n",
                      "c.txt": "C\n"})
    local = site["local"]
    (local / "a.txt").unlink()
    shutil.rmtree(local / "dir")

    res = run_sitecopy(site, ["--list", "testsite"])
    assert res.returncode == 0, res.stdout + res.stderr
    assert ("These items have been deleted, but will be left on the server"
            in res.stdout), res.stdout

    res = update_and_check(site)
    assert "Nothing to do - no changes found" in res.stdout
    assert "a.txt" in remote_tree(site)
    assert "dir/b.txt" in remote_tree(site)

    # Other changes are made, and the deleted items still kept.
    (local / "c.txt").write_text("C, changed\n")
    res = update_and_check(site)
    assert "Uploading c.txt" in res.stdout
    assert "Deleting" not in res.stdout
    assert "a.txt" in remote_tree(site)

@pytest.mark.xfail(strict=True, reason="--list counts the deleted items "
                   "which nodelete leaves on the server as items to update")
@pytest.mark.site_lines("nodelete")
def test_nodelete_list_count(site):
    setup_site(site, {"a.txt": "A\n", "b.txt": "B\n"})
    (site["local"] / "a.txt").unlink()
    (site["local"] / "b.txt").write_text("B, changed\n")
    res = run_sitecopy(site, ["--list", "testsite"])
    assert "(1 item to update)" in res.stdout, res.stdout

@pytest.mark.site_lines("nooverwrite")
def test_nooverwrite(site):
    # With nooverwrite, a changed file is deleted from the server
    # before the new version is uploaded.
    setup_site(site, {"a.txt": "A\n"})
    (site["local"] / "a.txt").write_text("A, changed\n")
    res = update_and_check(site)
    deleting = res.stdout.find("Deleting a.txt")
    uploading = res.stdout.find("Uploading a.txt")
    assert 0 <= deleting < uploading, res.stdout

# -- Lowercase ----------------------------------------------------------------

@pytest.mark.site_lines("lowercase")
def test_lowercase(site):
    setup_site(site, {"Dir/": None, "Dir/File.TXT": "Mixed\n",
                      "UPPER.HTML": "Upper\n"})
    remote = remote_tree(site)
    assert set(remote) == {"dir/", "dir/file.txt", "upper.html"}

    # The output uses the local names.
    (site["local"] / "Dir/File.TXT").write_text("Mixed, changed\n")
    res = update_and_check(site)
    assert "Uploading Dir/File.TXT" in res.stdout

@pytest.mark.xfail(strict=True, reason="after --fetch, the update tries "
                   "to create the mixed-case directory again, which fails, "
                   "and deletes the file fetched from the server")
@pytest.mark.site_lines("lowercase")
def test_lowercase_after_fetch(site):
    setup_site(site, {"Dir/": None, "Dir/File.TXT": "Mixed\n"})
    res = run_sitecopy(site, ["--fetch", "testsite"])
    assert res.returncode == 0, res.stdout + res.stderr
    write_tree(site["local"], {"Dir/New.txt": "New\n"})
    update_and_check(site)

# -- Excluded and ignored files -------------------------------------------

@pytest.mark.site_lines("exclude *.bak", "exclude /private")
def test_exclude(site):
    setup_site(site, {"a.txt": "A\n", "a.txt.bak": "Backup\n",
                      "dir/": None, "dir/b.bak": "Backup\n",
                      "private/": None, "private/secret.txt": "Secret\n",
                      "dir/private/": None, "dir/private/c.txt": "C\n"},
               expected={"a.txt", "dir/", "dir/private/",
                         "dir/private/c.txt"})

@pytest.mark.site_lines("ignore *.cfg")
def test_ignore(site):
    # Local changes to ignored files are not uploaded.
    setup_site(site, {"a.txt": "A\n", "site.cfg": "Config\n"})
    uploaded = remote_tree(site)["site.cfg"]
    (site["local"] / "site.cfg").write_text("Config, changed locally\n")
    res = run_sitecopy(site, ["--update", "testsite"])
    assert res.returncode == 0, res.stdout + res.stderr
    assert remote_tree(site)["site.cfg"] == uploaded

@pytest.mark.site_lines("exclude stats/*")
def test_exclude_directory_contents(site):
    # Debian bug #167277: a pattern embedding a slash was classified
    # as a base-name pattern and matched nothing, so `exclude
    # stats/*' did not keep the contents of the directory off the
    # server.
    setup_site(site, {"index.html": "Root\n", "stats/": None,
                      "stats/ctry.html": "Ctry\n",
                      "stats/usage.html": "Usage\n"},
               expected={"index.html", "stats/"})

@pytest.mark.site_lines("exclude stats/index.html")
def test_exclude_file_within_directory(site):
    # Debian bug #167277: `exclude stats/index.html' matched nothing,
    # so the file could not be excluded without also excluding the
    # root index.html sharing its base name.
    setup_site(site, {"index.html": "Root\n", "stats/": None,
                      "stats/index.html": "Stats\n",
                      "stats/ctry.html": "Ctry\n"},
               expected={"index.html", "stats/", "stats/ctry.html"})

@pytest.mark.site_lines("exclude stats/*")
def test_exclude_fetch(site):
    # Files on the server which match an exclude pattern are left out
    # of the fetched file list (Debian bug #167277).
    server_exec(site, "mkdir -p '%s/stats' && printf 'Usage\\n' > "
                "'%s/stats/usage.html'" % (site["root"], site["root"]))
    res = run_sitecopy(site, ["--initialize", "testsite"])
    assert res.returncode == 0, res.stdout + res.stderr
    res = run_sitecopy(site, ["--fetch", "testsite"])
    assert res.returncode == 0, res.stdout + res.stderr
    assert "usage.html" not in res.stdout

# -- Symbolic links ---------------------------------------------------------

@pytest.mark.axes("symlinks")
def test_symlinks(site):
    # By default the target of a link is uploaded; with `symlinks
    # ignore' links are skipped.
    local = site["local"]
    res = run_sitecopy(site, ["--initialize", "testsite"])
    assert res.returncode == 0, res.stdout + res.stderr
    write_tree(local, {"target.txt": "Target\n"})
    (local / "link.txt").symlink_to("target.txt")
    res = run_sitecopy(site, ["--update", "testsite"])
    assert res.returncode == 0, res.stdout + res.stderr

    remote = remote_tree(site)
    if "symlinks ignore" in site["config"]:
        assert set(remote) == {"target.txt"}
    else:
        assert remote["link.txt"] == remote["target.txt"]

# -- Permissions --------------------------------------------------------------

@pytest.mark.axes("permissions")
def test_permissions(site):
    local = site["local"]
    res = run_sitecopy(site, ["--initialize", "testsite"])
    assert res.returncode == 0, res.stdout + res.stderr
    write_tree(local, {"plain.txt": "Plain\n", "script.sh": "#!/bin/sh\n",
                       "private.txt": "Private\n", "dir/": None,
                       "dir/f.txt": "F\n"})
    (local / "script.sh").chmod(0o755)
    (local / "private.txt").chmod(0o600)
    (local / "dir").chmod(0o711)
    res = run_sitecopy(site, ["--update", "testsite"])
    assert res.returncode == 0, res.stdout + res.stderr

    modes = remote_modes(site)
    config = site["config"]
    if "permissions all" in config:
        assert modes["plain.txt"] == "644"
        assert modes["script.sh"] == "755"
        assert modes["private.txt"] == "600"
    elif "permissions exec" in config:
        # With WebDAV, only the executable live property can be set,
        # which mod_dav_fs maps to the owner's execute bit.
        expected = "744" if config.protocol == "dav" else "755"
        assert modes["script.sh"] == expected
        assert modes["private.txt"] == "644"
    else:
        assert modes["script.sh"] == "644"
    if "permissions dir" in config:
        assert modes["dir"] == "711"
