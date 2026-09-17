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

# Install the gettext infrastructure (m4/*.m4, po/*) for the version
# given by AM_GNU_GETTEXT_VERSION, so that the macros used by aclocal
# and po/Makefile.in.in always come from the same gettext release.
${AUTOPOINT:-autopoint} --force

${ACLOCAL:-aclocal} -I m4 -I neon/macros
${AUTOHEADER:-autoheader}
${AUTOCONF:-autoconf}
${LIBTOOLIZE:-libtoolize} --copy --force >/dev/null
rm -rf autom4te*.cache

