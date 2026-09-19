"""Tests for sitecopy's FTP driver against a scripted FTP server.

Debian bug #496988: the initial `--fetch' of a site fails when any
file has a leading space in its name (e.g. " 2003.doc"), since the
unix-style LIST parser mishandles such lines.

These tests run a minimal scripted FTP server (just enough of the
protocol for a --fetch: greeting, USER/PASS, PASV, LIST over a data
connection, MDTM and QUIT) so the whole fetch path is exercised
locally.
"""

import os
import socket
import threading

import pytest

from common import run_sitecopy

HOST = "127.0.0.1"
PORT_RANGE = range(22070, 22080)

# Files which "exist" on the scripted server.  Note the leading space
# in " 2003.doc".
REMOTE_FILES = {
    "index.html": {"size": 15360, "mtime": "20030828220517"},
    " 2003.doc": {"size": 2048, "mtime": "20030828220517"},
}


def _listing():
    """Render the unix-style LIST response for the site root.

    A leading space in a filename shows up as a doubled column
    separator after the year field.
    """
    lines = [
        "total 4",
        "drwxr-xr-x   2 ftp  ftp    4096 Aug 28 22:05 .",
        "drwxr-xr-x   2 ftp  ftp    4096 Aug 28 22:05 ..",
    ]
    for name, info in REMOTE_FILES.items():
        lines.append("-rw-r--r--   1 ftp  ftp  %5d Aug 28  2003 %s"
                     % (info["size"], name))
    return "".join(line + "\r\n" for line in lines)


def _bind_port():
    for port in PORT_RANGE:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((HOST, port))
            return s, port
        except OSError:
            continue
    raise RuntimeError("no free port in range %s" % PORT_RANGE)


class ScriptedFTPServer:
    """Minimal FTP server with a canned listing, serving one connection
    at a time.  Commands starting with a key of the failing dict get
    its value as their reply."""

    def __init__(self):
        self.commands = []
        self.failing = {}
        self.listener, self.port = _bind_port()
        self.listener.listen(1)
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self):
        while True:
            try:
                conn, _ = self.listener.accept()
            except OSError:
                return
            with conn:
                self._session(conn)

    def _session(self, conn):
        f = conn.makefile("rwb", buffering=0)
        self._reply(f, "220 scripted FTP server ready")
        while True:
            line = f.readline()
            if not line:
                break
            cmd = line.decode("utf-8", "replace").strip()
            self.commands.append(cmd)
            upper = cmd.upper()
            failure = [reply for prefix, reply in self.failing.items()
                       if upper.startswith(prefix)]
            if failure:
                self._reply(f, failure[0])
            elif upper.startswith("USER"):
                self._reply(f, "331 password required")
            elif upper.startswith("PASS"):
                self._reply(f, "230 logged in")
            elif upper.startswith("PASV"):
                self._pasv(f)
            elif upper.startswith("EPSV"):
                self._epsv(f)
            elif upper.startswith("PORT"):
                self._port(f, cmd)
            elif upper.startswith("LIST"):
                self._list(f)
            elif upper.startswith("MDTM"):
                self._mdtm(f, cmd)
            elif upper.startswith("QUIT"):
                self._reply(f, "221 goodbye")
                break
            else:
                # SYST, TYPE, PWD, CWD, FEAT, NOOP, ...
                self._reply(f, "200 OK")

    @staticmethod
    def _reply(f, text):
        f.write((text + "\r\n").encode("ascii"))

    def _pasv(self, f):
        data_sock, data_port = _bind_port()
        data_sock.listen(1)
        self._reply(f, "227 Entering Passive Mode (%s,%d,%d)" %
                    (HOST.replace(".", ","), data_port >> 8, data_port & 0xff))
        self._data_listener = data_sock

    def _epsv(self, f):
        data_sock, data_port = _bind_port()
        data_sock.listen(1)
        self._reply(f, "229 Entering Extended Passive Mode (|||%d|)" % data_port)
        self._data_listener = data_sock

    def _port(self, f, cmd):
        # Active mode: connect to the address given in the PORT
        # command once a transfer command is received.
        h1, h2, h3, h4, p1, p2 = cmd[5:].split(",")
        self._data_listener = None
        self._data_address = ("%s.%s.%s.%s" % (h1, h2, h3, h4),
                              int(p1) * 256 + int(p2))
        self._reply(f, "200 PORT command successful")

    def _data_connection(self):
        if self._data_listener is None:
            return socket.create_connection(self._data_address)
        data_conn, _ = self._data_listener.accept()
        self._data_listener.close()
        return data_conn

    def _list(self, f):
        self._reply(f, "150 Opening data connection")
        data_conn = self._data_connection()
        with data_conn:
            data_conn.sendall(_listing().encode("ascii"))
        self._reply(f, "226 Transfer complete")

    @staticmethod
    def _mdtm(f, cmd):
        # cmd is like "MDTM / 2003.doc": the filename may have a
        # leading space, and may or may not be preceded by a path.
        name = cmd[4:].strip().lstrip("/")
        if name in REMOTE_FILES:
            ScriptedFTPServer._reply(f, "213 " + REMOTE_FILES[name]["mtime"])
        else:
            ScriptedFTPServer._reply(f, "550 File not found")

    def stop(self):
        # Shutting down the listener wakes the thread from accept().
        try:
            self.listener.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.listener.close()
        self.thread.join(timeout=5)


@pytest.fixture
def ftp_site(tmp_path):
    local_dir = tmp_path / "local"
    store_dir = tmp_path / "storage"
    local_dir.mkdir()
    store_dir.mkdir()

    server = ScriptedFTPServer()

    config_file = tmp_path / ".sitecopyrc"
    config_file.write_text(f"""
site testsite
  server {HOST}
    port {server.port}
  remote /
  local {local_dir}
  protocol ftp
  username test
  password test
""")
    os.chmod(config_file, 0o600)
    os.chmod(store_dir, 0o700)

    yield {
        "rcfile": config_file,
        "local": local_dir,
        "store": store_dir,
        "port": server.port,
        "server": server,
    }

    server.stop()


def test_fetch_leading_space_filename(ftp_site):
    # The initial fetch of a site containing a file with a leading
    # space in its name (" 2003.doc") must succeed, and the file must
    # be recorded under its real name.  (#496988)
    res = run_sitecopy(ftp_site, ["--fetch", "testsite"])
    assert res.returncode == 0, res.stdout + res.stderr
    assert "File: index.html - size 15360" in res.stdout
    assert "File:  2003.doc - size 2048" in res.stdout


def test_fetch_normal_filename(ftp_site):
    REMOTE_FILES.pop(" 2003.doc")
    try:
        res = run_sitecopy(ftp_site, ["--fetch", "testsite"])
        assert res.returncode == 0, res.stdout + res.stderr
        assert "File: index.html - size 15360" in res.stdout
    finally:
        REMOTE_FILES[" 2003.doc"] = {"size": 2048, "mtime": "20030828220517"}


def test_long_netrc_password(ftp_site, tmp_path):
    # A password from ~/.netrc longer than the FE_LBUFSIZ (256 byte)
    # buffer used to be strcpy'd into it, overflowing the buffer and
    # corrupting the password sent.
    rcfile = ftp_site["rcfile"]
    rcfile.write_text(rcfile.read_text().replace("  password test\n", ""))
    password = "p" * 300
    netrc = tmp_path / ".netrc"
    netrc.write_text(f"machine {HOST} login test password {password}\n")
    os.chmod(netrc, 0o600)
    env = dict(os.environ, HOME=str(tmp_path))
    res = run_sitecopy(ftp_site, ["--fetch", "testsite"], env=env)
    assert res.returncode == 0, res.stdout + res.stderr
    assert "PASS " + password in ftp_site["server"].commands


def test_fetch_active_mode(ftp_site):
    # A fetch using an active mode (PORT) data connection.
    with open(ftp_site["rcfile"], "a") as fp:
        fp.write("  ftp nopasv\n")
    res = run_sitecopy(ftp_site, ["--fetch", "testsite"])
    assert res.returncode == 0, res.stdout + res.stderr
    assert "File: index.html - size 15360" in res.stdout
    assert any(cmd.startswith("PORT 127,0,0,1,")
               for cmd in ftp_site["server"].commands)


def test_fetch_long_filename(ftp_site):
    # FTP commands were formatted into a 1024-byte buffer, so a
    # command for a long filename was silently truncated, naming a
    # different file.
    name = "long" * 300
    REMOTE_FILES[name] = {"size": 42, "mtime": "20030828220517"}
    try:
        res = run_sitecopy(ftp_site, ["--fetch", "testsite"])
        assert res.returncode == 0, res.stdout + res.stderr
        assert "File: %s - size 42" % name in res.stdout
        assert "MDTM /" + name in ftp_site["server"].commands
    finally:
        del REMOTE_FILES[name]


@pytest.mark.xfail(strict=True, reason="a directory whose permissions "
                   "can't be set is created again by each update")
def test_dirperms_failure(ftp_site):
    # A directory is created, but setting its permissions fails.  The
    # next update sets its permissions, and doesn't create it again.
    with open(ftp_site["rcfile"], "a") as fp:
        fp.write("  permissions dir\n")
    (ftp_site["local"] / "dir").mkdir()
    res = run_sitecopy(ftp_site, ["--init", "testsite"])
    assert res.returncode == 0, res.stdout + res.stderr
    server = ftp_site["server"]
    server.failing["SITE CHMOD"] = "550 Permission denied"
    res = run_sitecopy(ftp_site, ["--update", "testsite"])
    assert res.returncode != 0, res.stdout + res.stderr
    assert "MKD /dir" in server.commands

    del server.failing["SITE CHMOD"]
    server.commands.clear()
    res = run_sitecopy(ftp_site, ["--update", "testsite"])
    assert res.returncode == 0, res.stdout + res.stderr
    assert not any(cmd.startswith("MKD") for cmd in server.commands)
    assert any(cmd.startswith("SITE CHMOD") for cmd in server.commands)
