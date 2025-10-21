"""Factory for creating storage adapters based on configuration."""

from typing import Dict
from .local import LocalStorageAdapter
from .azure_blob import AzureBlobStorageAdapter


def create_storage_adapter(config: Dict) -> object:
    """Create a storage adapter from a config dict.

    Config keys:
      - mode: 'local' or 'azure_blob'
      - root: local path root (for local)
      - account_url: Full account URL for blob storage
      - container: container name
      - max_concurrency: optional
    """
    mode = config.get("mode", "local")
    if mode == "azure_blob":
        return AzureBlobStorageAdapter(
            account_url=config["account_url"],
            container=config["container"],
            max_concurrency=config.get("max_concurrency", 4)
        )
    else:
        return LocalStorageAdapter(config.get("root", "."))
