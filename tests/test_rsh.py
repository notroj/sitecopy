"""Tests for the rsh driver, using a wrapper script in place of rsh
which prints a canned directory listing, so that no remote host is
needed."""

import os

import pytest

from common import run_sitecopy

# Prints the listing of the site root, whatever it is asked to run.
LISTING_WRAPPER = """\
#!/bin/sh
cat <<'LISTING'
total 8
-rw-r--r--   1 joe  users     15 Aug 28  2003 index.html
-rw-r--r--   1 joe  users      4 Aug 28  2003 notes.txt
LISTING
"""


@pytest.fixture
def rsh_site(tmp_path):
    local = tmp_path / "local"
    store = tmp_path / "storage"
    local.mkdir()
    store.mkdir()
    os.chmod(store, 0o700)

    wrapper = tmp_path / "fake-rsh.sh"
    wrapper.write_text(LISTING_WRAPPER)
    wrapper.chmod(0o755)

    rcfile = tmp_path / ".sitecopyrc"
    rcfile.write_text(f"""site testsite
  server rsh.example
  remote /remote/
  local {local}
  protocol rsh
  rsh {wrapper}
  rcp {wrapper}
""")
    rcfile.chmod(0o600)

    return {"rcfile": rcfile, "local": local, "store": store}


def test_fetch_without_modtimes(rsh_site):
    # The rsh driver cannot get the modification time of a file, so a
    # fetch goes without them rather than failing, as it always has.
    res = run_sitecopy(rsh_site, ["--fetch", "testsite"])
    assert res.returncode == 0, res.stdout + res.stderr
    assert "File: index.html - size 15" in res.stdout, res.stdout
    assert "File: notes.txt - size 4" in res.stdout, res.stdout
