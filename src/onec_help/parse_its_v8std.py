import sys

from .knowledge.loaders import parse_its_v8std as _impl

sys.modules[__name__] = _impl
