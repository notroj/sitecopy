import pytest
import os
import socket
import subprocess
import time

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

@pytest.fixture
def sitecopy_ftp_env(tmp_path):
    return make_sitecopy_env(tmp_path, """\
  port 2121
  remote /home/sitecopy/site/
  protocol ftp
  username sitecopy
  password sitecopy
""")

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

@pytest.fixture
def httpd_container(tmp_path):
    cid = run_container("sitecopy-test-httpd", ["8080:80"], 8080)

    yield {"port": 8080, "cid": cid, "root": "/var/www/html/dav"}

    subprocess.run(["podman", "kill", cid], capture_output=True)

@pytest.fixture
def vsftpd_container(tmp_path):
    cid = run_container("sitecopy-test-vsftpd",
                        ["2121:21", "21100-21109:21100-21109"], 2121)

    yield {"port": 2121, "cid": cid, "root": "/home/sitecopy/site"}

    subprocess.run(["podman", "kill", cid], capture_output=True)
