"""Public, patient-independent knowledge catalog. No network or record-store access."""

from .catalog import CatalogDenied, KnowledgeCatalog

__all__ = ["CatalogDenied", "KnowledgeCatalog"]
