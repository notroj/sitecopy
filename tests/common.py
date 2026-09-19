import hashlib
import os
import shutil
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

# Files in the test corpus, relative to the site root.  Includes
# several levels of nested directories, a binary file, and an empty
# directory (listed with a trailing slash).
CORPUS = {
    "index.html": "<html>Home</html>\n",
    "about.txt": "About this site\n",
    "docs/": None,
    "docs/intro.txt": "Introduction\n",
    "docs/faq.html": "<html>FAQ</html>\n",
    "docs/guide/": None,
    "docs/guide/ch1.txt": "Chapter one\n" * 50,
    "docs/guide/ch2.txt": "Chapter two\n" * 50,
    "docs/guide/images/": None,
    "docs/guide/images/fig1.png": bytes(range(256)) * 16,
    "assets/": None,
    "assets/css/": None,
    "assets/css/site.css": "body { color: black; }\n",
    "assets/js/": None,
    "assets/js/app.js": "console.log('hello');\n",
    "deep/": None,
    "deep/a/": None,
    "deep/a/b/": None,
    "deep/a/b/c/": None,
    "deep/a/b/c/leaf.txt": "A leaf\n",
    "empty/": None,
}

def write_tree(root, tree):
    """Create the given tree of files and directories under root."""
    for name, content in sorted(tree.items()):
        path = root / name
        if content is None:
            path.mkdir(parents=True, exist_ok=True)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(content, bytes):
                path.write_bytes(content)
            else:
                path.write_text(content)

def local_tree(root):
    """Return a dict mapping each path under root to the MD5 checksum
    of its contents, or None for a directory (with a trailing slash)."""
    tree = {}
    for dirpath, dirnames, filenames in os.walk(root):
        rel = os.path.relpath(dirpath, root)
        prefix = "" if rel == "." else rel + "/"
        for d in dirnames:
            tree[prefix + d + "/"] = None
        for f in filenames:
            with open(os.path.join(dirpath, f), "rb") as fp:
                tree[prefix + f] = hashlib.md5(fp.read()).hexdigest()
    return tree

def remote_tree(server):
    """Return the tree on the server in the same form as local_tree,
    listed from inside the server's container."""
    script = ("cd '%s' && find . -mindepth 1 -type d -printf '%%P/\\n' "
              "&& find . -type f -exec md5sum {} +") % server["root"]
    run = subprocess.run(["podman", "exec", server["cid"], "sh", "-c", script],
                         capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    tree = {}
    for line in run.stdout.splitlines():
        if line.endswith("/"):
            tree[line] = None
        else:
            csum, name = line.split(None, 1)
            tree[name.removeprefix("./")] = csum
    return tree

def assert_trees_match(sitecopy_env, server):
    assert remote_tree(server) == local_tree(sitecopy_env["local"])

def check_update_cycle(sitecopy_env, server):
    """Initialize the site against an empty remote directory, then run
    a series of updates which add, change and delete files and nested
    directories, checking after each that the remote tree matches the
    local tree."""
    local = sitecopy_env["local"]

    res = run_sitecopy(sitecopy_env, ["--initialize", "testsite"])
    assert res.returncode == 0, res.stdout + res.stderr

    assert_no_update(sitecopy_env)

    # Upload the whole corpus.
    write_tree(local, CORPUS)
    assert_update_success(sitecopy_env)
    assert_trees_match(sitecopy_env, server)
    assert_no_update(sitecopy_env)

    # Change files at several depths, add new files to new and
    # existing directories, and delete a single file.
    (local / "index.html").write_text("<html>Home, changed</html>\n")
    (local / "docs/guide/ch2.txt").write_text("Chapter two, revised\n")
    (local / "deep/a/b/c/leaf.txt").write_text("A changed leaf\n")
    write_tree(local, {
        "docs/guide/ch3.txt": "Chapter three\n",
        "empty/now-full.txt": "No longer empty\n",
        "assets/fonts/": None,
        "assets/fonts/font.bin": bytes(range(255, -1, -1)),
    })
    (local / "about.txt").unlink()
    assert_update_success(sitecopy_env)
    assert_trees_match(sitecopy_env, server)
    assert_no_update(sitecopy_env)

    # Delete whole nested subtrees.
    shutil.rmtree(local / "docs/guide")
    shutil.rmtree(local / "deep")
    assert_update_success(sitecopy_env)
    assert_trees_match(sitecopy_env, server)
    assert_no_update(sitecopy_env)

    # Delete everything.
    for path in local.iterdir():
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
    assert_update_success(sitecopy_env)
    assert remote_tree(server) == {}
