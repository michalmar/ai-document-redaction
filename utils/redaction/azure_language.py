"""Azure AI Language PII redaction strategy."""

import logging
from pathlib import Path
from azure.core.credentials import AzureKeyCredential
from azure.ai.textanalytics.aio import TextAnalyticsClient

from .base import RedactionStrategy, RedactionResult, split_into_chunks
from .config import RedactionConfig
from ..retry import retry_with_backoff

logger = logging.getLogger(__name__)


class AzureLanguageStrategy(RedactionStrategy):
    """PII redaction using Azure AI Language service."""
    
    def __init__(self, config: RedactionConfig):
        """
        Initialize Azure Language strategy.
        
        Args:
            config: RedactionConfig with language_endpoint and language_api_key
        """
        self.config = config
        self.client = TextAnalyticsClient(
            endpoint=config.language_endpoint,
            credential=AzureKeyCredential(config.language_api_key)
        )
    
    async def redact_document(
        self,
        file_path: str,
        output_path: str
    ) -> RedactionResult:
        """
        Redact PII from a Markdown document using Azure AI Language.
        
        Args:
            file_path: Path to input markdown file
            output_path: Path to save redacted output
            
        Returns:
            RedactionResult with operation details
        """
        try:
            logger.debug(f"Redacting with Azure Language: {file_path}")
            
            # Read document
            document_text = Path(file_path).read_text(encoding="utf-8")
            
            # Split into chunks if needed
            chunks = split_into_chunks(document_text, self.config.max_chunk_size)
            
            # Process chunks with retry logic
            redacted_chunks = []
            total_entities = 0
            entity_categories = {}
            
            for chunk_idx, chunk in enumerate(chunks):
                success, response, error_msg = await retry_with_backoff(
                    self._redact_chunk_inner,
                    chunk,
                    self.client,
                    self.config.language
                )
                
                if not success:
                    logger.error(
                        f"✗ Redaction failed for chunk {chunk_idx + 1}/{len(chunks)} "
                        f"in {Path(file_path).name} - {error_msg}"
                    )
                    return RedactionResult(
                        success=False,
                        entities_redacted=0,
                        error_message=f"Chunk {chunk_idx + 1} failed: {error_msg}"
                    )
                
                docs = [doc for doc in response if not doc.is_error]
                
                if docs:
                    doc = docs[0]
                    redacted_chunks.append(doc.redacted_text)
                    total_entities += len(doc.entities)
                    
                    # Track entity categories
                    for entity in doc.entities:
                        category = entity.category
                        entity_categories[category] = entity_categories.get(category, 0) + 1
                else:
                    # Handle document-level errors
                    error_docs = [doc for doc in response if doc.is_error]
                    if error_docs:
                        error_msg = f"Document error: {error_docs[0].error.message}"
                        logger.error(
                            f"✗ Redaction failed for chunk {chunk_idx + 1}/{len(chunks)} "
                            f"in {Path(file_path).name} - {error_msg}"
                        )
                        return RedactionResult(
                            success=False,
                            entities_redacted=0,
                            error_message=error_msg
                        )
                    # No error but no docs - use original chunk
                    redacted_chunks.append(chunk)
            
            # Save redacted content
            redacted_content = "".join(redacted_chunks)
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            Path(output_path).write_text(redacted_content, encoding="utf-8")
            
            logger.debug(
                f"✓ Redacted: {Path(file_path).name} ({total_entities} entities, "
                f"categories: {entity_categories})"
            )
            
            return RedactionResult(
                success=True,
                entities_redacted=total_entities,
                metadata={"entity_categories": entity_categories}
            )
            
        except Exception as e:
            logger.error(f"✗ Redaction failed: {Path(file_path).name} - {e}")
            return RedactionResult(
                success=False,
                entities_redacted=0,
                error_message=str(e)
            )
    
    async def close(self):
        """Close the Azure Language client."""
        await self.client.close()
    
    @staticmethod
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
