import os
import subprocess

def run_sitecopy(senv, args):
    """Helper to run sitecopy with the custom config."""
    cmd = ["./sitecopy", "--rcfile", str(senv["rcfile"]),
           "--storepath", str(senv["store"])] + args
    return subprocess.run(cmd, capture_output=True, text=True)

def assert_no_update(sitecopy_env):
    res = run_sitecopy(sitecopy_env, ["--list", "testsite"])
    assert res.returncode == 0
    assert "The remote site does not need updating." in res.stdout

def assert_update_success(sitecopy_env):
    res = run_sitecopy(sitecopy_env, ["--update", "testsite"])
    assert res.returncode == 0
    assert "Update completed successfully" in res.stdout
