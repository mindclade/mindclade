# Copyright (c) 2026 Mindclade. All rights reserved.
# Proprietary and confidential. Unauthorized use, copying, or distribution is prohibited.

import sys

import pytest


def main() -> int:
    if len(sys.argv) < 2:
        raise SystemExit("expected exactly one pytest test-file path")
    return pytest.main([sys.argv[1], *sys.argv[2:]])


if __name__ == "__main__":
    raise SystemExit(main())
