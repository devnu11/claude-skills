"""Top-level code."""

import logging

LIMIT = 3
logger = logging.getLogger(__name__)  # expect: global-scope fail
for item in range(LIMIT):
    print(item)


def main():
    """Entry."""


main()
