"""Azure Blob Storage adapter using Entra ID (DefaultAzureCredential).

This adapter is optimized for small files and uses in-memory transfers.
"""

import logging
import asyncio
from typing import Iterable, List
from azure.identity.aio import DefaultAzureCredential
from azure.storage.blob.aio import BlobServiceClient
from azure.core.exceptions import ResourceNotFoundError

from .base import StorageAdapter

logger = logging.getLogger(__name__)


class AzureBlobStorageAdapter(StorageAdapter):
    """Adapter for Azure Blob Storage.

    Args:
        account_url: Full account URL, e.g. https://{account}.blob.core.windows.net
        container: container name to use as root
        max_concurrency: Maximum concurrency for parallel operations
    """

    def __init__(self, account_url: str, container: str, max_concurrency: int = 4):
        self.account_url = account_url
        self.container_name = container
        self.credential = DefaultAzureCredential()
        self.client = BlobServiceClient(account_url=self.account_url, credential=self.credential)
        self.max_concurrency = max_concurrency

    async def _get_container_client(self):
        return self.client.get_container_client(self.container_name)

    async def list_files(self, prefix: str = "") -> Iterable[str]:
        container = await self._get_container_client()
        async with container:
            blob_list = container.list_blobs(name_starts_with=prefix)
            results: List[str] = []
            async for blob in blob_list:
                results.append(blob.name)
            return results

    async def read_bytes(self, path: str) -> bytes:
        container = await self._get_container_client()
        blob_client = container.get_blob_client(path)
        try:
            stream = await blob_client.download_blob()
            data = await stream.readall()
            return data
        except ResourceNotFoundError:
            raise FileNotFoundError(path)

    async def write_bytes(self, path: str, content: bytes) -> None:
        container = await self._get_container_client()
        blob_client = container.get_blob_client(path)
        await blob_client.upload_blob(content, overwrite=True, max_concurrency=self.max_concurrency)

    async def exists(self, path: str) -> bool:
        container = await self._get_container_client()
        blob_client = container.get_blob_client(path)
        try:
            await blob_client.get_blob_properties()
            return True
        except ResourceNotFoundError:
            return False

    async def delete(self, path: str) -> None:
        container = await self._get_container_client()
        blob_client = container.get_blob_client(path)
        try:
            await blob_client.delete_blob()
        except ResourceNotFoundError:
            pass

    async def makedirs(self, path: str) -> None:
        # No-op for blob storage
        return

    async def close(self):
        # Clean up credential and client
        try:
            await self.client.close()
        finally:
            await self.credential.close()
