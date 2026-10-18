"""SEGAN: Sound Effect Grammar And Notation."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__: str = version("segan")
except PackageNotFoundError:  # running from a source tree without installing
    __version__ = "0.0.0+unknown"
