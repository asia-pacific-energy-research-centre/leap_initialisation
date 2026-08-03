"""Developer-linked and portable distribution of the LEAP review tools.

Two supported ways to run the same code:

* **Developer mode** (:mod:`developer_launcher`) runs against the maintainer's
  live ``leap_initialisation`` / ``leap_mappings`` / ``leap_dashboard`` working
  copies, resolved from one explicit local settings file. Local edits take
  effect on the next run; there is no build step.
* **Portable release mode** (:mod:`build_release`, :mod:`portable_main`) is a
  versioned Windows folder built from an exact set of repository commits, for
  colleagues with no Python, Conda, Git, or repository checkouts.

Both modes execute the same command implementations in :mod:`commands`, write
the same run manifest, and apply the same input validation. The only difference
is where the source modules and configuration are resolved from.
"""

from __future__ import annotations

__all__ = ["RELEASE_PACKAGE_NAME"]

#: Name of the packaged application. Used for the package folder, the frozen
#: executable, and the developer-mode settings directory.
RELEASE_PACKAGE_NAME = "leap-review-tools"
