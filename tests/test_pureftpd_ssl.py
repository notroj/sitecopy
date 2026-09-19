"""FTP over TLS tests against pure-ftpd, configured to require TLS
for the control and data connections."""

import pytest

from conftest import SERVERS, make_sitecopy_env, sitecopy_features
from server_tests import *
from ftps_tests import *

pytestmark = pytest.mark.protocol("pureftpds")

def test_server_without_tls(tmp_path, containers):
    # With TLS disabled, pure-ftpd refuses AUTH TLS, and sitecopy
    # fails rather than logging in without TLS.
    if "FTPS" not in sitecopy_features():
        pytest.skip("sitecopy built without FTPS support")
    server = SERVERS["pureftpd"]
    containers("pureftpd")
    senv = make_sitecopy_env(tmp_path, server.rcfile + "  ftp secure\n")
    res = run_sitecopy(senv, ["--initialize", "testsite"])
    assert res.returncode == 0, res.stdout + res.stderr
    write_tree(senv["local"], {"a.txt": "A\n"})

    res = run_sitecopy(senv, ["--update", "testsite"])
    assert res.returncode != 0, res.stdout + res.stderr
    assert "Server does not support FTP over TLS" in res.stdout
