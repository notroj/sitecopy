#!/bin/sh -ex
rm -rf config.cache autom4te*.cache
test -f .version || echo -n 0.0.0 > .version
mkdir -p m4/neon
curl -s 'https://raw.githubusercontent.com/notroj/neon/master/macros/neon.m4' > m4/neon/neon.m4
curl -s 'https://git.savannah.gnu.org/gitweb/?p=autoconf-archive.git;a=blob_plain;f=m4/ax_type_socklen_t.m4' > m4/neon/socklen.m4
${ACLOCAL:-aclocal} -I m4/neon
${AUTOHEADER:-autoheader}
${AUTOCONF:-autoconf}
