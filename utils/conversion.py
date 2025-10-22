"""Document conversion utilities using Azure Document Intelligence."""

import logging
import subprocess
import shutil
from pathlib import Path
from dataclasses import dataclass
from typing import Tuple
from azure.core.credentials import AzureKeyCredential
from azure.ai.documentintelligence.aio import DocumentIntelligenceClient
from azure.ai.documentintelligence.models import AnalyzeDocumentRequest, DocumentContentFormat

from .retry import retry_with_backoff

logger = logging.getLogger(__name__)


@dataclass
class ConversionConfig:
    """Configuration for document conversion."""
    endpoint: str
    api_key: str
    
    def validate(self):
        """Validate configuration."""
        if not self.endpoint:
            raise ValueError("Document Intelligence endpoint is required")
        if not self.api_key:
            raise ValueError("Document Intelligence API key is required")


class ConversionFactory:
    """Factory for creating document conversion client."""
    
    @staticmethod
    def create_client(config: ConversionConfig) -> DocumentIntelligenceClient:
        """
        Create and return a DocumentIntelligenceClient.
        
        Args:
            config: ConversionConfig with endpoint and API key
            
        Returns:
            DocumentIntelligenceClient instance
        """
        config.validate()
        return DocumentIntelligenceClient(
            endpoint=config.endpoint,
            credential=AzureKeyCredential(config.api_key)
        )


async def _convert_document_inner(
    file_bytes: bytes,
    client: DocumentIntelligenceClient
):
    """
    Inner function for document conversion that can be retried.
    
    Args:
        file_bytes: Document bytes to convert
        client: DocumentIntelligenceClient instance
        
    Returns:
        Azure analyze result
    """
    poller = await client.begin_analyze_document(
        "prebuilt-layout",
        AnalyzeDocumentRequest(bytes_source=file_bytes),
        output_content_format=DocumentContentFormat.MARKDOWN
    )
    
    return await poller.result()


def convert_doc_to_docx(doc_path: str, output_dir: str) -> Tuple[bool, str, str]:
    """
    Convert a DOC file to DOCX using LibreOffice headless mode.
    
    Args:
        doc_path: Path to input DOC file
        output_dir: Directory where converted DOCX will be saved
        
    Returns:
        Tuple of (success, docx_path, error_message)
    """
    try:
        doc_file = Path(doc_path)
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        
        # Check if LibreOffice is available
        soffice_cmd = shutil.which("soffice")
        if not soffice_cmd:
            # Try common paths on different platforms
            common_paths = [
                "/Applications/LibreOffice.app/Contents/MacOS/soffice",  # macOS
                "/usr/bin/soffice",  # Linux
                "C:\\Program Files\\LibreOffice\\program\\soffice.exe"  # Windows
            ]
            for path in common_paths:
                if Path(path).exists():
                    soffice_cmd = path
                    break
        
        if not soffice_cmd:
            error_msg = "LibreOffice (soffice) not found. Please install LibreOffice."
            logger.error(error_msg)
            return False, "", error_msg
        
        logger.debug(f"Converting DOC to DOCX: {doc_file.name}")
        
        # Run LibreOffice conversion
        # --headless: run without GUI
        # --convert-to docx: output format
        # --outdir: output directory
        result = subprocess.run(
            [
                soffice_cmd,
                "--headless",
                "--convert-to",
                "docx",
                "--outdir",
                str(output_path),
                str(doc_file)
            ],
            capture_output=True,
            text=True,
            timeout=60  # 60 second timeout
        )
        
        if result.returncode != 0:
            error_msg = f"LibreOffice conversion failed: {result.stderr}"
            logger.error(f"✗ DOC conversion failed: {doc_file.name} - {error_msg}")
            return False, "", error_msg
        
        # Construct expected output path
        docx_filename = doc_file.stem + ".docx"
        docx_path = output_path / docx_filename
        
        if not docx_path.exists():
            error_msg = "DOCX file not created by LibreOffice"
            logger.error(f"✗ DOC conversion failed: {doc_file.name} - {error_msg}")
            return False, "", error_msg
        
        logger.debug(f"✓ DOC converted to DOCX: {doc_file.name}")
        return True, str(docx_path), ""
        
    except subprocess.TimeoutExpired:
        error_msg = "LibreOffice conversion timed out (60s)"
        logger.error(f"✗ DOC conversion failed: {Path(doc_path).name} - {error_msg}")
        return False, "", error_msg
    except Exception as e:
        error_msg = str(e)
        logger.error(f"✗ DOC conversion failed: {Path(doc_path).name} - {error_msg}")
        return False, "", error_msg


async def convert_document(
    file_path: str,
    output_path: str,
    client: DocumentIntelligenceClient
) -> Tuple[bool, int, str]:
    """
    Convert a single document to Markdown with retry logic.
    
    Args:
        file_path: Path to input document
        output_path: Path to save markdown output
        client: DocumentIntelligenceClient instance
        
    Returns:
        Tuple of (success, page_count, error_message)
    """
    try:
        logger.debug(f"Converting: {file_path}")
        
        # Read file
        with open(file_path, "rb") as f:
            file_bytes = f.read()
        
        # Execute conversion with retry logic
        success, analyze_result, error_msg = await retry_with_backoff(
            _convert_document_inner,
            file_bytes,
            client
        )
        
        if not success:
            logger.error(f"✗ Conversion failed: {Path(file_path).name} - {error_msg}")
            return False, 0, error_msg
        
        # Extract and save markdown
        markdown_content = analyze_result.content if analyze_result.content else ""
        page_count = len(analyze_result.pages) if analyze_result.pages else 0
        
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_text(markdown_content, encoding="utf-8")
        
        logger.debug(f"✓ Converted: {Path(file_path).name} ({page_count} pages)")
        return True, page_count, ""
        
    except Exception as e:
        logger.error(f"✗ Conversion failed: {Path(file_path).name} - {e}")
        return False, 0, str(e)
