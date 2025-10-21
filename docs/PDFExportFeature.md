# PDF Export Feature

## Overview

The PDF export feature provides an optional fourth stage in the anonymization pipeline that converts anonymized Markdown files to PDF format. This allows for professional document distribution and archival purposes.

## Architecture

### Components

1. **PDFExportConfig** (`utils/pdf_export.py`)
   - Configuration dataclass for PDF export settings
   - Validates required dependencies
   - Supports custom CSS styling

2. **PDFExporter** (`utils/pdf_export.py`)
   - Main class for Markdown to PDF conversion
   - Uses `markdown` library for Markdown→HTML conversion
   - Uses `weasyprint` library for HTML→PDF rendering
   - Provides default professional CSS styling

3. **Pipeline Integration** (`utils/pipeline.py`)
   - `run_pdf_export_stage()`: Executes PDF export for all anonymized files
   - Processes files sequentially (no batching needed)
   - Preserves folder structure from Markdown output

4. **Metrics Tracking** (`utils/metrics.py`)
   - `pdf_export_enabled`: Feature flag
   - `pdf_exported_success`: Count of successful exports
   - `pdf_exported_failed`: Count of failed exports
   - `pdf_export_duration`: Time spent in PDF export stage

## Usage

### Command Line

Enable PDF export with the `--export-pdf` flag:

```bash
python main.py ./inp ./anonymized --export-pdf
```

Combine with other options:

```bash
python main.py ./inp ./anonymized \
  --batch-size 10 \
  --language cs \
  --redaction-strategy azure_openai \
  --validate \
  --export-pdf
```

### Output Structure

PDF files are created in a separate directory alongside the Markdown output:

```
./anonymized/
  ├── IPR123/
  │   ├── document1.md
  │   └── document2.md
  └── IPR456/
      └── document3.md

./anonymized_pdf/
  ├── IPR123/
  │   ├── document1.pdf
  │   └── document2.pdf
  └── IPR456/
      └── document3.pdf
```

## Dependencies

PDF export requires two additional Python packages:

- **markdown**: Converts Markdown to HTML
- **weasyprint**: Renders HTML to PDF

### Installation

Install all dependencies including PDF support:

```bash
pip install -r requirements.txt
```

Or install PDF dependencies separately:

```bash
pip install markdown weasyprint
```

### WeasyPrint System Dependencies

WeasyPrint requires system-level libraries for PDF rendering:

**macOS:**
```bash
brew install pango
```

**Ubuntu/Debian:**
```bash
apt-get install libpango-1.0-0 libpangoft2-1.0-0
```

**Windows:**
WeasyPrint typically works out-of-the-box on Windows.

## Styling

### Default CSS

The PDF exporter includes professional default styling:
- A4 page size with 2cm margins
- Clean typography with readable fonts
- Proper heading hierarchy
- Styled code blocks and tables
- Appropriate spacing and colors

### Custom CSS (Future Enhancement)

The architecture supports custom CSS through `PDFExportConfig.css_styles`, though this is not currently exposed via command line.

To use custom CSS programmatically:

```python
pdf_config = PDFExportConfig(
    enabled=True,
    css_styles="body { font-size: 12pt; }"
)
```

## Error Handling

- Dependency check at initialization prevents runtime failures
- Individual file conversion errors are logged but don't stop the pipeline
- Failed exports are tracked in metrics
- All errors include the filename and detailed error message

## Performance Considerations

- PDF conversion is I/O bound (disk writes)
- No batching/concurrency implemented (sequential processing)
- For large datasets, expect approximately 0.5-2 seconds per document
- No impact on earlier pipeline stages (conversion, redaction, validation)

## Future Enhancements

Potential improvements for future iterations:

1. **Custom CSS via CLI**: Expose CSS customization through command-line argument
2. **Concurrent Processing**: Add async batch processing for PDF generation
3. **PDF Metadata**: Embed document metadata (title, author, creation date)
4. **Compression Options**: Support for different PDF compression levels
5. **Page Numbering**: Add configurable headers/footers with page numbers
6. **Watermarking**: Optional watermark support for sensitive documents
7. **Multiple Formats**: Support additional export formats (DOCX, HTML)

## Integration with Existing Features

### Checkpoint System

PDF export respects the checkpoint system:
- Folders already processed will not generate PDFs on re-run
- Use `--clear-checkpoint` to regenerate all PDFs

### Validation

PDF export only runs if redaction was successful:
- Skipped if no files were successfully redacted
- Can be combined with `--validate` flag

### Metrics

PDF export metrics are included in the final summary:
- Stage 4 summary shows success/failure counts
- Duration tracked separately from other stages
- Included in total pipeline duration

## Troubleshooting

### Missing Dependencies Error

```
ValueError: PDF export requires additional dependencies. Install with: pip install markdown weasyprint
```

**Solution**: Install required packages as shown above.

### WeasyPrint Import Error

```
ImportError: cannot import name 'HTML' from 'weasyprint'
```

**Solution**: Install system dependencies (Pango) as shown in Dependencies section.

### PDF Output Quality Issues

- Check source Markdown quality (tables, formatting)
- Consider custom CSS for specific rendering needs
- Verify font availability on the system

## Design Decisions

1. **Optional Feature**: PDF export is opt-in to keep base dependencies minimal
2. **Separate Output Directory**: PDFs stored separately to avoid confusion with Markdown sources
3. **Default Styling**: Professional defaults eliminate need for CSS knowledge
4. **Sequential Processing**: Simpler implementation; parallelization deferred until proven necessary
5. **Dependency Validation**: Early validation prevents runtime surprises
