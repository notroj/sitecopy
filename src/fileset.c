/* 
   sitecopy, for managing remote web sites. file_set_* calls.
   Copyright (C) 1999-2004, Joe Orton <joe@manyfish.co.uk>
                                                                     
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

/* This is a Hack.
 * A Hack which makes a bad situation slightly better.
 * But, nonetheless, it is a hack.
 *
 * Sometime in the future, we need to make state handling more generic.
 * For now, we have two functions, file_set_local and file_set_stored,
 * which are essentially the same other than a few minor details.
 */

#define FS_NAME file_set_local
#define FS_UV "set_local"
#define FS_ALPHA local
#define FS_BETA stored
#define FS_LONELY file_new

#include "fileset.h"

#undef FS_NAME
#undef FS_UV
#undef FS_ALPHA
#undef FS_BETA
#undef FS_LONELY

#define FS_NAME file_set_stored
#define FS_UV "set_stored"
#define FS_ALPHA stored
#define FS_BETA local
#define FS_LONELY file_deleted

#include "fileset.h"

