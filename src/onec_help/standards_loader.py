import sys

from .knowledge.loaders import standards_loader as _impl

sys.modules[__name__] = _impl
