"""Tests run against each server, imported into test_dav.py and
test_vsftpd.py, which select the server with a protocol marker.  Each
test takes the site fixture and is run once per valid combination of
the rcfile option axes named by its axes marker (see siteconfig.py).
"""

import shutil
import time

import pytest

from common import *
from siteconfig import RELATIVE_ROOT

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

@pytest.mark.site_lines("state checksum", "checkmoved renames")
def test_swapped_names_survive_update(site):
    # Two files which swap names are two moves, each of which is the
    # other's source: applied in either order, one move overwrites
    # the file which the other has yet to move, so a file was lost
    # from the server and another left with the wrong contents, all
    # reported as a successful update.
    setup_site(site, {"aaa.txt": "contents of aaa\n",
                      "zzz.txt": "contents of zzz\n"})
    local = site["local"]
    (local / "aaa.txt").rename(local / "swapped")
    (local / "zzz.txt").rename(local / "aaa.txt")
    (local / "swapped").rename(local / "zzz.txt")
    res = run_sitecopy(site, ["--update", "testsite"])
    assert res.returncode == 0, res.stdout + res.stderr
    assert "Moving aaa.txt->zzz.txt: done." in res.stdout, res.stdout
    assert "Moving zzz.txt->aaa.txt: done." in res.stdout, res.stdout
    assert "Deleting" not in res.stdout, res.stdout
    assert "Uploading" not in res.stdout, res.stdout
    remote = remote_tree(site)
    assert remote.get("aaa.txt") == md5(b"contents of zzz\n"), remote
    assert remote.get("zzz.txt") == md5(b"contents of aaa\n"), remote
    assert_no_update(site)

@pytest.mark.site_lines("state checksum", "checkmoved renames")
def test_three_way_rotation_survives_update(site):
    # A three-way rotation of names is a longer cycle of moves with
    # the same defect.
    setup_site(site, {"aaa.txt": "contents of aaa\n",
                      "mmm.txt": "contents of mmm\n",
                      "zzz.txt": "contents of zzz\n"})
    local = site["local"]
    (local / "aaa.txt").rename(local / "rotated")
    (local / "mmm.txt").rename(local / "aaa.txt")
    (local / "zzz.txt").rename(local / "mmm.txt")
    (local / "rotated").rename(local / "zzz.txt")
    res = run_sitecopy(site, ["--update", "testsite"])
    assert res.returncode == 0, res.stdout + res.stderr
    assert "Moving aaa.txt->zzz.txt: done." in res.stdout, res.stdout
    assert "Moving mmm.txt->aaa.txt: done." in res.stdout, res.stdout
    assert "Moving zzz.txt->mmm.txt: done." in res.stdout, res.stdout
    assert "Deleting" not in res.stdout, res.stdout
    assert "Uploading" not in res.stdout, res.stdout
    remote = remote_tree(site)
    assert remote.get("aaa.txt") == md5(b"contents of mmm\n"), remote
    assert remote.get("mmm.txt") == md5(b"contents of zzz\n"), remote
    assert remote.get("zzz.txt") == md5(b"contents of aaa\n"), remote
    assert_no_update(site)


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

# -- Fetch --------------------------------------------------------------

FETCH_TREE = {
    "index.html": "<html>Home</html>\n",
    "name with spaces.txt": "Spaces\n",
    "image.bin": bytes(range(256)) * 4,
    "grow.txt": "Grows\n",
    "same.txt": "Same size\n",
    "gone.txt": "Deleted locally\n",
    "docs/": None,
    "docs/a.txt": "A\n",
    "docs/sub/": None,
    "docs/sub/deep.txt": "Deep\n",
    "empty/": None,
}

@pytest.mark.axes("state", "safe", "delete", protocol_axes=("state",))
def test_fetch(site):
    # The stored state is fetched from the server: with checksum
    # state, each file is downloaded to checksum it; with timesize
    # state, the stored times are those of the local files.
    local = site["local"]
    config = site["config"]
    setup_site(site, FETCH_TREE)

    # With the site in sync, fetching into an empty state leaves
    # nothing to update.
    (site["store"] / "testsite").unlink()
    res = run_sitecopy(site, ["--fetch", "testsite"])
    assert res.returncode == 0, res.stdout + res.stderr
    assert_no_update(site)

    # Changes on the server by someone else: a new file and directory,
    # a file grown, and a file changed without changing its size.
    create_remote(site, "remote-only.txt", "Only on the server\n")
    create_remote(site, "remote-dir/r.txt", "In a directory\n")
    if "safe" in config:
        # A later modification time is needed for safe mode.
        change_remote_later(site, "grow.txt", "Grows, on the server\n")
    else:
        change_remote(site, "grow.txt", "Grows, on the server\n",
                      int(time.time()))
    change_remote(site, "same.txt", "Same SIZE\n", int(time.time()))
    # Local changes: a new file, and a file deleted.
    write_tree(local, {"local-only.txt": "Only local\n"})
    (local / "gone.txt").unlink()

    res = run_sitecopy(site, ["--fetch", "testsite"])
    assert res.returncode == 0, res.stdout + res.stderr
    if "safe" in config:
        # Let time pass before the conditional uploads.
        time.sleep(2)
    res = run_sitecopy(site, ["--update", "testsite"])
    assert res.returncode == 0, res.stdout + res.stderr
    assert "Update completed successfully" in res.stdout, res.stdout

    # The server has the local files, except that the file changed
    # without changing its size is only detected with checksum state,
    # or in safe mode, since its modification time on the server has
    # changed since the last fetch: otherwise the server's version is
    # kept.
    expected = local_tree(local)
    if "state checksum" not in config and "safe" not in config:
        expected["same.txt"] = md5(b"Same SIZE\n")
    # Files not present locally are deleted, unless nodelete.
    if "nodelete" in config:
        expected.update({"remote-only.txt": md5(b"Only on the server\n"),
                         "remote-dir/": None,
                         "remote-dir/r.txt": md5(b"In a directory\n"),
                         "gone.txt": md5(b"Deleted locally\n")})
    assert remote_tree(site) == expected
    assert_no_update(site)

# -- Relative remote directory ------------------------------------------

# FTP commands with a path argument, which must be relative for a site
# with a relative directory.
PATH_COMMANDS = {"STOR", "RETR", "DELE", "MKD", "RMD", "RNFR", "RNTO",
                 "MDTM", "LIST", "SITE"}

def logged_ftp_commands(lines):
    """Return (verb, argument) for each FTP command in the given vsftpd
    log lines, which record commands as: ... "FTP command: Client
    "ADDRESS", "VERB ARGUMENT"."""
    commands = []
    for line in lines:
        if "FTP command:" not in line:
            continue
        command = line.rsplit(', "', 1)[1].rstrip('"')
        verb, _, arg = command.partition(" ")
        commands.append((verb.upper(), arg))
    return commands

@pytest.mark.site_lines(RELATIVE_ROOT)
def test_relative_root(site):
    # With the site's directory given relative to the directory the
    # user logs in to, FTP commands use relative paths, and `ftp
    # usecwd' has no effect.  Upload, change and delete files in
    # nested directories (the changes using temporary uploads, and
    # setting permissions), move a file between directories, then
    # fetch the site into an empty state, with timesize and checksum
    # state (which downloads each file).
    local = site["local"]
    vsftpd = site["logfile"] == "/var/log/vsftpd.log"
    if vsftpd:
        mark = server_log_mark(site)
    setup_site(site, FETCH_TREE)

    add_site_lines(site, "tempupload", "permissions all")
    (local / "docs/a.txt").write_text("A, changed\n")
    write_tree(local, {"new/": None, "new/dir/": None,
                       "new/dir/n.txt": "New\n"})
    shutil.rmtree(local / "docs/sub")
    (local / "gone.txt").unlink()
    update_and_check(site)

    # A move between directories, with RNFR and RNTO.
    add_site_lines(site, "checkmoved")
    (local / "new/dir/n.txt").rename(local / "docs/n.txt")
    move_and_check(site, "new/dir/n.txt", "docs/n.txt", True)

    for state in ("timesize", "checksum"):
        add_site_lines(site, "state " + state)
        (site["store"] / "testsite").unlink()
        res = run_sitecopy(site, ["--fetch", "testsite"])
        assert res.returncode == 0, res.stdout + res.stderr
        assert_no_update(site)

    if vsftpd:
        # vsftpd logs each command: check the paths are relative.
        commands = logged_ftp_commands(server_log_since(site, mark))
        sent = {verb for verb, _ in commands}
        assert PATH_COMMANDS <= sent, sorted(PATH_COMMANDS - sent)
        assert "CWD" not in sent
        assert ("RNFR", "site/new/dir/n.txt") in commands
        assert ("RNTO", "site/docs/n.txt") in commands
        for verb, arg in commands:
            if verb == "SITE":
                # SITE CHMOD MODE PATH
                arg = arg.split(" ", 2)[2]
            if verb in PATH_COMMANDS:
                assert arg.startswith("site/"), (verb, arg)

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

@pytest.mark.full_only
@pytest.mark.site_lines("exclude *.tmp", "exclude cache", "exclude /docs/*.m4")
def test_exclude_patterns(site):
    # A pattern without a slash matches the base name of files and
    # directories at any depth, and an excluded directory's contents
    # are excluded too; a pattern with a leading slash matches the
    # path from the site's root.
    setup_site(site, {"a.txt": "A\n", "b.tmp": "Temp\n",
                      "sub/": None, "sub/c.tmp": "Temp\n",
                      "sub/d.txt": "D\n",
                      "cache/": None, "cache/x.txt": "Cached\n",
                      "sub/cache/": None, "sub/cache/y.txt": "Cached\n",
                      "docs/": None, "docs/g.m4": "M4\n",
                      "docs/h.txt": "H\n",
                      "other/": None, "other/g.m4": "M4\n"},
               expected={"a.txt", "sub/", "sub/d.txt", "docs/",
                         "docs/h.txt", "other/", "other/g.m4"})

@pytest.mark.full_only
@pytest.mark.site_lines("exclude /only-root.txt", "exclude anywhere.txt")
def test_exclude_leading_slash(site):
    # With a leading slash, a pattern matches the path from the site's
    # root; without, the base name at any depth.
    setup_site(site, {"only-root.txt": "R\n", "anywhere.txt": "A\n",
                      "sub/": None, "sub/only-root.txt": "R\n",
                      "sub/anywhere.txt": "A\n"},
               expected={"sub/", "sub/only-root.txt"})

@pytest.mark.full_only
def test_exclude_added_later(site):
    # A file already uploaded which comes to match an exclude pattern
    # is deleted from the server.
    setup_site(site, {"a.txt": "A\n", "b.log": "Log\n"})
    add_site_lines(site, "exclude *.log")
    res = run_sitecopy(site, ["--update", "testsite"])
    assert res.returncode == 0, res.stdout + res.stderr
    assert "Deleting b.log" in res.stdout, res.stdout
    assert set(remote_tree(site)) == {"a.txt"}
    assert_no_update(site)

@pytest.mark.full_only
@pytest.mark.site_lines("exclude *.bak")
def test_exclude_fetch(site):
    # Excluded files on the server are ignored by --fetch, so aren't
    # deleted by a later update.
    setup_site(site, {"a.txt": "A\n"})
    create_remote(site, "b.bak", "Backup\n")
    (site["store"] / "testsite").unlink()
    res = run_sitecopy(site, ["--fetch", "testsite"])
    assert res.returncode == 0, res.stdout + res.stderr
    assert "b.bak" not in res.stdout, res.stdout
    assert_no_update(site)
    write_tree(site["local"], {"c.txt": "C\n"})
    res = run_sitecopy(site, ["--update", "testsite"])
    assert res.returncode == 0, res.stdout + res.stderr
    assert set(remote_tree(site)) == {"a.txt", "b.bak", "c.txt"}

@pytest.mark.full_only
@pytest.mark.site_lines("ignore *.cfg")
def test_ignore_updates(site):
    # Changes to ignored files are not uploaded, but ignored files are
    # created and deleted as normal.
    local = site["local"]
    setup_site(site, {"a.cfg": "A\n", "sub/": None, "sub/b.cfg": "B\n",
                      "c.txt": "C\n"})
    uploaded = remote_tree(site)["a.cfg"]

    (local / "a.cfg").write_text("A, changed locally\n")
    res = run_sitecopy(site, ["--list", "testsite"])
    assert "[a.cfg]" in res.stdout, res.stdout
    assert "are ignored during updates" in res.stdout, res.stdout
    res = run_sitecopy(site, ["--update", "testsite"])
    assert res.returncode == 0, res.stdout + res.stderr
    assert remote_tree(site)["a.cfg"] == uploaded

    # A new ignored file is uploaded, and a deleted one deleted.
    write_tree(local, {"n.cfg": "New\n"})
    (local / "sub/b.cfg").unlink()
    res = run_sitecopy(site, ["--update", "testsite"])
    assert res.returncode == 0, res.stdout + res.stderr
    remote = remote_tree(site)
    assert remote["n.cfg"] == md5(b"New\n")
    assert "sub/b.cfg" not in remote
    assert remote["a.cfg"] == uploaded

@pytest.mark.full_only
@pytest.mark.site_lines("ignore /conf/*.cfg", "ignore local.ini")
def test_ignore_leading_slash(site):
    # With a leading slash, a pattern matches the path from the site's
    # root; without, the base name at any depth.
    local = site["local"]
    tree = {"conf/": None, "conf/a.cfg": "A\n", "other/": None,
            "other/a.cfg": "A\n", "local.ini": "L\n",
            "sub/": None, "sub/local.ini": "L\n"}
    setup_site(site, tree)
    uploaded = remote_tree(site)
    for name in ("conf/a.cfg", "other/a.cfg", "local.ini", "sub/local.ini"):
        (local / name).write_text("Changed locally\n")
    res = run_sitecopy(site, ["--update", "testsite"])
    assert res.returncode == 0, res.stdout + res.stderr
    remote = remote_tree(site)
    assert remote["other/a.cfg"] == md5(b"Changed locally\n")
    for name in ("conf/a.cfg", "local.ini", "sub/local.ini"):
        assert remote[name] == uploaded[name], name

@pytest.mark.full_only
@pytest.mark.site_lines("ignore *.cfg")
def test_ignore_synchronize(site):
    # Synchronize mode overwrites local changes to ignored files with
    # the files on the server.
    local = site["local"]
    setup_site(site, {"a.cfg": "A\n", "c.txt": "C\n"})
    (local / "a.cfg").write_text("A, changed locally\n")
    res = run_sitecopy(site, ["--synchronize", "testsite"])
    assert res.returncode == 0, res.stdout + res.stderr
    assert (local / "a.cfg").read_text() == "A\n"

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
