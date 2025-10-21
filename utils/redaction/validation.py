"""LLM-based PII validation for redacted documents."""

import logging
from pathlib import Path
from dataclasses import dataclass
from openai import AsyncAzureOpenAI

from .config import ValidationConfig
from .base import split_into_chunks
from ..retry import retry_with_backoff

logger = logging.getLogger(__name__)


VALIDATION_SYSTEM_PROMPT = """You are a PII (Personally Identifiable Information) validation assistant.

Your task is to analyze the provided text and identify ANY remaining PII that should have been redacted.

Look for these PII types:
- Person names (full names, first names, last names, nicknames)
- Email addresses
- Phone numbers (all formats)
- Physical addresses (street addresses, cities with street numbers, postal codes)
- National identification numbers (SSN, passport numbers, ID card numbers, etc.)
- Financial information (credit card numbers, bank account numbers, IBAN)
- Dates of birth
- License plate numbers
- Medical record numbers
- IP addresses
- URLs containing personal information
- Company registration numbers with personal context
- Tax identification numbers

Respond ONLY with a JSON object:
{
  "has_pii": true/false,
  "pii_found": ["category1", "category2", ...],
  "confidence": "high/medium/low",
  "details": "Brief explanation if PII found"
}

If NO PII is found, respond:
{
  "has_pii": false,
  "pii_found": [],
  "confidence": "high",
  "details": "No PII detected"
}"""


@dataclass
class ValidationResult:
    """
    Result of PII validation.
    
    Args:
        success: Whether validation succeeded
        has_pii: Whether PII was detected in redacted document
        pii_categories: List of PII categories found
        confidence: Confidence level (high/medium/low)
        details: Explanation of findings
        error_message: Error message if validation failed
        tokens_used: Total tokens consumed
        prompt_tokens: Prompt tokens used
        completion_tokens: Completion tokens used
    """
    success: bool
    has_pii: bool = False
    pii_categories: list[str] | None = None
    confidence: str = ""
    details: str = ""
    error_message: str = ""
    tokens_used: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0


class DocumentValidator:
    """LLM-based validator for checking PII in redacted documents."""
    
    def __init__(self, config: ValidationConfig):
        """
        Initialize validator.
        
        Args:
            config: ValidationConfig with OpenAI credentials
        """
        self.config = config
        self.client = AsyncAzureOpenAI(
            api_key=config.openai_api_key,
            api_version=config.openai_api_version,
            azure_endpoint=config.openai_endpoint
        )
    
    async def validate_document(self, file_path: str) -> ValidationResult:
        """
        Validate a redacted document for remaining PII.
        
        Args:
            file_path: Path to redacted markdown file
            
        Returns:
            ValidationResult with findings
        """
        try:
            logger.debug(f"Validating: {file_path}")
            
            # Read document
            document_text = Path(file_path).read_text(encoding="utf-8")
            
            # Split into chunks if needed
            chunks = split_into_chunks(document_text, self.config.max_chunk_size)
            
            # Validate each chunk
            total_tokens = 0
            total_prompt_tokens = 0
            total_completion_tokens = 0
            all_pii_found = []
            has_any_pii = False
            all_details = []
            
            for chunk_idx, chunk in enumerate(chunks):
                success, result, error_msg = await retry_with_backoff(
                    self._validate_chunk_inner,
                    chunk,
                    self.client,
                    self.config.openai_deployment
                )
                
                if not success:
                    logger.error(
                        f"✗ Validation failed for chunk {chunk_idx + 1}/{len(chunks)} "
                        f"in {Path(file_path).name} - {error_msg}"
                    )
                    return ValidationResult(
                        success=False,
                        error_message=f"Chunk {chunk_idx + 1} failed: {error_msg}",
                        tokens_used=total_tokens,
                        prompt_tokens=total_prompt_tokens,
                        completion_tokens=total_completion_tokens
                    )
                
                has_pii, pii_found, confidence, details, tokens, prompt_tok, completion_tok = result
                
                total_tokens += tokens
                total_prompt_tokens += prompt_tok
                total_completion_tokens += completion_tok
                
                if has_pii:
                    has_any_pii = True
                    all_pii_found.extend(pii_found)
                    all_details.append(f"Chunk {chunk_idx + 1}: {details}")
            
            # Deduplicate PII categories
            unique_pii = list(set(all_pii_found))
            
            if has_any_pii:
                logger.warning(
                    f"⚠ Validation found PII in {Path(file_path).name}: {unique_pii}"
                )
            else:
                logger.debug(
                    f"✓ Validation passed: {Path(file_path).name} (no PII detected)"
                )
            
            return ValidationResult(
                success=True,
                has_pii=has_any_pii,
                pii_categories=unique_pii if has_any_pii else [],
                confidence="high" if not has_any_pii else "medium",
                details=" | ".join(all_details) if all_details else "No PII detected",
                tokens_used=total_tokens,
                prompt_tokens=total_prompt_tokens,
                completion_tokens=total_completion_tokens
            )
            
        except Exception as e:
            logger.error(f"✗ Validation failed: {Path(file_path).name} - {e}")
            return ValidationResult(
                success=False,
                error_message=str(e)
            )
    
    async def close(self):
        """Close the OpenAI client."""
        await self.client.close()
    
    async def __aenter__(self):
        """Async context manager entry."""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()
    
    @staticmethod
    async def _validate_chunk_inner(
        chunk: str,
        client: AsyncAzureOpenAI,
        deployment: str
    ):
        """
        Inner function for LLM-based validation that can be retried.
        
        Args:
            chunk: Text chunk to validate
            client: AsyncAzureOpenAI instance
            deployment: Deployment/model name
            
        Returns:
            Tuple of (has_pii, pii_found_list, confidence, details, tokens_used, prompt_tokens, completion_tokens)
        """
        import json
        
        response = await client.chat.completions.create(
            model=deployment,
            messages=[
                {"role": "system", "content": VALIDATION_SYSTEM_PROMPT},
                {"role": "user", "content": chunk}
            ],
            temperature=0,
            response_format={"type": "json_object"}
        )
        
        content = response.choices[0].message.content
        tokens_used = response.usage.total_tokens
        prompt_tokens = response.usage.prompt_tokens
        completion_tokens = response.usage.completion_tokens
        
        # Parse JSON response
        result = json.loads(content)
        
        has_pii = result.get("has_pii", False)
        pii_found = result.get("pii_found", [])
        confidence = result.get("confidence", "low")
        details = result.get("details", "")
        
        return has_pii, pii_found, confidence, details, tokens_used, prompt_tokens, completion_tokens
