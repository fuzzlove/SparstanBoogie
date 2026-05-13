#!/usr/bin/env python3
"""Root entrypoint for The Sparstan Boogie."""

# WARNING:
# - Requires Python 3.12 to run correctly.
# - Incorrect usage can cause a system bootloop.
# - Use with extreme caution and make a full system backup first.

import os
import runpy


def main():
    red = "\033[31m"
    reset = "\033[0m"
    warning = f"{red}WARNING{reset}"
    print("=" * 72)
    print(f"{warning}: THIS TOOL REQUIRES PYTHON 3.12")
    print(f"{warning}: MISUSE CAN CAUSE A SYSTEM BOOTLOOP")
    print(f"{warning}: USE WITH CAUTION AND MAKE A FULL SYSTEM BACKUP FIRST")
    print("=" * 72)
    root = os.path.dirname(os.path.abspath(__file__))
    script = os.path.join(root, "bin", "sparse.py")
    runpy.run_path(script, run_name="__main__")


if __name__ == "__main__":
    main()
