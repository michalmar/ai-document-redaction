"""Speed-optimized Azure OpenAI PII redaction strategy using entity extraction + replacement."""

import logging
import json
import re
from pathlib import Path
from openai import AsyncAzureOpenAI

from .base import RedactionStrategy, RedactionResult, split_into_chunks
from .config import RedactionConfig
from ..retry import retry_with_backoff

logger = logging.getLogger(__name__)


EXTRACTION_SYSTEM_PROMPT = """You are a PII (Personally Identifiable Information) extraction assistant for Czech documents.

Your task is to identify ALL PII entities in the provided text and return them as a JSON object.

PII entities include:
- Person names (full names, first names, last names, nicknames)
- Company names (legal names, trade names)
- Email addresses
- Phone numbers (all formats)
- Physical addresses (cities, street addresses, cities with street numbers, postal codes)
- National identification numbers (SSN, passport numbers, ID card numbers, etc.)
- Financial information (credit card numbers, bank account numbers, IBAN)
- IP addresses
- Company registration numbers with personal context

IMPORTANT:
1. Return ONLY a valid JSON object with key "entities" containing an array of strings
2. Each string should be an EXACT PII entity from the text (preserve exact spelling, spacing, capitalization)
3. Do NOT add explanations, notes, or any additional text
4. Do NOT include context or categories
5. Return {"entities": []} if no PII is found
6. Format: {"entities": ["entity1", "entity2", "entity3"]}

Example output:
{"entities": ["Jan Novák", "jan.novak@example.com", "+420 123 456 789", "Praha 1, Václavské náměstí 1"]}
"""


class AzureOpenAIFastStrategy(RedactionStrategy):
    """
    Speed-optimized PII redaction using Azure OpenAI.
    
    Strategy:
    1. LLM identifies PII entities and returns structured JSON list
    2. Python performs exact string replacement for all occurrences
    
    Trade-offs:
    - Faster and cheaper than full LLM redaction (smaller output tokens)
    - May miss variations or context-sensitive PII patterns
    - Best for documents with consistent, exact PII formats
    - Uses exact string matching (case-sensitive)
    """
    
    def __init__(self, config: RedactionConfig):
        """
        Initialize Azure OpenAI Fast strategy.
        
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
        self._output_root = None  # Will be set from first output_path
        self._input_root = None  # Will be set from first file_path
    
    async def redact_document(
        self,
        file_path: str,
        output_path: str
    ) -> RedactionResult:
        """
        Redact PII from a Markdown document using Azure OpenAI extraction + replacement.
        
        Args:
            file_path: Path to input markdown file
            output_path: Path to save redacted output
            
        Returns:
            RedactionResult with operation details including token usage
        """
        try:
            logger.debug(f"Redacting with Azure OpenAI Fast: {file_path}")
            
            # Detect output root from first file (the top-level output directory)
            if self._output_root is None:
                output_path_obj = Path(output_path).resolve()
                input_path_obj = Path(file_path).resolve()
                
                # For output root: go up from the file to find the actual output directory
                # The output directory is the one that contains subdirectories with files
                # Strategy: go up until we find a directory that looks like it contains organized subfolders
                # OR matches common names like 'output', 'out', 'anonymized', 'redacted'
                current = output_path_obj.parent
                
                # Go up max 3 levels to find the root
                for level in range(3):
                    parent = current.parent
                    if parent == current:  # Reached filesystem root
                        break
                    
                    # Check if current directory name suggests it's the output root
                    if current.name in ['output', 'out', 'anonymized', 'redacted', 'temp']:
                        self._output_root = current
                        break
                    
                    # Check if we're at a level where siblings exist (suggests we're in a subfolder)
                    # and parent looks more like a root
                    if level < 2:  # Don't go too far up
                        current = parent
                    else:
                        break
                
                # If we didn't find a good root, use the immediate parent
                if self._output_root is None:
                    # Go back to output file's parent directory
                    # For files in subfolders, we want the root before the subfolders start
                    # Simple heuristic: if output_path has more than 2 parts after resolve,
                    # use grandparent, otherwise use parent
                    self._output_root = output_path_obj.parent.parent if len(output_path_obj.parent.parts) > 2 else output_path_obj.parent
                
                # Similar logic for input root
                current = input_path_obj.parent
                for level in range(3):
                    parent = current.parent
                    if parent == current:
                        break
                    if current.name in ['input', 'inp', 'temp', 'source', '.temp_markdown']:
                        self._input_root = current
                        break
                    if level < 2:
                        current = parent
                    else:
                        break
                
                if self._input_root is None:
                    self._input_root = input_path_obj.parent.parent if len(input_path_obj.parent.parts) > 2 else input_path_obj.parent
                
                logger.info(f"Detected output root: {self._output_root}")
                logger.info(f"Detected input root: {self._input_root}")
            
            # Read document
            document_text = Path(file_path).read_text(encoding="utf-8")
            
            # Split into chunks if needed
            chunks = split_into_chunks(document_text, self.config.max_chunk_size_openai)
            
            # Filter out empty chunks
            non_empty_chunks = [(idx, chunk) for idx, chunk in enumerate(chunks) if chunk.strip()]
            logger.info(
                f"Document {file_path} split into {len(chunks)} chunk(s), "
                f"processing {len(non_empty_chunks)} non-empty chunk(s)."
            )
            
            # Extract PII entities from all chunks
            all_entities = set()
            chunk_tokens = 0
            chunk_prompt_tokens = 0
            chunk_completion_tokens = 0
            entities_by_chunk = []  # Track entities per chunk for logging
            
            for chunk_idx, chunk in non_empty_chunks:
                success, result, error_msg = await retry_with_backoff(
                    self._extract_entities_inner,
                    chunk,
                    self.client,
                    self.config.openai_deployment
                )
                
                if not success:
                    logger.error(
                        f"✗ Entity extraction failed for chunk {chunk_idx + 1}/{len(chunks)} "
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
                
                entities, tokens, prompt_tok, completion_tok = result
                all_entities.update(entities)
                chunk_tokens += tokens
                chunk_prompt_tokens += prompt_tok
                chunk_completion_tokens += completion_tok
                
                # Store entities for this chunk for logging
                entities_by_chunk.append({
                    "chunk_index": chunk_idx,
                    "chunk_size": len(chunk),
                    "entities_found": sorted(list(entities)),
                    "entity_count": len(entities)
                })
            
            # Create log file with extracted entities (if enabled)
            if self.config.enable_entity_logging:
                self._save_entity_log(
                    file_path, 
                    output_path, 
                    entities_by_chunk, 
                    all_entities,
                    self._input_root,
                    self._output_root
                )
            
            # Update instance totals
            self.total_tokens += chunk_tokens
            self.prompt_tokens += chunk_prompt_tokens
            self.completion_tokens += chunk_completion_tokens
            
            logger.info(
                f"Extracted {len(all_entities)} unique PII entities from {Path(file_path).name}"
            )
            
            # Perform replacement
            redacted_content = document_text
            entities_redacted_count = 0
            
            # Sort entities by length (longest first) to avoid partial replacements
            sorted_entities = sorted(all_entities, key=len, reverse=True)
            
            for entity in sorted_entities:
                # Count occurrences before replacement
                occurrences = redacted_content.count(entity)
                if occurrences > 0:
                    # Use regex for exact matching to avoid partial word replacements
                    # Escape special regex characters in the entity
                    escaped_entity = re.escape(entity)
                    redacted_content = re.sub(escaped_entity, "[REDACTED]", redacted_content)
                    entities_redacted_count += occurrences
                    logger.debug(f"Replaced {occurrences}x: {entity[:50]}...")
            
            # Save redacted content
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            Path(output_path).write_text(redacted_content, encoding="utf-8")
            
            logger.debug(
                f"✓ Redacted: {Path(file_path).name} ({entities_redacted_count} replacements, "
                f"{len(all_entities)} unique entities, tokens: {chunk_tokens})"
            )
            
            return RedactionResult(
                success=True,
                entities_redacted=entities_redacted_count,
                metadata={
                    "tokens_used": chunk_tokens,
                    "prompt_tokens": chunk_prompt_tokens,
                    "completion_tokens": chunk_completion_tokens,
                    "unique_entities": len(all_entities),
                    "total_replacements": entities_redacted_count
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
    def _save_entity_log(
        input_file_path: str,
        output_file_path: str,
        entities_by_chunk: list,
        all_entities: set,
        input_root: Path | None,
        output_root: Path | None
    ):
        """
        Save extracted entities to a log file for analysis.
        
        Args:
            input_file_path: Original input file path
            output_file_path: Redacted output file path
            entities_by_chunk: List of entity data per chunk
            all_entities: Set of all unique entities found
            input_root: Root directory of input files (for calculating relative path)
            output_root: Root directory of output files (for placing log)
        """
        input_file = Path(input_file_path).resolve()
        output_file = Path(output_file_path).resolve()
        
        # Determine output root if not provided
        if output_root is None:
            output_root = output_file.parent
        else:
            output_root = Path(output_root).resolve()
        
        # Calculate relative path from input root to maintain folder structure
        # The pipeline already maintains structure, so we can use the output file's path
        # to determine the relative directory
        try:
            # First, try using the output file's structure relative to output_root
            if output_file.parent != output_root:
                relative_dir = output_file.parent.relative_to(output_root)
                logger.debug(f"Using output structure - relative_dir: {relative_dir}")
            else:
                # File is directly in output root
                relative_dir = Path(".")
                logger.debug(f"Output file is directly in output_root")
        except (ValueError, AttributeError) as e:
            logger.warning(f"Could not calculate relative path from output, trying input: {e}")
            # Fallback: try from input root
            if input_root:
                input_root = Path(input_root).resolve()
                try:
                    relative_path = input_file.relative_to(input_root)
                    relative_dir = relative_path.parent
                    logger.debug(f"Using input structure - relative_dir: {relative_dir}")
                except ValueError:
                    relative_dir = Path(".")
                    logger.debug(f"Could not calculate from input, using '.'")
            else:
                relative_dir = Path(".")
                logger.debug(f"No input_root, using '.')")
        
        # Create log directory structure: output_root/log/relative_structure/
        log_root = output_root / "log"
        log_dir = log_root / relative_dir
        log_dir.mkdir(parents=True, exist_ok=True)
        
        # Create log filename
        input_filename = input_file.stem
        log_file = log_dir / f"{input_filename}.ENTITIES.log"
        
        # Generate log content
        log_lines = []
        log_lines.append("=" * 80)
        log_lines.append(f"PII ENTITY EXTRACTION LOG - {Path(input_file_path).name}")
        log_lines.append("=" * 80)
        log_lines.append(f"Strategy: azure_openai_fast")
        log_lines.append(f"Input file: {input_file_path}")
        log_lines.append(f"Output file: {output_file_path}")
        log_lines.append(f"Total chunks processed: {len(entities_by_chunk)}")
        log_lines.append(f"Total unique entities: {len(all_entities)}")
        log_lines.append("=" * 80)
        log_lines.append("")
        
        # Per-chunk details
        for chunk_data in entities_by_chunk:
            log_lines.append(f"CHUNK {chunk_data['chunk_index'] + 1}:")
            log_lines.append(f"  Chunk size: {chunk_data['chunk_size']} characters")
            log_lines.append(f"  Entities found: {chunk_data['entity_count']}")
            if chunk_data['entities_found']:
                log_lines.append("  Entities:")
                for entity in chunk_data['entities_found']:
                    log_lines.append(f"    - {entity}")
            else:
                log_lines.append("  (No entities found)")
            log_lines.append("")
        
        # Summary of all unique entities
        log_lines.append("=" * 80)
        log_lines.append(f"ALL UNIQUE ENTITIES ({len(all_entities)}):")
        log_lines.append("=" * 80)
        for entity in sorted(all_entities):
            log_lines.append(f"  - {entity}")
        log_lines.append("")
        log_lines.append("=" * 80)
        log_lines.append("END OF LOG")
        log_lines.append("=" * 80)
        
        # Write log file
        log_file.write_text("\n".join(log_lines), encoding="utf-8")
        logger.info(f"Entity extraction log saved to: {log_file}")
    
    @staticmethod
    async def _extract_entities_inner(
        chunk: str,
        client: AsyncAzureOpenAI,
        deployment: str
    ):
        """
        Inner function for LLM-based PII entity extraction that can be retried.
        
        Args:
            chunk: Text chunk to extract entities from
            client: AsyncAzureOpenAI instance
            deployment: Deployment/model name
            
        Returns:
            Tuple of (entities_set, tokens_used, prompt_tokens, completion_tokens)
        """
        logger.debug(f"Extracting entities from chunk: length={len(chunk)} chars, deployment={deployment}")
        
        response = await client.chat.completions.create(
            model=deployment,
            messages=[
                {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
                {"role": "user", "content": chunk}
            ],
            response_format={"type": "json_object"},
            max_completion_tokens=4000,  # JSON list should be much smaller than input
            reasoning_effort="low"
        )
        
        content = response.choices[0].message.content
        tokens_used = response.usage.total_tokens
        prompt_tokens = response.usage.prompt_tokens
        completion_tokens = response.usage.completion_tokens
        
        logger.debug(
            f"LLM extraction response: {len(content)} chars, "
            f"tokens: {tokens_used} (prompt: {prompt_tokens}, completion: {completion_tokens})"
        )
        logger.debug(f"Raw LLM response: {content[:500]}...")
        
        # Parse JSON response
        try:
            # Handle cases where LLM wraps in markdown code blocks
            if content.strip().startswith("```"):
                # Extract JSON from markdown code block
                json_match = re.search(r'```(?:json)?\s*(\[.*?\])\s*```', content, re.DOTALL)
                if json_match:
                    content = json_match.group(1)
            
            data = json.loads(content)
            
            # Handle different possible response formats
            if isinstance(data, dict):
                # Try common keys that might contain the entities list
                entities = data.get("entities") or data.get("pii") or data.get("items") or []
            elif isinstance(data, list):
                # Direct array response
                entities = data
            else:
                logger.warning(f"Unexpected JSON format: {type(data)}, content: {content[:200]}")
                entities = []
            
            # Validate and filter entities
            valid_entities = set()
            for entity in entities:
                if isinstance(entity, str) and entity.strip():
                    valid_entities.add(entity.strip())
            
            logger.debug(f"Extracted {len(valid_entities)} valid entities from chunk")
            
            return valid_entities, tokens_used, prompt_tokens, completion_tokens
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON response: {e}, content: {content[:500]}")
            raise ValueError(f"LLM returned invalid JSON: {e}")
