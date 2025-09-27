dnl   This file is free software; you can redistribute it and/or
dnl   modify it under the terms of the GNU Library General Public
dnl   License as published by the Free Software Foundation; either
dnl   version 2 of the License, or (at your option) any later version.

dnl   This library is distributed in the hope that it will be useful,
dnl   but WITHOUT ANY WARRANTY; without even the implied warranty of
dnl   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
dnl   Library General Public License for more details.

dnl  You should have received a copy of the GNU Library General Public License
dnl   along with this library; see the file COPYING.LIB.  If not, write to
dnl   the Free Software Foundation, Inc., 59 Temple Place - Suite 330,
dnl   Boston, MA 02111-1307, USA.        

dnl This configure script is:
dnl  Copyright (C) 2000-2008 Joe Orton (joe@manyfish.co.uk)
dnl Portions are:
dnl  Copyright (C) 1994, 1995, 1996, 1997, 1998 Free Software Foundation, Inc.
dnl  Copyright (C) 1997 Janos Farkas (chexum@shadow.banki.hu)
dnl

dnl Extract the version (sans LF) from .version, created at release-time.
m4_define(sc_version, m4_translit(m4_include(.version), [
]))

AC_INIT([sitecopy], [sc_version], [https://github.com/notroj/sitecopy],,[https://www.manyfish.uk/sitecopy/])

AC_CONFIG_SRCDIR(src/sites.c)
AC_CONFIG_HEADER(config.h)

EXTRAOBJS=""
proto_msg=""
top_builddir=`pwd`
PACKAGE=sitecopy

AC_DEFINE([_GNU_SOURCE], [1], [Always defined])

NEON_WITH_LIBS

dnl Optional features

AC_ARG_ENABLE(ftp,
 AC_HELP_STRING([--disable-ftp], [disable FTP support]),,
 [enable_ftp=yes])
AC_ARG_ENABLE(webdav,
 AC_HELP_STRING([--disable-webdav], [disable WebDAV support]),,
 [enable_webdav=yes])
AC_ARG_ENABLE(rsh,
 AC_HELP_STRING([--disable-rsh], [disable rsh/rcp support]),,
 [enable_rsh=yes])

dnl Check for programs

AC_PROG_CC
AC_PROG_MAKE_SET
AC_ISC_POSIX
AC_PROG_INSTALL
AC_LANG_C
AC_C_INLINE
AC_C_CONST

AC_HEADER_STDC

AC_EXEEXT

if test "$enable_ftp" = "yes"; then
	EXTRAOBJS="$EXTRAOBJS src/ftp.o src/ftpdriver.o"
	proto_msg="FTP"
	AC_DEFINE(USE_FTP, 1, [Define to compile the FTP protocol driver])
fi

if test "$enable_webdav" = "yes"; then
    # Add the required DAV objects to NEONOBJS
    proto_msg="WebDAV ${proto_msg}"
    EXTRAOBJS="$EXTRAOBJS src/davdriver.o"
    AC_DEFINE(USE_DAV, 1, [Define to compile the WebDAV protocol driver])
fi

# XML parser support is always required
NEON_NEED_XML_PARSER=yes

if test "$enable_rsh" = "yes"; then
    EXTRAOBJS="$EXTRAOBJS src/rshdriver.o"
    proto_msg="rsh/rcp ${proto_msg}"
    AC_DEFINE(USE_RSH, 1, [Define to compile the rsh/rcp protocol driver])
fi

AC_ARG_ENABLE(sftp,
 AC_HELP_STRING([--disable-sftp], [disable sftp/ssh support]),,
 [enable_sftp=no
  AC_CHECK_FUNCS([socketpair pipe], [enable_sftp=yes; break])
 ])

if test "$enable_sftp" = "yes"; then
    EXTRAOBJS="$EXTRAOBJS src/sftpdriver.o"
    proto_msg="sftp/ssh ${proto_msg}"
    AC_DEFINE([USE_SFTP], 1, [Define to compile the sftp/ssh protocol driver])
fi

NEON_DEBUG()

dnl Check for library functions

AC_CACHE_CHECK([for GNU fnmatch], [sc_cv_gnu_fnmatch], [
AC_COMPILE_IFELSE([AC_LANG_PROGRAM([[#include <fnmatch.h>]], [[int flags = FNM_LEADING_DIR;]])], 
[sc_cv_gnu_fnmatch=yes], [sc_cv_gnu_fnmatch=no])])

if test "$sc_cv_gnu_fnmatch" = "no"; then
   AC_LIBOBJ(lib/fnmatch)
fi

# Support neon 0.24 through 0.29
dnl NE_REQUIRE_VERSIONS([0], [30 31 32])

dnl Build neon
NEON_LIBRARY

dnl Check for getopt_long
AC_CHECK_FUNC(getopt_long,,[AC_LIBOBJ(lib/getopt)
AC_LIBOBJ(lib/getopt1)])

dnl Check for strcasecmp
AC_CHECK_FUNC(strcasecmp,,[AC_LIBOBJ(lib/strcasecmp)])

dnl Check for stuff
AC_CHECK_FUNCS(strdup strsignal strerror memcpy setlocale nl_langinfo)

AC_TYPE_SIGNAL

AC_CHECK_HEADERS(stdarg.h string.h strings.h sys/time.h regex.h \
	locale.h langinfo.h stdlib.h unistd.h limits.h sys/select.h fcntl.h)

AX_TYPE_SOCKLEN_T

XGETTEXT_EXTRA_OPTIONS=--from-code=UTF-8

AM_GNU_GETTEXT_VERSION([0.22.5])
AM_GNU_GETTEXT([external])

BUILD_INCLUDED_LIBINTL=no
AC_SUBST(BUILD_INCLUDED_LIBINTL)

if test "$USE_NLS" = "yes"; then
    if test "$USE_INCLUDED_LIBINTL" = "yes"; then
	nls_msg="Built using included libintl"
        CPPFLAGS="$CPPFLAGS -I\$(top_builddir)/intl"
    else
	nls_msg="Built using native support"
    fi
else
    nls_msg="Not built"
fi

NEON_WARNINGS

dnl --------------------------------
dnl FE configuration
dnl --------------------------------

# Console front end
EXTRAOBJS="$EXTRAOBJS src/console_fe.o"
AC_LIBOBJ(lib/rpmatch)
AC_LIBOBJ(lib/yesno)

# This goes in CPPFLAGS so libneon/Makefile can pick up config.h
CPPFLAGS="$CPPFLAGS -I\$(top_builddir)"

dnl Makefile substitutions

AC_SUBST(EXTRAOBJS)

AC_CONFIG_FILES([Makefile po/Makefile.in])

AC_OUTPUT

AC_MSG_NOTICE([Configured sitecopy $PACKAGE_VERSION:

  Install prefix:        ${prefix}
  Compiler:              ${CC}
  Supported protocols:   ${proto_msg}
  neon library:          ${neon_library_message}
  XML Parser:            ${neon_xml_parser_message}
  SSL library:		 ${ne_SSL_message}
  Internationalization:  ${nls_msg}
])


# Create all the necessary directories for VPATH builds.
for i in src intl lib/expat lib/expat/xmltok lib/expat/gennmtab \
         lib/expat/xmlparse; do
  test -d $i || mkdir $i
done
