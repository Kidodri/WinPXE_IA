'''

This file contains helper functions used throughout the PyPXE services

'''

import os.path
import logging

class PathTraversalException(Exception):
    pass

def normalize_path(base, filename):
    abs_path = os.path.abspath(base)
    joined = os.path.join(abs_path, filename)
    normalized = os.path.normpath(joined)
    if normalized.startswith(os.path.join(abs_path, '')):
        return normalized
    raise PathTraversalException('Path Traversal detected')

def get_child_logger(logger, name):
    return logging.getLogger("{0}.{1}".format(logger.name, name))
