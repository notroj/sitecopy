#!/bin/bash -ex
# Release script run before generating a release tarball.
# Usage: ./.release.sh VERSION

echo $1 > .version

sed s/@VERSION@/$1/ < sitecopy.spec.in > sitecopy.spec

exec ./.update-po.sh
