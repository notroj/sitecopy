import os
import subprocess

def run_sitecopy(senv, args):
    """Helper to run sitecopy with the custom config."""
    cmd = ["./sitecopy", "--rcfile", str(senv["rcfile"]),
           "--storepath", str(senv["store"])] + args
    return subprocess.run(cmd, capture_output=True, text=True)

def assert_no_update(sitecopy_env):
    res = run_sitecopy(sitecopy_env, ["--list", "testsite"])
    assert res.returncode == 0, res.stdout + res.stderr
    assert "The remote site does not need updating." in res.stdout

def assert_update_success(sitecopy_env):
    res = run_sitecopy(sitecopy_env, ["--update", "testsite"])
    assert res.returncode == 0, res.stdout + res.stderr
    assert "Update completed successfully" in res.stdout

def check_update_cycle(sitecopy_env):
    """Initialize the site against an empty remote directory, then
    upload and delete a file, and a file within a new directory,
    checking that each update succeeds."""
    res = run_sitecopy(sitecopy_env, ["--initialize", "testsite"])
    assert res.returncode == 0

    assert_no_update(sitecopy_env)

    newfile = sitecopy_env["local"] / "newfile.txt"
    newfile.write_text("Hello, world\n")
    assert_update_success(sitecopy_env)

    newfile.unlink()
    assert_update_success(sitecopy_env)

    newdir = sitecopy_env["local"] / "newdir"
    newdir.mkdir()
    newfile = newdir / "subdir.txt"
    newfile.write_text("Here also\n")
    assert_update_success(sitecopy_env)

    newfile.unlink()
    newdir.rmdir()
    assert_update_success(sitecopy_env)
