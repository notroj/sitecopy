"""FTP over TLS tests against vsftpd, configured to require TLS for
logins and data connections, and session reuse on data connections.
The tests in server_tests.py are run over TLS too."""

import pytest

from common import *
from conftest import SERVERS, make_sitecopy_env, sitecopy_features
from server_tests import *

pytestmark = pytest.mark.protocol("ftps")

def test_untrusted_certificate(site):
    # Without the saved certificate, the server's self-signed
    # certificate is not trusted, and the user is asked whether to
    # accept it.
    certfile = site["store"] / "testsite.crt"
    certfile.unlink()
    res = run_sitecopy(site, ["--initialize", "testsite"])
    assert res.returncode == 0, res.stdout + res.stderr
    write_tree(site["local"], {"a.txt": "A\n"})

    res = run_sitecopy(site, ["--update", "testsite"], input="n\n")
    assert res.returncode != 0, res.stdout + res.stderr
    assert "Server certificate is not trusted" in res.stdout
    assert "Server certificate verification failed" in res.stdout
    assert not certfile.exists()
    assert remote_tree(site) == {}

    # Once accepted, the certificate is saved, and trusted from then
    # on without asking.
    res = run_sitecopy(site, ["--update", "testsite"], input="y\n")
    assert res.returncode == 0, res.stdout + res.stderr
    assert certfile.exists()
    assert_trees_match(site)

    (site["local"] / "a.txt").write_text("A, changed\n")
    res = run_sitecopy(site, ["--update", "testsite"])
    assert res.returncode == 0, res.stdout + res.stderr
    assert "not trusted" not in res.stdout
    assert_trees_match(site)

def test_login_requires_tls(site):
    # The server refuses logins without TLS, so the other tests only
    # pass if TLS is used.
    rcfile = site["rcfile"]
    rcfile.write_text(rcfile.read_text().replace("  ftp secure\n", ""))
    res = run_sitecopy(site, ["--initialize", "testsite"])
    assert res.returncode == 0, res.stdout + res.stderr
    write_tree(site["local"], {"a.txt": "A\n"})
    res = run_sitecopy(site, ["--update", "testsite"])
    assert res.returncode != 0, res.stdout + res.stderr
    assert "Could not authorise user" in res.stdout
    assert server_log_lines(site, "Non-anonymous sessions must use "
                            "encryption")

def test_server_without_tls(tmp_path, containers):
    # A server which doesn't support TLS refuses AUTH TLS, and no
    # credentials are sent.
    if "FTPS" not in sitecopy_features():
        pytest.skip("sitecopy built without FTPS support")
    server = SERVERS["ftp"]
    cid = containers("ftp")
    senv = make_sitecopy_env(tmp_path, server.rcfile + "  ftp secure\n")
    res = run_sitecopy(senv, ["--initialize", "testsite"])
    assert res.returncode == 0, res.stdout + res.stderr
    write_tree(senv["local"], {"a.txt": "A\n"})

    res = run_sitecopy(senv, ["--update", "testsite"])
    assert res.returncode != 0, res.stdout + res.stderr
    assert "Server does not support FTP over TLS" in res.stdout

    run = subprocess.run(["podman", "exec", cid, "grep", "-F",
                          "AUTH TLS", "/var/log/vsftpd.log"],
                         capture_output=True, text=True)
    assert run.stdout, "AUTH TLS not sent"
    # The connection which sent AUTH TLS sent no USER command.
    pid = run.stdout.splitlines()[-1].split("[pid ", 1)[1].split("]")[0]
    run = subprocess.run(["podman", "exec", cid, "grep", "-F",
                          "[pid %s]" % pid, "/var/log/vsftpd.log"],
                         capture_output=True, text=True)
    commands = [line for line in run.stdout.splitlines()
                if "FTP command:" in line]
    assert not any('"USER ' in line or '"PASS ' in line
                   for line in commands), commands
