"""Pipeline orchestration for document anonymization."""

import asyncio
import logging
import time
import shutil
from pathlib import Path
from typing import List, Tuple, Dict

from .metrics import PipelineMetrics
from .conversion import ConversionConfig, ConversionFactory, convert_document, convert_doc_to_docx
from .redaction import RedactionConfig, ValidationConfig, create_redaction_strategy
from .redaction.validation import DocumentValidator
from .checkpoint import CheckpointManager
from .storage.factory import create_storage_adapter
from .pdf_export import PDFExportConfig, PDFExporter
from .report import ReportConfig, ReportManager
from .filename_anonymizer import FilenameAnonymizer, AnonymizationConfig

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = (".pdf", ".docx", ".xlsx", ".pptx", ".jpg", ".jpeg", ".png", ".tiff", ".bmp")
DOC_EXTENSION = ".doc"


def collect_input_files(input_dir: str, supported_extensions: Tuple[str, ...] | None = None, include_doc: bool = True) -> Tuple[List[Tuple[Path, Path]], int, Dict[str, int], Dict[str, int]]:
    """
    Collect supported files from input directory.
    
    Args:
        input_dir: Input directory path
        supported_extensions: Optional override for supported extensions
        include_doc: Whether to include .doc files (they will be converted to .docx)
        
    Returns:
        Tuple of (supported_files, total_skipped, folder_total_counts, folder_unsupported_counts)
        - supported_files: List of (file_path, relative_path) tuples for supported files
        - total_skipped: Total number of unsupported files
        - folder_total_counts: Dict mapping folder names to total file counts (all files)
        - folder_unsupported_counts: Dict mapping folder names to unsupported file counts
    """
    input_path = Path(input_dir)
    if not input_path.exists():
        raise FileNotFoundError(f"Input directory not found: {input_dir}")
    
    all_files = [f for f in input_path.rglob("*") if f.is_file()]
    
    input_file_tuples = []
    skipped = 0
    folder_total_counts: Dict[str, int] = {}
    folder_unsupported_counts: Dict[str, int] = {}
    
    for file in all_files:
        relative_path = file.relative_to(input_path)
        folder_name = relative_path.parts[0] if len(relative_path.parts) > 1 else "_root"
        
        # Count total files per folder
        folder_total_counts[folder_name] = folder_total_counts.get(folder_name, 0) + 1
        # Allow caller to override supported extensions (used for redaction-only which expects .md files)
        exts = SUPPORTED_EXTENSIONS if supported_extensions is None else supported_extensions
        
        # Check if file is supported or is a .doc file (when include_doc is True)
        if file.suffix.lower() in exts:
            input_file_tuples.append((file, relative_path))
        elif include_doc and file.suffix.lower() == DOC_EXTENSION:
            # Include .doc files - they will be converted to .docx before processing
            input_file_tuples.append((file, relative_path))
        else:
            skipped += 1
            folder_unsupported_counts[folder_name] = folder_unsupported_counts.get(folder_name, 0) + 1
            logger.warning(f"Skipping unsupported file: {file.relative_to(input_path)}")
    
    return sorted(input_file_tuples, key=lambda x: str(x[1])), skipped, folder_total_counts, folder_unsupported_counts


def _append_error_log(error_log_path: Path, stage: str, file_path: str) -> None:
    """
    Append an error entry to the error.log file. Each row format: stage,full_path_to_file
    """
    try:
        # Ensure parent directory exists
        error_log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(error_log_path, "a", encoding="utf-8") as fh:
            fh.write(f"{stage},{file_path}\n")
    except Exception:
        # Best-effort logging; don't let this break the pipeline
        logger.debug(f"Failed to write to error log: {error_log_path}")


async def run_conversion_stage(
    input_file_tuples: List[Tuple[Path, Path]],
    temp_dir: Path,
    conversion_config: ConversionConfig,
    batch_size: int,
    metrics: PipelineMetrics
    ,
    error_log_path: Path | None = None
) -> Tuple[Dict[str, Dict[str, int]], Dict[str, Dict[str, float]]]:
    """
    Run document conversion stage.
    
    Args:
        input_file_tuples: List of (file_path, relative_path) tuples
        temp_dir: Temporary directory for markdown files
        conversion_config: Conversion configuration
        batch_size: Number of documents to process concurrently
        metrics: Pipeline metrics to update
        
    Returns:
        Tuple of (folder_stats, folder_timings)
        - folder_stats: Dictionary mapping folder names to their success/total file counts
        - folder_timings: Dictionary mapping folder names to start/end times
    """
    logger.info("="*70)
    logger.info("STAGE 1: Converting documents to Markdown")
    logger.info("="*70)
    
    # Create temporary directory for DOC to DOCX conversions
    doc_temp_dir = temp_dir.parent / ".temp_doc_conversion"
    doc_temp_dir.mkdir(parents=True, exist_ok=True)
    
    # Pre-process DOC files: convert to DOCX
    processed_file_tuples = []
    for file, relative_path in input_file_tuples:
        if file.suffix.lower() == DOC_EXTENSION:
            # Convert DOC to DOCX
            logger.info(f"Converting DOC to DOCX: {relative_path}")
            success, docx_path, error_msg = convert_doc_to_docx(str(file), str(doc_temp_dir))
            
            if success:
                # Replace with converted DOCX path, keep original relative path
                processed_file_tuples.append((Path(docx_path), relative_path))
                metrics.doc_converted += 1
            else:
                # Log error and skip this file
                logger.error(f"Failed to convert DOC file: {relative_path} - {error_msg}")
                metrics.converted_failed += 1
                if error_log_path is not None:
                    _append_error_log(error_log_path, "doc_conversion", str(file.resolve()))
        else:
            # Keep as is for supported formats
            processed_file_tuples.append((file, relative_path))
    
    doc_client = ConversionFactory.create_client(conversion_config)
    
    # Track success per folder
    folder_stats: Dict[str, Dict[str, int]] = {}
    folder_timings: Dict[str, Dict[str, float]] = {}
    
    conversion_start = time.time()
    
    try:
        async with doc_client:
            for i in range(0, len(processed_file_tuples), batch_size):
                batch = processed_file_tuples[i:i + batch_size]
                batch_num = i // batch_size + 1
                total_batches = (len(processed_file_tuples) + batch_size - 1) // batch_size
                
                logger.info(f"\nConversion batch {batch_num}/{total_batches} ({len(batch)} files)")
                
                # Record batch start time
                batch_start_time = time.time()
                
                # Create conversion tasks
                tasks = []
                for file, relative_path in batch:
                    # Preserve original filename with extension, then add .md
                    output_file = temp_dir / (str(relative_path) + ".md")
                    tasks.append(convert_document(str(file), str(output_file), doc_client))
                
                # Execute batch
                results = await asyncio.gather(*tasks, return_exceptions=True)
                
                # Record batch end time
                batch_end_time = time.time()
                
                # Process results and track per-folder success
                for (file, relative_path), result in zip(batch, results):
                    # Extract first-level folder
                    folder_name = relative_path.parts[0] if len(relative_path.parts) > 1 else "_root"
                    
                    if folder_name not in folder_stats:
                        folder_stats[folder_name] = {"total": 0, "success": 0}
                        folder_timings[folder_name] = {"start": batch_start_time, "end": batch_end_time}
                    else:
                        # Update end time with latest batch that processed this folder
                        folder_timings[folder_name]["end"] = batch_end_time
                    folder_stats[folder_name]["total"] += 1
                    
                    if isinstance(result, Exception):
                        metrics.converted_failed += 1
                        if error_log_path is not None:
                            _append_error_log(error_log_path, "convert", str(file.resolve()))
                    elif isinstance(result, tuple):
                        success, pages, error = result
                        if success:
                            metrics.converted_success += 1
                            metrics.total_pages += pages
                            folder_stats[folder_name]["success"] += 1
                        else:
                            metrics.converted_failed += 1
                            if error_log_path is not None:
                                _append_error_log(error_log_path, "convert", str(file.resolve()))
    
    finally:
        metrics.conversion_duration = time.time() - conversion_start
        logger.info(f"\nStage 1 complete: {metrics.converted_success} successful, "
                   f"{metrics.converted_failed} failed ({metrics.conversion_duration:.2f}s)")
        
        # Clean up temporary DOC conversion directory
        try:
            shutil.rmtree(doc_temp_dir, ignore_errors=True)
        except Exception:
            pass
        
        return folder_stats, folder_timings


async def run_redaction_stage(
    temp_dir: Path,
    final_output: Path,
    redaction_config: RedactionConfig,
    batch_size: int,
    metrics: PipelineMetrics,
    folder_timings: Dict[str, Dict[str, float]]
    ,
    error_log_path: Path | None = None
) -> Dict[str, Dict[str, int]]:
    """
    Run PII redaction stage using strategy pattern.
    
    Args:
        temp_dir: Temporary directory with markdown files
        final_output: Final output directory
        redaction_config: Redaction configuration
        batch_size: Number of documents to process concurrently
        metrics: Pipeline metrics to update
        folder_timings: Dictionary to update with folder timing information
        
    Returns:
        Dictionary mapping folder names to their success/total file counts
    """
    logger.info("\n" + "="*70)
    logger.info(f"STAGE 2: Redacting PII (strategy: {redaction_config.strategy_type})")
    logger.info("="*70)
    
    # Create redaction strategy
    strategy = create_redaction_strategy(redaction_config)
    
    # Track success per folder
    folder_stats: Dict[str, Dict[str, int]] = {}
    
    redaction_start = time.time()
    
    try:
        async with strategy:
            # Get all markdown files from temp directory recursively
            markdown_file_tuples = []
            for md_file in temp_dir.rglob("*.md"):
                relative_path = md_file.relative_to(temp_dir)
                markdown_file_tuples.append((md_file, relative_path))
            
            markdown_file_tuples = sorted(markdown_file_tuples, key=lambda x: str(x[1]))
            
            for i in range(0, len(markdown_file_tuples), batch_size):
                batch = markdown_file_tuples[i:i + batch_size]
                batch_num = i // batch_size + 1
                total_batches = (len(markdown_file_tuples) + batch_size - 1) // batch_size
                
                logger.info(f"\nRedaction batch {batch_num}/{total_batches} ({len(batch)} files)")
                
                # Record batch start time
                batch_start_time = time.time()
                
                # Create redaction tasks
                tasks = []
                for file, relative_path in batch:
                    output_file = final_output / relative_path
                    tasks.append(strategy.redact_document(str(file), str(output_file)))
                
                # Execute batch
                results = await asyncio.gather(*tasks, return_exceptions=True)
                
                # Record batch end time
                batch_end_time = time.time()
                
                # Process results and track per-folder success
                for (file, relative_path), result in zip(batch, results):
                    # Extract first-level folder
                    folder_name = relative_path.parts[0] if len(relative_path.parts) > 1 else "_root"
                    
                    if folder_name not in folder_stats:
                        folder_stats[folder_name] = {"total": 0, "success": 0}
                    folder_stats[folder_name]["total"] += 1
                    # Update end time for this folder with latest batch
                    if folder_name in folder_timings:
                        folder_timings[folder_name]["end"] = batch_end_time
                    
                    if isinstance(result, Exception):
                        metrics.redacted_failed += 1
                        if error_log_path is not None:
                            _append_error_log(error_log_path, "redact", str(file.resolve()))
                    else:
                        if result.success:
                            metrics.redacted_success += 1
                            metrics.total_entities_redacted += result.entities_redacted
                            folder_stats[folder_name]["success"] += 1
                            
                            # Track token usage if available
                            if result.metadata:
                                tokens = result.metadata.get("tokens_used", 0)
                                prompt_tokens = result.metadata.get("prompt_tokens", 0)
                                completion_tokens = result.metadata.get("completion_tokens", 0)
                                
                                metrics.total_tokens_used += tokens
                                metrics.total_prompt_tokens += prompt_tokens
                                metrics.total_completion_tokens += completion_tokens
                        else:
                            metrics.redacted_failed += 1
                            if error_log_path is not None:
                                _append_error_log(error_log_path, "redact", str(file.resolve()))
    
    finally:
        metrics.redaction_duration = time.time() - redaction_start
        logger.info(f"\nStage 2 complete: {metrics.redacted_success} successful, "
                   f"{metrics.redacted_failed} failed ({metrics.redaction_duration:.2f}s)")
        if metrics.total_tokens_used > 0:
            logger.info(f"Total tokens used: {metrics.total_tokens_used:,}")
        return folder_stats


async def run_validation_stage(
    final_output: Path,
    validation_config: ValidationConfig,
    batch_size: int,
    metrics: PipelineMetrics
    ,
    error_log_path: Path | None = None
):
    """
    Run optional LLM-based PII validation stage.
    
    Args:
        final_output: Directory with redacted markdown files
        validation_config: Validation configuration
        batch_size: Number of documents to process concurrently
        metrics: Pipeline metrics to update
    """
    if not validation_config.enabled:
        return
    
    logger.info("\n" + "="*70)
    logger.info("STAGE 3: Validating redacted documents for remaining PII")
    logger.info("="*70)
    
    validator = DocumentValidator(validation_config)
    
    validation_start = time.time()
    
    try:
        async with validator:
            # Get all markdown files from output directory
            markdown_files = sorted(final_output.rglob("*.md"))
            
            for i in range(0, len(markdown_files), batch_size):
                batch = markdown_files[i:i + batch_size]
                batch_num = i // batch_size + 1
                total_batches = (len(markdown_files) + batch_size - 1) // batch_size
                
                logger.info(f"\nValidation batch {batch_num}/{total_batches} ({len(batch)} files)")
                
                # Create validation tasks
                tasks = [validator.validate_document(str(file)) for file in batch]
                
                # Execute batch
                results = await asyncio.gather(*tasks, return_exceptions=True)
                
                # Process results paired with files so we can log failures per-file
                for file, result in zip(batch, results):
                    if isinstance(result, Exception):
                        metrics.validated_failed += 1
                        if error_log_path is not None:
                            _append_error_log(error_log_path, "validate", str(Path(file).resolve()))
                    else:
                        if result.success:
                            metrics.validated_success += 1
                            if result.has_pii:
                                metrics.validation_pii_found += 1
                            
                            # Track token usage
                            metrics.validation_tokens_used += result.tokens_used
                            metrics.validation_prompt_tokens += result.prompt_tokens
                            metrics.validation_completion_tokens += result.completion_tokens
                        else:
                            metrics.validated_failed += 1
                            if error_log_path is not None:
                                _append_error_log(error_log_path, "validate", str(Path(file).resolve()))
    
    finally:
        metrics.validation_duration = time.time() - validation_start
        logger.info(f"\nStage 3 complete: {metrics.validated_success} successful, "
                   f"{metrics.validated_failed} failed, "
                   f"{metrics.validation_pii_found} with PII found ({metrics.validation_duration:.2f}s)")
        if metrics.validation_tokens_used > 0:
            logger.info(f"Total validation tokens used: {metrics.validation_tokens_used:,}")


async def run_pdf_export_stage(
    final_output: Path,
    pdf_output: Path,
    pdf_config: PDFExportConfig,
    metrics: PipelineMetrics
    ,
    error_log_path: Path | None = None
):
    """
    Run optional PDF export stage.
    
    Args:
        final_output: Directory with redacted markdown files
        pdf_output: Directory for PDF output
        pdf_config: PDF export configuration
        metrics: Pipeline metrics to update
    """
    if not pdf_config.enabled:
        return
    
    logger.info("\n" + "="*70)
    logger.info("STAGE 4: Exporting to PDF")
    logger.info("="*70)
    
    exporter = PDFExporter(pdf_config)
    
    pdf_start = time.time()
    
    try:
        # Get all markdown files from output directory, excluding temp folder
        all_markdown_files = final_output.rglob("*.md")
        markdown_files = sorted([
            f for f in all_markdown_files 
            if ".temp_markdown" not in f.parts
        ])
        
        logger.info(f"\nExporting {len(markdown_files)} files to PDF")
        
        for md_file in markdown_files:
            relative_path = md_file.relative_to(final_output)
            pdf_file = pdf_output / relative_path.with_suffix(".pdf")
            
            success, error_msg = exporter.convert_markdown_to_pdf(
                str(md_file),
                str(pdf_file)
            )
            
            if success:
                metrics.pdf_exported_success += 1
            else:
                metrics.pdf_exported_failed += 1
                if error_log_path is not None:
                    _append_error_log(error_log_path, "pdf_export", str(md_file.resolve()))
    
    finally:
        metrics.pdf_export_duration = time.time() - pdf_start
        logger.info(f"\nStage 4 complete: {metrics.pdf_exported_success} successful, "
                   f"{metrics.pdf_exported_failed} failed ({metrics.pdf_export_duration:.2f}s)")


async def execute_pipeline(
    input_dir: str,
    output_dir: str,
    conversion_config: ConversionConfig,
    redaction_config: RedactionConfig,
    validation_config: ValidationConfig,
    pdf_config: PDFExportConfig,
    report_config: ReportConfig,
    anonymization_config: AnonymizationConfig,
    batch_size: int = 5,
    enable_checkpoint: bool = True,
    stage: str = "both"
) -> PipelineMetrics:
    """
    Execute the complete anonymization pipeline.
    
    Args:
        input_dir: Input directory with documents to process
        output_dir: Final output directory for anonymized documents
        conversion_config: Configuration for document conversion
        redaction_config: Configuration for PII redaction
        validation_config: Configuration for optional PII validation
        pdf_config: Configuration for optional PDF export
        report_config: Configuration for CSV reporting
        anonymization_config: Configuration for filename/folder anonymization
        batch_size: Number of documents to process concurrently
        enable_checkpoint: Enable checkpoint-based incremental processing
        stage: Which pipeline stage to run ("convert", "redact", or "both")
        
    Returns:
        PipelineMetrics with processing statistics
    """
    metrics = PipelineMetrics()
    metrics.validation_enabled = validation_config.enabled
    metrics.pdf_export_enabled = pdf_config.enabled
    metrics.redaction_strategy = redaction_config.strategy_type
    
    # Set model name for OpenAI strategy
    if redaction_config.strategy_type == "azure_openai" and redaction_config.openai_deployment:
        metrics.model_name = redaction_config.openai_deployment
    
    # Initialize storage adapters (optional for azure blob)
    storage_adapter_in = None
    storage_adapter_out = None
    use_azure_blob = False
    if isinstance(input_dir, dict) and input_dir.get("mode") == "azure_blob":
        # Support passing storage config via input_dir dict (backwards compatible)
        storage_config = input_dir
        # Expect storage_config to contain keys: mode, account_url, input_container, output_container, input_prefix, output_prefix
        input_container = storage_config.get("input_container")
        output_container = storage_config.get("output_container")
        if not input_container or not output_container:
            raise ValueError("storage_config must include input_container and output_container for azure_blob mode")
        adapter_in_config = {
            "mode": "azure_blob",
            "account_url": storage_config["account_url"],
            "container": input_container,
            "max_concurrency": storage_config.get("max_concurrency", 4)
        }
        adapter_out_config = {
            "mode": "azure_blob",
            "account_url": storage_config["account_url"],
            "container": output_container,
            "max_concurrency": storage_config.get("max_concurrency", 4)
        }
        storage_adapter_in = create_storage_adapter(adapter_in_config)
        storage_adapter_out = create_storage_adapter(adapter_out_config)
        use_azure_blob = True
        # Extract prefixes
        input_prefix = storage_config.get("input_prefix", "")
        output_prefix = storage_config.get("output_prefix", "")
        # Use local temp directories for processing
        temp_root = Path(output_dir) / ".azure_workdir"
        temp_input_root = temp_root / "input"
        temp_output_root = temp_root / "output"
        temp_input_root.mkdir(parents=True, exist_ok=True)
        temp_output_root.mkdir(parents=True, exist_ok=True)
        # Download input blobs to temp_input_root
        logger.info("Downloading input blobs from Azure Blob Storage to local workspace...")
        blob_list = await storage_adapter_in.list_files(prefix=input_prefix)
        # Filter and download in parallel batches
        download_tasks = []
        for blob_name in sorted(blob_list):
            # Create local path relative to prefix
            rel_path = Path(blob_name[len(input_prefix):].lstrip('/')) if input_prefix else Path(blob_name)
            local_path = temp_input_root / rel_path
            local_path.parent.mkdir(parents=True, exist_ok=True)
            download_tasks.append((blob_name, local_path))

        # Download with concurrency
        sem = asyncio.Semaphore(batch_size)

        async def _download_blob(blob_name, local_path):
            async with sem:
                try:
                    data = await storage_adapter_in.read_bytes(blob_name)
                    local_path.write_bytes(data)
                except Exception as e:
                    logger.error(f"Failed to download blob {blob_name}: {e}")
                    # Log as conversion-stage error (file couldn't be retrieved)
                    try:
                        _append_error_log(error_log_path, "download", blob_name)
                    except Exception:
                        logger.debug("Failed to append download error to error.log")

        # Run downloads in batches to avoid creating too many tasks at once
        for i in range(0, len(download_tasks), batch_size):
            batch = download_tasks[i:i + batch_size]
            tasks = [asyncio.create_task(_download_blob(bn, lp)) for bn, lp in batch]
            await asyncio.gather(*tasks)

        # Substitute local paths for pipeline
        original_input_dir = input_dir
        input_dir = str(temp_input_root)
        # Use the temp output as final output working dir
        original_output_dir = output_dir
        output_dir = str(temp_output_root)

    # If using azure blob, attempt to retrieve existing checkpoint from output container
    if use_azure_blob and storage_adapter_out is not None and enable_checkpoint:
        try:
            from .checkpoint import CHECKPOINT_FILENAME
            blob_name = f"{output_prefix.rstrip('/')}/{CHECKPOINT_FILENAME}" if output_prefix else CHECKPOINT_FILENAME
            if await storage_adapter_out.exists(blob_name):
                data = await storage_adapter_out.read_bytes(blob_name)
                (Path(output_dir) / CHECKPOINT_FILENAME).parent.mkdir(parents=True, exist_ok=True)
                (Path(output_dir) / CHECKPOINT_FILENAME).write_bytes(data)
                logger.info("Downloaded checkpoint from Azure blob to local output directory")
        except Exception:
            logger.debug("No checkpoint blob found or failed to download checkpoint; continuing")

    # Initialize checkpoint manager
    checkpoint = CheckpointManager(output_dir) if enable_checkpoint else None
    
    # Initialize report manager
    report_manager = ReportManager(report_config, output_dir)

    # Prepare error log path and clear existing error.log
    error_log_path = Path(output_dir) / "error.log"
    try:
        if error_log_path.exists():
            error_log_path.unlink()
    except Exception:
        logger.debug("Could not clear existing error.log; continuing")
    
    # Collect input files (returns all counts including unsupported)
    if stage == "redact":
        input_file_tuples, skipped, folder_total_counts, folder_unsupported_counts = collect_input_files(input_dir, supported_extensions=(".md",), include_doc=False)
    else:
        input_file_tuples, skipped, folder_total_counts, folder_unsupported_counts = collect_input_files(input_dir, include_doc=True)
    metrics.skipped_unsupported = skipped
    
    # PRE-STAGE 0: Filename and Folder Anonymization
    # Only run anonymization for "convert" or "both" stages
    # For "redact" stage, just load existing mappings for reporting
    folder_name_reverse_map = {}
    if anonymization_config and anonymization_config.enabled:
        # Pass storage adapter if using Azure Blob mode
        storage_adapter_for_mappings = storage_adapter_out if use_azure_blob else None
        anonymizer = FilenameAnonymizer(
            anonymization_config, 
            Path(output_dir) if not use_azure_blob else temp_output_root,
            storage_adapter=storage_adapter_for_mappings
        )
        
        try:
            async with anonymizer:
                if stage in ("convert", "both"):
                    # Run full anonymization for convert/both stages
                    logger.info("="*70)
                    logger.info("PRE-STAGE 0: Filename & Folder Anonymization (Partial Replacement)")
                    logger.info("="*70)
                    logger.info(f"Detection strategy: {anonymization_config.detection_strategy.value}")
                    logger.info(f"Confidence threshold: {anonymization_config.confidence_threshold}")
                    logger.info(f"Hash length: {anonymization_config.hash_length} characters")
                    if use_azure_blob:
                        logger.info(f"Storage mode: Azure Blob Storage")
                    logger.info("")
                    
                    # Load existing entity cache if available
                    if use_azure_blob:
                        # Load from blob storage
                        await anonymizer.load_entity_cache_from_blob(prefix=output_prefix)
                    else:
                        # Load from local filesystem
                        anonymizer.load_entity_cache()
                    
                    # Step 1: Anonymize folder names
                    logger.info("Step 1: Anonymizing folders...")
                    input_file_tuples, folder_mappings = await anonymizer.anonymize_folders(
                        input_file_tuples
                    )
                    folder_pii_count = sum(1 for m in folder_mappings if m["contained_pii"])
                    logger.info(f"  Anonymized {folder_pii_count} folders with PII (out of {len(folder_mappings)} total)")
                    logger.info("")
                    
                    # Build reverse mapping: anonymized_folder -> original_folder
                    # This is needed for reporting to show original names
                    folder_name_reverse_map = {
                        m["anonymized_folder"]: m["original_folder"]
                        for m in folder_mappings
                    }
                    
                    # Update folder_total_counts and folder_unsupported_counts to use anonymized names as keys
                    # But keep values mapped correctly
                    updated_folder_total_counts = {}
                    updated_folder_unsupported_counts = {}
                    for original_name, count in folder_total_counts.items():
                        # Find the anonymized name for this original name
                        anonymized_name = original_name  # default to original
                        for m in folder_mappings:
                            if m["original_folder"] == original_name:
                                anonymized_name = m["anonymized_folder"]
                                break
                        updated_folder_total_counts[anonymized_name] = count
                    
                    for original_name, count in folder_unsupported_counts.items():
                        anonymized_name = original_name  # default to original
                        for m in folder_mappings:
                            if m["original_folder"] == original_name:
                                anonymized_name = m["anonymized_folder"]
                                break
                        updated_folder_unsupported_counts[anonymized_name] = count
                    
                    # Replace the old dictionaries with updated ones
                    folder_total_counts = updated_folder_total_counts
                    folder_unsupported_counts = updated_folder_unsupported_counts
                    
                    # Step 2: Anonymize filenames
                    logger.info("Step 2: Anonymizing filenames...")
                    input_file_tuples, filename_mappings = await anonymizer.anonymize_filenames(
                        input_file_tuples
                    )
                    file_pii_count = sum(1 for m in filename_mappings if m["contained_pii"])
                    logger.info(f"  Anonymized {file_pii_count} filenames with PII (out of {len(filename_mappings)} total)")
                    logger.info("")
                    
                    # Step 3: Save mappings
                    if use_azure_blob:
                        # Save to blob storage
                        await anonymizer.save_mappings_to_blob(
                            filename_mappings, 
                            folder_mappings,
                            prefix=output_prefix
                        )
                    else:
                        # Save to local filesystem
                        anonymizer.save_mappings(filename_mappings, folder_mappings)
                    
                    logger.info("")
                    logger.info(f"Pre-Stage 0 complete")
                    logger.info("")
                
                elif stage == "redact":
                    # For redact-only stage, just load existing mappings for reporting
                    logger.info("Loading existing folder mappings for reporting...")
                    mapping_path = Path(output_dir) / ".mappings" / "folder_mapping.json"
                    if mapping_path.exists():
                        import json
                        with open(mapping_path, 'r', encoding='utf-8') as f:
                            folder_mappings = json.load(f)
                            folder_name_reverse_map = {
                                m["anonymized_folder"]: m["original_folder"]
                                for m in folder_mappings
                            }
                            logger.info(f"Loaded {len(folder_mappings)} folder mappings")
                    else:
                        logger.debug("No existing folder mappings found")
                
        except Exception as e:
            logger.error(f"Filename anonymization failed: {e}")
            raise
    
    # Filter out files from completed folders
    if checkpoint:
        input_file_tuples, skipped_checkpoint = checkpoint.filter_pending_files(input_file_tuples)
        metrics.skipped_checkpoint = skipped_checkpoint
        input_file_tuples, skipped_checkpoint = checkpoint.filter_pending_files(input_file_tuples)
        metrics.skipped_checkpoint = skipped_checkpoint
    
    metrics.total_files = len(input_file_tuples)
    
    if not input_file_tuples:
        logger.error("No supported documents found in input directory")
        return metrics
    
    logger.info(f"Found {len(input_file_tuples)} documents to process")
    
    # Create temporary and output directories
    # If redact-only: assume input_dir already contains markdown files, so use it as temp_dir
    if stage == "redact":
        temp_dir = Path(input_dir)
    else:
        temp_dir = Path(output_dir) / ".temp_markdown"
    temp_dir.mkdir(parents=True, exist_ok=True)
    
    final_output = Path(output_dir)
    final_output.mkdir(parents=True, exist_ok=True)
    
    try:
        # Stage 1: Convert documents to Markdown
        if stage in ("convert", "both"):
            conversion_folder_stats, folder_timings = await run_conversion_stage(
                input_file_tuples,
                temp_dir,
                conversion_config,
                batch_size,
                metrics
                ,
                error_log_path
            )
        else:
            # When redaction-only, we didn't run conversion; build empty conversion stats
            conversion_folder_stats = {}
            folder_timings = {}
        
        # Only proceed to stage 2 if we have converted files (when conversion was run)
        if stage in ("convert", "both") and metrics.converted_success == 0:
            logger.error("No documents were successfully converted. Aborting pipeline.")
            return metrics
        
        redaction_folder_stats = {}
        if stage in ("redact", "both"):
            # If stage==redact: ensure input contains markdown files
            redaction_folder_stats = await run_redaction_stage(
                temp_dir,
                final_output,
                redaction_config,
                batch_size,
                metrics,
                folder_timings
                ,
                error_log_path
            )
        
        # Mark folders as completed if all files succeeded
        if checkpoint:
            for folder_name, stats in redaction_folder_stats.items():
                if stats["success"] == stats["total"] and stats["total"] > 0:
                    checkpoint.mark_folder_completed(
                        folder_name,
                        stats["total"],
                        stats["success"]
                    )
                else:
                    logger.warning(
                        f"Folder '{folder_name}' not marked as completed: "
                        f"{stats['success']}/{stats['total']} files succeeded"
                    )
        
        # Stage 3: Optional validation
        if validation_config.enabled and metrics.redacted_success > 0:
            await run_validation_stage(
                final_output,
                validation_config,
                batch_size,
                metrics
                ,
                error_log_path
            )
        
        # Stage 4: Optional PDF export
        if pdf_config.enabled and metrics.redacted_success > 0:
            pdf_output = final_output.parent / (final_output.name + "_pdf")
            await run_pdf_export_stage(
                final_output,
                pdf_output,
                pdf_config,
                metrics
                ,
                error_log_path
            )

        # If only converting, copy markdowns from temp_dir to final_output for output persistence
        if stage == "convert":
            for md_file in Path(temp_dir).rglob("*.md"):
                rel = md_file.relative_to(temp_dir)
                dest = final_output / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                try:
                    dest.write_bytes(md_file.read_bytes())
                except Exception as e:
                    logger.error(f"Failed to persist converted file {md_file} to output: {e}")
                    if error_log_path is not None:
                        _append_error_log(error_log_path, "convert", str(md_file.resolve()))
        
        # Generate folder-level reports
        for anonymized_folder_name in folder_total_counts.keys():
            # Get original folder name for display (if anonymized)
            original_folder_name = folder_name_reverse_map.get(anonymized_folder_name, anonymized_folder_name) if 'folder_name_reverse_map' in locals() else anonymized_folder_name
            
            timing = folder_timings.get(anonymized_folder_name, {"start": 0.0, "end": 0.0})
            duration = timing["end"] - timing["start"] if timing["end"] > 0 else 0.0
            total_input_count = folder_total_counts.get(anonymized_folder_name, 0)
            unsupported_count = folder_unsupported_counts.get(anonymized_folder_name, 0)
            
            conv_stats = conversion_folder_stats.get(anonymized_folder_name, {"success": 0, "total": 0})
            red_stats = redaction_folder_stats.get(anonymized_folder_name, {"success": 0, "total": 0})
            
            output_count = red_stats.get("success", 0)
            
            report_manager.add_folder_report(
                folder_name=original_folder_name,  # Use original name for reporting
                duration=duration,
                input_count=total_input_count,
                unsupported_count=unsupported_count,
                output_count=output_count,
                conversion_success=conv_stats.get("success", 0),
                conversion_failed=conv_stats.get("total", 0) - conv_stats.get("success", 0),
                redaction_success=red_stats.get("success", 0),
                redaction_failed=red_stats.get("total", 0) - red_stats.get("success", 0),
                stage=stage
            )
        
        # Print summary table and write CSV report
        report_manager.print_summary_table()
        report_manager.write_report()
    
    finally:
        # Clean up temporary directory
        logger.info("\nCleaning up temporary files...")
        shutil.rmtree(temp_dir, ignore_errors=True)

    # If using azure blob storage, upload outputs back to the container and upload checkpoint
    if use_azure_blob and storage_adapter_in is not None and storage_adapter_out is not None:
            logger.info("Uploading anonymized outputs to Azure Blob Storage...")
            # Upload final markdown files
            for md_file in Path(output_dir).rglob("*.md"):
                rel = md_file.relative_to(output_dir)
                blob_name = f"{output_prefix.rstrip('/')}/{rel.as_posix()}" if output_prefix else rel.as_posix()
                content = md_file.read_bytes()
                try:
                    await storage_adapter_out.write_bytes(blob_name, content)
                except Exception as e:
                    logger.error(f"Failed to upload blob {blob_name}: {e}")
                    try:
                        _append_error_log(error_log_path, "upload", str(md_file.resolve()))
                    except Exception:
                        logger.debug("Failed to append upload error to error.log")

            # Upload PDFs if any
            pdf_dir = Path(output_dir).parent / (Path(output_dir).name + "_pdf")
            if pdf_dir.exists():
                for pdf_file in pdf_dir.rglob("*.pdf"):
                    rel = pdf_file.relative_to(pdf_dir)
                    # Put PDFs under output_prefix with same relative path
                    blob_name = f"{output_prefix.rstrip('/')}/{rel.as_posix()}" if output_prefix else rel.as_posix()
                    content = pdf_file.read_bytes()
                    try:
                        await storage_adapter_out.write_bytes(blob_name, content)
                    except Exception as e:
                        logger.error(f"Failed to upload PDF blob {blob_name}: {e}")
                        try:
                            _append_error_log(error_log_path, "upload", str(pdf_file.resolve()))
                        except Exception:
                            logger.debug("Failed to append PDF upload error to error.log")

            # Upload checkpoint file if exists
            checkpoint_path = Path(output_dir) / CHECKPOINT_FILENAME
            try:
                    if checkpoint_path.exists():
                        blob_name = f"{output_prefix.rstrip('/')}/{CHECKPOINT_FILENAME}" if output_prefix else CHECKPOINT_FILENAME
                        try:
                            await storage_adapter_out.write_bytes(blob_name, checkpoint_path.read_bytes())
                        except Exception as e:
                            logger.error(f"Failed to upload checkpoint blob {blob_name}: {e}")
                            try:
                                _append_error_log(error_log_path, "upload", str(checkpoint_path.resolve()))
                            except Exception:
                                logger.debug("Failed to append checkpoint upload error to error.log")
            except NameError:
                # CHECKPOINT_FILENAME may not be in scope here; import it
                from .checkpoint import CHECKPOINT_FILENAME
                checkpoint_path = Path(output_dir) / CHECKPOINT_FILENAME
                if checkpoint_path.exists():
                    blob_name = f"{output_prefix.rstrip('/')}/{CHECKPOINT_FILENAME}" if output_prefix else CHECKPOINT_FILENAME
                    await storage_adapter_out.write_bytes(blob_name, checkpoint_path.read_bytes())

            # Upload error.log if present
            error_log_file = Path(output_dir) / "error.log"
            if error_log_file.exists():
                blob_name = f"{output_prefix.rstrip('/')}/{error_log_file.name}" if output_prefix else error_log_file.name
                await storage_adapter_out.write_bytes(blob_name, error_log_file.read_bytes())

            # Attempt to close the adapter (clean credentials)
            try:
                await storage_adapter_in.close()
                await storage_adapter_out.close()
            except Exception:
                pass
            
            # Optionally clean up local workdir
            try:
                shutil.rmtree(temp_root, ignore_errors=True)
            except Exception:
                pass
    
    return metrics
