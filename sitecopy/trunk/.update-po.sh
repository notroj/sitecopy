#!/bin/sh
inmk=/usr/share/gettext/po/Makefile.in.in
tmpmk=`mktemp /tmp/sitecopy.XXXXXX`
pot=`mktemp /tmp/sitecopy.XXXXXX`

cd po

lngs=`echo *.po | sed "s/.po//g"`
for l in $lngs; do
    CATALOGS="$CATALOGS $l.gmo"
    POFILES="$POFILES $l.po"
done
GMOFILES="$CATALOGS"

sed -e "/^#/d" -e "/^[ 	]*\$/d" -e "s,.*,     ../& \\\\," \
    -e "\$s/\(.*\) \\\\/\1/" < POTFILES.in > $pot

sed -e "/POTFILES =/r $pot" \
    -e "s/@SET_MAKE@//g" \
    -e "s/@PACKAGE@/sitecopy/g" \
    -e "s/@VERSION@/$1/g" \
    -e "/^.*VPATH.*$/d" \
    -e "s/@srcdir@/./g" -e "s/@top_srcdir@/../g" \
    -e "s/@CATALOGS@/$CATALOGS/g" -e "s/@POFILES@/$POFILES/g" \
    -e "s/@GMOFILES@/$GMOFILES/g" \
    -e "s/@GMSGFMT@/msgfmt/g" -e "s/@MSGFMT@/msgfmt/g" \
    -e "s/@XGETTEXT@/xgettext/g" \
    -e "s/: Makefile/:/g" \
    -e "s/\$(MAKE) update-gmo/echo Done/g" \
$inmk > $tmpmk

make -f $tmpmk update-po update-gmo

rm -f $pot $tmpmk
