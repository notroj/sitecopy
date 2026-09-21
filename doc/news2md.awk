#!/usr/bin/awk -f
# Extract the top-most entry from a NEWS file and convert to GitHub Flavoured Markdown.

BEGIN {
    "date +'%-d %B %Y'" | getline today
}

/^Changes in release / {
    found++          # second entry reached — stop
    match($0, /[0-9]+\.[0-9]+(\.[0-9]+)?/)
    ver     = substr($0, RSTART, RLENGTH)
    tarball = "sitecopy-" ver ".tar.gz"
    url     = tarball
    print "#### Changes in release " ver " ([" tarball "](" url ")), " today
    next
}

found && /^\* / {
    line = substr($0, 3)
    if (/:\s*$/) {             # ends with colon — section heading
        sub(/:$/, "", line)
        in_section = 1
        print "\n##### " line "\n"
    } else {                   # plain bullet item
        if (in_section) {
            in_section = 0
            print "\n##### Other changes\n"
        }
        print "- " line
    }
    next
}

found && /^ - / {              # bullet item
    line = substr($0, 4)
    print "- " line
    next
}

found && /^   / {              # continuation of previous bullet
    print "  " substr($0, 4)
    next
}
