# DOC to DOCX Conversion Feature

## Overview
Added support for processing legacy Microsoft Word DOC files by automatically converting them to DOCX format before processing through the document anonymization pipeline.

## Rationale
The Azure Document Intelligence service used in the pipeline supports DOCX but not the older DOC format. Rather than skip these files, the feature transparently converts them using LibreOffice headless mode before passing them to the main conversion pipeline.

## Implementation Details

### 1. New Function: `convert_doc_to_docx()` in `utils/conversion.py`
- Uses LibreOffice headless mode (`soffice --headless --convert-to docx`)
- Checks for LibreOffice availability in PATH and common installation locations
- Returns tuple: (success, docx_path, error_message)
- Includes 60-second timeout to prevent hanging on problematic files
- Proper error handling and logging

### 2. Modified: `utils/pipeline.py`
- Added `DOC_EXTENSION = ".doc"` constant
- Updated `collect_input_files()` to accept `include_doc` parameter
  - When True, includes .doc files in processing list
  - Set to False for redact-only stage (expects .md files)
- Modified `run_conversion_stage()` to preprocess DOC files:
  - Creates temporary directory `.temp_doc_conversion`
  - Converts all DOC files to DOCX before Azure Document Intelligence processing
  - Updates file tuples to point to converted DOCX files
  - Cleans up temporary conversion directory after stage completes
  - Logs conversion failures appropriately

### 3. Enhanced Metrics: `utils/metrics.py`
- Added `doc_converted: int = 0` field to track number of DOC files converted
- Updated `print_summary()` to display DOC conversion count when > 0

## Workflow Integration
1. User places documents in input folder (including .doc files)
2. Pipeline collects files, now including .doc files
3. During Stage 1 (Document Conversion):
   - DOC files are converted to DOCX using LibreOffice
   - Converted DOCX files replace original DOC files in processing queue
   - Azure Document Intelligence processes DOCX files normally
4. Metrics report shows number of DOC files converted
5. Temporary conversion directory is cleaned up

## Error Handling
- If LibreOffice is not installed: logs clear error message
- If conversion fails: file is marked as failed, error logged to error.log
- If conversion times out (>60s): file is skipped with timeout error
- Conversion errors don't block processing of other files

## Dependencies
- Requires LibreOffice installed on the system
- Searches for `soffice` in:
  - System PATH
  - `/Applications/LibreOffice.app/Contents/MacOS/soffice` (macOS)
  - `/usr/bin/soffice` (Linux)
  - `C:\Program Files\LibreOffice\program\soffice.exe` (Windows)

## Testing Considerations
- Verify LibreOffice is installed before running with DOC files
- Test with various DOC file sizes and complexities
- Verify timeout mechanism works for corrupted files
- Check that metrics correctly track converted DOC files
