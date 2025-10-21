"""Pipeline metrics tracking."""

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class PipelineMetrics:
    """Metrics for the complete pipeline."""
    total_files: int = 0
    converted_success: int = 0
    converted_failed: int = 0
    redacted_success: int = 0
    redacted_failed: int = 0
    skipped_unsupported: int = 0
    skipped_checkpoint: int = 0
    total_pages: int = 0
    total_entities_redacted: int = 0
    conversion_duration: float = 0.0
    redaction_duration: float = 0.0
    
    # Redaction strategy info
    redaction_strategy: str = ""
    model_name: str = ""  # Model/deployment name for OpenAI strategy
    
    # Token usage metrics (for LLM-based operations)
    total_tokens_used: int = 0
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    
    # Validation metrics
    validation_enabled: bool = False
    validated_success: int = 0
    validated_failed: int = 0
    validation_pii_found: int = 0
    validation_duration: float = 0.0
    validation_tokens_used: int = 0
    validation_prompt_tokens: int = 0
    validation_completion_tokens: int = 0
    
    # PDF export metrics
    pdf_export_enabled: bool = False
    pdf_exported_success: int = 0
    pdf_exported_failed: int = 0
    pdf_export_duration: float = 0.0
    
    @property
    def total_duration(self) -> float:
        """Total pipeline duration."""
        return self.conversion_duration + self.redaction_duration + self.validation_duration + self.pdf_export_duration
    
    def print_summary(self):
        """Print pipeline summary."""
        logger.info("="*70)
        logger.info("ANONYMIZATION PIPELINE SUMMARY")
        logger.info("="*70)
        logger.info(f"Total input files: {self.total_files}")
        if self.skipped_unsupported > 0:
            logger.info(f"Skipped (unsupported format): {self.skipped_unsupported}")
        if self.skipped_checkpoint > 0:
            logger.info(f"Skipped (already processed): {self.skipped_checkpoint}")
        logger.info("")
        logger.info("Stage 1 - Document Conversion:")
        logger.info(f"  Successful: {self.converted_success}")
        logger.info(f"  Failed: {self.converted_failed}")
        logger.info(f"  Total pages: {self.total_pages}")
        logger.info(f"  Duration: {self.conversion_duration:.2f}s")
        logger.info("")
        strategy_label = self.redaction_strategy
        if self.model_name:
            strategy_label += f" / {self.model_name}"
        logger.info(f"Stage 2 - PII Redaction ({strategy_label}):")
        logger.info(f"  Successful: {self.redacted_success}")
        logger.info(f"  Failed: {self.redacted_failed}")
        logger.info(f"  Entities redacted: {self.total_entities_redacted}")
        logger.info(f"  Duration: {self.redaction_duration:.2f}s")
        if self.total_tokens_used > 0:
            logger.info(f"  Tokens used: {self.total_tokens_used:,} "
                       f"(prompt: {self.total_prompt_tokens:,}, "
                       f"completion: {self.total_completion_tokens:,})")
        logger.info("")
        
        if self.validation_enabled:
            logger.info("Stage 3 - PII Validation:")
            logger.info(f"  Successful: {self.validated_success}")
            logger.info(f"  Failed: {self.validated_failed}")
            logger.info(f"  Documents with PII found: {self.validation_pii_found}")
            logger.info(f"  Duration: {self.validation_duration:.2f}s")
            logger.info(f"  Tokens used: {self.validation_tokens_used:,} "
                       f"(prompt: {self.validation_prompt_tokens:,}, "
                       f"completion: {self.validation_completion_tokens:,})")
            logger.info("")
        
        if self.pdf_export_enabled:
            logger.info("Stage 4 - PDF Export:")
            logger.info(f"  Successful: {self.pdf_exported_success}")
            logger.info(f"  Failed: {self.pdf_exported_failed}")
            logger.info(f"  Duration: {self.pdf_export_duration:.2f}s")
            logger.info("")
        
        logger.info(f"Total pipeline duration: {self.total_duration:.2f}s")
        if self.redacted_success > 0:
            logger.info(f"Average time per document: {self.total_duration / self.redacted_success:.2f}s")
        logger.info("="*70)
