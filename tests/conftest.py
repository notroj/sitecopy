import pytest
import os
import subprocess

@pytest.fixture
def sitecopy_env(tmp_path):
    # Setup directories
    local_dir = tmp_path / "local"
    remote_dir = tmp_path / "remote"
    store_dir = tmp_path / "storage"
    local_dir.mkdir()
    remote_dir.mkdir()
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
        "remote": remote_dir,
        "store": store_dir,
    }
