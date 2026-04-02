import sys

from .knowledge.loaders import snippet_classifier as _impl

sys.modules[__name__] = _impl
