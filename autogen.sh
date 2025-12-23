#!/bin/sh
set -ex
rm -rf config.cache autom4te*.cache aclocal.m4
INCLUDES="-I m4 -I neon/macros"

for d in /usr/share/gettext/m4; do
    if test -d "$d"; then
        INCLUDES="$INCLUDES -I ${d}"
    fi
done

${ACLOCAL:-aclocal} ${INCLUDES}
${AUTOHEADER:-autoheader}
${AUTOCONF:-autoconf}
${LIBTOOLIZE:-libtoolize} --copy --force >/dev/null
rm -rf autom4te*.cache

