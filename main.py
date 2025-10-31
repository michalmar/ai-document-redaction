#!/usr/bin/env python3
"""
Orchestrate document anonymization pipeline.

This script orchestrates a two-stage pipeline:
1. Convert documents to Markdown using Azure Document Intelligence
2. Redact PII from the Markdown documents using Azure AI Language

The pipeline processes all supported documents in an input folder and
outputs fully anonymized documents to the specified output folder.
"""

import os
import sys
import argparse
import asyncio
import logging
from azure.core.exceptions import HttpResponseError
from dotenv import load_dotenv

from utils.conversion import ConversionConfig
from utils.redaction import RedactionConfig, ValidationConfig
from utils.pdf_export import PDFExportConfig
from utils.report import ReportConfig
from utils.filename_anonymizer import AnonymizationConfig, DetectionStrategy
from utils.pipeline import execute_pipeline
from utils.checkpoint import CheckpointManager
from utils.storage.factory import create_storage_adapter

load_dotenv()

# Configure logging (will be set dynamically based on --log-level)
logger = logging.getLogger(__name__)


def main():
    """Main entry point for the orchestration script."""
    parser = argparse.ArgumentParser(
        description="Orchestrate document anonymization pipeline (conversion + PII redaction)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Example:
  %(prog)s ./inp ./anonymized --batch-size 10 --language cs
  %(prog)s ./inp ./anonymized --redaction-strategy azure_openai --validate
  %(prog)s ./inp ./anonymized --clear-checkpoint  # Reprocess all files

Pipeline stages:
  1. Convert documents to Markdown (Azure Document Intelligence)
  2. Redact PII from Markdown (Azure AI Language OR Azure OpenAI)
  3. Validate redacted documents (Optional, LLM-based)
  4. Export to PDF (Optional, Markdown to PDF conversion)

Checkpoint feature:
  By default, the pipeline tracks completed first-level folders and skips them
  on subsequent runs. Use --no-checkpoint to disable or --clear-checkpoint to
  reset and reprocess all files.

Environment variables required:
  DOCUMENTINTELLIGENCE_ENDPOINT - Azure Document Intelligence endpoint
  DOCUMENTINTELLIGENCE_API_KEY - Azure Document Intelligence API key
  
  For --redaction-strategy azure_language (default):
    AZURE_LANGUAGE_ENDPOINT - Azure Language endpoint
    AZURE_LANGUAGE_KEY - Azure Language API key
  
  For --redaction-strategy azure_openai:
    AZURE_OPENAI_ENDPOINT - Azure OpenAI endpoint
    AZURE_OPENAI_API_KEY - Azure OpenAI API key
    AZURE_OPENAI_DEPLOYMENT - Azure OpenAI deployment name
  
  For --validate flag:
    AZURE_OPENAI_ENDPOINT - Azure OpenAI endpoint (if not already set)
    AZURE_OPENAI_API_KEY - Azure OpenAI API key (if not already set)
    AZURE_OPENAI_DEPLOYMENT - Azure OpenAI deployment name (if not already set)
        """
    )
    
    parser.add_argument(
        "input_dir",
        nargs='?',
        default=None,
        help="Input directory containing documents to anonymize (not required for azure_blob mode)"
    )
    
    parser.add_argument(
        "output_dir",
        nargs='?',
        default=None,
        help="Output directory for anonymized documents (not required for azure_blob mode)"
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
        help="Document language code for PII detection (default: en). Use 'cs' for Czech, 'de' for German, etc."
    )
    
    parser.add_argument(
        "--redaction-strategy",
        dest="redaction_strategy",
        choices=["azure_language", "azure_openai", "azure_openai_fast"],
        default="azure_language",
        help="PII redaction strategy (default: azure_language). 'azure_openai' uses full LLM redaction. 'azure_openai_fast' uses LLM extraction + Python replacement (faster, cheaper)."
    )
    
    parser.add_argument(
        "--validate",
        dest="validate",
        action="store_true",
        help="Enable optional Stage 3: LLM-based validation of redacted documents for remaining PII"
    )
    
    parser.add_argument(
        "--enable-entity-logging",
        dest="enable_entity_logging",
        action="store_true",
        help="Enable entity extraction logging for azure_openai_fast strategy (creates .ENTITIES.log files)"
    )
    
    parser.add_argument(
        "--export-pdf",
        dest="export_pdf",
        action="store_true",
        help="Enable optional Stage 4: Export anonymized Markdown files to PDF format"
    )
    
    parser.add_argument(
        "--report-file",
        dest="report_file",
        default=None,
        help="Path to CSV report file (default: <output_dir>/pipeline_report.csv)"
    )
    
    parser.add_argument(
        "--no-report",
        dest="no_report",
        action="store_true",
        help="Disable CSV report generation"
    )
    
    parser.add_argument(
        "--no-checkpoint",
        dest="no_checkpoint",
        action="store_true",
        help="Disable checkpoint-based incremental processing (process all files)"
    )
    
    parser.add_argument(
        "--clear-checkpoint",
        dest="clear_checkpoint",
        action="store_true",
        help="Clear existing checkpoint and reprocess all files"
    )
    
    parser.add_argument(
        "--log-level",
        dest="log_level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Logging level (default: INFO)"
    )

    parser.add_argument(
        "--stage",
        dest="stage",
        choices=["convert", "redact", "both"],
        default="both",
        help="Which pipeline stage to run: 'convert' (conversion only), 'redact' (redaction only assumes input is markdown), or 'both' (default)"
    )

    parser.add_argument(
        "--storage-mode",
        dest="storage_mode",
        choices=["local", "azure_blob"],
        default="local",
        help="Storage mode for input/output - local or azure_blob (default: local)"
    )

    parser.add_argument(
        "--storage-account",
        dest="storage_account",
        default=None,
        help="Azure storage account name (required for azure_blob mode)"
    )

    parser.add_argument(
        "--input-container",
        dest="input_container",
        default=None,
        help="Azure input container name or 'container/folder' path (required for azure_blob mode)"
    )

    parser.add_argument(
        "--output-container",
        dest="output_container",
        default=None,
        help="Azure output container name or 'container/folder' path (required for azure_blob mode)"
    )

    parser.add_argument(
        "--no-anonymize-filenames",
        dest="no_anonymize_filenames",
        action="store_true",
        help="Disable filename and folder PII anonymization (enabled by default)"
    )

    parser.add_argument(
        "--filename-detection-strategy",
        dest="filename_detection_strategy",
        choices=["azure_language"],
        default="azure_language",
        help="PII detection strategy for filenames/folders (azure_language only)"
    )

    parser.add_argument(
        "--filename-confidence-threshold",
        dest="filename_confidence_threshold",
        type=float,
        default=0.8,
        help="Confidence threshold for PII detection in filenames (0.0-1.0, default: 0.8)"
    )

    parser.add_argument(
        "--filename-hash-length",
        dest="filename_hash_length",
        type=int,
        default=8,
        choices=[6, 8, 10, 12, 16],
        help="Length of hash used for PII replacement (default: 8 chars)"
    )

    
    args = parser.parse_args()
    
    # Configure logging with user-specified level
    log_level = getattr(logging, args.log_level)
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(levelname)s - %(name)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        force=True  # Override any existing configuration
    )
    
    # Suppress Azure SDK HTTP logging unless DEBUG
    if log_level > logging.DEBUG:
        logging.getLogger('azure.core.pipeline.policies.http_logging_policy').setLevel(logging.WARNING)
        logging.getLogger('httpx').setLevel(logging.WARNING)
    
    try:
        logger.info("="*70)
        logger.info("DOCUMENT ANONYMIZATION PIPELINE")
        logger.info("="*70)
        
        # Display input/output info based on storage mode
        if args.storage_mode == "azure_blob":
            logger.info(f"Storage mode: Azure Blob Storage")
            logger.info(f"Storage account: {args.storage_account}")
            logger.info(f"Input: {args.input_container}")
            logger.info(f"Output: {args.output_container}")
        else:
            logger.info(f"Storage mode: Local filesystem")
            logger.info(f"Input directory: {args.input_dir}")
            logger.info(f"Output directory: {args.output_dir}")
        
        logger.info(f"Batch size: {args.batch_size}")
        logger.info(f"Language: {args.language}")
        logger.info(f"Redaction strategy: {args.redaction_strategy}")
        logger.info(f"Validation enabled: {args.validate}")
        logger.info(f"PDF export enabled: {args.export_pdf}")
        logger.info(f"Filename anonymization: {not args.no_anonymize_filenames}")
        if not args.no_anonymize_filenames:
            logger.info(f"  Detection strategy: {args.filename_detection_strategy}")
            logger.info(f"  Confidence threshold: {args.filename_confidence_threshold}")
            logger.info(f"  Hash length: {args.filename_hash_length}")
        logger.info(f"Checkpoint enabled: {not args.no_checkpoint}")
        if args.clear_checkpoint:
            logger.info("Clear checkpoint: Yes (will reprocess all files)")
        logger.info("")
        
        # Validate environment variables for conversion only
        doc_endpoint = os.environ.get("DOCUMENTINTELLIGENCE_ENDPOINT")
        doc_key = os.environ.get("DOCUMENTINTELLIGENCE_API_KEY")
        if args.stage in ("convert", "both"):
            if not all([doc_endpoint, doc_key]):
                raise ValueError(
                    "Missing required environment variables for conversion stage:\n"
                    "  DOCUMENTINTELLIGENCE_ENDPOINT\n"
                    "  DOCUMENTINTELLIGENCE_API_KEY\n"
                )
        
        # Get redaction strategy credentials
        lang_endpoint = os.environ.get("AZURE_LANGUAGE_ENDPOINT")
        lang_key = os.environ.get("AZURE_LANGUAGE_KEY")
        openai_endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT")
        openai_key = os.environ.get("AZURE_OPENAI_API_KEY")
        openai_deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT")

        # Validate based on selected strategy only if redaction will run
        if args.stage in ("redact", "both"):
            if args.redaction_strategy == "azure_language":
                if not all([lang_endpoint, lang_key]):
                    raise ValueError(
                        "Missing required environment variables for azure_language strategy:\n"
                        "  AZURE_LANGUAGE_ENDPOINT\n"
                        "  AZURE_LANGUAGE_KEY\n"
                    )
            elif args.redaction_strategy == "azure_openai":
                if not all([openai_endpoint, openai_key, openai_deployment]):
                    raise ValueError(
                        "Missing required environment variables for azure_openai strategy:\n"
                        "  AZURE_OPENAI_ENDPOINT\n"
                        "  AZURE_OPENAI_API_KEY\n"
                        "  AZURE_OPENAI_DEPLOYMENT\n"
                    )

        # Validate validation requirements if validation will be run
        if args.validate and args.stage in ("redact", "both"):
            if not all([openai_endpoint, openai_key, openai_deployment]):
                raise ValueError(
                    "Missing required environment variables for validation:\n"
                    "  AZURE_OPENAI_ENDPOINT\n"
                    "  AZURE_OPENAI_API_KEY\n"
                    "  AZURE_OPENAI_DEPLOYMENT\n"
                )
        
        # Create configurations
        conversion_config = ConversionConfig(
            endpoint=doc_endpoint,
            api_key=doc_key
        )
        
        redaction_config = RedactionConfig(
            strategy_type=args.redaction_strategy,
            language=args.language,
            language_endpoint=lang_endpoint,
            language_api_key=lang_key,
            openai_endpoint=openai_endpoint,
            openai_api_key=openai_key,
            openai_deployment=openai_deployment,
            enable_entity_logging=args.enable_entity_logging
        )
        
        validation_config = ValidationConfig(
            enabled=args.validate,
            openai_endpoint=openai_endpoint,
            openai_api_key=openai_key,
            openai_deployment=openai_deployment
        )
        
        pdf_config = PDFExportConfig(
            enabled=args.export_pdf
        )
        
        report_config = ReportConfig(
            enabled=not args.no_report,
            output_file=args.report_file
        )
        
        # Create filename anonymization config
        anonymization_config = AnonymizationConfig(
            enabled=not args.no_anonymize_filenames,
            detection_strategy=DetectionStrategy.AZURE_LANGUAGE,
            confidence_threshold=args.filename_confidence_threshold,
            hash_length=args.filename_hash_length,
            language=args.language,
            preserve_extensions=True,
            anonymize_all_folders=True,
            language_endpoint=lang_endpoint,
            language_api_key=lang_key
        )
        
        # Handle checkpoint clearing
        if args.clear_checkpoint:
            if args.storage_mode == "azure_blob":
                if not all([args.storage_account, args.output_container]):
                    raise ValueError("--storage-account and --output-container are required to clear checkpoint in azure_blob mode")
                
                # Parse container/folder from output_container
                def parse_container_path(path: str) -> tuple[str, str]:
                    parts = path.split('/', 1)
                    container = parts[0]
                    prefix = parts[1] if len(parts) > 1 else ""
                    return container, prefix
                
                output_container, output_prefix = parse_container_path(args.output_container)
                
                account_url = f"https://{args.storage_account}.blob.core.windows.net"
                adapter = create_storage_adapter({
                    "mode": "azure_blob",
                    "account_url": account_url,
                    "container": output_container,
                    "max_concurrency": args.batch_size
                })
                # Delete checkpoint blob
                from utils.checkpoint import CHECKPOINT_FILENAME
                blob_name = CHECKPOINT_FILENAME if not output_prefix else f"{output_prefix.rstrip('/')}/{CHECKPOINT_FILENAME}"
                try:
                    # adapter is a storage adapter with async methods - run in event loop
                    async def _delete():
                        await adapter.delete(blob_name)
                        await adapter.close()
                    asyncio.run(_delete())
                    logger.info("Checkpoint cleared from Azure output container - all files will be reprocessed")
                except Exception as e:
                    logger.error(f"Failed to clear checkpoint in Azure: {e}")
            else:
                checkpoint = CheckpointManager(args.output_dir)
                checkpoint.clear_checkpoint()
                logger.info("Checkpoint cleared - all files will be reprocessed")
        
        # Run pipeline
        # Validate positional args vs storage mode
        if args.storage_mode == "local":
            if args.input_dir is None or args.output_dir is None:
                parser.error("input_dir and output_dir are required for local storage mode")

        # Prepare storage config if using azure_blob
        storage_config = None
        if args.storage_mode == "azure_blob":
            if not all([args.storage_account, args.input_container, args.output_container]):
                raise ValueError(
                    "When using azure_blob storage_mode, you must provide --storage-account, --input-container and --output-container"
                )
            
            # Parse container/folder from input_container and output_container
            # Format: "container" or "container/folder" or "container/folder/subfolder"
            def parse_container_path(path: str) -> tuple[str, str]:
                parts = path.split('/', 1)
                container = parts[0]
                prefix = parts[1] if len(parts) > 1 else ""
                return container, prefix
            
            input_container, input_prefix = parse_container_path(args.input_container)
            output_container, output_prefix = parse_container_path(args.output_container)
            
            account_url = f"https://{args.storage_account}.blob.core.windows.net"
            storage_config = {
                "mode": "azure_blob",
                "account_url": account_url,
                "input_container": input_container,
                "output_container": output_container,
                "input_prefix": input_prefix,
                "output_prefix": output_prefix,
                "max_concurrency": args.batch_size
            }

        metrics = asyncio.run(execute_pipeline(
            storage_config if storage_config else args.input_dir,
            # For local, use provided output_dir; for azure_blob, use output_prefix from parsed container
            args.output_dir if args.storage_mode == "local" else (output_prefix if storage_config else ""),
            conversion_config,
            redaction_config,
            validation_config,
            pdf_config,
            report_config,
            anonymization_config,
            args.batch_size,
            enable_checkpoint=not args.no_checkpoint,
            stage=args.stage
        ))
        
        # Print summary
        metrics.print_summary()
        
        # Exit with error if any stage failed
        if metrics.converted_failed > 0 or metrics.redacted_failed > 0 or metrics.validated_failed > 0:
            sys.exit(1)
        
    except HttpResponseError as error:
        logger.error(f"Azure API Error: {error.message}")
        if hasattr(error, 'error') and error.error:
            logger.error(f"Error code: {error.error.code}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
