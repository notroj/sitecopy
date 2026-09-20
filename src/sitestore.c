/* 
   sitecopy, for managing remote web sites. Stored state handling routines.
   Copyright (C) 1999-2006, Joe Orton <joe@manyfish.co.uk>
                                                                     
   This program is free software; you can redistribute it and/or modify
   it under the terms of the GNU General Public License as published by
   the Free Software Foundation; either version 2 of the License, or
   (at your option) any later version.
  
   This program is distributed in the hope that it will be useful,
   but WITHOUT ANY WARRANTY; without even the implied warranty of
   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
   GNU General Public License for more details.
  
   You should have received a copy of the GNU General Public License
   along with this program; if not, write to the Free Software
   Foundation, Inc., 675 Mass Ave, Cambridge, MA 02139, USA.

*/

#include "config.h"

#include <sys/stat.h>

#ifdef HAVE_UNISTD_H
#include <unistd.h>
#endif
#ifdef HAVE_STDLIB_H
#include <stdlib.h>
#endif
#ifdef HAVE_STRING_H
#include <string.h>
#endif

#ifdef HAVE_LIMITS_H
#include <limits.h>
#endif

#include <ctype.h>
#include <errno.h>
#include <fcntl.h>
#include <stdarg.h>
#include <stdio.h>
#include <unistd.h>

#include <ne_xml.h>
#include <ne_dates.h>
#include <ne_alloc.h>
#include <ne_string.h>

#include "i18n.h"
#include "common.h"
#include "sitesi.h"

/* Use a version in the site state file: 
 * Bump the major number if a backwardly-incompatible change is made.
 */
#define SITE_STATE_FILE_VERSION "1.0"

/* Used in stored.mode to indicate no mode known. */
#define INVALID_MODE ((mode_t)-1)

/* Set the error string of the site to the given message. */
static void set_error(struct site *site, const char *fmt, ...)
    ne_attribute((format (printf, 2, 3)));

static void set_error(struct site *site, const char *fmt, ...)
{
    char buf[512];
    va_list ap;

    va_start(ap, fmt);
    ne_vsnprintf(buf, sizeof buf, fmt, ap);
    va_end(ap);

    if (site->last_error)
        ne_free(site->last_error);
    site->last_error = ne_strdup(buf);
}

/* The lock file holds one "key value" pair per line, e.g.
 *
 *    pid 1234
 *
 * so that what is known about a lock can be extended later (a WebDAV
 * lock token, say).  Keys which are not recognized are ignored. */

/* Return the value of the given key in the lock file of the site,
 * ne_malloc-allocated, or NULL if the file has no such key. */
static char *read_lock_value(struct site *site, const char *key)
{
    size_t keylen = strlen(key);
    char *value = NULL;
    char line[256];
    FILE *fp;

    fp = fopen(site->infolock, "r");
    if (fp == NULL)
        return NULL;

    while (value == NULL && fgets(line, sizeof line, fp) != NULL) {
        ne_shave(line, "\r\n");
        if (strncmp(line, key, keylen) == 0 && line[keylen] == ' ')
            value = ne_strdup(line + keylen + 1);
    }

    fclose(fp);

    return value;
}

int site_lock_storage(struct site *site)
{
    char buf[64];
    size_t len;
    int fd;

    if (site->lock_fd != -1)
        return SITE_OK;

    fd = open(site->infolock, O_WRONLY | O_CREAT | O_EXCL, 0600);
    if (fd < 0) {
        if (errno == EEXIST) {
            char *pid = read_lock_value(site, "pid");

            if (pid != NULL) {
                set_error(site, _("Locked by process %s; if it is no "
                                  "longer running, remove `%s'."),
                          pid, site->infolock);
                ne_free(pid);
            }
            else {
                set_error(site, _("Locked; if no other sitecopy is "
                                  "running, remove `%s'."),
                          site->infolock);
            }
            return SITE_LOCKED;
        }

        set_error(site, _("Could not create lock file `%s': %s"),
                  site->infolock, strerror(errno));
        return SITE_FAILED;
    }

    /* Record the process holding the lock, for the message given to
     * whoever finds it. */
    len = ne_snprintf(buf, sizeof buf, "pid %ld\n", (long)getpid());
    if (write(fd, buf, len) < (ssize_t)len)
        NE_DEBUG(DEBUG_FILES, "store: could not write lock file: %s\n",
                 strerror(errno));

    site->lock_fd = fd;

    return SITE_OK;
}

void site_unlock_storage(struct site *site)
{
    if (site->lock_fd == -1)
        return;

    close(site->lock_fd);
    site->lock_fd = -1;
    if (unlink(site->infolock))
        NE_DEBUG(DEBUG_FILES, "store: could not remove lock file `%s': %s\n",
                 site->infolock, strerror(errno));
}

/* Opens the storage file for writing */
FILE *site_open_storage_file(struct site *site) 
{
    if (site->storage_file == NULL) {
        site->storage_file = fopen(site->infotemp, "w" FOPEN_BINARY_FLAGS);
    }
    return site->storage_file;
}

int site_close_storage_file(struct site *site)
{
    int ret = fclose(site->storage_file);
    if (!ret) {
        ret = rename(site->infotemp, site->infofile);
    }
    site->storage_file = NULL;
    /* The stored state is now written, so another process may have
     * the site. */
    site_unlock_storage(site);
    return ret;
}

/* Return escaped form of 'filename'; any XML-unsafe characters are
 * escaped. */
static char *fn_escape(const char *filename)
{
    const unsigned char *pnt = (const unsigned char *)filename;
    char *ret = ne_malloc(strlen(filename) * 3 + 1), *p = ret;

    do {
        if (!(isalnum(*pnt) || *pnt == '/' || *pnt == '.' || *pnt == '-') 
            || *pnt > 0x7f) {
            sprintf(p, "%%%02x", *pnt);
            p += 3;
        } else {
            *p++ = *(char *)pnt;
        }
    } while (*++pnt != '\0');

    *p = '\0';
    
    return ret;
}

/* Return unescaped filename; reverse of fn_escape. */
static char *fn_unescape(const char *filename)
{
    const unsigned char *pnt = (const unsigned char *)filename;
    char *ret = ne_malloc(strlen(filename) + 1), *p = ret;

    do {
        if (*pnt == '%') {
            *p = (NE_ASC2HEX(pnt[1]) << 4) & 0xf0;
            *p++ |= (NE_ASC2HEX(pnt[2]) & 0x0f);
            pnt += 2;
        } else {
            *p++ = *pnt;
        }
    } while (*++pnt != '\0');

    *p = '\0';

    return ret;
}

/* Write out the stored state for the site. 
 * Returns 0 on success, non-zero on error. */
int site_write_stored_state(struct site *site) 
{
    struct site_file *current, **sorted;
    unsigned i, num_items;
    FILE *fp;

    fp = site_open_storage_file(site);
    if (fp == NULL) {
	return -1;
    }

    sorted = site_sorted_files_list(site, site_file_is_stored,
                                    site_file_cmp_stored, &num_items);

    fprintf(fp, "<?xml version=\"1.0\" encoding=\"ISO-8859-1\"?>\n");
    fprintf(fp, "<sitestate version='" SITE_STATE_FILE_VERSION "'>\n");
    fprintf(fp, "<options>\n");
    fprintf(fp, " <saved-by package='" PACKAGE_NAME "'"
	    " version='" PACKAGE_VERSION "'/>\n");
    if (site->state_method == state_checksum) {
	/* For forwards-compatibility */
	fprintf(fp, " <checksum-algorithm><checksum-MD5/></checksum-algorithm>\n");
    }
    fprintf(fp, " <state-method><state-%s/></state-method>\n",
	     (site->state_method==state_checksum)?"checksum":"timesize");
    if (site->safemode) {
	fprintf(fp, " <safemode/>\n");
    }
    fprintf(fp, " <escaped-filenames/>\n");
    fprintf(fp, "</options>\n");
    fprintf(fp, "<items>\n");
    /* Now write out the items */
    for (i = 0; i < num_items; i++) {
	char *fname;
	current = sorted[i];
	fprintf(fp, "<item>");
	fprintf(fp, "<type><type-%s/></type>",
		 (current->type==file_file)?"file":(
		     (current->type==file_dir)?"directory":"link"));
        /* escape filenames correctly for XML. */
        fname = fn_escape(current->stored.filename);
	fprintf(fp, "<filename>%s</filename>\n", fname);
        ne_free(fname);
        if (current->stored.mode != INVALID_MODE) {
            fprintf(fp, "<protection>%03o</protection>", 
                    current->stored.mode); /* three-digit octal */
        }
	switch (current->type) {
	case file_link:
	    fprintf(fp, "<linktarget>%s</linktarget>", 
		     current->stored.linktarget);
	    break;
	case file_file:
	    fprintf(fp, "<size>%" NE_FMT_OFF_T "</size>", 
		    current->stored.size);
	    switch (site->state_method) {
	    case state_checksum: {
		char csum[33];
		ne_md5_to_ascii(current->stored.checksum, csum);
		fprintf(fp, "<checksum>%s</checksum>", csum);
	    } break;
	    case state_timesize:
		fprintf(fp, "<modtime>%ld</modtime>", current->stored.time);
		break;
	    }
	    fprintf(fp, "<ascii>%s</ascii>",
		     current->stored.ascii?"<true/>":"<false/>");
	    if (current->server.exists) {
		fprintf(fp, "<server-modtime>%ld</server-modtime>", 
			 current->server.time);
	    }
	    break;
	case file_dir:
	    /* nothing to do */
	    break;
	}
	fprintf(fp, "</item>\n");
    }
    fprintf(fp, "</items>\n");
    fprintf(fp, "</sitestate>\n");

    site->stored_state_method = site->state_method;
    ne_free(sorted);
    return site_close_storage_file(site);
}

/* neon ne_xml-based XML parsing */

#define ELM_BASE 500
#define SITE_ELM_sitestate (ELM_BASE + 1)
#define SITE_ELM_options (ELM_BASE + 2)
#define SITE_ELM_opt_saved_by (ELM_BASE + 3)
#define SITE_ELM_opt_checksum (ELM_BASE + 4)
#define SITE_ELM_opt_checksum_md5 (ELM_BASE + 5)
#define SITE_ELM_opt_state_method (ELM_BASE + 6)
#define SITE_ELM_opt_state_method_timesize (ELM_BASE + 7)
#define SITE_ELM_opt_state_method_checksum (ELM_BASE + 8)
#define SITE_ELM_items (ELM_BASE + 9)
#define SITE_ELM_item (ELM_BASE + 10)
#define SITE_ELM_type (ELM_BASE + 11)
#define SITE_ELM_type_file (ELM_BASE + 12)
#define SITE_ELM_type_directory (ELM_BASE + 13)
#define SITE_ELM_type_link (ELM_BASE + 14)
#define SITE_ELM_filename (ELM_BASE + 15)
#define SITE_ELM_size (ELM_BASE + 16)
#define SITE_ELM_modtime (ELM_BASE + 17)
#define SITE_ELM_ascii (ELM_BASE + 18)
#define SITE_ELM_linktarget (ELM_BASE + 19)
#define SITE_ELM_checksum (ELM_BASE + 20)
#define SITE_ELM_protection (ELM_BASE + 21)
#define SITE_ELM_server_modtime (ELM_BASE + 22)
#define SITE_ELM_true (ELM_BASE + 23)
#define SITE_ELM_false (ELM_BASE + 24)

static const struct ne_xml_idmap elmmap[] = {
    { "", "sitestate", SITE_ELM_sitestate },
    { "", "options", SITE_ELM_options },
    { "", "saved-by", SITE_ELM_opt_saved_by },
    { "", "checksum-algorithm", SITE_ELM_opt_checksum },
    { "", "checksum-MD5", SITE_ELM_opt_checksum_md5 },
    { "", "state-method", SITE_ELM_opt_state_method },
    { "", "state-timesize", SITE_ELM_opt_state_method_timesize },
    { "", "state-checksum", SITE_ELM_opt_state_method_checksum },
    { "", "items", SITE_ELM_items },
    { "", "item", SITE_ELM_item },
    { "", "type", SITE_ELM_type },
    { "", "type-file", SITE_ELM_type_file },
    { "", "type-directory", SITE_ELM_type_directory },
    { "", "type-link", SITE_ELM_type_link },
    { "", "filename", SITE_ELM_filename },
    { "", "size", SITE_ELM_size },
    { "", "modtime", SITE_ELM_modtime },
    { "", "ascii", SITE_ELM_ascii },
    { "", "linktarget", SITE_ELM_linktarget },
    { "", "checksum", SITE_ELM_checksum },
    { "", "protection", SITE_ELM_protection },
    { "", "server-modtime", SITE_ELM_server_modtime },
    { "", "true", SITE_ELM_true },
    { "", "false", SITE_ELM_false }
};

struct site_xmldoc {
    ne_xml_parser *parser;
    struct site *site;
    /* What we've collected so far */
    enum file_type type;
    struct file_state stored;
    struct file_state server;
    ne_buffer *cdata;
    unsigned int truth:2; /* 0: invalid, 1: true, 2: false */
};

static int start_element(void *userdata, int parent,
                         const char *nspace, const char *name,
                         const char **atts)
{
    int state = ne_xml_mapid(elmmap, NE_XML_MAPLEN(elmmap), nspace, name);
    struct site_xmldoc *doc = userdata;

    if (state)
        ne_buffer_clear(doc->cdata);

    if (state == SITE_ELM_item) {
        /* Clear current stored state */
        memset(&doc->stored, 0, sizeof doc->stored);
        /* Initialize perms bits to invalid state */
        doc->stored.mode = INVALID_MODE;
    }

    if (state == SITE_ELM_ascii) {
        doc->truth = 0;
    }

    return state;
}

static int char_data(void *userdata, int state, const char *cdata, size_t len)
{
    struct site_xmldoc *doc = userdata;
    ne_buffer_append(doc->cdata, cdata, len);
    return 0;
}

static int end_element(void *userdata, int state,
                       const char *nspace, const char *name) 
{
    struct site_xmldoc *doc = userdata;
    const char *cdata = doc->cdata->data;
    char err[512];

    /* Dispatch Ajax */
    switch (state) {
    case SITE_ELM_opt_state_method_timesize:
	doc->site->stored_state_method = state_timesize;
	break;
    case SITE_ELM_opt_state_method_checksum:
	doc->site->stored_state_method = state_checksum;
	break;
    case SITE_ELM_type_file:
	doc->type = file_file;
	break;
    case SITE_ELM_type_directory:
	doc->type = file_dir;
	break;
    case SITE_ELM_type_link:
	doc->type = file_link;
	break;
    case SITE_ELM_filename:
	doc->stored.filename = fn_unescape(cdata);
	break;
    case SITE_ELM_checksum:
	if (strlen(cdata) > 32) {
            ne_snprintf(err, sizeof err, _("Invalid checksum at line %d"),
                        ne_xml_currentline(doc->parser));
            ne_xml_set_error(doc->parser, err);
	    return -1;
	} else {
	    /* FIXME: validate */
	    ne_ascii_to_md5(cdata, doc->stored.checksum);
#ifdef DEBUGGING
	    {
		char tmp[33];
		ne_md5_to_ascii(doc->stored.checksum, tmp);
		NE_DEBUG(DEBUG_FILES, "Checksum recoded: [%32s]\n", tmp);
	    }
#endif /* DEBUGGING */
	}
	break;
    case SITE_ELM_size:
        errno = 0;
	doc->stored.size = sc_strtoff(cdata, NULL, 10);
        if (errno == ERANGE)
            goto overflow_err;
	break;
    case SITE_ELM_protection:
	doc->stored.mode = strtoul(cdata, NULL, 8);
	break;
    case SITE_ELM_server_modtime:
	doc->server.time = strtol(cdata, NULL, 10);
	if (doc->server.time == LONG_MIN || doc->server.time == LONG_MAX)
            goto overflow_err;
	doc->server.exists = true;
	break;
    case SITE_ELM_modtime:
	doc->stored.time = strtol(cdata, NULL, 10);
	if (doc->stored.time == LONG_MIN || doc->stored.time == LONG_MAX)
            goto overflow_err;
	break;
    case SITE_ELM_true:
	doc->truth = 1;
	break;
    case SITE_ELM_false:
	doc->truth = 2;
	break;
    case SITE_ELM_ascii:
	if (doc->truth) {
	    doc->stored.ascii = doc->truth == 1;
	} else {
            ne_snprintf(err, sizeof err, _("Boolean missing in 'ascii' "
                                           "at line %d"),
                        ne_xml_currentline(doc->parser));
            ne_xml_set_error(doc->parser, err);
	    return -1;
	}
	break;
    case SITE_ELM_linktarget:
	doc->stored.linktarget = ne_strdup(cdata);
	break;
    case SITE_ELM_item: {
	struct site_file *file;
	doc->stored.exists = true;
	file = file_set_stored(doc->type, &doc->stored, doc->site);
	if (doc->server.exists) {
	    file_state_copy(&file->server, &doc->server, doc->site);
	}
	DEBUG_DUMP_FILE_PROPS(DEBUG_FILES, file, doc->site);
    }	break;
    default:
	break;
    }

    return 0;
overflow_err:
    ne_snprintf(err, sizeof err, _("Size overflow (%s) in '%s' at line %d"),
                cdata, name, ne_xml_currentline(doc->parser));
    ne_xml_set_error(doc->parser, err);
    return -1;
}

/* Read a new XML-format state storage file */
static int parse_storage_file(struct site *site, FILE *fp)
{
    ne_xml_parser *p;
    struct site_xmldoc doc = {0};
    int ret;
    
    doc.site = site;
    doc.cdata = ne_buffer_create();

    doc.parser = p = ne_xml_create();
    ne_xml_push_handler(p, start_element, char_data, end_element, &doc);
    
    ret = 0;
    do {
	char buffer[BUFSIZ];
	int len;	
	len = fread(buffer, 1, BUFSIZ, fp);
	if (len < BUFSIZ) {
	    if (feof(fp)) {
		ret = 1;
	    } else if (ferror(fp)) {
		ret = -1;
		/* And don't parse anything else... */
		break;
	    }
	}
	ne_xml_parse(p, buffer, len);
    } while (ret == 0 && !ne_xml_failed(p));

    if (!ne_xml_failed(p)) ne_xml_parse(p, "", 0);

    if (ne_xml_failed(p)) {
	site->last_error = ne_strdup(ne_xml_get_error(p));
	ret = SITE_ERRORS;
    } else if (ret < 0) {
	site->last_error = ne_strdup(strerror(errno));
	ret = SITE_ERRORS;
    }

    ne_xml_destroy(p);
    
    return ret;    
}

int site_read_stored_state(struct site *site)
{
    FILE *fp;
    int ret;

    NE_DEBUG(DEBUG_FILES, "Reading info file: %s\n", site->infofile);
    fp = fopen(site->infofile, "r");
    if (fp == NULL) {
	struct stat st;
        site->last_error = ne_strdup(strerror(errno));
	ret = stat(site->infofile, &st);
	if ((ret == 0) || (errno != ENOENT)) {
	    /* The file exists but could not be opened for reading...
	     * this is an error condition. */
	    NE_DEBUG(DEBUG_FILES, "Stat failed %s\n", strerror(errno));
	    return SITE_ERRORS;
	} else {
	    NE_DEBUG(DEBUG_FILES, "Info file doesn't exist.\n");
	    return SITE_FAILED;
	}
    }
    ret = parse_storage_file(site, fp);
    fclose(fp);
    return ret;
}

