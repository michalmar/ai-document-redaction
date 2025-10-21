#!/usr/bin/env python3
"""
Document to Markdown Converter

Converts various document formats to Markdown using Microsoft's markitdown library.
Supports PDF, PowerPoint, Word, Excel, images, HTML, and more.
"""

import argparse
import sys
from pathlib import Path
from markitdown import MarkItDown


def convert_document(input_path: str, output_dir: str = "output") -> None:
    """
    Convert a document to Markdown format.

    Args:
        input_path: Path to the input document file
        output_dir: Directory where the output Markdown file will be saved (default: "output")

    Raises:
        FileNotFoundError: If the input file does not exist
        Exception: If conversion fails
    """
    input_file = Path(input_path)
    
    if not input_file.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")
    
    # Create output directory if it doesn't exist
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    # Generate output filename (replace extension with .md)
    output_file = output_path / f"{input_file.stem}.md"
    
    # Initialize MarkItDown converter
    md = MarkItDown(enable_plugins=False)
    
    # Convert document
    print(f"Converting: {input_file}")
    result = md.convert(str(input_file))
    
    # Write output
    output_file.write_text(result.text_content, encoding="utf-8")
    print(f"Saved to: {output_file}")


def main() -> int:
    """
    Main entry point for the script.

    Returns:
        Exit code (0 for success, 1 for error)
    """
    parser = argparse.ArgumentParser(
        description="Convert documents to Markdown format",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s document.pdf
  %(prog)s presentation.pptx -o converted
  %(prog)s report.docx --output-dir markdown_files
        """
    )
    parser.add_argument(
        "input_path",
        help="Path to the document to convert"
    )
    parser.add_argument(
        "-o", "--output-dir",
        default="output",
        help="Output directory for the Markdown file (default: output)"
    )
    
    args = parser.parse_args()
    
    try:
        convert_document(args.input_path, args.output_dir)
        return 0
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Error converting document: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
