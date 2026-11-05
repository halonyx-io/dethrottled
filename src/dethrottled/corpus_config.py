"""Validated bounds shared by corpus admission, indexing and maintenance."""

import os


def integer(name, default):
    return max(1, int(os.getenv("DETHROTTLED_CORPUS_" + name, str(default))))
