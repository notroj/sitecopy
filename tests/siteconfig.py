"""Site configurations used to parametrize the server tests.

Each axis is a set of alternative values for some rcfile option(s);
every value maps an ID to the rcfile lines it adds to the site.  A
test declares which axes it is run over with the `axes' marker, and
runs once per valid combination of values across those axes, for
each protocol (see pytest_generate_tests in conftest.py).
"""

import itertools

class Axis:
    def __init__(self, values, protocols=None, always=False):
        # values: dict mapping value ID -> tuple of rcfile lines
        self.values = values
        # protocols: set of protocols the axis applies to, or None
        # for all protocols.
        self.protocols = protocols
        # always: whether the axis applies to every test, whether or
        # not the test names it.
        self.always = always

    def applies_to(self, protocol):
        return self.protocols is None or protocol in self.protocols

AXES = {
    "ftp": Axis({
        "pasv": (),
        "usecwd": ("ftp usecwd",),
    }, protocols={"ftp"}, always=True),
    "state": Axis({
        "timesize": (),
        "checksum": ("state checksum",),
    }),
    "moves": Axis({
        "nomoves": (),
        "checkmoved": ("checkmoved",),
        "renames": ("checkmoved renames",),
    }),
    "delete": Axis({
        "delete": (),
        "nodelete": ("nodelete",),
    }),
    "overwrite": Axis({
        "overwrite": (),
        "nooverwrite": ("nooverwrite",),
    }),
    "safe": Axis({
        "nosafe": (),
        "safe": ("safe",),
    }),
    "tempupload": Axis({
        "direct": (),
        "tempupload": ("tempupload",),
    }),
    "lowercase": Axis({
        "case": (),
        "lowercase": ("lowercase",),
    }),
    "symlinks": Axis({
        "follow": (),
        "ignore": ("symlinks ignore",),
    }),
    "permissions": Axis({
        "noperms": (),
        "exec": ("permissions exec",),
        "all": ("permissions all",),
        "alldir": ("permissions all", "permissions dir"),
    }),
}

# rcfile lines which are only valid in combination with another.
REQUIRES = {
    "checkmoved renames": "state checksum",
}

# Pairs of rcfile lines which are rejected in combination
# (rcfile_verify in src/rcfile.c).
CONFLICTS = [
    ("safe", "nooverwrite"),
    ("safe", "tempupload"),
]

# rcfile lines which are only valid for some protocols.
PROTOCOL_ONLY = {
    "permissions all": {"ftp"},
    "permissions dir": {"ftp"},
}

class SiteConfig:
    """A protocol plus a combination of rcfile option lines."""

    def __init__(self, protocol, value_ids, lines):
        self.protocol = protocol
        self.id = "-".join((protocol,) + value_ids)
        self.lines = lines

    def __contains__(self, line):
        return line in self.lines

    def rcfile(self):
        return "".join("  %s\n" % line for line in self.lines)

    def __repr__(self):
        return "SiteConfig(%s)" % self.id

def is_valid(protocol, lines):
    """Returns whether the given combination of rcfile lines is
    accepted by sitecopy for a site using the given protocol."""
    return (all(REQUIRES[line] in lines
                for line in lines if line in REQUIRES)
            and not any(a in lines and b in lines for a, b in CONFLICTS)
            and all(protocol in PROTOCOL_ONLY[line]
                    for line in lines if line in PROTOCOL_ONLY))

def site_configs(protocol, axis_names, extra_lines=()):
    """Yield each valid SiteConfig for the given protocol, combining
    every value of each named axis which applies to the protocol,
    plus the axes which always apply, plus the given extra lines."""
    names = [name for name, axis in AXES.items()
             if (axis.always or name in axis_names)
             and axis.applies_to(protocol)]
    unknown = set(axis_names) - set(AXES)
    if unknown:
        raise ValueError("unknown axes: %s" % ", ".join(sorted(unknown)))

    for combo in itertools.product(*(AXES[name].values.items()
                                     for name in names)):
        ids = tuple(value_id for value_id, _ in combo)
        lines = tuple(line for _, value_lines in combo
                      for line in value_lines) + tuple(extra_lines)
        if is_valid(protocol, lines):
            yield SiteConfig(protocol, ids, lines)
