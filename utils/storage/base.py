"""Abstract storage adapter interface.

Defines common operations used by the pipeline so storage backends are interchangeable.
"""

from abc import ABC, abstractmethod
from typing import Iterable, Tuple


class StorageAdapter(ABC):
    """Abstract storage adapter interface."""

    @abstractmethod
    async def list_files(self, prefix: str = "") -> Iterable[str]:
        """List files under a given prefix/path.

        Returns a list of paths (strings) relative to the base root.
        """
        pass

    @abstractmethod
    async def read_bytes(self, path: str) -> bytes:
        """Read file content as bytes."""
        pass

    @abstractmethod
    async def write_bytes(self, path: str, content: bytes) -> None:
        """Write bytes to a path, creating parent folders as needed."""
        pass

    @abstractmethod
    async def exists(self, path: str) -> bool:
        """Return True if path exists."""
        pass

    @abstractmethod
    async def delete(self, path: str) -> None:
        """Delete a file at path (no-op if not present)."""
        pass

    @abstractmethod
    async def makedirs(self, path: str) -> None:
        """Ensure that a directory (prefix) exists. For blob storage this is a no-op."""
        pass
