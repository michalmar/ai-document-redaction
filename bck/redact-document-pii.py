#!/usr/bin/env python3
"""
Redact PII from Markdown documents using Azure AI Language services (async).

This script takes Markdown documents and redacts personally identifiable
information (PII) using Azure's Text Analytics PII recognition service.
Uses async/await for improved performance. Supports batch processing
of multiple documents.
"""

import os
import sys
import argparse
import asyncio
import logging
import time
from pathlib import Path
from dataclasses import dataclass
from typing import List
from azure.core.credentials import AzureKeyCredential
from azure.ai.textanalytics.aio import TextAnalyticsClient
from azure.core.exceptions import HttpResponseError

from dotenv import load_dotenv
load_dotenv()  # Load environment variables from .env file if present

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Suppress Azure SDK HTTP logging
logging.getLogger('azure.core.pipeline.policies.http_logging_policy').setLevel(logging.WARNING)


@dataclass
class RedactionResult:
    """Result of a document redaction operation."""
    file_path: str
    output_path: str
    success: bool
    entities_redacted: int = 0
    characters_original: int = 0
    characters_redacted: int = 0
    duration_seconds: float = 0.0
    error_message: str = ""


@dataclass
class BatchMetrics:
    """Metrics for batch processing."""
    total_files: int = 0
    successful: int = 0
    failed: int = 0
    skipped: int = 0
    total_entities_redacted: int = 0
    total_characters_original: int = 0
    total_characters_redacted: int = 0
    total_duration_seconds: float = 0.0
    
    def add_result(self, result: RedactionResult):
        """Add a redaction result to metrics."""
        self.total_files += 1
        if result.success:
            self.successful += 1
            self.total_entities_redacted += result.entities_redacted
            self.total_characters_original += result.characters_original
            self.total_characters_redacted += result.characters_redacted
        else:
            self.failed += 1
        self.total_duration_seconds += result.duration_seconds
    
    def print_summary(self):
        """Print metrics summary."""
        logger.info("\n" + "="*60)
        logger.info("BATCH PROCESSING SUMMARY")
        logger.info("="*60)
        logger.info(f"Total files processed: {self.total_files}")
        logger.info(f"Successful: {self.successful}")
        logger.info(f"Failed: {self.failed}")
        if self.skipped > 0:
            logger.info(f"Skipped (unsupported): {self.skipped}")
        logger.info(f"Total entities redacted: {self.total_entities_redacted}")
        logger.info(f"Total characters (original): {self.total_characters_original}")
        logger.info(f"Total characters (redacted): {self.total_characters_redacted}")
        logger.info(f"Total duration: {self.total_duration_seconds:.2f}s")
        if self.successful > 0:
            logger.info(f"Average time per file: {self.total_duration_seconds / self.successful:.2f}s")
            logger.info(f"Average entities per file: {self.total_entities_redacted / self.successful:.1f}")
        logger.info("="*60)


async def redact_document_pii(
    document_path: str,
    output_path: str | None = None,
    client: TextAnalyticsClient | None = None,
    redaction_character: str = "*",
    language: str = "en"
) -> RedactionResult:
    """
    Redact PII from a Markdown document using Azure AI Language services (async).
    
    Args:
        document_path: Path to local Markdown file
        output_path: Optional path to save the redacted output. If None, returns redacted string.
        client: Optional TextAnalyticsClient to reuse. If None, creates a new one.
        redaction_character: Character to use for redaction (default: "*")
        language: Document language code (default: "en")
        
    Returns:
        RedactionResult with redaction status and metrics
        
    Raises:
        ValueError: If endpoint or key environment variables are not set
    """
    start_time = time.time()
    result = RedactionResult(
        file_path=document_path,
        output_path=output_path or "<not saved>",
        success=False
    )
    
    # Get credentials from environment variables
    endpoint = os.environ.get("AZURE_LANGUAGE_ENDPOINT")
    key = os.environ.get("AZURE_LANGUAGE_KEY")
    
    if not endpoint or not key:
        raise ValueError(
            "Missing required environment variables:\n"
            "  AZURE_LANGUAGE_ENDPOINT\n"
            "  AZURE_LANGUAGE_KEY\n\n"
            "Please set them before running this script."
        )
    
    # Initialize or reuse the Text Analytics client
    close_client = False
    if client is None:
        client = TextAnalyticsClient(
            endpoint=endpoint,
            credential=AzureKeyCredential(key)
        )
        close_client = True
    
    try:
        # Read local file
        file_path = Path(document_path)
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {document_path}")
        
        document_text = file_path.read_text(encoding="utf-8")
        result.characters_original = len(document_text)
        
        logger.info(f"Analyzing PII: {document_path}")
        
        # Split document into chunks if needed (Azure has a limit of ~5120 characters per document)
        # For simplicity, we'll process the entire document if it's under the limit
        # or split it into chunks if larger
        max_chars = 5000  # Safe limit under the API constraint
        chunks = []
        
        if len(document_text) <= max_chars:
            chunks = [document_text]
        else:
            # Split by paragraphs to maintain context
            paragraphs = document_text.split('\n\n')
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
        
        logger.info(f"Processing {len(chunks)} chunk(s)")
        
        # Process chunks and collect redacted text
        redacted_chunks = []
        total_entities = 0
        
        for i, chunk in enumerate(chunks):
            logger.debug(f"Processing chunk {i+1}/{len(chunks)} ({len(chunk)} chars)")
            
            response = await client.recognize_pii_entities(
                [chunk],
                language=language
            )
            
            docs = [doc for doc in response if not doc.is_error]
            
            if not docs:
                # Handle error case
                for doc in response:
                    if doc.is_error:
                        logger.warning(f"Chunk {i+1} error: {doc.error.message}")
                redacted_chunks.append(chunk)
            else:
                doc = docs[0]
                redacted_chunks.append(doc.redacted_text)
                total_entities += len(doc.entities)
                
                logger.debug(f"Chunk {i+1}: Found {len(doc.entities)} PII entities")
                for entity in doc.entities:
                    logger.debug(f"  - {entity.category}: {entity.text} (confidence: {entity.confidence_score:.2f})")
        
        # Combine redacted chunks
        redacted_content = "".join(redacted_chunks)
        
        result.success = True
        result.entities_redacted = total_entities
        result.characters_redacted = len(redacted_content)
        
        # Save to file if output path specified
        if output_path:
            output_file = Path(output_path)
            output_file.parent.mkdir(parents=True, exist_ok=True)
            output_file.write_text(redacted_content, encoding="utf-8")
            logger.info(
                f"✓ Saved: {output_path} "
                f"({result.entities_redacted} entities redacted, "
                f"{result.characters_original} → {result.characters_redacted} chars)"
            )
        
    except Exception as e:
        result.success = False
        result.error_message = str(e)
        logger.error(f"✗ Failed: {document_path} - {e}")
    
    finally:
        if close_client:
            await client.close()
        result.duration_seconds = time.time() - start_time
    
    return result


async def process_batch(
    file_paths: List[str],
    output_dir: str,
    batch_size: int = 5,
    language: str = "en"
) -> BatchMetrics:
    """
    Process multiple documents in batches.
    
    Args:
        file_paths: List of file paths to process
        output_dir: Directory to save redacted outputs
        batch_size: Number of documents to process concurrently
        language: Document language code
        
    Returns:
        BatchMetrics with processing statistics
    """
    metrics = BatchMetrics()
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    # Get credentials
    endpoint = os.environ.get("AZURE_LANGUAGE_ENDPOINT")
    key = os.environ.get("AZURE_LANGUAGE_KEY")
    
    if not endpoint or not key:
        raise ValueError(
            "Missing required environment variables:\n"
            "  AZURE_LANGUAGE_ENDPOINT\n"
            "  AZURE_LANGUAGE_KEY\n\n"
            "Please set them before running this script."
        )
    
    # Create shared client
    client = TextAnalyticsClient(
        endpoint=endpoint,
        credential=AzureKeyCredential(key)
    )
    
    logger.info(f"Starting batch processing: {len(file_paths)} files, batch size: {batch_size}")
    
    async with client:
        # Process files in batches
        for i in range(0, len(file_paths), batch_size):
            batch = file_paths[i:i + batch_size]
            batch_num = i // batch_size + 1
            total_batches = (len(file_paths) + batch_size - 1) // batch_size
            
            logger.info(f"\nProcessing batch {batch_num}/{total_batches} ({len(batch)} files)")
            
            # Create tasks for current batch
            tasks = []
            for file_info in batch:
                # Handle both old format (string) and new format (tuple)
                if isinstance(file_info, tuple):
                    abs_path, rel_path = file_info
                    input_file = Path(abs_path)
                    # Preserve subdirectory structure
                    output_file = output_path / rel_path
                else:
                    # Backward compatibility for single string paths
                    input_file = Path(file_info)
                    output_file = output_path / input_file.name
                
                tasks.append(
                    redact_document_pii(
                        str(input_file),
                        str(output_file),
                        client=client,
                        language=language
                    )
                )
            
            # Execute batch concurrently
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Process results
            for result in results:
                if isinstance(result, Exception):
                    logger.error(f"Unexpected error: {result}")
                    metrics.total_files += 1
                    metrics.failed += 1
                elif isinstance(result, RedactionResult):
                    metrics.add_result(result)
    
    return metrics


def collect_files_from_directory(
    directory: str,
    extensions: tuple = (".md", ".txt")
) -> tuple[List[tuple[str, str]], int]:
    """
    Recursively collect all supported text files from a directory and its subdirectories.
    
    Args:
        directory: Directory path to scan
        extensions: Tuple of file extensions to include
        
    Returns:
        Tuple of (list of (absolute_path, relative_path) tuples, count of skipped files)
    """
    dir_path = Path(directory)
    if not dir_path.exists():
        raise FileNotFoundError(f"Directory not found: {directory}")
    
    if not dir_path.is_dir():
        raise ValueError(f"Not a directory: {directory}")
    
    # Normalize extensions to lowercase for comparison
    extensions_lower = tuple(ext.lower() for ext in extensions)
    
    # Get all files recursively
    all_files = [f for f in dir_path.rglob("*") if f.is_file()]
    
    # Separate supported and unsupported files
    supported_files = []
    skipped_count = 0
    
    for file in all_files:
        if file.suffix.lower() in extensions_lower:
            relative_path = file.relative_to(dir_path)
            supported_files.append((str(file), str(relative_path)))
        else:
            skipped_count += 1
            logger.warning(f"Skipping unsupported file: {file.relative_to(dir_path)}")
    
    return sorted(supported_files, key=lambda x: x[1]), skipped_count


def main():
    """Main entry point for the script."""
    parser = argparse.ArgumentParser(
        description="Redact PII from Markdown documents using Azure AI Language services",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  Single file:
    %(prog)s document.md
    %(prog)s document.md -o redacted.md
    %(prog)s document.txt --output redacted.txt --language cs
  
  Batch processing:
    %(prog)s --batch-dir ./documents --output-dir ./redacted
    %(prog)s --batch-dir ./output --output-dir ./redacted --batch-size 10

Environment variables required:
  AZURE_LANGUAGE_ENDPOINT - Your Azure Language endpoint
  AZURE_LANGUAGE_KEY - Your Azure Language API key
        """
    )
    
    parser.add_argument(
        "document_path",
        nargs="?",
        help="Path to local document file to redact (not used with --batch-dir)"
    )
    
    parser.add_argument(
        "-o", "--output",
        dest="output_path",
        help="Output path for redacted file (default: input filename with _redacted suffix)"
    )
    
    parser.add_argument(
        "--batch-dir",
        dest="batch_dir",
        help="Process all supported documents in this directory"
    )
    
    parser.add_argument(
        "--output-dir",
        dest="output_dir",
        default="./redacted",
        help="Output directory for batch processing (default: ./redacted)"
    )
    
    parser.add_argument(
        "--batch-size",
        dest="batch_size",
        type=int,
        default=5,
        help="Number of documents to process concurrently (default: 5)"
    )
    
    parser.add_argument(
        "--language",
        dest="language",
        default="en",
        help="Document language code (default: en). Use 'cs' for Czech, 'de' for German, etc."
    )
    
    parser.add_argument(
        "--log-level",
        dest="log_level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Logging level (default: INFO)"
    )
    
    args = parser.parse_args()
    
    # Set log level
    logger.setLevel(getattr(logging, args.log_level))
    
    try:
        # Batch processing mode
        if args.batch_dir:
            if args.document_path:
                logger.warning("Ignoring document_path argument in batch mode")
            
            logger.info(f"Collecting files from: {args.batch_dir}")
            file_paths, skipped_count = collect_files_from_directory(args.batch_dir)
            
            if not file_paths:
                logger.error(f"No supported documents found in: {args.batch_dir}")
                sys.exit(1)
            
            logger.info(f"Found {len(file_paths)} documents to process")
            
            metrics = asyncio.run(process_batch(
                file_paths,
                args.output_dir,
                args.batch_size,
                args.language
            ))
            
            # Add skipped files to metrics
            metrics.skipped = skipped_count
            
            metrics.print_summary()
            
            if metrics.failed > 0:
                sys.exit(1)
        
        # Single file mode
        else:
            if not args.document_path:
                parser.error("document_path is required when not using --batch-dir")
            
            # If no output path specified, generate one based on input
            output_path = args.output_path
            if not output_path:
                input_file = Path(args.document_path)
                output_path = str(input_file.parent / f"{input_file.stem}_redacted{input_file.suffix}")
            
            result = asyncio.run(redact_document_pii(
                args.document_path,
                output_path,
                language=args.language
            ))
            
            if not result.success:
                logger.error(f"Redaction failed: {result.error_message}")
                sys.exit(1)
        
    except HttpResponseError as error:
        logger.error(f"API Error: {error.message}")
        if hasattr(error, 'error') and error.error:
            logger.error(f"Error code: {error.error.code}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
