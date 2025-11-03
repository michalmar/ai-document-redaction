"""Pipeline reporting and CSV logging functionality."""

import csv
import logging
from pathlib import Path
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class FolderReport:
    """Report data for a single first-level folder."""
    timestamp: str
    folder_name: str
    duration_seconds: float
    input_document_count: int
    unsupported_count: int
    output_document_count: int
    processed_without_issues: bool
    issue_count: int
    conversion_success: int
    conversion_failed: int
    redaction_success: int
    redaction_failed: int
    validation_success: int
    validation_failed: int
    pdf_export_success: int
    pdf_export_failed: int


@dataclass
class ReportConfig:
    """Configuration for pipeline reporting."""
    enabled: bool = True
    output_file: Optional[str] = None
    
    def get_report_path(self, output_dir: str) -> Path:
        """
        Get the path for the report file.
        
        Args:
            output_dir: Base output directory
            
        Returns:
            Path to report CSV file
        """
        if self.output_file:
            return Path(self.output_file)
        return Path(output_dir) / "pipeline_report.csv"


class ReportManager:
    """Manage pipeline reporting and CSV logging."""
    
    CSV_HEADERS = [
        "timestamp",
        "folder_name",
        "duration_seconds",
        "input_document_count",
        "unsupported_count",
        "output_document_count",
        "processed_without_issues",
        "issue_count",
        "conversion_success",
        "conversion_failed",
        "redaction_success",
        "redaction_failed",
        "validation_success",
        "validation_failed",
        "pdf_export_success",
        "pdf_export_failed"
    ]
    
    def __init__(self, config: ReportConfig, output_dir: str):
        """
        Initialize report manager.
        
        Args:
            config: ReportConfig instance
            output_dir: Base output directory for reports
        """
        self.config = config
        self.report_path = config.get_report_path(output_dir)
        self.folder_reports: List[FolderReport] = []
    
    def add_folder_report(
        self,
        folder_name: str,
        duration: float,
        input_count: int,
        unsupported_count: int,
        output_count: int,
        conversion_success: int,
        conversion_failed: int,
        redaction_success: int,
        redaction_failed: int,
        validation_success: int = 0,
        validation_failed: int = 0,
        pdf_export_success: int = 0,
        pdf_export_failed: int = 0,
        stage: str = "both"
    ):
        """
        Add a folder processing report.
        
        Args:
            folder_name: Name of the first-level folder
            duration: Processing duration in seconds
            input_count: Total number of files in folder (supported + unsupported)
            unsupported_count: Number of unsupported files (not processed)
            output_count: Number of successfully processed documents
            conversion_success: Number of successful conversions
            conversion_failed: Number of failed conversions
            redaction_success: Number of successful redactions
            redaction_failed: Number of failed redactions
            validation_success: Number of successful validations
            validation_failed: Number of failed validations
            pdf_export_success: Number of successful PDF exports
            pdf_export_failed: Number of failed PDF exports
            stage: Pipeline stage that was run ("convert", "redact", or "both")
        """
        issue_count = (
            conversion_failed + 
            redaction_failed + 
            validation_failed + 
            pdf_export_failed
        )
        
        supported_count = input_count - unsupported_count
        
        # Determine success based on which stage was run
        if stage == "convert":
            # For convert-only, success means all conversions succeeded
            processed_without_issues = issue_count == 0 and conversion_success == supported_count
        elif stage == "redact":
            # For redact-only, success means all redactions succeeded
            processed_without_issues = issue_count == 0 and redaction_success == supported_count
        else:
            # For "both", success means final output matches supported count
            processed_without_issues = issue_count == 0 and output_count == supported_count
        
        report = FolderReport(
            timestamp=datetime.now().isoformat(),
            folder_name=folder_name,
            duration_seconds=round(duration, 2),
            input_document_count=input_count,
            unsupported_count=unsupported_count,
            output_document_count=output_count,
            processed_without_issues=processed_without_issues,
            issue_count=issue_count,
            conversion_success=conversion_success,
            conversion_failed=conversion_failed,
            redaction_success=redaction_success,
            redaction_failed=redaction_failed,
            validation_success=validation_success,
            validation_failed=validation_failed,
            pdf_export_success=pdf_export_success,
            pdf_export_failed=pdf_export_failed
        )
        
        self.folder_reports.append(report)
        logger.debug(f"Added report for folder '{folder_name}': "
                    f"{output_count}/{input_count} total ({unsupported_count} unsupported), "
                    f"{issue_count} issues")
    
    def write_report(self):
        """Write all folder reports to CSV file."""
        if not self.config.enabled or not self.folder_reports:
            return
        
        try:
            # Ensure parent directory exists
            self.report_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Check if file exists to determine if we need headers
            file_exists = self.report_path.exists()
            
            # Write to CSV (append mode if file exists)
            mode = 'a' if file_exists else 'w'
            with open(self.report_path, mode, newline='', encoding='utf-8') as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=self.CSV_HEADERS)
                
                # Write header only if creating new file
                if not file_exists:
                    writer.writeheader()
                
                # Write all folder reports
                for report in self.folder_reports:
                    writer.writerow(asdict(report))
            
            logger.info(f"Pipeline report written to: {self.report_path}")
            logger.info(f"  Folders processed: {len(self.folder_reports)}")
            
            # Summary statistics
            total_input = sum(r.input_document_count for r in self.folder_reports)
            total_output = sum(r.output_document_count for r in self.folder_reports)
            folders_without_issues = sum(1 for r in self.folder_reports if r.processed_without_issues)
            
            logger.info(f"  Total documents: {total_output}/{total_input} processed")
            logger.info(f"  Folders without issues: {folders_without_issues}/{len(self.folder_reports)}")
            
        except Exception as e:
            logger.error(f"Failed to write pipeline report: {e}")
    
    def print_summary_table(self):
        """Print a summary table of folder reports to the console."""
        if not self.folder_reports:
            return
        
        logger.info("\n" + "="*115)
        logger.info("FOLDER-LEVEL PROCESSING SUMMARY")
        logger.info("="*115)
        
        # Header
        header = f"{'Folder':<30} {'Total':<8} {'Unsupp':<8} {'Output':<8} {'Issues':<8} {'Status':<10} {'Duration':<10}"
        logger.info(header)
        logger.info("-"*115)
        
        # Rows
        for report in self.folder_reports:
            status = "✓ OK" if report.processed_without_issues else "✗ ERRORS"
            duration_str = f"{report.duration_seconds:.2f}s"
            
            row = (
                f"{report.folder_name:<30} "
                f"{report.input_document_count:<8} "
                f"{report.unsupported_count:<8} "
                f"{report.output_document_count:<8} "
                f"{report.issue_count:<8} "
                f"{status:<10} "
                f"{duration_str:<10}"
            )
            logger.info(row)
        
        logger.info("="*115)
