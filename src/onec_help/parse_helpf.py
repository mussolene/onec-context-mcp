import sys

from .knowledge.loaders import parse_helpf as _impl

sys.modules[__name__] = _impl
