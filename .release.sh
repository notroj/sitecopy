#!/bin/sh
# Script used by maintainer when rolling a release tarball.

set -e

echo $1 > .version

# Generate docs for Xsitecopy
cd gnome/doc
db2html -o `pwd` xsitecopy.sgml
# Remove generated images dir
rm xsitecopy/stylesheet-images/*.gif
rmdir -p xsitecopy/stylesheet-images
