"""Tests of FTP over TLS run against each server requiring TLS,
imported into test_vsftpd_ssl.py and test_pureftpd_ssl.py, which
select the server with a protocol marker."""

from common import *
from conftest import SERVERS

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

def test_ftps_url(site):
    # A site named by an ftps:// URL uses FTP over TLS, as with
    # "ftp secure".
    server = SERVERS[site["config"].protocol]
    rcfile = site["rcfile"]
    rcfile.write_text("""
site ftps://localhost:%d%s/
  local %s
  username sitecopy
  password sitecopy
""" % (server.port, server.root, site["local"]))
    certfile = site["store"] / "testsite.crt"
    certfile.rename(site["store"] / "localhost.crt")

    res = run_sitecopy(site, ["--initialize", "localhost"])
    assert res.returncode == 0, res.stdout + res.stderr
    write_tree(site["local"], {"a.txt": "A\n", "dir/": None,
                               "dir/b.txt": "B\n"})
    res = run_sitecopy(site, ["--update", "localhost"])
    assert res.returncode == 0, res.stdout + res.stderr
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
