"""Offline regressions must never start automatic blocklist downloads.

Adblock-specific tests enable it explicitly and supply frozen/local responses.
"""
import os

os.environ.setdefault('DETHROTTLED_ADBLOCK', '0')
# Waymarks learn from reads; stubbed reads of example.com must not teach the
# record anything another test then acts on. Waymark tests enable it.
os.environ.setdefault('DETHROTTLED_WAYMARKS', '0')
# Same for engine yields: stub searches must not demote engines in later tests.
os.environ.setdefault('DETHROTTLED_ENGINE_POLICY', '0')
