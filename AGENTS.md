# AGENTS.md

Notes for AI coding agents working on sitecopy.

sitecopy is a C program which keeps remote web sites in sync with a
local copy, over FTP, WebDAV (via the neon library, bundled as a git
submodule in `neon/`) and SFTP.  Sources live in `src/`, helper code
in `lib/`, the man page in `doc/sitecopy.1`, and tests in `tests/`.

## Building

    ./autogen.sh
    ./configure --with-included-neon --with-ssl=openssl --enable-warnings
    make EXTRA_CFLAGS=-Werror

Use `--with-neon=/usr` instead of `--with-included-neon` to build
against a system neon.  Code must build cleanly with `--enable-warnings`
and `-Werror`, as CI enforces this.

## Testing

The test suite is written in Python using pytest and runs the built
`./sitecopy` binary from the top of the tree:

    make check

`make check` builds `sitecopy`, builds the podman container images
used by the WebDAV and FTP tests (`tests/httpd-Containerfile` and
`tests/vsftpd-Containerfile`, stamped by `tests/*-container-stamp`),
then runs `pytest-3 -v tests/`.  If an image has been removed but its
stamp file remains, delete the stamp to force a rebuild.

To run a subset directly (after `make`), from the top-level directory:

    pytest-3 -v tests/test_basic.py
    pytest-3 -v tests/test_ftp.py -k leading_space

Test layout:

- `tests/conftest.py` — shared fixtures: `sitecopy_env` (a temporary
  rcfile, local directory and storage directory for a WebDAV site named
  `testsite`, with no server), and `site` (the same, configured for a
  server running in a container, whose site directory is emptied
  before each test).  `SERVERS` describes the servers: the WebDAV
  server on port 8080, and the FTP server on port 2121 with passive
  ports 21100-21109.  Each container is started once per session.
- `tests/siteconfig.py` — rcfile option axes (`AXES`) for the server
  tests, e.g. `state` (timesize/checksum) and `moves` (none,
  `checkmoved`, `checkmoved renames`), and `REQUIRES`, listing
  options only valid with another.  A test marked
  `@pytest.mark.axes("state", "moves")` runs once per valid
  combination of those axes; axes marked `always`, such as `ftp`
  (with and without `ftp usecwd`), apply to every test for their
  protocol.  Add new rcfile variations as axes or axis values here.
- `tests/common.py` — helpers such as `run_sitecopy()`,
  `update_and_check()` (update, then compare the remote tree with the
  local tree from inside the container), `assert_moved()` and
  `check_update_cycle()`.
- `tests/server_tests.py` — the tests run against each server.  It is
  not collected directly: `test_dav.py` and `test_vsftpd.py` import
  it and select their server with `pytestmark =
  pytest.mark.protocol(...)`, so the servers can be tested
  separately, e.g. `pytest-3 tests/test_dav.py`.  Test IDs name the
  protocol and configuration, e.g. `[ftp-usecwd-checksum-renames]`,
  so `-k` can select configurations.
- `test_basic.py` — option handling and local state, no server needed.
- `test_ftp.py` — FTP against a scripted in-process FTP server.
- `test_false_success.py` — SFTP failure handling, using a wrapper
  script in place of ssh/sftp; no network access needed.

Guidelines:

- Every bug fix should come with a regression test where practical.
  Prefer tests which run entirely locally (scripted servers, wrapper
  scripts) over ones which need containers or network access.
- Reference the upstream or distribution bug in the test's docstring
  (e.g. "Debian bug #496988").
- Confirm a new regression test fails without the fix and passes with
  it.
- Run the full `make check` before considering a change done, and
  report any failures faithfully.  CI (`.github/workflows/ci.yml`)
  runs the build and `make check` on Ubuntu with bundled and system
  neon, with and without `-Werror`.

## Changelog: GNU-style commit messages

The change log is kept in the git commit messages, which follow the
GNU ChangeLog style.  User-visible changes should additionally be
summarized in `NEWS`.

Format:

    Short summary sentence:

    * src/file.c (function_name): Describe what changed.
      (other_function): Describe what changed here.

    * src/file.h (struct foo): Add bar field.

Rules:

- One `* file (symbol): Description.` entry per file; list each
  changed function, macro, struct or variable in parentheses.
  Several symbols with the same description may share parentheses,
  e.g. `(foo, bar):`.  Several files with the same description may
  share one entry, e.g. `* src/a.c, src/b.c: ...`.
- Continuation lines are indented by two spaces; separate entries for
  different files with a blank line.
- Write complete sentences in the imperative/present tense, starting
  with a capital letter and ending with a full stop.  Describe *what*
  changed in the entries; put the *why* in the free-text paragraph.
- Use the conventional phrasings: `New function.`, `New file.`,
  `Removed.`, `Removed; replaced by foo.`, `Use foo.`, `Declare and
  document the above.`, `Update.`
- Quote in the GNU style with a backtick and apostrophe: `` `foo' ``.
- For a small, single-file change the summary line may itself be the
  entry, e.g. `* NEWS: Update.` or
  `* src/lsparser.c (ls_init): Initialize curdir to empty string.`
- Mention related bug numbers (e.g. "issue #123") in the
  explanation or the relevant entry.

Example:

    Factor out the sorted file list used when writing stored state.

    * src/sites.c (site_file_cmp_stored, site_sorted_files_list): New
      functions, moved and generalized from sitestore.c.

    * src/sites.h (file_cmp_fn, site_file_cmp_stored,
      site_sorted_files_list): Declare and document the above.

    * src/sitestore.c (site_file_cmp): Removed; replaced by
      site_file_cmp_stored.
      (site_write_stored_state): Use site_sorted_files_list.
