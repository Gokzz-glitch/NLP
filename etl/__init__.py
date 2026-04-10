"""ETL package entrypoint.

Keep imports lightweight so submodules like `spatial_database_init` can be
loaded without pulling optional PDF/OCR dependencies into the import path.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

__version__ = "0.1.0"

if TYPE_CHECKING:
  from .pipeline import ETLPipeline as ETLPipeline


def __getattr__(name: str):
  if name == "ETLPipeline":
    from .pipeline import ETLPipeline

    return ETLPipeline
  raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["ETLPipeline"]
