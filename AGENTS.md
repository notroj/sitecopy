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

## Code style

New and modified C code in `src/` and `lib/` follows the style of
recent neon code (e.g. `ne_getmodtime` in `neon/src/ne_basic.c`, or
`neon/src/ne_request.c`), not the older sitecopy style with tabs and
inconsistent bracing.

- Function definitions put the return type and name on one line, and
  the opening `{` on a line of its own.
- Indent by 4 spaces; never use tab characters.
- `if`, `for`, `while` and `switch` keep `{` on the same line as the
  condition.  `else` and `else if` start a new line after the closing
  `}`, never `} else {`.  Single-statement bodies may omit braces.
- `case` labels align with their `switch`; the statements under them
  are indented by 4 spaces.
- A space after keywords (`if (`, `while (`) but not after function
  names in calls; spaces around binary and assignment operators;
  pointer declarations as `char *p`.
- Comments use `/* ... */`, not `//`.
- Keep lines within about 80 columns.  Wrap long argument lists with
  continuation lines aligned after the opening parenthesis; split
  long strings by concatenation, and put `&&`/`||` at the start of a
  wrapped condition.

Example:

    static int check_file(struct site *site, const char *name,
                          int flags)
    {
        int ret;

        if (name == NULL) {
            ret = SITE_ERRORS;
        }
        else if (flags & CHECK_REMOTE) {
            ret = check_remote(site, name);
        }
        else
            ret = SITE_OK;

        return ret;
    }

When modifying an existing function, bring the whole function into
this style; don't reformat untouched functions or whole files as part
of an unrelated change.

Prefer neon's string and memory helpers (`ne_malloc`, `ne_strdup`,
`ne_concat`, `ne_buffer_*`, `ne_snprintf`, `ne_strnzcpy`) over manual
length arithmetic and fixed-size buffers.  sitecopy supports neon 0.29
and later (`NE_MINIMUM_VERSION(0, 29)` in `configure.ac`), so only use
APIs present in 0.29; e.g. `ne_strhash()` and `ne_strparam()` need
0.32 (see `neon/NEWS`).

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
  server on port 8080, the FTP server on port 2121 with passive
  ports 21100-21109, and the same vsftpd image requiring FTP over TLS
  (`ftps`) on port 2122 with passive ports 21110-21119, whose
  self-signed certificate is saved as the site's certificate so that
  it is trusted.  Each container is started once per session.  The
  `ftps` tests are skipped if `sitecopy --version` doesn't list
  "FTPS", i.e. if sitecopy was built without FTP over TLS support
  (which needs neon 0.37 or later with SSL support).
- `tests/siteconfig.py` — rcfile option axes (`AXES`) for the server
  tests, e.g. `state`, `moves`, `delete`, `overwrite`, `safe`,
  `tempupload`, `lowercase`, `symlinks` and `permissions`, plus the
  rules for valid combinations: `REQUIRES` (options only valid with
  another), `CONFLICTS` (options rejected together) and
  `PROTOCOL_ONLY`.  A test marked `@pytest.mark.axes("state",
  "moves")` runs once per valid combination of those axes; axes
  marked `always`, such as `ftp` (with and without `ftp usecwd`),
  apply to every test for their protocol.  `@pytest.mark.site_lines(
  "nodelete")` adds rcfile lines to every configuration of a test.
  Add new rcfile variations as axes or axis values here, and
  combinations sitecopy rejects to the tables (and to
  `REJECTED_CONFIGS` in `test_basic.py`).
- `tests/common.py` — helpers such as `run_sitecopy()`,
  `update_and_check()` (update, then compare the tree on the server,
  listed from inside the container, with `expected_remote()`, a model
  of what should be there given the configuration, e.g. `nodelete`
  keeps deleted files and `lowercase` lowercases names),
  `move_and_check()`, `change_remote_later()` (change a file on the
  server as if someone else did) and `check_update_cycle()`.  When a
  server test fails, its report includes the recent server logs.
- `tests/server_tests.py` — the tests run against each server.  It is
  not collected directly: `test_dav.py`, `test_vsftpd.py` and
  `test_vsftpd_ssl.py` import it and select their server with
  `pytestmark = pytest.mark.protocol(...)`, so the servers can be tested
  separately, e.g. `pytest-3 tests/test_dav.py`.  Test IDs name the
  protocol and configuration, e.g. `[ftp-usecwd-checksum-renames]`,
  so `-k` can select configurations.
- `test_basic.py` — option handling and local state, no server needed.
- `test_ftp.py` — FTP against a scripted in-process FTP server.
- `test_false_success.py` — SFTP failure handling, using a wrapper
  script in place of ssh/sftp; no network access needed.

Guidelines:

- Known bugs which aren't fixed yet get a regression test marked
  `@pytest.mark.xfail(strict=True, reason=...)` describing the bug,
  so that the fix turns it into a passing test.  A bug affecting only
  some configurations of a server test goes in `KNOWN_BUGS` in
  `tests/siteconfig.py` instead.  Check the xfail fails for the stated
  reason (`pytest-3 --runxfail`).
- Server tests must not depend on timing: e.g. a test which relies on
  a later modification time must wait for a later second (see
  `change_remote_later()`), rather than passing only because it runs
  fast.

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
