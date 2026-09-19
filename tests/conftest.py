import pytest
import os
import socket
import subprocess
import time

import siteconfig

def make_sitecopy_env(tmp_path, site_config):
    """Create the local and storage directories and an rcfile defining
    the site 'testsite' with the given configuration lines."""
    local_dir = tmp_path / "local"
    store_dir = tmp_path / "storage"
    local_dir.mkdir()
    store_dir.mkdir()

    config_file = tmp_path / ".sitecopyrc"
    config_content = f"""
site testsite
  server localhost
  local {local_dir}
{site_config}"""
    config_file.write_text(config_content)
    os.chmod(config_file, 0o600)
    os.chmod(store_dir, 0o700)

    return {
        "rcfile": config_file,
        "local": local_dir,
        "store": store_dir,
    }

@pytest.fixture
def sitecopy_env(tmp_path):
    return make_sitecopy_env(tmp_path, """\
  port 8080
  remote /dav/
  protocol dav
""")

class Server:
    """A server run in a container for the tests of one protocol."""

    def __init__(self, image, ports, port, root, rcfile, command=(),
                 certfile=None, requires=None, run_args=(), logfile=None):
        self.image = image
        # Port specs published from the container.
        self.ports = ports
        # Port on which the server accepts connections.
        self.port = port
        # Directory holding the site on the server.
        self.root = root
        # rcfile lines configuring the site for this server.
        self.rcfile = rcfile
        # Arguments for the container's entrypoint, if not the default.
        self.command = list(command)
        # Server certificate in the container, which is saved as the
        # site's certificate so that it is trusted.
        self.certfile = certfile
        # Feature which `sitecopy --version' must list for the tests
        # to run.
        self.requires = requires
        # Additional arguments for `podman run'.
        self.run_args = list(run_args)
        # Server's log file in the container, or None for the
        # container's own output.
        self.logfile = logfile

# pure-ftpd refuses to start ("421 Unable to switch capabilities")
# without these capabilities, which podman doesn't grant by default.
PURE_FTPD_RUN_ARGS = ["--cap-add", "DAC_READ_SEARCH,SYS_NICE,AUDIT_WRITE"]

SERVERS = {
    "dav": Server("sitecopy-test-httpd", ["8080:80"], 8080,
                  "/var/www/html/dav", """\
  port 8080
  remote /dav/
  protocol dav
"""),
    "ftp": Server("sitecopy-test-vsftpd",
                  ["2121:21", "21100-21109:21100-21109"], 2121,
                  "/home/sitecopy/site", """\
  port 2121
  remote /home/sitecopy/site/
  protocol ftp
  username sitecopy
  password sitecopy
""", logfile="/var/log/vsftpd.log"),
    # FTP over TLS: the same image, with TLS required.
    "ftps": Server("sitecopy-test-vsftpd",
                   ["2122:21", "21110-21119:21110-21119"], 2122,
                   "/home/sitecopy/site", """\
  port 2122
  remote /home/sitecopy/site/
  protocol ftp
  username sitecopy
  password sitecopy
  ftp secure
""", command=["/etc/vsftpd/vsftpd-tls.conf"],
                   certfile="/etc/vsftpd/cert.pem", requires="FTPS",
                   logfile="/var/log/vsftpd.log"),
    # pure-ftpd, which needs capabilities beyond podman's defaults.
    "pureftpd": Server("sitecopy-test-pure-ftpd",
                       ["2123:21", "21200-21209:21200-21209"], 2123,
                       "/home/sitecopy/site", """\
  port 2123
  remote /home/sitecopy/site/
  protocol ftp
  username sitecopy
  password sitecopy
""", command=["-p", "21200:21209"], run_args=PURE_FTPD_RUN_ARGS,
                       logfile="/var/log/pure-ftpd.log"),
    # pure-ftpd with TLS required for the control and data connections.
    "pureftpds": Server("sitecopy-test-pure-ftpd",
                        ["2124:21", "21210-21219:21210-21219"], 2124,
                        "/home/sitecopy/site", """\
  port 2124
  remote /home/sitecopy/site/
  protocol ftp
  username sitecopy
  password sitecopy
  ftp secure
""", command=["-p", "21210:21219", "-Y", "3",
              "-2", "/etc/pure-ftpd/cert.pem,/etc/pure-ftpd/key.pem"],
                        certfile="/etc/pure-ftpd/cert.pem", requires="FTPS",
                        run_args=PURE_FTPD_RUN_ARGS,
                        logfile="/var/log/pure-ftpd.log"),
}

def sitecopy_features():
    """Return the features listed by `sitecopy --version'."""
    run = subprocess.run(["./sitecopy", "--version"],
                         capture_output=True, text=True)
    return run.stdout.split(":", 1)[1].replace(",", " ").split()

def pytest_addoption(parser):
    parser.addoption("--full", action="store_true",
                     help="run the server tests across every valid "
                     "combination of rcfile options (make check-full), "
                     "rather than a minimal set covering each option "
                     "value at least once")

def pytest_configure(config):
    config.addinivalue_line(
        "markers", "axes(*names, protocol_axes=()): run a test using the "
        "site fixture once for each valid combination of the named rcfile "
        "option axes (see siteconfig.py); protocol_axes names axes which "
        "change protocol use for the test, so are also combined for "
        "REDUCED_PROTOCOLS")
    config.addinivalue_line(
        "markers", "protocol(name): run tests using the site fixture "
        "only against the server for the given protocol")
    config.addinivalue_line(
        "markers", "site_lines(*lines): add the given rcfile lines to "
        "every configuration of a test using the site fixture")
    config.addinivalue_line(
        "markers", "default_config: run a test using the site fixture "
        "only in the default configuration, with the default value of "
        "each axis, for each protocol")

def pytest_generate_tests(metafunc):
    """Parametrize each test using the site fixture over every
    combination of the rcfile option axes it names (with --full), or a
    minimal set of combinations covering each value of each axis, for
    the server named by its protocol marker (or every server, if
    none)."""
    if "site_config" not in metafunc.fixturenames:
        return
    marker = metafunc.definition.get_closest_marker("axes")
    axis_names = marker.args if marker else ()
    protocol_axes = marker.kwargs.get("protocol_axes", ()) if marker else ()
    marker = metafunc.definition.get_closest_marker("protocol")
    protocols = marker.args if marker else SERVERS.keys()
    marker = metafunc.definition.get_closest_marker("site_lines")
    extra_lines = marker.args if marker else ()
    configs = []
    for protocol in protocols:
        protocol_configs = list(siteconfig.site_configs(
            protocol, axis_names, extra_lines, protocol_axes))
        if metafunc.definition.get_closest_marker("default_config"):
            # Only the first, with the default value of each axis.
            protocol_configs = protocol_configs[:1]
        elif not metafunc.config.getoption("full"):
            protocol_configs = siteconfig.minimal_configs(protocol_configs)
        configs += protocol_configs
    params = []
    for config in configs:
        reason = siteconfig.known_bug(metafunc.function.__name__, config)
        marks = [pytest.mark.xfail(strict=True, reason=reason)] if reason else []
        params.append(pytest.param(config, id=config.id, marks=marks))
    metafunc.parametrize("site_config", params)

def run_container(image, ports, wait_port, command=(), run_args=()):
    """Run the given container image detached, publishing the given
    list of port specs, with the given arguments for its entrypoint if
    any, and additional arguments for podman run, and wait until
    wait_port accepts connections.  Returns the container ID."""
    cmd = ["podman", "run", "--rm", "-d"] + list(run_args)
    for port in ports:
        cmd += ["-p", port]
    run = subprocess.run(cmd + [image] + list(command),
                         capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    cid = run.stdout.strip()
    assert len(cid) > 0

    deadline = time.monotonic() + 10
    while True:
        try:
            with socket.create_connection(("localhost", wait_port), timeout=1):
                break
        except OSError:
            if time.monotonic() > deadline:
                subprocess.run(["podman", "kill", cid], capture_output=True)
                pytest.fail(f"{image} did not start listening on {wait_port}")
            time.sleep(0.1)

    return cid

def podman_exec(cid, script):
    """Run the shell script inside the given container, returning the
    CompletedProcess."""
    return subprocess.run(["podman", "exec", cid, "sh", "-c", script],
                          capture_output=True, text=True)

@pytest.fixture(scope="session")
def containers():
    """Returns a function which gives the container ID of the server
    for a protocol, starting the container on first use.  Containers
    are shared by all the tests in the session."""
    running = {}

    def get(protocol):
        if protocol not in running:
            server = SERVERS[protocol]
            running[protocol] = run_container(server.image, server.ports,
                                              server.port, server.command,
                                              server.run_args)
        return running[protocol]

    yield get

    for cid in running.values():
        subprocess.run(["podman", "kill", cid], capture_output=True)

@pytest.fixture
def site(tmp_path, site_config, containers):
    """A site configured with site_config, against an empty directory
    on the server for its protocol.  A dict with the keys of
    make_sitecopy_env plus 'config', 'cid', 'root', and 'expected',
    the tree expected on the server (see common.expected_remote)."""
    server = SERVERS[site_config.protocol]
    if server.requires and server.requires not in sitecopy_features():
        pytest.skip("sitecopy built without %s support" % server.requires)
    cid = containers(site_config.protocol)

    run = podman_exec(cid, "find '%s' -mindepth 1 -delete" % server.root)
    assert run.returncode == 0, run.stderr

    rcfile = server.rcfile
    if any(line.startswith("remote ") for line in site_config.lines):
        # The configuration gives the site's directory instead.
        rcfile = "".join(line for line in rcfile.splitlines(True)
                         if not line.startswith("  remote "))
    env = make_sitecopy_env(tmp_path, rcfile + site_config.rcfile())
    if server.certfile:
        run = podman_exec(cid, "cat '%s'" % server.certfile)
        assert run.returncode == 0, run.stderr
        (env["store"] / "testsite.crt").write_text(run.stdout)
    env.update(config=site_config, cid=cid, root=server.root,
               logfile=server.logfile, expected={})
    return env

@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """Add the recent server logs to the report of a failed test using
    the site fixture."""
    outcome = yield
    report = outcome.get_result()
    site = getattr(item, "funcargs", {}).get("site")
    if report.when != "call" or not report.failed or site is None:
        return
    if site["logfile"] is None:
        cmd = ["podman", "logs", "--tail", "100", site["cid"]]
        title = "container log"
    else:
        cmd = ["podman", "exec", site["cid"],
               "tail", "-n", "100", site["logfile"]]
        title = site["logfile"]
    run = subprocess.run(cmd, capture_output=True, text=True)
    report.sections.append(("server: " + title, run.stdout + run.stderr))
