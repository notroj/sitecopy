import hashlib
import os
import shutil
import subprocess
import time

def run_sitecopy(senv, args, env=None, input=""):
    """Helper to run sitecopy with the custom config, optionally with
    the given environment and standard input.

    For debugging (see tests/README.md): if $SITECOPY_DEBUG is set, it
    is passed as --debug to sitecopy, and the command line and output
    are printed, so that pytest shows them with the test's captured
    output.  If $SITECOPY_TEST_LOG is set, the command line, debug
    output (using --logfile, so that stderr is unchanged), stdout and
    stderr of each invocation are appended to the file it names."""
    cmd = ["./sitecopy", "--rcfile", str(senv["rcfile"]),
           "--storepath", str(senv["store"])]
    debug = os.environ.get("SITECOPY_DEBUG")
    log = os.environ.get("SITECOPY_TEST_LOG")
    if debug:
        cmd.append("--debug=" + debug)
        if log:
            cmd.append("--logfile=" + os.path.abspath(log))
    cmd += args
    header = "==== %s\n$ %s\n" % (os.environ.get("PYTEST_CURRENT_TEST", ""),
                                 " ".join(cmd))
    if log:
        with open(log, "a") as fp:
            fp.write(header)
    res = subprocess.run(cmd, capture_output=True, text=True, env=env,
                         input=input)
    output = "---- exit status %d\n---- stdout:\n%s---- stderr:\n%s" % (
        res.returncode, res.stdout, res.stderr)
    if log:
        with open(log, "a") as fp:
            fp.write(output)
    if debug:
        print(header + output)
    return res

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
    "README.Html": "<html>Read me</html>\n",
    "Mixed/": None,
    "Mixed/Case.TXT": "Mixed case\n",
    "Mixed/Sub/": None,
    "Mixed/Sub/lower.txt": "Lower case in a mixed case directory\n",
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

def md5(data):
    """Return the MD5 checksum of data, as in local_tree."""
    return hashlib.md5(data).hexdigest()

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

def remote_tree(site):
    """Return the tree on the server in the same form as local_tree,
    listed from inside the server's container."""
    script = ("cd '%s' && find . -mindepth 1 -type d -printf '%%P/\\n' "
              "&& find . -type f -exec md5sum {} +") % site["root"]
    run = subprocess.run(["podman", "exec", site["cid"], "sh", "-c", script],
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

def remote_name(site, path):
    """Return the name on the server of the given site-relative path,
    which is lowercased in its entirety with `lowercase'
    (file_full_remote in src/sitefiles.c)."""
    return path.lower() if "lowercase" in site["config"] else path

def expected_remote(site, gone=()):
    """Update and return site["expected"], the tree expected on the
    server after an update of the current local tree.  With `nodelete'
    files and directories deleted locally stay on the server, unless
    they are in gone, the local paths known to have been removed from
    the server by the update (e.g. by a move)."""
    mapped = {remote_name(site, path): csum
              for path, csum in local_tree(site["local"]).items()}
    if "nodelete" in site["config"]:
        expected = {path: csum for path, csum in site["expected"].items()
                    if path not in {remote_name(site, g) for g in gone}}
        expected.update(mapped)
    else:
        expected = mapped
    site["expected"] = expected
    return expected

def assert_trees_match(site, gone=()):
    assert remote_tree(site) == expected_remote(site, gone)

def update_and_check(site, gone=()):
    """Update the site, check the update succeeded, that the remote
    tree is as expected (see expected_remote) and that no further
    update is needed, and return the CompletedProcess."""
    res = run_sitecopy(site, ["--update", "testsite"])
    assert res.returncode == 0, res.stdout + res.stderr
    # With `nodelete', an update with only deletions does nothing.
    assert ("Update completed successfully" in res.stdout
            or "Nothing to do - no changes found" in res.stdout), res.stdout
    assert_trees_match(site, gone)
    assert_no_update(site)
    return res

def setup_site(site, tree, expected=None):
    """Initialize the site, then create and upload the given tree.  If
    expected is given, it is the set of paths expected on the server
    afterwards, rather than the whole tree."""
    res = run_sitecopy(site, ["--initialize", "testsite"])
    assert res.returncode == 0, res.stdout + res.stderr
    write_tree(site["local"], tree)
    if expected is None:
        update_and_check(site)
    else:
        res = run_sitecopy(site, ["--update", "testsite"])
        assert res.returncode == 0, res.stdout + res.stderr
        assert set(remote_tree(site)) == expected
        assert_no_update(site)

def move_and_check(site, src, dst, moved):
    """Update the site after the local move of file src to dst, and
    check the update moved src to dst on the server if moved is true,
    or otherwise uploaded dst and deleted src (unless `nodelete')."""
    res = update_and_check(site, gone=[src] if moved else [])
    if moved:
        assert "Moving %s->%s" % (src, dst) in res.stdout, res.stdout
        assert "Uploading %s" % dst not in res.stdout, res.stdout
    else:
        assert "Moving" not in res.stdout, res.stdout
        assert "Uploading %s" % dst in res.stdout, res.stdout
        deleted = "Deleting %s" % src in res.stdout
        assert deleted != ("nodelete" in site["config"]), res.stdout
    return res

def moves_detected(site):
    return "checkmoved" in site["config"] or renames_detected(site)

def renames_detected(site):
    return "checkmoved renames" in site["config"]

def check_update_cycle(site):
    """Initialize the site against an empty remote directory, then run
    a series of updates which add, change and delete files and nested
    directories, checking after each that the remote tree is as
    expected."""
    local = site["local"]

    res = run_sitecopy(site, ["--initialize", "testsite"])
    assert res.returncode == 0, res.stdout + res.stderr

    assert_no_update(site)

    # Upload the whole corpus.
    write_tree(local, CORPUS)
    update_and_check(site)

    # In safe mode, changed files are only uploaded if unchanged on
    # the server since the last update; let time pass, as it would.
    if "safe" in site["config"]:
        time.sleep(2)

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
    update_and_check(site)

    # Delete whole nested subtrees.
    shutil.rmtree(local / "docs/guide")
    shutil.rmtree(local / "deep")
    update_and_check(site)

    # Delete everything.
    for path in local.iterdir():
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
    update_and_check(site)
    if "nodelete" not in site["config"]:
        assert remote_tree(site) == {}

def server_exec(site, script):
    """Run the shell script inside the site's server container, and
    return its stdout, checking that it succeeds."""
    run = subprocess.run(["podman", "exec", site["cid"], "sh", "-c", script],
                         capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    return run.stdout

def change_remote(site, path, content, mtime):
    """Replace the content of the file path on the server, as if
    changed by someone else, setting its modification time to mtime
    (seconds since the epoch).  The file keeps its ownership."""
    remote = "%s/%s" % (site["root"], remote_name(site, path))
    server_exec(site, "cp -p '%s' /tmp/owner && printf '%%s' '%s' > '%s' "
                "&& chown --reference=/tmp/owner '%s' && touch -d @%d '%s'"
                % (remote, content, remote, remote, mtime, remote))

def create_remote(site, path, content):
    """Create the file path on the server with the given content, as
    if by someone else, creating any parent directories, owned like
    the site's root directory so that sitecopy can delete them."""
    parts = remote_name(site, path).split("/")
    top = "%s/%s" % (site["root"], parts[0])
    remote = "%s/%s" % (site["root"], "/".join(parts))
    server_exec(site, "mkdir -p \"$(dirname '%s')\" && printf '%%s' '%s' > '%s' "
                "&& chown -R --reference='%s' '%s'"
                % (remote, content, remote, site["root"], top))

def change_remote_later(site, path, content):
    """Replace the content of the file path on the server, as if
    changed by someone else, with a modification time in a later
    second than any earlier upload."""
    time.sleep(2)
    change_remote(site, path, content, int(time.time()))

def remote_modes(site):
    """Return a dict mapping each path on the server to its octal
    permission bits, as a string (e.g. '644')."""
    out = server_exec(site, "cd '%s' && find . -mindepth 1 -printf '%%P %%m\\n'"
                      % site["root"])
    return dict(line.rsplit(" ", 1) for line in out.splitlines())

def server_log_lines(site, text):
    """Return the lines of the server's log containing text: its log
    file (e.g. the vsftpd log, which records each upload), searched
    inside the container, since it grows large and older versions of
    podman can truncate large output from podman exec; or the
    container's output (e.g. the httpd access log)."""
    if site["logfile"] is None:
        run = subprocess.run(["podman", "logs", site["cid"]],
                             capture_output=True, text=True)
        assert run.returncode == 0, run.stderr
        log = run.stdout + run.stderr
        return [line for line in log.splitlines() if text in line]
    run = subprocess.run(["podman", "exec", site["cid"],
                          "grep", "-F", "--", text, site["logfile"]],
                         capture_output=True, text=True)
    assert run.returncode in (0, 1), run.stderr
    return run.stdout.splitlines()

def add_site_lines(site, *lines):
    """Add the given rcfile lines to the site, which is the last in
    the rcfile."""
    with open(site["rcfile"], "a") as fp:
        fp.write("".join("  %s\n" % line for line in lines))
