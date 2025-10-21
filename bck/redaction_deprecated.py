"""PII redaction utilities using Azure AI Language."""

import logging
from pathlib import Path
from dataclasses import dataclass
from typing import Tuple
from azure.core.credentials import AzureKeyCredential
from azure.ai.textanalytics.aio import TextAnalyticsClient

from .retry import retry_with_backoff

logger = logging.getLogger(__name__)


@dataclass
class RedactionConfig:
    """Configuration for PII redaction."""
    endpoint: str
    api_key: str
    language: str = "en"
    max_chunk_size: int = 5000
    
    def validate(self):
        """Validate configuration."""
        if not self.endpoint:
            raise ValueError("Azure Language endpoint is required")
        if not self.api_key:
            raise ValueError("Azure Language API key is required")


class RedactionFactory:
    """Factory for creating PII redaction client."""
    
    @staticmethod
    def create_client(config: RedactionConfig) -> TextAnalyticsClient:
        """
        Create and return a TextAnalyticsClient.
        
        Args:
            config: RedactionConfig with endpoint and API key
            
        Returns:
            TextAnalyticsClient instance
        """
        config.validate()
        return TextAnalyticsClient(
            endpoint=config.endpoint,
            credential=AzureKeyCredential(config.api_key)
        )


async def _redact_chunk_inner(
    chunk: str,
    client: TextAnalyticsClient,
    language: str
):
    """
    Inner function for PII redaction that can be retried.
    
    Args:
        chunk: Text chunk to redact
        client: TextAnalyticsClient instance
        language: Document language code
        
    Returns:
        PII recognition response
    """
    return await client.recognize_pii_entities([chunk], language=language)


async def redact_document(
    file_path: str,
    output_path: str,
    client: TextAnalyticsClient,
    language: str = "en",
    max_chunk_size: int = 5000
) -> Tuple[bool, int, str]:
    """
    Redact PII from a Markdown document with retry logic.
    
    Args:
        file_path: Path to input markdown
        output_path: Path to save redacted output
        client: TextAnalyticsClient instance
        language: Document language code
        max_chunk_size: Maximum characters per chunk
        
    Returns:
        Tuple of (success, entities_redacted, error_message)
    """
    try:
        logger.debug(f"Redacting: {file_path}")
        
        # Read document
        document_text = Path(file_path).read_text(encoding="utf-8")
        
        # Split into chunks if needed
        chunks = _split_into_chunks(document_text, max_chunk_size)
        
        # Process chunks with retry logic
        redacted_chunks = []
        total_entities = 0
        
        for chunk_idx, chunk in enumerate(chunks):
            success, response, error_msg = await retry_with_backoff(
                _redact_chunk_inner,
                chunk,
                client,
                language
            )
            
            if not success:
                logger.error(f"✗ Redaction failed for chunk {chunk_idx + 1}/{len(chunks)} "
                           f"in {Path(file_path).name} - {error_msg}")
                return False, 0, f"Chunk {chunk_idx + 1} failed: {error_msg}"
            
            docs = [doc for doc in response if not doc.is_error]
            
            if docs:
                doc = docs[0]
                redacted_chunks.append(doc.redacted_text)
                total_entities += len(doc.entities)
            else:
                # Handle document-level errors
                error_docs = [doc for doc in response if doc.is_error]
                if error_docs:
                    error_msg = f"Document error: {error_docs[0].error.message}"
                    logger.error(f"✗ Redaction failed for chunk {chunk_idx + 1}/{len(chunks)} "
                               f"in {Path(file_path).name} - {error_msg}")
                    return False, 0, error_msg
                # No error but no docs - use original chunk
                redacted_chunks.append(chunk)
        
        # Save redacted content
        redacted_content = "".join(redacted_chunks)
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_text(redacted_content, encoding="utf-8")
        
        logger.debug(f"✓ Redacted: {Path(file_path).name} ({total_entities} entities)")
        return True, total_entities, ""
        
    except Exception as e:
        logger.error(f"✗ Redaction failed: {Path(file_path).name} - {e}")
        return False, 0, str(e)


def _split_into_chunks(text: str, max_chars: int) -> list[str]:
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
