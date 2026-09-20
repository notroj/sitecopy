"""Regression tests for specific bugs, each run once against vsftpd
in its default configuration (plus any rcfile lines the test needs),
rather than across every combination of rcfile options.

Tests for bugs which are not fixed yet are strict xfails: fixing the
bug turns the test into a pass, which then must be recorded by
removing the xfail marker."""

import os
import re
import select
import signal
import subprocess
import time

import pytest

from common import *

pytestmark = [pytest.mark.protocol("ftp"), pytest.mark.default_config]

def stored_items(site):
    """Return the filenames recorded in the site's stored state."""
    state = (site["store"] / "testsite").read_text()
    return re.findall(r"<filename>([^<]*)</filename>", state)

# -- Storage file locking -------------------------------------------------

def test_lock_excludes_concurrent_update(site):
    # While one update is in progress, a second update of the same
    # site fails rather than racing it.  --prompting stops the first
    # update with the lock held, waiting for an answer.
    setup_site(site, {"a.txt": "A\n"})
    (site["local"] / "a.txt").write_text("A, changed\n")

    cmd = ["./sitecopy", "--rcfile", str(site["rcfile"]),
           "--storepath", str(site["store"]), "--prompting",
           "--update", "testsite"]
    first = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, text=True)
    lock = site["store"] / "testsite.lock"
    try:
        # Wait for the first process to take the lock; it then stops
        # at the prompt, holding it.  (The prompt itself cannot be
        # waited for: it is not flushed when stdout is a pipe.)
        for _ in range(300):
            if lock.exists():
                break
            time.sleep(0.1)
        assert lock.exists(), "first sitecopy did not take the lock"

        res = run_sitecopy(site, ["--update", "testsite"])
        assert res.returncode != 0, res.stdout + res.stderr
        assert "Locked by process %d" % first.pid in res.stdout, res.stdout
        assert "Skipping site `testsite'" in res.stdout, res.stdout
        # The second process left the first one's upload alone.
        assert remote_tree(site)["a.txt"] == md5(b"A\n")
    finally:
        first.stdin.write("y\n")
        first.stdin.close()
        assert first.wait(timeout=30) == 0
        first.stdout.close()

    # The first update finished, so the site is unlocked and updated.
    assert not lock.exists()
    assert remote_tree(site)["a.txt"] == md5(b"A, changed\n")
    assert_no_update(site)

def test_prompt_flushed_to_pipe(site):
    # The prompt must reach a pipe before the answer is given, or a
    # caller which is not a terminal sees nothing and appears to hang.
    setup_site(site, {})
    write_tree(site["local"], {"a.txt": "A\n"})

    cmd = ["./sitecopy", "--rcfile", str(site["rcfile"]),
           "--storepath", str(site["store"]), "--prompting",
           "--update", "testsite"]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE)
    try:
        # Read the raw pipe, since anything buffered by Python would
        # not be seen by select.
        fd = proc.stdout.fileno()
        output = b""
        deadline = time.time() + 30
        while b"(y/n)" not in output and time.time() < deadline:
            ready, _w, _x = select.select([fd], [], [], 1)
            if ready:
                output += os.read(fd, 4096)
        assert b"Upload a.txt" in output, output
        assert b"(y/n)" in output, output
    finally:
        proc.stdin.write(b"y\n")
        proc.stdin.close()
        assert proc.wait(timeout=30) == 0
        proc.stdout.close()

    assert remote_tree(site)["a.txt"] == md5(b"A\n")

def test_interrupt_records_progress(site):
    # An interrupted update stops, records what it did, and releases
    # the lock; the next update finishes the job.  --prompting, with
    # one "y" on standard input, stops the update after the first file
    # has been uploaded.
    setup_site(site, {})
    write_tree(site["local"], {"a.txt": "A\n", "b.txt": "B\n",
                               "c.txt": "C\n"})

    cmd = ["./sitecopy", "--rcfile", str(site["rcfile"]),
           "--storepath", str(site["store"]), "--prompting",
           "--update", "testsite"]
    first = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, text=True)
    first.stdin.write("y\n")
    first.stdin.flush()

    # Wait for the first upload, then interrupt.
    for _ in range(300):
        uploaded = set(remote_tree(site))
        if uploaded:
            break
        time.sleep(0.1)
    assert uploaded, "no file was uploaded"
    first.send_signal(signal.SIGINT)
    out, _err = first.communicate(timeout=30)

    assert first.returncode != 0, out
    assert "Interrupted while updating" in out, out
    # Only the first file was uploaded, and the lock is gone.
    assert set(remote_tree(site)) == uploaded, out
    assert not (site["store"] / "testsite.lock").exists()
    # The upload which did happen was recorded, so the next update
    # only has the rest to do.
    assert stored_items(site) == sorted(uploaded)

    res = run_sitecopy(site, ["--update", "testsite"])
    assert res.returncode == 0, res.stdout + res.stderr
    assert set(remote_tree(site)) == {"a.txt", "b.txt", "c.txt"}
    assert_no_update(site)

# -- exclude and ignore patterns -----------------------------------------

@pytest.mark.site_lines("exclude stats/*")
def test_exclude_directory_contents(site):
    # A pattern embedding a slash matches the site-relative filename,
    # so the contents of the directory are excluded, but not the
    # directory itself (Debian bug #167277).
    setup_site(site, {"index.html": "Root\n", "stats/": None,
                      "stats/ctry.html": "Ctry\n",
                      "stats/deep/": None, "stats/deep/usage.html": "Usage\n"},
               expected={"index.html", "stats/"})

@pytest.mark.site_lines("exclude stats/index.html")
def test_exclude_file_within_directory(site):
    # A file can be excluded without excluding the file of the same
    # base name in the site root (Debian bug #167277).
    setup_site(site, {"index.html": "Root\n", "stats/": None,
                      "stats/index.html": "Stats\n",
                      "stats/ctry.html": "Ctry\n"},
               expected={"index.html", "stats/", "stats/ctry.html"})

@pytest.mark.site_lines("ignore sub/local.ini")
def test_ignore_within_directory(site):
    # An ignore pattern embedding a slash matches the site-relative
    # filename too.
    setup_site(site, {"local.ini": "A\n", "sub/": None,
                      "sub/local.ini": "B\n"})
    (site["local"] / "local.ini").write_text("A, changed\n")
    (site["local"] / "sub" / "local.ini").write_text("B, changed\n")
    res = run_sitecopy(site, ["--update", "testsite"])
    assert res.returncode == 0, res.stdout + res.stderr
    remote = remote_tree(site)
    assert remote["local.ini"] == md5(b"A, changed\n"), remote
    assert remote["sub/local.ini"] == md5(b"B\n"), remote

# -- --verify -------------------------------------------------------------

def test_verify_subdirectories(site):
    setup_site(site, {"top.txt": "Top\n", "dir/": None,
                      "dir/sub.txt": "Sub\n", "dir/deeper/": None,
                      "dir/deeper/d.txt": "Deeper\n"})
    res = run_sitecopy(site, ["--verify", "testsite"])
    assert res.returncode == 0, res.stdout + res.stderr
    assert "Verify completed successfully" in res.stdout, res.stdout
    assert "on server" not in res.stdout, res.stdout

    # A file changed on the server in a subdirectory is found.
    change_remote(site, "dir/deeper/d.txt", "Changed, longer\n", 0)
    res = run_sitecopy(site, ["--verify", "testsite"])
    assert "Changed on server: dir/deeper/d.txt" in res.stdout, res.stdout

@pytest.mark.site_lines("state checksum")
def test_verify_checksum(site):
    setup_site(site, {"a.txt": "A\n", "b.txt": "B\n"})
    res = run_sitecopy(site, ["--verify", "testsite"])
    assert res.returncode == 0, res.stdout + res.stderr
    assert "Changed on server" not in res.stdout, res.stdout

    # A change on the server which keeps the file's size is found.
    change_remote(site, "b.txt", "C\n", 0)
    res = run_sitecopy(site, ["--verify", "testsite"])
    assert "Changed on server: b.txt" in res.stdout, res.stdout
    assert "Changed on server: a.txt" not in res.stdout, res.stdout

def test_verify_changed_status(site):
    setup_site(site, {"a.txt": "A\n", "b.txt": "B\n"})
    change_remote(site, "b.txt", "Changed, longer\n", 0)
    res = run_sitecopy(site, ["--verify", "testsite"])
    assert "Changed on server: b.txt" in res.stdout, res.stdout
    assert res.returncode != 0, res.stdout + res.stderr

def test_verify_added_status(site):
    setup_site(site, {"a.txt": "A\n"})
    create_remote(site, "new.txt", "New\n")
    res = run_sitecopy(site, ["--verify", "testsite"])
    assert "Added on server: new.txt" in res.stdout, res.stdout
    assert res.returncode != 0, res.stdout + res.stderr

def test_verify_excluded(site):
    # A file uploaded before it came to be excluded is still on the
    # server until the next update, and isn't missing.
    setup_site(site, {"a.txt": "A\n", "b.log": "Log\n"})
    add_site_lines(site, "exclude *.log")
    res = run_sitecopy(site, ["--verify", "testsite"])
    assert res.returncode == 0, res.stdout + res.stderr
    assert "missing from server" not in res.stdout, res.stdout

def test_verify_file_became_directory(site):
    setup_site(site, {"a.txt": "A\n", "x": "X\n"})
    server_exec(site, "cd '%s' && rm x && mkdir x && chown --reference=. x"
                % site["root"])
    res = run_sitecopy(site, ["--verify", "testsite"])
    assert "Changed on server: x" in res.stdout, res.stdout
    assert res.returncode != 0, res.stdout + res.stderr

# -- --fetch --------------------------------------------------------------

@pytest.mark.site_lines("state checksum")
def test_fetch_checksum_download_failure(site):
    setup_site(site, {"a.txt": "A\n", "unreadable.txt": "U\n"})
    # The server can't read the file, so can't send it.
    server_exec(site, "chmod 000 '%s/unreadable.txt'" % site["root"])
    try:
        (site["store"] / "testsite").unlink()
        res = run_sitecopy(site, ["--fetch", "testsite"])
        assert res.returncode != 0, res.stdout + res.stderr
        assert "Failed to fetch" in res.stdout, res.stdout
        # The stored state isn't written.
        assert not (site["store"] / "testsite").exists()
    finally:
        server_exec(site, "chmod 644 '%s/unreadable.txt'" % site["root"])

def test_fetch_many_directories(site):
    # A directory on the server holding more subdirectories, each with
    # a file, than the fetch's directory stack initially holds (it
    # used to be a fixed size, silently skipping the rest).
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

@pytest.mark.site_lines("tempupload")
def test_tempupload_name_clash(site):
    setup_site(site, {".in.page.txt": "A real file\n"})
    write_tree(site["local"], {"page.txt": "Page\n"})
    res = run_sitecopy(site, ["--update", "testsite"])
    assert res.returncode == 0, res.stdout + res.stderr
    remote = remote_tree(site)
    assert remote.get(".in.page.txt") == md5(b"A real file\n"), remote
    assert remote.get("page.txt") == md5(b"Page\n"), remote
