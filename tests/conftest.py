"""Offline regressions must never start automatic blocklist downloads.

Adblock-specific tests enable it explicitly and supply frozen/local responses.
"""
import os

os.environ.setdefault('DETHROTTLED_ADBLOCK', '0')
