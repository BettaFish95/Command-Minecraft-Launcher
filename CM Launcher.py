#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CM Launcher 入口。"""
from __future__ import annotations

import os
import sys

if getattr(sys, "frozen", False):
    _BASE = os.path.dirname(os.path.abspath(sys.executable))
else:
    _BASE = os.path.dirname(os.path.abspath(__file__))
if _BASE not in sys.path:
    sys.path.insert(0, _BASE)

from mc_launcher.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
