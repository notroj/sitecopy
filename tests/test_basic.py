import subprocess
import os

def run_sitecopy(senv, args):
    """Helper to run sitecopy with the custom config."""
    cmd = ["./sitecopy", "--rcfile", str(senv["rcfile"]),
           "--storepath", str(senv["store"])] + args
    return subprocess.run(cmd, capture_output=True, text=True)

def assert_no_update(sitecopy_env):
    res = run_sitecopy(sitecopy_env, ["--list", "testsite"])
    assert res.returncode == 0
    assert "The remote site does not need updating." in res.stdout

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

