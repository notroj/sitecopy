"""Regression tests for specific bugs, each run once against vsftpd
in its default configuration (plus any rcfile lines the test needs),
rather than across every combination of rcfile options.

Tests for bugs which are not fixed yet are strict xfails: fixing the
bug turns the test into a pass, which then must be recorded by
removing the xfail marker."""

import os
import re

import pytest

from common import *

pytestmark = [pytest.mark.protocol("ftp"), pytest.mark.default_config]

def stored_items(site):
    """Return the filenames recorded in the site's stored state."""
    state = (site["store"] / "testsite").read_text()
    return re.findall(r"<filename>([^<]*)</filename>", state)

# -- --verify -------------------------------------------------------------

@pytest.mark.xfail(strict=True, reason="--verify lists only the site's "
                   "top directory, so reports every file in a "
                   "subdirectory as missing from the server")
def test_verify_subdirectories(site):
    setup_site(site, {"top.txt": "Top\n", "dir/": None,
                      "dir/sub.txt": "Sub\n", "dir/deeper/": None,
                      "dir/deeper/d.txt": "Deeper\n"})
    res = run_sitecopy(site, ["--verify", "testsite"])
    assert res.returncode == 0, res.stdout + res.stderr
    assert "Verify completed successfully" in res.stdout, res.stdout

@pytest.mark.xfail(strict=True, reason="--verify with checksum state "
                   "compares the stored checksums with checksums which "
                   "are never fetched, so reports every file as changed")
@pytest.mark.site_lines("state checksum")
def test_verify_checksum(site):
    setup_site(site, {"a.txt": "A\n", "b.txt": "B\n"})
    res = run_sitecopy(site, ["--verify", "testsite"])
    assert res.returncode == 0, res.stdout + res.stderr
    assert "Changed on server" not in res.stdout, res.stdout

# -- --fetch --------------------------------------------------------------

@pytest.mark.xfail(strict=True, reason="--fetch ignores a failure to "
                   "download a file for its checksum, and records an "
                   "empty checksum for it")
@pytest.mark.site_lines("state checksum")
def test_fetch_checksum_download_failure(site):
    setup_site(site, {"a.txt": "A\n", "unreadable.txt": "U\n"})
    # The server can't read the file, so can't send it.
    server_exec(site, "chmod 000 '%s/unreadable.txt'" % site["root"])
    try:
        (site["store"] / "testsite").unlink()
        res = run_sitecopy(site, ["--fetch", "testsite"])
        assert res.returncode != 0, res.stdout + res.stderr
    finally:
        server_exec(site, "chmod 644 '%s/unreadable.txt'" % site["root"])

@pytest.mark.xfail(strict=True, reason="--fetch silently skips "
                   "directories beyond a fixed limit of 1024 pending "
                   "directories")
def test_fetch_many_directories(site):
    # A directory on the server holding more subdirectories than the
    # fetch's directory stack can hold, each with a file.
    count = 1030
    res = run_sitecopy(site, ["--initialize", "testsite"])
    assert res.returncode == 0, res.stdout + res.stderr
    server_exec(site, "cd '%s' && for i in $(seq %d); do mkdir d$i "
                "&& echo x > d$i/f; done && chown -R --reference=. ."
                % (site["root"], count))

    res = run_sitecopy(site, ["--fetch", "testsite"])
    assert res.returncode == 0, res.stdout + res.stderr
    assert len(stored_items(site)) == 2 * count

# -- Updates ---------------------------------------------------------------

@pytest.mark.xfail(strict=True, reason="with nooverwrite, if the upload "
                   "fails after the remote file was deleted, later "
                   "updates try to delete it again, fail, and never "
                   "upload it")
@pytest.mark.site_lines("nooverwrite")
def test_nooverwrite_failed_upload(site):
    setup_site(site, {"a.txt": "A\n"})
    path = site["local"] / "a.txt"
    path.write_text("A, changed\n")
    # The upload fails, since sitecopy can't read the local file,
    # after the remote file has been deleted.
    path.chmod(0)
    try:
        res = run_sitecopy(site, ["--update", "testsite"])
        assert res.returncode != 0, res.stdout + res.stderr
        assert "a.txt" not in remote_tree(site)
    finally:
        path.chmod(0o644)

    # Once the file can be read, the next update uploads it.
    res = run_sitecopy(site, ["--update", "testsite"])
    assert res.returncode == 0, res.stdout + res.stderr
    assert remote_tree(site)["a.txt"] == md5(b"A, changed\n")

@pytest.mark.xfail(strict=True, reason="with tempupload, a file is "
                   "uploaded to a temporary \".in.\" name, overwriting a "
                   "file of that name on the server")
@pytest.mark.site_lines("tempupload")
def test_tempupload_name_clash(site):
    setup_site(site, {".in.page.txt": "A real file\n"})
    write_tree(site["local"], {"page.txt": "Page\n"})
    res = run_sitecopy(site, ["--update", "testsite"])
    assert res.returncode == 0, res.stdout + res.stderr
    remote = remote_tree(site)
    assert remote.get(".in.page.txt") == md5(b"A real file\n"), remote
    assert remote.get("page.txt") == md5(b"Page\n"), remote
