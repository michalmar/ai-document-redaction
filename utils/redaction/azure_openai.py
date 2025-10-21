"""Azure OpenAI LLM-based PII redaction strategy."""

import logging
import json
from pathlib import Path
from openai import AsyncAzureOpenAI

from .base import RedactionStrategy, RedactionResult, split_into_chunks
from .config import RedactionConfig
from ..retry import retry_with_backoff

logger = logging.getLogger(__name__)


REDACTION_SYSTEM_PROMPT = """You are a PII (Personally Identifiable Information) redaction assistant for Czech documents.

Your task is to identify and redact ALL PII entities in the provided text by replacing them with [REDACTED].

PII entities include:
- Person names (full names, first names, last names, nicknames)
- Company names (legal names, trade names)
- Email addresses
- Phone numbers (all formats)
- Physical addresses (cities, street addresses, cities with street numbers, postal codes)
- National identification numbers (SSN, passport numbers, ID card numbers, etc.)
- Financial information (credit card numbers, bank account numbers, IBAN)
- Dates of birth
- License plate numbers
- Medical record numbers
- IP addresses
- URLs
- Company registration numbers with personal context
- Tax identification numbers

IMPORTANT:
1. Replace each PII entity with exactly "[REDACTED]"
2. Preserve the document structure, formatting, and all non-PII content
3. Do NOT add explanations, notes, or any additional text
4. Return ONLY the redacted text
"""
# After the redacted text, on a new line starting with "ENTITIES:", list the categories of entities you found (comma-separated)."""


class AzureOpenAIStrategy(RedactionStrategy):
    """PII redaction using Azure OpenAI LLM."""
    
    def __init__(self, config: RedactionConfig):
        """
        Initialize Azure OpenAI strategy.
        
        Args:
            config: RedactionConfig with openai_endpoint, openai_api_key, and openai_deployment
        """
        self.config = config
        self.client = AsyncAzureOpenAI(
            api_key=config.openai_api_key,
            api_version=config.openai_api_version,
            azure_endpoint=config.openai_endpoint
        )
        self.total_tokens = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
    
    async def redact_document(
        self,
        file_path: str,
        output_path: str
    ) -> RedactionResult:
        """
        Redact PII from a Markdown document using Azure OpenAI.
        
        Args:
            file_path: Path to input markdown file
            output_path: Path to save redacted output
            
        Returns:
            RedactionResult with operation details including token usage
        """
        try:
            logger.debug(f"Redacting with Azure OpenAI: {file_path}")
            
            # Read document
            document_text = Path(file_path).read_text(encoding="utf-8")
            
            # Split into chunks if needed (use larger chunk size for LLM)
            chunks = split_into_chunks(document_text, self.config.max_chunk_size_openai)
            
            # Filter out empty chunks (avoid unnecessary API calls and token costs)
            non_empty_chunks = [(idx, chunk) for idx, chunk in enumerate(chunks) if chunk.strip()]
            logger.info(
                f"Document {file_path} split into {len(chunks)} chunk(s), "
                f"processing {len(non_empty_chunks)} non-empty chunk(s)."
            )
            
            # Process chunks with retry logic
            redacted_chunks = []
            chunk_tokens = 0
            chunk_prompt_tokens = 0
            chunk_completion_tokens = 0
            entity_categories_all = {}
            
            for chunk_idx, chunk in non_empty_chunks:
                success, result, error_msg = await retry_with_backoff(
                    self._redact_chunk_inner,
                    chunk,
                    self.client,
                    self.config.openai_deployment
                )
                
                if not success:
                    logger.error(
                        f"✗ Redaction failed for chunk {chunk_idx + 1}/{len(chunks)} "
                        f"in {Path(file_path).name} - {error_msg}"
                    )
                    return RedactionResult(
                        success=False,
                        entities_redacted=0,
                        error_message=f"Chunk {chunk_idx + 1} failed: {error_msg}",
                        metadata={
                            "tokens_used": chunk_tokens,
                            "prompt_tokens": chunk_prompt_tokens,
                            "completion_tokens": chunk_completion_tokens
                        }
                    )
                
                redacted_text, entity_categories, tokens, prompt_tok, completion_tok = result
                redacted_chunks.append(redacted_text)
                chunk_tokens += tokens
                chunk_prompt_tokens += prompt_tok
                chunk_completion_tokens += completion_tok
                
                # Aggregate entity categories
                for category in entity_categories:
                    entity_categories_all[category] = entity_categories_all.get(category, 0) + 1
            
            # Update instance totals
            self.total_tokens += chunk_tokens
            self.prompt_tokens += chunk_prompt_tokens
            self.completion_tokens += chunk_completion_tokens
            
            # Save redacted content
            redacted_content = "".join(redacted_chunks)
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            Path(output_path).write_text(redacted_content, encoding="utf-8")
            
            # Estimate entity count from categories
            total_entities = sum(entity_categories_all.values())
            
            logger.debug(
                f"✓ Redacted: {Path(file_path).name} ({total_entities} entities, "
                f"tokens: {chunk_tokens}, categories: {entity_categories_all})"
            )
            
            return RedactionResult(
                success=True,
                entities_redacted=total_entities,
                metadata={
                    "tokens_used": chunk_tokens,
                    "prompt_tokens": chunk_prompt_tokens,
                    "completion_tokens": chunk_completion_tokens,
                    "entity_categories": entity_categories_all
                }
            )
            
        except Exception as e:
            logger.error(f"✗ Redaction failed: {Path(file_path).name} - {e}")
            return RedactionResult(
                success=False,
                entities_redacted=0,
                error_message=str(e),
                metadata={
                    "tokens_used": self.total_tokens,
                    "prompt_tokens": self.prompt_tokens,
                    "completion_tokens": self.completion_tokens
                }
            )
    
    async def close(self):
        """Close the Azure OpenAI client."""
        await self.client.close()
    
    @staticmethod
    async def _redact_chunk_inner(
        chunk: str,
        client: AsyncAzureOpenAI,
        deployment: str
    ):
        """
        Inner function for LLM-based PII redaction that can be retried.
        
        Args:
            chunk: Text chunk to redact
            client: AsyncAzureOpenAI instance
            deployment: Deployment/model name
            
        Returns:
            Tuple of (redacted_text, entity_categories_dict, tokens_used, prompt_tokens, completion_tokens)
        """
        logger.debug(f"Parameters for LLM call: chunk length={len(chunk)}chars, max_completion_tokens={int((len(chunk)) * 1.2)}, deployment={deployment}")
        response = await client.chat.completions.create(
            model=deployment,
            messages=[
                {"role": "system", "content": REDACTION_SYSTEM_PROMPT},
                {"role": "user", "content": chunk}
            ],
            # temperature=0,
            # max_tokens=len(chunk) * 2  # Allow space for redaction markers
            max_completion_tokens = int((len(chunk)) * 1.2),  # / 1.5 char to tokens, 1.2x buffer
            reasoning_effort="low"
        )
        # logger.debug(f"LLM raw response: {json.dumps(response, indent=2)[:500]}...")
        
        content = response.choices[0].message.content
        tokens_used = response.usage.total_tokens
        prompt_tokens = response.usage.prompt_tokens
        completion_tokens = response.usage.completion_tokens
        
        # Log raw response for debugging
        logger.debug(
            f"LLM response length: {len(content)} chars, "
            f"input length: {len(chunk)} chars"
        )
        
        # Parse out entity categories if present
        entity_categories = {}
        redacted_text = content
        
        if "ENTITIES:" in content:
            parts = content.split("ENTITIES:", 1)
            # Don't strip trailing newlines, only leading/trailing spaces on each line
            redacted_text = parts[0].rstrip()
            categories_str = parts[1].strip()
            
            # Validate that we have content before ENTITIES marker
            if not redacted_text:
                logger.warning(
                    f"LLM returned empty content before ENTITIES marker. "
                    f"Raw response: {content[:200]}..."
                )
                # Fallback: use the full content without parsing
                redacted_text = content
                entity_categories = {}
                return redacted_text, entity_categories, tokens_used, prompt_tokens, completion_tokens
            
            # Parse categories
            if categories_str and categories_str.lower() != "none":
                for cat in categories_str.split(","):
                    cat = cat.strip()
                    if cat:
                        entity_categories[cat] = entity_categories.get(cat, 0) + 1
        
        # Final validation: ensure we have content
        if not redacted_text or len(redacted_text) < 5:
            logger.error(f"Parameters for LLM call: chunk length={len(chunk)}chars, chunk tokens={int(len(chunk))}, max_completion_tokens={int((len(chunk) / 1.5) * 1.2)}, deployment={deployment}")
            logger.error(
                f"LLM returned insufficient content (length: {len(redacted_text)}). "
                f"Raw response: {content[:500]}"
            )
            raise ValueError(
                f"LLM returned empty or insufficient content. "
                f"Response length: {len(content)}, Parsed length: {len(redacted_text)}"
            )
        
        return redacted_text, entity_categories, tokens_used, prompt_tokens, completion_tokens
