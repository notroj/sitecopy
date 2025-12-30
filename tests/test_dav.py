import subprocess
import os
from common import *

def test_dav(sitecopy_env, httpd_container):
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
