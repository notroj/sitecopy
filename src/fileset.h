
/* This is a hack. It requires all of the below to be defined:
 *
 * FS_NAME:   The name of the function.
 * FS_UV:     A string giving the name of the function, for debugging.
 * FS_ALPHA:  The "alpha" state name.
 * FS_BETA:   The "beta" state name.
 * FS_LONELY: The file_diff to be used for lonely (unmatched) files.
 *
 * Could maybe be implemented properly if we have states in an array,
 * and pass alpha and beta state names as indexes into the
 * arrray. Then, each of the above can be passed as parameters.  */

#if !defined(FS_NAME) || !defined(FS_UV) || !defined(FS_ALPHA) || !defined(FS_BETA) || !defined(FS_LONELY)
#error including fileset.h
#endif

/* was file_set_local/stored.
 * This function is the most complex code in sitecopy.
 * Long hard thought has gone into getting this right.
 * (And it's still wrong, of course. The correct solution is to use
 * a hash table or two.) 
 */

struct site_file * FS_NAME (enum file_type type, struct file_state *state, 
			    struct site *site)
{
    struct site_file *file, *direct = NULL, *moved = NULL, *frename = NULL;
    enum file_diff dir_diff;
    char *bname = NULL; /* init to shut up gcc */
    NE_DEBUG(DEBUG_FILES, FS_UV " on %s: \n", state->filename);
    if (site->checkmoved && (type==file_file)) 
	bname = base_name(state->filename);
    for (file=site->files; file!=NULL; file=file->next) {
	/* TODO: profile and reorder these checks for best case. */
	if (file->FS_BETA.exists && 
	    (direct == NULL) &&
	    (file->type == type) && 
	    (strcmp(file->FS_BETA.filename, state->filename) == 0)) {
	    /* Direct match found! */
	    NE_DEBUG(DEBUG_FILES, "Direct match found.\n");
	    direct = file;
	} else if (site->checkmoved && 	/* Check for moved files... */
		   (type == file_file) && 
		   (file->type == file_file) && 
		   (file_compare(file_file, state, &file->FS_BETA, site)
		    == file_moved)) {
	    /* TODO: There is a slight fuzz here - if checkrenames is true, 
	     * we'll always match the first 'direct move' candidate as a 
	     * 'rename move'. This shouldn't matter, since we prefer
	     * the move to the rename in the single candidate case,
	     * and in the multiple candidate case,  */
	    if ((moved == NULL) && 
	       strcmp(bname, base_name(file->FS_BETA.filename)) == 0) {
		NE_DEBUG(DEBUG_FILES, "Move candidate: %s\n", 
		      file->FS_BETA.filename);
		moved = file;
	    } else if (site->checkrenames && frename == NULL) {
		NE_DEBUG(DEBUG_FILES, "Rename move candidate: %s\n", 
		      file->FS_BETA.filename);
		frename = file;
	    }
	}
	/* Stop searching if we've found all we need */
	if (direct!=NULL && moved!=NULL && frename!=NULL) break;
    }
    NE_DEBUG(DEBUG_FILES, "Found: %s-%s-%s\n", 
	  direct?"direct":"", moved?"moved":"", frename?"rename":"");
    /* We prefer a direct move to a rename */
    if (moved == NULL) moved = frename;
    if (direct != NULL) {
	dir_diff = file_compare(type, state, &direct->FS_BETA, site);
	NE_DEBUG(DEBUG_FILES, "Direct compare: %s\n", 
	      DEBUG_GIVE_DIFF(dir_diff));
    } else {
	dir_diff = FS_LONELY;
    }

    /* Enter the critical section: we are about to modify the files
     * list. */
    site_enter(site);

    /* We prefer a move to a CHANGED direct match. */
    if ((direct==NULL && moved==NULL) ||
	(direct!=NULL && direct->diff == file_moved &&
	 moved==NULL && dir_diff != file_unchanged)) {
	NE_DEBUG(DEBUG_FILES, "Creating new file.\n");
	file = file_insert(type, site);
	file->type = type;
	file->diff = FS_LONELY;
	if (type == file_file) {
	    file->ignore = file_isignored(state->filename, site);
	}
    } else {
	/* Overwrite file case...
	 * Again, we still prefer a move to a direct match */
	if (moved!=NULL && dir_diff!=file_unchanged) {
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
	if (file->FS_ALPHA.exists) {
	    /* SHOVE! */
	    struct site_file *other;
	    NE_DEBUG(DEBUG_FILES, "Shoving file:\n");
	    other = file_insert(file->type, site);
	    other->type = file->type;
	    other->diff = FS_LONELY;
	    other->ignore = file->ignore;
	    /* Copy over the stored state for the moved file. */
	    memcpy(&other->FS_ALPHA, &file->FS_ALPHA, sizeof(struct file_state));
	    DEBUG_DUMP_FILE_PROPS(DEBUG_FILES, file, site);
	    site_stats_increase(other, site);
	}
    }
    /* Finish up - write over the new state */
    memcpy(&file->FS_ALPHA, state, sizeof(struct file_state));
    /* And update the stats */
    site_stats_increase(file, site);
    site_stats_update(site);
    site_leave(site);
    return file;
}
