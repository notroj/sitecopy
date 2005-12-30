/* 
   sitecopy, for managing remote web sites. file_set_* calls.
   Copyright (C) 1999-2005, Joe Orton <joe@manyfish.co.uk>
                                                                     
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

#ifdef HAVE_STRING_H
#include <string.h>
#endif

#ifdef HAVE_STDDEF_H
#include <stddef.h>
#endif

#include <ne_alloc.h>
#include <ne_utils.h>

#include "basename.h"
#include "common.h"
#include "sitesi.h"

/* Inserts a file into the files list, position chosen by type.  Must
 * be in critical section on calling. file_set_* ensure this. */
static struct site_file *
file_insert(enum file_type type, struct site *site) 
{
    struct site_file *file;
    file = ne_calloc(sizeof(struct site_file));
    if (site->files == NULL) {
	/* Empty list */
	site->files = file;
	site->files_tail = file;
    } else if (type == file_dir) {
	/* Append file */
	site->files_tail->next = file;
	file->prev = site->files_tail;
	site->files_tail = file;
    } else {
	/* Prepend file */
	site->files->prev = file;
	file->next = site->files;
	site->files = file;
    }
    return file;
}

#define FS_ALPHA(f) ((struct file_state *) (((char *)(f)) + alpha_off))
#define FS_BETA(f) ((struct file_state *) (((char *)(f)) + beta_off))

/* file_set implementation, used to update the files list.
 *
 * file_set takes a file type 'type', a file state 'state', the site,
 * two structure offsets, alpha_off and beta_off, and a default diff
 * type, 'default_diff'.  alpha_off represents the offset into a
 * site_file structure for the state which 'state' represents;
 * beta_off represents the offset into the structure for the state
 * against which this state should be compared.
 */
static struct site_file *file_set(enum file_type type, struct file_state *state, 
                                  struct site *site,
                                  size_t alpha_off, size_t beta_off,
                                  enum file_diff default_diff)
{
    struct site_file *file, *direct = NULL, *moved = NULL, *frename = NULL;
    enum file_diff dir_diff;
    char *bname = NULL; /* init to shut up gcc */

    if (site->checkmoved && type == file_file) {
	bname = base_name(state->filename);
    }

    for (file = site->files; file; file = file->next) {
        struct file_state *beta = FS_BETA(file);

	if (beta->exists && direct == NULL
            && file->type == type
            && strcmp(beta->filename, state->filename) == 0) {
	    /* Direct match found! */
	    NE_DEBUG(DEBUG_FILES, "Direct match found.\n");
	    direct = file;
	} 
        /* If this is not a direct match, check for a move/rename candidate,
         * unless the file already has a complete state and diff is unchanged. */
        else if (site->checkmoved 
                 && type == file_file && file->type == file_file
                 && file->diff != file_unchanged
                 && file_compare(file_file, state, 
                                 beta, site) == file_moved) {
	    /* TODO: There is a slight fuzz here - if checkrenames is true, 
	     * we'll always match the first 'direct move' candidate as a 
	     * 'rename move'. This shouldn't matter, since we prefer
	     * the move to the rename in the single candidate case,
	     * and in the multiple candidate case. */
	    if (!moved 
                && strcmp(bname, base_name(beta->filename)) == 0) {
		NE_DEBUG(DEBUG_FILES, "Move candidate: %s\n", 
                         beta->filename);
		moved = file;
	    } else if (site->checkrenames && frename == NULL) {
		NE_DEBUG(DEBUG_FILES, "Rename move candidate: %s\n", 
                         beta->filename);
		frename = file;
	    }
	}

        /* If all candidates are found, stop looking. */
	if (direct && moved && frename) {
            break;
        }
    }
    NE_DEBUG(DEBUG_FILES, "Found: %s-%s-%s\n", 
	  direct?"direct":"", moved?"moved":"", frename?"rename":"");
    /* We prefer a direct move to a rename */
    if (moved == NULL) moved = frename;
    if (direct != NULL) {
	dir_diff = file_compare(type, state, FS_BETA(direct), site);
	NE_DEBUG(DEBUG_FILES, "Direct compare: %s\n", 
	      DEBUG_GIVE_DIFF(dir_diff));
    } else {
	dir_diff = default_diff;
    }

    /* We prefer a move to a CHANGED direct match. */
    if ((direct == NULL && moved == NULL)
        || (direct != NULL && direct->diff == file_moved
            && moved == NULL && dir_diff != file_unchanged)) {
	NE_DEBUG(DEBUG_FILES, "Creating new file.\n");
	file = file_insert(type, site);
	file->type = type;
	file->diff = default_diff;
	if (type == file_file) {
	    file->ignore = file_isignored(state->filename, site);
	}
    } else {
	/* Overwrite file case...
	 * Again, we still prefer a move to a direct match */
	if (moved != NULL && dir_diff != file_unchanged) {
	    NE_DEBUG(DEBUG_FILES, "Using moved file.\n");
	    file = moved;
	    site_stats_decrease(file, site);
	    file->diff = file_moved;
	} else {
	    NE_DEBUG(DEBUG_FILES, "Using direct match.\n");
	    file = direct;
	    site_stats_decrease(file, site);
	    file->diff = dir_diff;
	}

	if (FS_ALPHA(file)->exists) {
	    /* SHOVE! */
	    struct site_file *other;
	    NE_DEBUG(DEBUG_FILES, "Shoving file:\n");
	    other = file_insert(file->type, site);
	    other->type = file->type;
	    other->diff = default_diff;
	    other->ignore = file->ignore;
	    /* Copy over the stored state for the moved file. */
	    memcpy(FS_ALPHA(other), FS_ALPHA(file), sizeof(struct file_state));
	    DEBUG_DUMP_FILE_PROPS(DEBUG_FILES, file, site);
	    site_stats_increase(other, site);
	}
    }

    /* Finish up - write over the new state */
    memcpy(FS_ALPHA(file), state, sizeof(struct file_state));

    /* And update the stats */
    site_stats_increase(file, site);
    site_stats_update(site);

    return file;
}


#ifndef offsetof
#define offsetof(t, m) ((size_t) (((char *)&(((t *)NULL)->m)) - (char *)NULL))
#endif

struct site_file *file_set_local(enum file_type type, struct file_state *state, 
                                 struct site *site)
{
    return file_set(type, state, site,
                    offsetof(struct site_file, local),
                    offsetof(struct site_file, stored),
                    file_new);
}

struct site_file *file_set_stored(enum file_type type, struct file_state *state, 
                                  struct site *site)
{
    return file_set(type, state, site,
                    offsetof(struct site_file, stored),
                    offsetof(struct site_file, local),
                    file_deleted);
}
