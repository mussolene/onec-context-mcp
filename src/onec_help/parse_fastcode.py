import sys

from .knowledge.loaders import parse_fastcode as _impl

sys.modules[__name__] = _impl
