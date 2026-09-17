# sitecopy

[![Build and test](https://github.com/notroj/sitecopy/actions/workflows/ci.yml/badge.svg)](https://github.com/notroj/sitecopy/actions/workflows/ci.yml)

`sitecopy` maintains remote web sites. It uploads files which have
changed locally, and deletes files from the server which have been
removed locally, keeping the remote site synchronized with the local
copy in a single command. It can optionally spot files which have been
moved locally, and move them remotely rather than re-uploading them.

sitecopy does not care about what is actually on the remote server: it
keeps a record of what it *thinks* is on the remote server, and works
from that.

## Supported protocols

| Protocol | Notes |
| --- | --- |
| FTP | `--disable-ftp` to omit |
| WebDAV (HTTP/HTTPS) | `--disable-webdav` to omit |
| sftp/ssh | enabled where `socketpair()` or `pipe()` is available; `--disable-sftp` to omit |
| rsh/rcp | `--disable-rsh` to omit |

## Building

### Requirements

* A C compiler and `make`
* [neon](https://github.com/notroj/neon) 0.29 or later, or the bundled
  copy (git submodule) built in-tree
* An XML parser (expat or libxml2) for neon
* GNU gettext (for `autogen.sh` and translations)
* autoconf, automake's `aclocal`, and libtool — only when building from
  a git checkout

### From a release tarball

```sh
./configure
make
make install
```

### From a git checkout

The neon library is a git submodule, so clone recursively (or run
`git submodule update --init` in an existing clone):

```sh
git clone --recursive https://github.com/notroj/sitecopy.git
cd sitecopy
./autogen.sh
./configure --with-included-neon --with-ssl=openssl
make
```

To build against a neon installed on the system instead of the bundled
copy, use `--with-neon=/usr` (or the prefix where neon is installed).

### Useful configure options

| Option | Effect |
| --- | --- |
| `--prefix=DIR` | Installation prefix (default `/usr/local`) |
| `--with-neon=DIR` | Use the neon library installed under `DIR` |
| `--with-included-neon` | Build the bundled neon in-tree |
| `--with-ssl=openssl` | Enable SSL/TLS support in the bundled neon |
| `--disable-ftp`, `--disable-webdav`, `--disable-sftp`, `--disable-rsh` | Omit a protocol driver |
| `--disable-nls` | Disable translations |
| `--enable-warnings` | Enable compiler warnings (for development) |

`configure` prints a summary of the protocols, neon library, XML
parser, SSL library and NLS support it selected.

### Running the tests

The test suite is written in Python and driven by pytest; it uses
[podman](https://podman.io/) to run the servers it tests against:

```sh
make check
```

## Usage

See the man page — `man sitecopy`, or `doc/sitecopy.1` in the source
tree — for instructions on how to start using sitecopy.

## More information

* `NEWS` — changes in this release
* Web site: https://www.manyfish.uk/sitecopy/
* Github repository: https://github.com/notroj/sitecopy/
* Bug reports: https://github.com/notroj/sitecopy/issues

## Copyright and license

```
Copyright (C) 1998-2012, Joe Orton <joe@manyfish.co.uk>
Copyright (C) 2003, 2004, Nobuyuki Tsuchimura <tutimura@nn.iij4u.or.jp>
Copyright (C) 2004, David A Knight <david@screem.org>
```

This program is free software; you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation; either version 2 of the License, or (at
your option) any later version.

This program is distributed in the hope that it will be useful, but
WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program; if not, see <https://www.gnu.org/licenses/>.
