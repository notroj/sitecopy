# Running the sitecopy tests

The tests are written in Python using pytest, and run the built
`./sitecopy` binary.  Always run them from the top-level directory of
the source tree.  How the test framework is organized (fixtures, the
rcfile option axes, helpers and guidelines for writing tests) is
described in the "Testing" section of `AGENTS.md`; this file covers
running the tests and investigating failures.

## Prerequisites

- `pytest-3` (e.g. the `python3-pytest` package).
- `podman`, for the tests against real servers, which run in
  containers.  The images need network access to `quay.io` the first
  time they are built.
- A built `sitecopy` (see "Building" in `AGENTS.md`).  `make check`
  builds it; when running pytest directly, run `make` first, since the
  tests don't rebuild it.

The container images are built by:

    make check-containers

which builds `sitecopy-test-httpd` from `tests/httpd-Containerfile`,
`sitecopy-test-vsftpd` from `tests/vsftpd-Containerfile` and
`sitecopy-test-pure-ftpd` from `tests/pure-ftpd-Containerfile`, and
records each build in a stamp file, `tests/*-container-stamp` (e.g.
`tests/vsftpd-container-stamp`).  An image is rebuilt when its
Containerfile or configuration files change.  To force a rebuild,
e.g. after the image was removed with `podman rmi`, or to pick up an
updated base image, delete its stamp file:

    rm tests/vsftpd-container-stamp
    make check-containers

## Running the tests

Build everything and run the whole suite:

    make check

This runs `pytest-3 -v tests/` after building sitecopy and the
images.  To run part of the suite, after `make` and `make
check-containers`:

    pytest-3 -v tests/test_basic.py                   # one file
    pytest-3 -v tests/test_ftp.py::test_fetch_active_mode   # one test
    pytest-3 -v tests/test_ftp.py -k leading_space    # by name

Server tests are parametrized: each runs once per valid combination
of the rcfile option axes it names (see `tests/siteconfig.py`).  The
test ID in brackets is the protocol followed by the ID of the value of
each axis used, in the order of `AXES`, e.g.:

    tests/test_vsftpd.py::test_update_cycle[ftp-usecwd-delete-overwrite-nosafe-direct-case]

is `test_update_cycle` against vsftpd with `ftp usecwd`, without
`nodelete`, `nooverwrite`, `safe`, `tempupload` or `lowercase`.  To
list the test IDs:

    pytest-3 --collect-only -q tests/test_vsftpd.py

Run a single configuration by giving its full ID (quoted, because of
the brackets):

    pytest-3 -v 'tests/test_vsftpd.py::test_update_cycle[ftp-usecwd-delete-overwrite-nosafe-direct-case]'

or select configurations with `-k`, which matches substrings of the
test names and IDs, e.g. every `test_update_cycle` configuration with
both `usecwd` and `tempupload`:

    pytest-3 -v tests/test_vsftpd.py -k 'test_update_cycle and usecwd and tempupload'

Useful pytest options: `-x` stops at the first failure, `--lf` reruns
only the tests which failed last time, and `-rA` shows the captured
output of passing tests too.

## Servers, containers and ports

| Test module | Server | Host ports |
|---|---|---|
| `test_basic.py`, `test_false_success.py` | none | none |
| `test_ftp.py` | scripted FTP server in the test process | a free port in 22070-22079 |
| `test_dav.py` | `sitecopy-test-httpd` (Apache mod_dav) | 8080 |
| `test_vsftpd.py` | `sitecopy-test-vsftpd` | 2121, passive 21100-21109 |
| `test_regression.py` | `sitecopy-test-vsftpd` | 2121, passive 21100-21109 |
| `test_vsftpd_ssl.py` | `sitecopy-test-vsftpd` with TLS required (and also the plain FTP server) | 2122, passive 21110-21119 |
| `test_pureftpd.py` | `sitecopy-test-pure-ftpd` | 2123, passive 21200-21209 |
| `test_pureftpd_ssl.py` | `sitecopy-test-pure-ftpd` with TLS required (and also the plain pure-ftpd server) | 2124, passive 21210-21219 |

Each container is started the first time a test needs it, shared by
all the tests of the session (the site directory on the server is
emptied before each test), and killed at the end of the session.  The
host ports are fixed, so only one test session using a given server
can run at a time: running two at once, e.g. in two source trees,
makes the second fail to start its container.  Check for other
sessions' containers before starting one:

    podman ps

If a session was interrupted (e.g. killed, rather than stopped with
Ctrl-C), its containers may be left running and keep the ports
busy.  The containers are started with `--rm`, so killing them also
removes them:

    podman ps --filter ancestor=sitecopy-test-vsftpd --filter ancestor=sitecopy-test-httpd \
              --filter ancestor=sitecopy-test-pure-ftpd
    podman kill <container ID>...

The FTPS tests are skipped if sitecopy was built without FTP over TLS
support, i.e. if `./sitecopy --version` doesn't list "FTPS".  The FTP
over TLS servers are only tested across the rcfile options which
change how sitecopy uses the FTP protocol (`PROTOCOL_AXES` in
`tests/siteconfig.py`), so tests of other options are reported as
skipped for them ("got empty parameter set").

## Expected failures

A known bug which isn't fixed yet has a regression test marked as a
strict xfail, reported as `x` (`XFAIL`) rather than a failure.
Because it is strict, the test failing is required: once the bug is
fixed, the test passing is reported as a failure (`XPASS(strict)`),
and the xfail marker must be removed.  A bug affecting only some
configurations of a server test is listed in `KNOWN_BUGS` in
`tests/siteconfig.py`, which marks just those configurations.  Tests
for specific bugs which don't depend on the rcfile options being
varied are in `tests/test_regression.py`, which runs each test once
against vsftpd in its default configuration.

To see how an xfail test actually fails, e.g. to check that it fails
for the stated reason, run it with `--runxfail`:

    pytest-3 --runxfail -v tests/test_vsftpd.py -k test_nodelete_list_count

`-rx` lists the reasons of the xfails in the summary.

## Server logs

When a server test fails, pytest's report includes the last 100 lines
of the server's log, in a section headed `server: ...`: the vsftpd
log, which records every FTP command and reply; the pure-ftpd log,
which records each transfer; or the container log for httpd, which
holds its access and error logs.  To inspect a server
yourself while its container is running (e.g. while a test is stopped
in the debugger with `--pdb`):

    podman ps                           # find the container ID
    podman exec <ID> tail -n 200 /var/log/vsftpd.log
    podman exec <ID> tail -n 200 /var/log/pure-ftpd.log
    podman logs <ID>                    # httpd
    podman exec -it <ID> sh             # look around

The site directory is `/home/sitecopy/site` for vsftpd and pure-ftpd,
and `/var/www/html/dav` for httpd.

## Capturing a sitecopy debug log

sitecopy can log what it does with `--debug=CHANNEL,...`; the
channels are `socket`, `files`, `rcfile`, `ftp`, `http`, `httpauth`,
`httpbody`, `ssl`, `xml`, `xmlparse`, `rsh`, `sftp` and `cleartext`
(which shows passwords, otherwise hidden, in plain text).  The debug
messages go to stderr, or are appended to the file given by
`--logfile=FILE`.  This needs a sitecopy built with debugging support,
which `./sitecopy --version` shows by listing "debugging".

The tests run sitecopy through `run_sitecopy()` in `tests/common.py`,
which captures its output.  Two environment variables make it log
each invocation:

- `SITECOPY_DEBUG=CHANNEL,...` passes `--debug=CHANNEL,...` to every
  invocation, and prints its command line, exit status, stdout and
  stderr, so they appear in the test's "Captured stdout call" section:
  shown for a failing test, or for every test with `-rA` (or
  immediately with `-s`).  Without `SITECOPY_TEST_LOG` the debug
  messages go to sitecopy's stderr.
- `SITECOPY_TEST_LOG=FILE` appends the same information for each
  invocation to FILE, each starting with a `====` line naming the
  test.  If `SITECOPY_DEBUG` is also set, the debug messages are
  written to FILE too, using `--logfile`, so sitecopy's stdout and
  stderr, which the tests check, are unchanged.  The file is appended
  to, so remove it first to start afresh.

For example, to capture the FTP protocol exchanges for one
configuration of `test_update_cycle`:

    rm -f /tmp/ftp-debug.log
    SITECOPY_DEBUG=ftp,socket SITECOPY_TEST_LOG=/tmp/ftp-debug.log \
      pytest-3 -v 'tests/test_vsftpd.py::test_update_cycle[ftp-pasv-delete-overwrite-nosafe-direct-case]'

which gives a log like:

    ==== tests/test_vsftpd.py::test_update_cycle[ftp-pasv-delete-overwrite-nosafe-direct-case] (call)
    $ ./sitecopy --rcfile /tmp/pytest-of-.../.sitecopyrc --storepath ... --debug=ftp,socket --logfile=/tmp/ftp-debug.log --update testsite
    Opening socket to port 2121
    < 220 (vsFTPd 3.0.5)
    FTP: Sending 'USER sitecopy':
    > USER sitecopy
    < 331 Please specify the password.
    ...
    ---- exit status 0
    ---- stdout:
    sitecopy: Updating site `testsite' (on localhost in /home/sitecopy/site/)
    ...
    ---- stderr:

Use `http`, `httpbody` and `socket` for the WebDAV tests, `ssl` for
the FTPS certificate handling, and `sftp` or `rsh` for
`test_false_success.py`.  `SITECOPY_TEST_LOG` alone, without
`SITECOPY_DEBUG`, records just the command lines and output.

The `sitecopy --version` run by `sitecopy_features()` in
`tests/conftest.py`, to check which features were built, doesn't use
`run_sitecopy()` and isn't logged.
