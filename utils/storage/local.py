"""Local filesystem storage adapter."""

import asyncio
from pathlib import Path
from typing import Iterable

from .base import StorageAdapter


class LocalStorageAdapter(StorageAdapter):
    """Adapter that reads/writes to the local filesystem."""

    def __init__(self, root: str):
        self.root = Path(root)

    async def list_files(self, prefix: str = "") -> Iterable[str]:
        base = (self.root / prefix) if prefix else self.root
        if not base.exists():
            return []
        return [str(p.relative_to(self.root)) for p in base.rglob("*") if p.is_file()]

    async def read_bytes(self, path: str) -> bytes:
        p = self.root / path
        return p.read_bytes()

    async def write_bytes(self, path: str, content: bytes) -> None:
        p = self.root / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content)

    async def exists(self, path: str) -> bool:
        return (self.root / path).exists()

    async def delete(self, path: str) -> None:
        p = self.root / path
        try:
            if p.exists():
                p.unlink()
        except FileNotFoundError:
            pass

    async def makedirs(self, path: str) -> None:
        (self.root / path).mkdir(parents=True, exist_ok=True)
