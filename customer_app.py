"""Compatibility launcher for the supported Qt customer application.

The project previously carried a second command-line CRUD implementation here.
That implementation did not understand the encrypted customer fields and could
silently write plaintext into the production database.  Keeping this module as
a launcher preserves old shortcuts without maintaining two database stacks.
"""

from customer_ui_qt import main


if __name__ == "__main__":
    raise SystemExit(main())
