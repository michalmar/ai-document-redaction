"""Storage adapter package for local and Azure Blob storage.

Provides a StorageAdapter interface plus Local and Azure Blob implementations.
"""

from .base import StorageAdapter
from .local import LocalStorageAdapter
from .azure_blob import AzureBlobStorageAdapter

__all__ = [
    "StorageAdapter",
    "LocalStorageAdapter",
    "AzureBlobStorageAdapter",
]
