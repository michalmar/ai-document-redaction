#!/usr/bin/env python3
"""
Convert documents to Markdown using Azure Document Intelligence API (async).

This script takes a document path (local file or URL) and converts it to
Markdown format using Azure's Document Intelligence Layout model with
markdown output format. Uses async/await for improved performance.
Supports batch processing of multiple documents.
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
from azure.ai.documentintelligence.aio import DocumentIntelligenceClient
from azure.ai.documentintelligence.models import AnalyzeDocumentRequest, DocumentContentFormat
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
class ConversionResult:
    """Result of a document conversion operation."""
    file_path: str
    output_path: str
    success: bool
    pages: int = 0
    characters: int = 0
    duration_seconds: float = 0.0
    error_message: str = ""


@dataclass
class BatchMetrics:
    """Metrics for batch processing."""
    total_files: int = 0
    successful: int = 0
    failed: int = 0
    skipped: int = 0
    total_pages: int = 0
    total_characters: int = 0
    total_duration_seconds: float = 0.0
    
    def add_result(self, result: ConversionResult):
        """Add a conversion result to metrics."""
        self.total_files += 1
        if result.success:
            self.successful += 1
            self.total_pages += result.pages
            self.total_characters += result.characters
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
        logger.info(f"Total pages: {self.total_pages}")
        logger.info(f"Total characters: {self.total_characters}")
        logger.info(f"Total duration: {self.total_duration_seconds:.2f}s")
        if self.successful > 0:
            logger.info(f"Average time per file: {self.total_duration_seconds / self.successful:.2f}s")
        logger.info("="*60)


async def convert_document_to_markdown(
    document_path: str, 
    output_path: str | None = None,
    client: DocumentIntelligenceClient | None = None
) -> ConversionResult:
    """
    Convert a document to Markdown using Azure Document Intelligence API (async).
    
    Args:
        document_path: Path to local file or URL to the document
        output_path: Optional path to save the markdown output. If None, returns markdown string.
        client: Optional DocumentIntelligenceClient to reuse. If None, creates a new one.
        
    Returns:
        ConversionResult with conversion status and metrics
        
    Raises:
        ValueError: If endpoint or key environment variables are not set
    """
    start_time = time.time()
    result = ConversionResult(
        file_path=document_path,
        output_path=output_path or "<not saved>",
        success=False
    )
    
    # Get credentials from environment variables
    endpoint = os.environ.get("DOCUMENTINTELLIGENCE_ENDPOINT")
    key = os.environ.get("DOCUMENTINTELLIGENCE_API_KEY")
    
    if not endpoint or not key:
        raise ValueError(
            "Missing required environment variables:\n"
            "  DOCUMENTINTELLIGENCE_ENDPOINT\n"
            "  DOCUMENTINTELLIGENCE_API_KEY\n\n"
            "Please set them before running this script."
        )
    
    # Initialize or reuse the Document Intelligence client
    close_client = False
    if client is None:
        client = DocumentIntelligenceClient(
            endpoint=endpoint,
            credential=AzureKeyCredential(key)
        )
        close_client = True
    
    try:
        # Determine if input is URL or local file
        is_url = document_path.startswith(("http://", "https://"))
        
        logger.info(f"Analyzing: {document_path}")
        
        # Start analysis with markdown output format
        if is_url:
            poller = await client.begin_analyze_document(
                "prebuilt-layout",
                AnalyzeDocumentRequest(url_source=document_path),
                output_content_format=DocumentContentFormat.MARKDOWN
            )
        else:
            # Read local file
            file_path = Path(document_path)
            if not file_path.exists():
                raise FileNotFoundError(f"File not found: {document_path}")
            
            with open(file_path, "rb") as f:
                file_bytes = f.read()
            
            poller = await client.begin_analyze_document(
                "prebuilt-layout",
                AnalyzeDocumentRequest(bytes_source=file_bytes),
                output_content_format=DocumentContentFormat.MARKDOWN
            )
        
        analyze_result = await poller.result()
        
        # Extract markdown content
        markdown_content = analyze_result.content if analyze_result.content else ""
        
        result.success = True
        result.pages = len(analyze_result.pages) if analyze_result.pages else 0
        result.characters = len(markdown_content)
        
        # Save to file if output path specified
        if output_path:
            output_file = Path(output_path)
            output_file.parent.mkdir(parents=True, exist_ok=True)
            output_file.write_text(markdown_content, encoding="utf-8")
            logger.info(f"✓ Saved: {output_path} ({result.pages} pages, {result.characters} chars)")
        
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
    batch_size: int = 5
) -> BatchMetrics:
    """
    Process multiple documents in batches.
    
    Args:
        file_paths: List of file paths to process
        output_dir: Directory to save markdown outputs
        batch_size: Number of documents to process concurrently
        
    Returns:
        BatchMetrics with processing statistics
    """
    metrics = BatchMetrics()
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    # Get credentials
    endpoint = os.environ.get("DOCUMENTINTELLIGENCE_ENDPOINT")
    key = os.environ.get("DOCUMENTINTELLIGENCE_API_KEY")
    
    if not endpoint or not key:
        raise ValueError(
            "Missing required environment variables:\n"
            "  DOCUMENTINTELLIGENCE_ENDPOINT\n"
            "  DOCUMENTINTELLIGENCE_API_KEY\n\n"
            "Please set them before running this script."
        )
    
    # Create shared client
    client = DocumentIntelligenceClient(
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
                    output_file = output_path / Path(rel_path).with_suffix(".md")
                else:
                    # Backward compatibility for single string paths
                    input_file = Path(file_info)
                    output_file = output_path / input_file.with_suffix(".md").name
                
                tasks.append(
                    convert_document_to_markdown(
                        str(input_file),
                        str(output_file),
                        client=client
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
                elif isinstance(result, ConversionResult):
                    metrics.add_result(result)
    
    return metrics


def collect_files_from_directory(
    directory: str,
    extensions: tuple = (".pdf", ".docx", ".xlsx", ".pptx", ".jpg", ".jpeg", ".png", ".tiff", ".bmp")
) -> tuple[List[tuple[str, str]], int]:
    """
    Recursively collect all supported document files from a directory and its subdirectories.
    
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
        description="Convert documents to Markdown using Azure Document Intelligence API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  Single file:
    %(prog)s document.pdf
    %(prog)s document.pdf -o output.md
    %(prog)s https://example.com/document.pdf --output converted.md
  
  Batch processing:
    %(prog)s --batch-dir ./documents --output-dir ./markdown
    %(prog)s --batch-dir ./inp --output-dir ./out --batch-size 10

Environment variables required:
  DOCUMENTINTELLIGENCE_ENDPOINT - Your Azure endpoint
  DOCUMENTINTELLIGENCE_API_KEY - Your Azure API key
        """
    )
    
    parser.add_argument(
        "document_path",
        nargs="?",
        help="Path to local document file or URL to analyze (not used with --batch-dir)"
    )
    
    parser.add_argument(
        "-o", "--output",
        dest="output_path",
        help="Output path for markdown file (default: input filename with .md extension)"
    )
    
    parser.add_argument(
        "--batch-dir",
        dest="batch_dir",
        help="Process all supported documents in this directory"
    )
    
    parser.add_argument(
        "--output-dir",
        dest="output_dir",
        default="./output",
        help="Output directory for batch processing (default: ./output)"
    )
    
    parser.add_argument(
        "--batch-size",
        dest="batch_size",
        type=int,
        default=5,
        help="Number of documents to process concurrently (default: 5)"
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
                args.batch_size
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
                if not args.document_path.startswith(("http://", "https://")):
                    input_file = Path(args.document_path)
                    output_path = str(input_file.with_suffix(".md"))
                else:
                    output_path = "output.md"
            
            result = asyncio.run(convert_document_to_markdown(args.document_path, output_path))
            
            if not result.success:
                logger.error(f"Conversion failed: {result.error_message}")
                sys.exit(1)
        
    except HttpResponseError as error:
        logger.error(f"API Error: {error.message}")
        if error.error:
            logger.error(f"Error code: {error.error.code}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
