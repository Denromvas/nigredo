#!/usr/bin/env python3
"""Запускач Nigredo: імпортує інтерпретатор як модуль, тож Python кешує його байткод і не компілює 2,4 тис. рядків
на кожен запуск. `python3 interpreter/nigredo.py …` працює так само, лише повільніше стартує."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import nigredo  # noqa: E402

sys.exit(nigredo.entry())
