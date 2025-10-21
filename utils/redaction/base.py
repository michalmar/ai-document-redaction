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

    chunks: list[str] = []
    paragraphs = text.split('\n\n')
    current_chunk = ""

    def _append_current():
        nonlocal current_chunk
        if current_chunk:
            chunks.append(current_chunk)
            current_chunk = ""

    for para in paragraphs:
        # Normalize paragraph endings
        para = para.rstrip()

        # If paragraph itself is small enough, try to append to current chunk
        if len(para) + 2 <= max_chars:
            if len(current_chunk) + len(para) + 2 <= max_chars:
                current_chunk += para + "\n\n"
            else:
                _append_current()
                current_chunk = para + "\n\n"
        else:
            # Paragraph is larger than max_chars; flush current_chunk and split paragraph
            _append_current()

            start = 0
            para_len = len(para)
            while start < para_len:
                end = start + max_chars
                if end >= para_len:
                    sub = para[start:para_len]
                    start = para_len
                else:
                    # Try to split at the last whitespace before the end for nicer boundaries
                    split_pos = para.rfind(' ', start, end)
                    if split_pos <= start:
                        # no whitespace found, force split at end
                        split_pos = end
                    sub = para[start:split_pos]
                    # Advance start; skip any whitespace at the next position
                    # If we split at a space, skip it to avoid leading spaces
                    start = split_pos + 1 if split_pos < para_len and para[split_pos] == ' ' else split_pos

                # Preserve paragraph separation for each sub-chunk
                chunks.append(sub + "\n\n")

    # Append remaining current chunk
    _append_current()

    # Final safety: ensure no chunk exceeds max_chars; if it does, force-split
    final_chunks: list[str] = []
    for c in chunks:
        if len(c) <= max_chars:
            final_chunks.append(c)
        else:
            # Force-split long chunk by character slices while trying not to break lines
            s = c
            i = 0
            while i < len(s):
                part = s[i:i+max_chars]
                final_chunks.append(part)
                i += max_chars

    return final_chunks
