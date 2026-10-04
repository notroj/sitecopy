"""Regression tests for specific bugs.  Tests using the site fixture
are each run once against vsftpd in its default configuration (plus
any rcfile lines the test needs), rather than across every combination
of rcfile options; tests using the sitecopy_env fixture need no server.

Tests for bugs which are not fixed yet are strict xfails: fixing the
bug turns the test into a pass, which then must be recorded by
removing the xfail marker."""

import os
import re
import resource
import select
import signal
import socket
import subprocess
import threading
import time

import pytest

from common import *
from conftest import make_sitecopy_env, sitecopy_features
from test_ftp import ftp_site

pytestmark = [pytest.mark.protocol("ftp"), pytest.mark.default_config]

def read_until(proc, text, count=1, timeout=30):
    """Read the raw standard output of 'proc' until 'text' has been
    seen 'count' times, and return what was read.  The raw pipe is
    read, since anything buffered by Python would not be seen by
    select."""
    fd = proc.stdout.fileno()
    output = b""
    deadline = time.time() + timeout
    while output.count(text) < count:
        assert time.time() < deadline, output
        ready, _w, _x = select.select([fd], [], [], 1)
        if ready:
            data = os.read(fd, 4096)
            assert data, output
            output += data
    return output

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
                             stdout=subprocess.PIPE)
    first.stdin.write(b"y\n")
    first.stdin.flush()

    # Wait until sitecopy asks about the second file, so that the
    # first upload has finished, then interrupt.  An interrupt any
    # earlier could cut off the reply to the first upload, which would
    # then rightly not be recorded.
    prompts = read_until(first, b"(y/n)", count=2)
    uploaded = set(remote_tree(site))
    assert uploaded, "no file was uploaded"
    first.send_signal(signal.SIGINT)
    out, _err = first.communicate(timeout=30)
    out = (prompts + out).decode("utf-8", "replace")

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

# -- Interrupting a blocked operation -----------------------------------

def _interruptible():
    """Whether sitecopy can interrupt a blocking network read, which
    needs neon 0.38 or later."""
    try:
        return "interruptible" in sitecopy_features()
    except OSError:
        return False

needs_interruptible_neon = pytest.mark.skipif(
    not _interruptible(),
    reason="sitecopy built without interruptible network reads")

def interrupt_when(senv, args, blocked):
    """Run sitecopy with 'args', send it SIGINT once blocked() is
    true, and return its exit status, its output, and the number of
    seconds it took to exit after the signal."""
    cmd = ["./sitecopy", "--rcfile", str(senv["rcfile"]),
           "--storepath", str(senv["store"])] + args
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True)
    try:
        deadline = time.monotonic() + 30
        while not blocked():
            assert proc.poll() is None, proc.communicate()[0]
            assert time.monotonic() < deadline, "sitecopy did not block"
            time.sleep(0.05)
        # Give it time to settle into the read.
        time.sleep(0.5)
        start = time.monotonic()
        proc.send_signal(signal.SIGINT)
        out, _err = proc.communicate(timeout=30)
        return proc.returncode, out, time.monotonic() - start
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.communicate()

class StallingDAVServer:
    """Minimal WebDAV server on 127.0.0.1, which answers OPTIONS as a
    class 1 server and any other request with 201, except that a
    request using a method in 'hanging' is read but never answered."""

    def __init__(self, hanging):
        self.hanging = set(hanging)
        self.methods = []
        self.listener = socket.create_server(("127.0.0.1", 0))
        self.port = self.listener.getsockname()[1]
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self):
        while True:
            try:
                conn, _ = self.listener.accept()
            except OSError:
                return
            threading.Thread(target=self._connection, args=(conn,),
                             daemon=True).start()

    def _connection(self, conn):
        with conn, conn.makefile("rb") as f:
            while True:
                request = f.readline()
                if not request:
                    return
                length = 0
                while True:
                    header = f.readline()
                    if header in (b"\r\n", b"\n", b""):
                        break
                    name, _, value = header.decode("latin-1").partition(":")
                    if name.strip().lower() == "content-length":
                        length = int(value)
                f.read(length)
                method = request.split()[0].decode("ascii")
                self.methods.append(method)
                if method in self.hanging:
                    # Never answer; wait for the client to give up.
                    while f.read(4096):
                        pass
                    return
                if method == "OPTIONS":
                    reply = (b"HTTP/1.1 200 OK\r\nDAV: 1\r\n"
                             b"Content-Length: 0\r\n\r\n")
                else:
                    reply = b"HTTP/1.1 201 Created\r\nContent-Length: 0\r\n\r\n"
                conn.sendall(reply)

    def stop(self):
        self.listener.close()
        self.thread.join(timeout=5)

@needs_interruptible_neon
def test_interrupt_blocked_ftp_reply(ftp_site):
    # Interrupting sitecopy while it waits for an FTP reply which
    # never comes stops it at once, rather than after the read
    # timeout, and the upload which was cut off is not recorded.
    server = ftp_site["server"]
    res = run_sitecopy(ftp_site, ["--initialize", "testsite"])
    assert res.returncode == 0, res.stdout + res.stderr
    (ftp_site["local"] / "a.txt").write_text("A\n")
    server.hanging.add("STOR")

    status, out, elapsed = interrupt_when(
        ftp_site, ["--update", "testsite"],
        lambda: any(c.startswith("STOR") for c in server.commands))
    assert status != 0, out
    assert elapsed < 10, out
    assert "Interrupted while updating" in out, out
    assert stored_items(ftp_site) == []
    assert not (ftp_site["store"] / "testsite.lock").exists()

@needs_interruptible_neon
def test_interrupt_blocked_dav_request(tmp_path):
    # Likewise for a WebDAV request which is never answered.
    server = StallingDAVServer({"PUT"})
    try:
        senv = make_sitecopy_env(tmp_path, f"""\
  port {server.port}
  remote /dav/
  protocol dav
""")
        res = run_sitecopy(senv, ["--initialize", "testsite"])
        assert res.returncode == 0, res.stdout + res.stderr
        (senv["local"] / "a.txt").write_text("A\n")

        status, out, elapsed = interrupt_when(
            senv, ["--update", "testsite"], lambda: "PUT" in server.methods)
        assert status != 0, out
        assert elapsed < 10, out
        assert "Interrupted while updating" in out, out
        assert stored_items(senv) == []
        assert not (senv["store"] / "testsite.lock").exists()
    finally:
        server.stop()

# -- Stored state ----------------------------------------------------------

def _limit_file_size(limit):
    """Return a function for run_sitecopy's preexec_fn which limits the
    size of files the child can write to 'limit' bytes; writes beyond
    that fail with EFBIG, rather than raising SIGXFSZ."""
    def preexec():
        signal.signal(signal.SIGXFSZ, signal.SIG_IGN)
        resource.setrlimit(resource.RLIMIT_FSIZE, (limit, limit))
    return preexec

# The stored state written by --initialize, which is smaller than the
# stdio buffer, so a failure to write it only shows up at fclose();
# and by --catchup of many files, which is larger, so it fails part
# way through.
@pytest.mark.parametrize("nfiles", [0, 200])
def test_storage_file_short_write(sitecopy_env, nfiles):
    # If the stored state cannot be written in full, the run fails,
    # and the previous stored state is left as it was rather than
    # replaced by a truncated one.
    store = sitecopy_env["store"]
    res = run_sitecopy(sitecopy_env, ["--initialize", "testsite"])
    assert res.returncode == 0, res.stdout + res.stderr
    before = (store / "testsite").read_bytes()
    limit = len(before) // 2

    for n in range(nfiles):
        (sitecopy_env["local"] / f"file-{n:04d}.txt").write_text("x\n")
    args = ["--catchup" if nfiles else "--initialize", "testsite"]
    res = run_sitecopy(sitecopy_env, args,
                       preexec_fn=_limit_file_size(limit))
    assert res.returncode != 0, res.stdout + res.stderr
    assert "Could not write storage file `" in res.stdout, res.stdout
    assert "testsite.new'" in res.stdout, res.stdout
    assert "have not been recorded" in res.stdout, res.stdout
    assert (store / "testsite").read_bytes() == before
    assert not (store / "testsite.new").exists()
    assert not (store / "testsite.lock").exists()

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


# -- Update progress ------------------------------------------------------

PERCENT = re.compile(r"\((\d+)% finished\)")

@pytest.mark.site_lines("checkmoved", "nooverwrite")
def test_update_progress_never_exceeds_100(site):
    # Debian bug #932161: a moved file and the pre-upload delete of
    # nooverwrite mode advance the update progress without being
    # counted in upload_total, which covers only changed and new
    # files, so the reported percentage exceeded 100%.
    res = run_sitecopy(site, ["--initialize", "testsite"])
    assert res.returncode == 0, res.stdout + res.stderr

    # Three equal-sized new files: 33%, 67%, 100%.
    for name, fill in (("a.bin", b"a"), ("b.bin", b"b"), ("c.bin", b"c")):
        (site["local"] / name).write_bytes(fill * 30000)
    res = run_sitecopy(site, ["--update", "-o", "testsite"])
    assert res.returncode == 0, res.stdout + res.stderr
    assert [int(p) for p in PERCENT.findall(res.stdout)] == [33, 67, 100], \
        res.stdout

    # A cross-directory move of a.bin and a changed b.bin: the move and
    # the nooverwrite pre-upload delete must not push the percentage
    # above 100%.
    (site["local"] / "sub").mkdir()
    (site["local"] / "a.bin").rename(site["local"] / "sub" / "a.bin")
    (site["local"] / "b.bin").write_bytes(b"B" * 31000)
    res = run_sitecopy(site, ["--update", "-o", "testsite"])
    assert res.returncode == 0, res.stdout + res.stderr
    assert "Moving a.bin->sub/a.bin: done." in res.stdout, res.stdout
    assert "Deleting b.bin: done." in res.stdout, res.stdout
    assert "Uploading b.bin:" in res.stdout, res.stdout
    assert [int(p) for p in PERCENT.findall(res.stdout)] == [100], res.stdout

    assert_no_update(site)
