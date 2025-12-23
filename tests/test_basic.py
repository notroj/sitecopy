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

    res = run_sitecopy(sitecopy_env, ["--catchup", "testsite"])
    assert res.returncode == 0

    assert_no_update(sitecopy_env)
