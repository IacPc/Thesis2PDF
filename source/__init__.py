"""thesis2pdf — Markdown to a Università di Pisa styled thesis PDF."""

from .builder import BuildError, ThesisBuilder, build

__all__ = ["build", "ThesisBuilder", "BuildError", "__version__"]
__version__ = "1.0.0"
