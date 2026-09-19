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

    def __init__(self, image, ports, port, root, rcfile):
        self.image = image
        # Port specs published from the container.
        self.ports = ports
        # Port on which the server accepts connections.
        self.port = port
        # Directory holding the site on the server.
        self.root = root
        # rcfile lines configuring the site for this server.
        self.rcfile = rcfile

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
"""),
}

def pytest_configure(config):
    config.addinivalue_line(
        "markers", "axes(*names): run a test using the site fixture once "
        "for each valid combination of the named rcfile option axes "
        "(see siteconfig.py)")
    config.addinivalue_line(
        "markers", "protocol(name): run tests using the site fixture "
        "only against the server for the given protocol")
    config.addinivalue_line(
        "markers", "site_lines(*lines): add the given rcfile lines to "
        "every configuration of a test using the site fixture")

def pytest_generate_tests(metafunc):
    """Parametrize each test using the site fixture over every
    combination of the rcfile option axes it names, for the server
    named by its protocol marker (or every server, if none)."""
    if "site_config" not in metafunc.fixturenames:
        return
    marker = metafunc.definition.get_closest_marker("axes")
    axis_names = marker.args if marker else ()
    marker = metafunc.definition.get_closest_marker("protocol")
    protocols = marker.args if marker else SERVERS.keys()
    marker = metafunc.definition.get_closest_marker("site_lines")
    extra_lines = marker.args if marker else ()
    configs = [config for protocol in protocols
               for config in siteconfig.site_configs(protocol, axis_names,
                                                     extra_lines)]
    metafunc.parametrize("site_config", configs,
                         ids=[config.id for config in configs])

def run_container(image, ports, wait_port):
    """Run the given container image detached, publishing the given
    list of port specs, and wait until wait_port accepts connections.
    Returns the container ID."""
    cmd = ["podman", "run", "--rm", "-d"]
    for port in ports:
        cmd += ["-p", port]
    run = subprocess.run(cmd + [image], capture_output=True, text=True)
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
                                              server.port)
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
    cid = containers(site_config.protocol)

    run = podman_exec(cid, "find '%s' -mindepth 1 -delete" % server.root)
    assert run.returncode == 0, run.stderr

    env = make_sitecopy_env(tmp_path, server.rcfile + site_config.rcfile())
    env.update(config=site_config, cid=cid, root=server.root,
               expected={})
    return env
