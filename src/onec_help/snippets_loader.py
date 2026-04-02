import sys

from .knowledge.loaders import snippets_loader as _impl

sys.modules[__name__] = _impl
