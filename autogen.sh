#!/bin/sh
set -ex
rm -rf config.cache autom4te*.cache aclocal.m4

# configure.ac reads the version from .version, which is created at
# release-time by .release.sh; fake one up for a git checkout.
if test ! -f .version && test -e .git; then
    branch=`git rev-parse --abbrev-ref HEAD 2>/dev/null` || branch=
    if test -z "$branch" -o "$branch" = "HEAD"; then
        branch=`git rev-parse --short HEAD 2>/dev/null` || branch=
    fi
    echo "${branch:-unknown}" > .version
fi

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

