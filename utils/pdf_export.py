"""PDF export utilities for converting Markdown to PDF."""

import logging
from pathlib import Path
from dataclasses import dataclass
from typing import Tuple, Optional

logger = logging.getLogger(__name__)


@dataclass
class PDFExportConfig:
    """Configuration for PDF export."""
    enabled: bool = False
    css_styles: Optional[str] = None
    
    def validate(self):
        """Validate configuration."""
        if self.enabled and not self._check_dependencies():
            raise ValueError(
                "PDF export requires additional dependencies. "
                "Install with: pip install markdown weasyprint"
            )
    
    @staticmethod
    def _check_dependencies() -> bool:
        """Check if required dependencies are installed."""
        try:
            import markdown
            import weasyprint
            return True
        except ImportError:
            return False


class PDFExporter:
    """Export Markdown files to PDF format."""
    
    DEFAULT_CSS = """
    @page {
        size: A4;
        margin: 2cm;
    }
    body {
        font-family: Arial, sans-serif;
        font-size: 11pt;
        line-height: 1.6;
        color: #333;
    }
    h1, h2, h3, h4, h5, h6 {
        color: #2c3e50;
        margin-top: 1.5em;
        margin-bottom: 0.5em;
    }
    h1 {
        font-size: 24pt;
        border-bottom: 2px solid #2c3e50;
        padding-bottom: 0.3em;
    }
    h2 {
        font-size: 18pt;
    }
    h3 {
        font-size: 14pt;
    }
    p {
        margin: 0.5em 0;
    }
    code {
        background-color: #f4f4f4;
        padding: 2px 6px;
        border-radius: 3px;
        font-family: 'Courier New', monospace;
    }
    pre {
        background-color: #f4f4f4;
        padding: 1em;
        border-radius: 5px;
        overflow-x: auto;
    }
    table {
        border-collapse: collapse;
        width: 100%;
        margin: 1em 0;
    }
    th, td {
        border: 1px solid #ddd;
        padding: 8px;
        text-align: left;
    }
    th {
        background-color: #f2f2f2;
    }
    """
    
    def __init__(self, config: PDFExportConfig):
        """
        Initialize PDF exporter.
        
        Args:
            config: PDFExportConfig instance
        """
        config.validate()
        self.config = config
        
        # Import dependencies only if needed
        import markdown
        import weasyprint
        
        self.markdown = markdown
        self.weasyprint = weasyprint
    
    def convert_markdown_to_pdf(
        self,
        markdown_path: str,
        pdf_path: str
    ) -> Tuple[bool, str]:
        """
        Convert a Markdown file to PDF.
        
        Args:
            markdown_path: Path to input Markdown file
            pdf_path: Path to save PDF output
            
        Returns:
            Tuple of (success, error_message)
        """
        try:
            logger.debug(f"Converting to PDF: {Path(markdown_path).name}")
            
            # Read Markdown content
            markdown_content = Path(markdown_path).read_text(encoding="utf-8")
            
            # Convert Markdown to HTML
            html_content = self.markdown.markdown(
                markdown_content,
                extensions=['tables', 'fenced_code', 'nl2br']
            )
            
            # Wrap in HTML structure with CSS
            css = self.config.css_styles or self.DEFAULT_CSS
            full_html = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="utf-8">
                <style>
                {css}
                </style>
            </head>
            <body>
                {html_content}
            </body>
            </html>
            """
            
            # Create output directory if needed
            Path(pdf_path).parent.mkdir(parents=True, exist_ok=True)
            
            # Convert HTML to PDF
            self.weasyprint.HTML(string=full_html).write_pdf(pdf_path)
            
            logger.debug(f"✓ PDF created: {Path(pdf_path).name}")
            return True, ""
            
        except Exception as e:
            logger.error(f"✗ PDF conversion failed: {Path(markdown_path).name} - {e}")
            return False, str(e)
