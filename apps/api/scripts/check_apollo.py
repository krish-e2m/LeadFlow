"""
LeadFlow - Apollo.io Deprecation Notice.
Apollo has been retired and replaced by Hunter.io as the primary B2B lead discovery
and enrichment provider.
Use scripts/check_hunter.py instead.
"""

import sys

# Windows consoles default to cp1252 and crash on symbols such as the star in ratings.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")


def main():
    print("=" * 65)
    print("  [DEPRECATED] Apollo.io provider has been retired in LeadFlow. ")
    print("  All active discovery, contact reveal, and company enrichment ")
    print("  have migrated to Hunter.io.                                   ")
    print("=" * 65)
    print("\nPlease run the Hunter.io smoke test instead:")
    print("    python scripts/check_hunter.py\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
