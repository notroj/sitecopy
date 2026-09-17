"""Regression tests for the "false success" bug family (Debian
#515217, #564462, #742661).

For a `protocol sftp' site, sitecopy drives an external sftp client
(the `rcp' rcfile keyword) via a pipe.  When the sftp process cannot
reach the network it prints the ssh diagnostics on stderr, exits, and
the pipe reaches EOF - which the sftp driver used to treat as
success, so the first file of an update was always marked as done
even though nothing was transferred, and a single-file update ended
with "Update completed successfully" and exit status 0.

These tests simulate the unreachable/timed-out ssh with a wrapper
script (no real network access needed) installed as the `rsh' and
`rcp' commands of an sftp site.
"""

import os

import pytest

from common import run_sitecopy

# Simulates "ssh: connect to host ... Network is unreachable" (Debian
# #515217, #564462): the sftp client prints the diagnostics on stderr
# and exits without ever speaking the sftp protocol on stdout.
UNREACHABLE_WRAPPER = """\
#!/bin/sh
echo "ssh: connect to host $1 port 22: Network is unreachable" >&2
echo "Couldn't read packet: Connection reset by peer" >&2
exit 1
"""

# Simulates "ssh: connect to host ... Connection timed out" (Debian
# #742661).
TIMEOUT_WRAPPER = """\
#!/bin/sh
sleep 1
echo "ssh: connect to host $1 port 22: Connection timed out" >&2
echo "Couldn't read packet: Connection reset by peer" >&2
exit 1
"""


@pytest.fixture
def make_sftp_env(tmp_path):
    """Factory creating an initialised sftp site whose rsh/rcp
    commands are the given wrapper script."""
    def _make(wrapper_content):
        local = tmp_path / "local"
        store = tmp_path / "storage"
        local.mkdir()
        store.mkdir()
        os.chmod(store, 0o700)

        wrapper = tmp_path / "fake-sftp.sh"
        wrapper.write_text(wrapper_content)
        wrapper.chmod(0o755)

        rcfile = tmp_path / ".sitecopyrc"
        rcfile.write_text(f"""site testsite
  server bug.example
  username testuser
  remote /remote/
  local {local}
  protocol sftp
  rsh {wrapper}
  rcp {wrapper}
""")
        rcfile.chmod(0o600)

        env = {"rcfile": rcfile, "local": local, "store": store}
        res = run_sitecopy(env, ["--initialize", "testsite"])
        assert res.returncode == 0, res.stdout + res.stderr
        return env

    return _make


def assert_update_fails(env):
    """Run --update and assert the failure is reported: non-zero
    exit, error summary, and no per-file "done" markers."""
    res = run_sitecopy(env, ["--update", "testsite"])
    assert res.returncode != 0, (
        "update must not exit 0 when the transfer fails:\n"
        + res.stdout + res.stderr)
    assert "Update completed successfully" not in res.stdout
    assert "Errors occurred while updating" in res.stdout
    # No file may be marked as uploaded.
    assert "] done." not in res.stdout
    return res


def test_unreachable_first_file_not_marked_done(make_sftp_env):
    # Debian #564462: with several files to upload, the FIRST one
    # was always reported "done" although ssh could not connect.
    env = make_sftp_env(UNREACHABLE_WRAPPER)
    for name in ("a", "b", "c"):
        (env["local"] / name).write_text("")

    res = assert_update_fails(env)
    assert "Uploading a" in res.stdout


def test_unreachable_rerun_still_fails(make_sftp_env):
    # Debian #515217/#564462: repeated updates each swallowed the
    # failure for the next remaining file, until a single-file run
    # finally printed "Update completed successfully" and exited 0.
    env = make_sftp_env(UNREACHABLE_WRAPPER)
    (env["local"] / "a").write_text("")

    for _ in range(3):
        assert_update_fails(env)

    # Nothing was ever uploaded, so the site must not be reported
    # up-to-date.
    res = run_sitecopy(env, ["--list", "testsite"])
    assert "does not need updating" not in res.stdout


def test_timeout_single_file_not_marked_done(make_sftp_env):
    # Debian #742661: on "Connection timed out" the first (and only)
    # file was marked as done.
    env = make_sftp_env(TIMEOUT_WRAPPER)
    (env["local"] / "only.txt").write_text("contents\n")

    res = assert_update_fails(env)
    assert "Uploading only.txt" in res.stdout
