import pytest
import os
import subprocess
import time

@pytest.fixture
def sitecopy_env(tmp_path):
    # Setup directories
    local_dir = tmp_path / "local"
    store_dir = tmp_path / "storage"
    local_dir.mkdir()
    store_dir.mkdir()

    # Create a dummy config file
    config_file = tmp_path / ".sitecopyrc"
    config_content = f"""
site testsite
  server localhost
    port 8080
  remote /dav/
  local {local_dir}
  protocol dav
"""
    config_file.write_text(config_content)
    os.chmod(config_file, 0o600)
    os.chmod(store_dir, 0o700)

    return {
        "rcfile": config_file,
        "local": local_dir,
        "store": store_dir,
    }

@pytest.fixture
def httpd_container(tmp_path):
    # Setup containers
    remote_dir = tmp_path / "remote-root"
    remote_dir.mkdir()

    cmd = ["podman", "run", "-p", "8080:80", "-d", "sitecopy-test-httpd"]
    run = subprocess.run(cmd, capture_output=True, text=True)
    assert run.returncode == 0
    cid = run.stdout.strip()

    time.sleep(1)

    yield {"port": 8080}

    subprocess.run(["podman", "kill", cid], capture_output=False)
    assert run.returncode == 0
