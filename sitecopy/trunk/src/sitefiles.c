/* 
   sitecopy, for managing remote web sites. File handling.
   Copyright (C) 1998-2004, Joe Orton <joe@manyfish.co.uk>
                                                                     
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

#include <config.h>

#include <sys/types.h>

/* Needed for S_IXUSR */
#include <sys/stat.h>

#ifdef HAVE_STDLIB_H
#include <stdlib.h>
#endif
#ifdef HAVE_UNISTD_H
#include <unistd.h>
#endif
#ifdef HAVE_STRING_H
#include <string.h>
#endif

#include <ctype.h>

#include "basename.h"

#include <ne_md5.h>
#include <ne_string.h>
#include <ne_alloc.h>

/* We pick up FNM_LEADING_DIR fnmatch() extension, since we define
 * _GNU_SOURCE in config.h. */
#include <fnmatch.h>

#include "frontend.h"
#include "sitesi.h"
					     
/* fnmatch the filename against list */
inline int fnlist_match(const char *filename, const struct fnlist *list);

/* Deletes the given file from the given site */
void file_delete(struct site *site, struct site_file *item) 
{
    site_enter(site);
    site_stats_decrease(item, site);
    site_stats_update(site);
    if (item->prev) {
	/* Not first in list */
	item->prev->next = item->next;
    } else {
	/* Not last in list */
	site->files = item->next;
    }
    if (item->next) {
	/* Not last in list */
	item->next->prev = item->prev;
    } else {
	/* Last in list */
	site->files_tail = item->prev;
    }
    site_leave(site);

    /* Now really destroy the file */
    file_state_destroy(&item->local);
    file_state_destroy(&item->stored);
    file_state_destroy(&item->server);
    free(item);
}

/* Prepends  an item to the fnlist. Returns the item. */
struct fnlist *fnlist_prepend(struct fnlist **list)
{
    struct fnlist *item = ne_malloc(sizeof(struct fnlist));
    item->next = *list;
    item->prev = NULL;
    if (*list != NULL) {
	(*list)->prev = item;
    }
    *list = item;
    return item;
}

/* Returns a deep copy of the given fnlist */
struct fnlist *fnlist_deep_copy(const struct fnlist *src)
{
    const struct fnlist *iter;
    struct fnlist *dest = NULL, *prev = NULL, *item = NULL;
    for (iter = src; iter != NULL; iter = iter->next) {
	item = ne_malloc(sizeof(struct fnlist));
	item->pattern = ne_strdup(iter->pattern);
	item->haspath = iter->haspath;
	if (prev != NULL) {
	    prev->next = item;
	} else {
	    /* First item in list */
	    dest = item;
	}
	item->prev = prev;
	item->next = NULL;
	prev = item;
    }
    return dest;
}

/* Performs fnmatch() of all the strings in the given string list again
 * the given filename. Returns true if a pattern matches, else false. */
inline int fnlist_match(const char *filename, const struct fnlist *list)
{
    const struct fnlist *item;
    char *bname = base_name(filename);    

    for (item=list; item != NULL; item=item->next) {
	NE_DEBUG(DEBUG_FILES, "%s ", item->pattern);
	if (item->haspath) {
	    if (fnmatch(item->pattern, filename, 
			 FNM_PATHNAME | FNM_LEADING_DIR) == 0)
		break;
	} else {
	    if (fnmatch(item->pattern, bname, 0) == 0)
		break;
	}
    }
	
#ifdef DEBUGGING
    if (item) {
	NE_DEBUG(DEBUG_FILES, "- matched.\n");
    } else if (list) {
	NE_DEBUG(DEBUG_FILES, "\n");
    } else {
	NE_DEBUG(DEBUG_FILES, "(none)\n");
    }
#endif /* DEBUGGING */

    return (item!=NULL);
}

/* Returns whether the given filename is excluded from the
 * given site */
int file_isexcluded(const char *filename, struct site *site)
{
    NE_DEBUG(DEBUG_FILES, "Matching excludes for %s:\n", filename);
    return fnlist_match(filename, site->excludes);
}

int file_isignored(const char *filename, struct site *site)
{
    NE_DEBUG(DEBUG_FILES, "Matching ignores for %s:\n", filename);
    return fnlist_match(filename, site->ignores);
}

int file_isascii(char *filename, struct site *site)
{
    NE_DEBUG(DEBUG_FILES, "Matching asciis for %s:\n", filename);
    return fnlist_match(filename, site->asciis);
}

void site_stats_update(struct site *site)
{
    NE_DEBUG(DEBUG_FILES, 
	  "Stats: moved=%d new=%d %sdeleted=%d%s changed=%d"
	  " ignored=%d unchanged=%d\n",
	  site->nummoved, site->numnew, site->nodelete?"[":"",
	  site->numdeleted, site->nodelete?"]":"", site->numchanged,
	  site->numignored, site->numunchanged);
    site->remote_is_different = (site->nummoved + site->numnew +
				 (site->nodelete?0:site->numdeleted) + 
				 site->numchanged) > 0;
    site->local_is_different = (site->nummoved + site->numnew +
				site->numdeleted + site->numchanged + 
				site->numignored) > 0;
    NE_DEBUG(DEBUG_FILES, "Remote: %s  Local: %s\n", 
	  site->remote_is_different?"yes":"no", 
	  site->local_is_different?"yes":"no");
}

void file_set_diff(struct site_file *file, struct site *site) 
{
    site_enter(site);
    site_stats_decrease(file, site);
    file->diff = file_compare(file->type, &file->local, &file->stored, site);
    site_stats_increase(file, site);
    site_stats_update(site);
    site_leave(site);
}

void file_state_copy(struct file_state *dest, const struct file_state *src,
                     struct site *site)
{
    site_enter(site);
    file_state_destroy(dest);
    memcpy(dest, src, sizeof(struct file_state));
    if (src->linktarget != NULL) {
	dest->linktarget = ne_strdup(src->linktarget);
    }
    if (src->filename != NULL) {
	dest->filename = ne_strdup(src->filename);
    }
    site_leave(site);
}

void file_state_destroy(struct file_state *state)
{
    if (state->linktarget != NULL) {
	free(state->linktarget);
	state->linktarget = NULL;
    }
    if (state->filename != NULL) {
	free(state->filename);
	state->filename = NULL;
    }
}

/* Checksum the file.
 * We pass the site atm, since it's likely we will add different
 * methods of checksumming later on, with better-faster-happier
 * algorithms.
 * Returns:
 *  0 on success
 *  non-zero on error (e.g., couldn't open file)
 */
int file_checksum(const char *fname, struct file_state *state, struct site *s)
{
    int ret;
    FILE *f;
    f = fopen(fname, "r" FOPEN_BINARY_FLAGS);
    if (f == NULL) {
	return -1;
    }
    ret = ne_md5_stream(f, state->checksum);
    fclose(f); /* worth checking return value? */
#ifdef DEBUGGING
    { 
	char tmp[33] = {0};
	ne_md5_to_ascii(state->checksum, tmp);
	NE_DEBUG(DEBUG_FILES, "Checksum: %s = [%32s]\n", fname, tmp);
    }
#endif /* DEBUGGING */
    return ret;
}    

char *file_full_remote(struct file_state *state, struct site *site)
{
    char *ret;
    ret = ne_malloc(strlen(site->remote_root) + strlen(state->filename) + 1);
    strcpy(ret, site->remote_root);
    if (site->lowercase) {
	int n, off, len;
	/* Write the remote filename in lower case */
	off = strlen(site->remote_root);
	len = strlen(state->filename) + 1; /* +1 for \0 */
	for (n = 0; n < len; n++) {
	    ret[off+n] = tolower(state->filename[n]);
	}
    } else {
	strcat(ret, state->filename);
    }
    return ret;
}

char *file_full_local(struct file_state *state, struct site *site)
{
    return ne_concat(site->local_root, state->filename, NULL);
}

char *file_name(const struct site_file *file)
{
    if (file->diff == file_deleted) {
	return file->stored.filename;
    } else {
	return file->local.filename;
    }
}

/* Returns whether the file "contents" have changed or not.
 * TODO: better name needed. */
int file_contents_changed(struct site_file *file, struct site *site)
{
    int ret = false;
    if (site->state_method == state_checksum) {
	if (memcmp(file->stored.checksum, file->local.checksum, 16))
	    ret = true;
    } else {
	if (file->stored.size != file->local.size ||
	    file->stored.time != file->local.time) 
	    ret = true;
    }
    if (file->stored.ascii != file->local.ascii)
	ret = true;
    return ret;
}

/* Return true if the permission of the given file need changing.  */
int file_perms_changed(struct site_file *file, struct site *site)
{
    /* Slightly obscure boolean here...
     *  If ('permissions all' OR ('permissions exec' and file is chmod u+x)
     *     AND
     *     EITHER (in tempupload mode or nooverwrite mode)
     *         OR the stored file perms are different from the local ones
     *         OR the file doesn't exist locally or remotely,
     *
     * Note that in tempupload and nooverwrite mode, we are
     * creating a new file, so the permissions on the new file
     * will always be "wrong".
     */
    if (((site->perms == sitep_all) || 
	 (((file->local.mode | file->stored.mode) & S_IXUSR) && 
	  (site->perms == sitep_exec))) &&
	(site->tempupload || site->nooverwrite ||
	 file->local.mode != file->stored.mode || 
	 file->local.exists != file->stored.exists)) {
	return true;
    } else {
	return false;
    }
}

void file_uploaded(struct site_file *file, struct site *site)
{
    site_enter(site);
    file->stored.size = file->local.size;
    if (site->state_method == state_checksum) {
	memcpy(file->stored.checksum, file->local.checksum, 16);
    } else {
	file->stored.time = file->local.time;
    }
    /* Now the filename */
    if (file->stored.filename) free(file->stored.filename);
    file->stored.filename = ne_strdup(file->local.filename);
    file->stored.ascii = file->local.ascii;
    file->stored.exists = file->local.exists;
    file->stored.mode = file->local.mode;
    /* Update the diff */
    file_set_diff(file, site);
    site_leave(site);
}
    
void file_downloaded(struct site_file *file, struct site *site)
{
    site_enter(site);
    file->local.size = file->stored.size;
    if (site->state_method == state_checksum) {
	memcpy(file->local.checksum, file->stored.checksum, 16);
    } else {
	file->local.time = file->stored.time;
    }
    /* Now the filename */
    if (file->local.filename) free(file->local.filename);
    file->local.filename = ne_strdup(file->stored.filename);
    file->local.ascii = file->stored.ascii;
    file->local.exists = file->stored.exists;
    file->local.mode = file->stored.mode;
    file_set_diff(file, site);
    site_leave(site);
}
