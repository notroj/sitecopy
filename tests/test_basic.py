import subprocess
import os

import pytest

from common import *
from conftest import make_sitecopy_env, sitecopy_features

def test_options(sitecopy_env):
    res = run_sitecopy(sitecopy_env, ["--version"])
    assert res.returncode == 0
    assert "Unix platform" in res.stdout

    res = run_sitecopy(sitecopy_env, ["--help"])
    assert res.returncode == 0
    assert "Usage: sitecopy" in res.stdout

def test_initialization(sitecopy_env):
    # Initialize the site storage
    local = sitecopy_env["local"]
    res = run_sitecopy(sitecopy_env, ["--initialize", "testsite"])
    assert res.returncode == 0

    res = run_sitecopy(sitecopy_env, ["--catchup", "testsite"])
    assert res.returncode == 0

    assert_no_update(sitecopy_env)

    alpha_dir = local / "alpha"
    assert alpha_dir.mkdir() == None

    res = run_sitecopy(sitecopy_env, ["--list", "testsite"])
    assert res.returncode == 1
    assert "The remote site needs updating (1 item to update)" in res.stdout

    res = run_sitecopy(sitecopy_env, ["--dry-run", "--update", "testsite"])
    assert res.returncode == 0
    assert "Update completed successfully" in res.stdout

    res = run_sitecopy(sitecopy_env, ["--catchup", "testsite"])
    assert res.returncode == 0

    assert_no_update(sitecopy_env)

def _write_rcfile_url(senv, url):
    rc = senv["rcfile"]
    rc.write_text(f"""
site {url}
    local {senv["local"]}
""")

def test_site_urls(sitecopy_env):
    # Initialize the site storage
    local = sitecopy_env["local"]
    res = run_sitecopy(sitecopy_env, ["--initialize", "testsite"])
    assert res.returncode == 0

    _write_rcfile_url(sitecopy_env, "http://localhost/dav/")
    res = run_sitecopy(sitecopy_env, ["--view", "localhost"])
    assert res.returncode == 0
    assert "Protocol: WebDAV" in res.stdout
    assert "Remote directory: /dav/" in res.stdout
    assert "Port: 80" in res.stdout
    assert "Server: localhost" in res.stdout

    _write_rcfile_url(sitecopy_env, "https://localhost/dav/")
    res = run_sitecopy(sitecopy_env, ["--view", "localhost"])
    assert res.returncode == 0
    assert "Protocol: WebDAV" in res.stdout
    assert "Remote directory: /dav/" in res.stdout
    assert "Port: 443" in res.stdout
    assert "Server: localhost" in res.stdout

    _write_rcfile_url(sitecopy_env, "http://example.com:8081/")
    res = run_sitecopy(sitecopy_env, ["--view", "example.com"])
    assert res.returncode == 0
    assert "Protocol: WebDAV" in res.stdout
    assert "Remote directory: /" in res.stdout
    assert "Port: 8081" in res.stdout
    assert "Server: example.com" in res.stdout

    _write_rcfile_url(sitecopy_env, "ftp://example.com/")
    res = run_sitecopy(sitecopy_env, ["--view", "example.com"])
    assert res.returncode == 0
    assert "Protocol: FTP" in res.stdout
    assert "Remote directory: /" in res.stdout
    assert "Port: 21" in res.stdout
    assert "Server: example.com" in res.stdout

    _write_rcfile_url(sitecopy_env, "ftps://example.com/site/")
    res = run_sitecopy(sitecopy_env, ["--view", "example.com"])
    if "FTPS" in sitecopy_features():
        assert res.returncode == 0, res.stdout + res.stderr
        assert "Protocol: FTP" in res.stdout
        assert "FTP over TLS will be used" in res.stdout
        assert "Remote directory: /site/" in res.stdout
        assert "Server: example.com" in res.stdout
    else:
        assert "FTP over TLS requires" in res.stdout

    _write_rcfile_url(sitecopy_env, "sftp://example.com/~/foo/bar")
    res = run_sitecopy(sitecopy_env, ["--view", "example.com"])
    assert res.returncode == 0
    assert "Protocol: sftp" in res.stdout
    assert "Remote directory: foo/bar\n" in res.stdout
    assert "Port: (default)" in res.stdout
    assert "Server: example.com" in res.stdout

    _write_rcfile_url(sitecopy_env, "ftp://example.com/~/foobar")
    res = run_sitecopy(sitecopy_env, ["--view", "example.com"])
    assert res.returncode == 0
    assert "Protocol: FTP" in res.stdout
    assert "Remote directory: foobar" in res.stdout
    assert "Port: 21" in res.stdout
    assert "Server: example.com" in res.stdout

REJECTED_CONFIGS = [
    ("dav", ["safe", "nooverwrite"],
     "Safe mode cannot be used in conjunction with nooverwrite"),
    ("ftp", ["safe", "tempupload"],
     "Safe mode cannot be used in conjunction with tempupload"),
    ("dav", ["symlinks maintain"], "WebDAV cannot maintain symbolic links"),
    ("ftp", ["symlinks maintain"], "FTP cannot maintain symbolic links"),
    ("dav", ["permissions all"], "File permissions are not supported in WebDAV"),
    ("dav", ["checkmoved renames"], None),
    # WebDAV has no login directory for a directory to be relative to.
    ("dav", ["remote ~/site/"],
     "Cannot use a relative remote directory in WebDAV"),
]

@pytest.mark.parametrize("protocol, lines, message", REJECTED_CONFIGS,
                         ids=["-".join([p] + l).replace(" ", "_")
                              for p, l, _ in REJECTED_CONFIGS])
def test_rejected_config(tmp_path, protocol, lines, message):
    # Invalid combinations of options are rejected before connecting
    # to the server.
    senv = make_sitecopy_env(tmp_path, "  remote /site/\n  protocol %s\n%s"
                             % (protocol,
                                "".join("  %s\n" % l for l in lines)))
    res = run_sitecopy(senv, ["--update", "testsite"])
    output = res.stdout + res.stderr
    assert res.returncode == 255, output
    if message:
        assert message in output
    assert "Skipping site `testsite'" in output

def test_long_rcfile_lines(sitecopy_env):
    # rcfile lines were read into a 128-byte buffer, so a longer line
    # was split, and the remainder parsed as a separate line.
    remote = "/" + "d" * 300 + "/"
    exclude = "x" * 300
    with open(sitecopy_env["rcfile"], "a") as fp:
        fp.write(f"  remote {remote}\n  exclude \"{exclude}\"\n")
    res = run_sitecopy(sitecopy_env, ["--view", "testsite"])
    assert res.returncode == 0, res.stdout + res.stderr
    assert "Remote directory: " + remote in res.stdout

def test_relative_remote(tmp_path):
    # A remote directory relative to the login directory, for FTP,
    # starts with "~/".
    senv = make_sitecopy_env(tmp_path, "  protocol ftp\n  remote ~/site\n")
    res = run_sitecopy(senv, ["--view", "testsite"])
    assert res.returncode == 0, res.stdout + res.stderr
    assert "Remote directory: ~/site/\n" in res.stdout

    senv["rcfile"].write_text(senv["rcfile"].read_text()
                              .replace("remote ~/site", "remote ~site"))
    res = run_sitecopy(senv, ["--view", "testsite"])
    assert res.returncode != 0, res.stdout + res.stderr
    assert "rcfile corrupt" in res.stdout + res.stderr

# -- Storage file locking ---------------------------------------------------

def test_lock_held_by_another_process(sitecopy_env):
    # A site whose lock file exists is left alone: another sitecopy
    # could be part way through updating it.
    lock = sitecopy_env["store"] / "testsite.lock"
    lock.write_text("pid 4242\n")
    for args in (["--initialize", "testsite"], ["--catchup", "testsite"]):
        res = run_sitecopy(sitecopy_env, args)
        assert res.returncode != 0, res.stdout + res.stderr
        assert "Locked by process 4242" in res.stdout, res.stdout
        assert "Skipping site `testsite'" in res.stdout, res.stdout
    # The storage file was not written, and the lock file is left for
    # the process which holds it.
    assert not (sitecopy_env["store"] / "testsite").exists()
    assert lock.read_text() == "pid 4242\n"

def test_lock_without_pid(sitecopy_env):
    # A lock file with no pid key still locks the site; keys which
    # sitecopy does not recognize are ignored.
    (sitecopy_env["store"] / "testsite.lock").write_text(
        "token opaquelocktoken:ac7f1a\n")
    res = run_sitecopy(sitecopy_env, ["--initialize", "testsite"])
    assert res.returncode != 0, res.stdout + res.stderr
    assert "testsite.lock" in res.stdout, res.stdout

def test_lock_released(sitecopy_env):
    # The lock is released once the stored state has been written, so
    # the next run can take it.
    store = sitecopy_env["store"]
    res = run_sitecopy(sitecopy_env, ["--initialize", "testsite"])
    assert res.returncode == 0, res.stdout + res.stderr
    assert not (store / "testsite.lock").exists()
    assert (store / "testsite").exists()

    res = run_sitecopy(sitecopy_env, ["--catchup", "testsite"])
    assert res.returncode == 0, res.stdout + res.stderr
    assert not (store / "testsite.lock").exists()

def test_lock_released_for_skipped_site(sitecopy_env):
    # A site whose action fails once the lock has been taken, here
    # because there is no server, does not leave the lock behind.
    res = run_sitecopy(sitecopy_env, ["--fetch", "testsite"])
    assert res.returncode != 0, res.stdout + res.stderr
    assert not (sitecopy_env["store"] / "testsite.lock").exists()

def test_no_lock_for_read_only_actions(sitecopy_env):
    # --list does not write the stored state, so is not locked out.
    res = run_sitecopy(sitecopy_env, ["--initialize", "testsite"])
    assert res.returncode == 0, res.stdout + res.stderr
    (sitecopy_env["store"] / "testsite.lock").write_text("pid 4242\n")
    res = run_sitecopy(sitecopy_env, ["--list", "testsite"])
    assert res.returncode == 0, res.stdout + res.stderr
