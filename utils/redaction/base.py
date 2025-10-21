"""Base classes for PII redaction strategies."""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Any

logger = logging.getLogger(__name__)


@dataclass
class RedactionResult:
    """
    Result of a redaction operation.
    
    Args:
        success: Whether redaction succeeded
        entities_redacted: Number of PII entities redacted
        error_message: Error message if failed
        metadata: Additional metadata (e.g., token usage, entity categories)
    """
    success: bool
    entities_redacted: int
    error_message: str = ""
    metadata: Dict[str, Any] | None = None


class RedactionStrategy(ABC):
    """Abstract base class for PII redaction strategies."""
    
    @abstractmethod
    async def redact_document(
        self,
        file_path: str,
        output_path: str
    ) -> RedactionResult:
        """
        Redact PII from a Markdown document.
        
        Args:
            file_path: Path to input markdown file
            output_path: Path to save redacted output
            
        Returns:
            RedactionResult with operation details
        """
        pass
    
    @abstractmethod
    async def close(self):
        """Close any open connections or clients."""
        pass
    
    async def __aenter__(self):
        """Async context manager entry."""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()


def split_into_chunks(text: str, max_chars: int) -> list[str]:
    """
    Split text into chunks respecting paragraph boundaries.
    
    Args:
        text: Text to split
        max_chars: Maximum characters per chunk
        
    Returns:
        List of text chunks
    """
    if len(text) <= max_chars:
        return [text]
    
    chunks = []
    paragraphs = text.split('\n\n')
    current_chunk = ""
    
    for para in paragraphs:
        if len(current_chunk) + len(para) + 2 <= max_chars:
            current_chunk += para + "\n\n"
        else:
            if current_chunk:
                chunks.append(current_chunk)
            current_chunk = para + "\n\n"
    
    if current_chunk:
        chunks.append(current_chunk)
    
    return chunks
