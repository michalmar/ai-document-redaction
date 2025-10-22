# Document Anonymization Pipeline

Automated pipeline for anonymizing documents by converting them to Markdown and redacting personally identifiable information (PII) using Azure AI services.

> **Note:** This project is intended for educational and demonstration purposes only. Ensure compliance with data privacy regulations and organizational policies when handling sensitive information.

## Overview

This project provides an example document anonymization pipeline built with a modular architecture:

### Main Components

1. **Pipeline Orchestration** (`main.py`) - Entry point that chains conversion, redaction, and optional validation stages
2. **Utility Modules** (`utils/`) - Modular services for each pipeline stage:
   - `conversion.py` - Document to Markdown conversion (Azure Document Intelligence)
   - `redaction/` - PII detection and redaction with multiple strategies:
     - `azure_language.py` - Azure AI Language strategy
     - `azure_openai.py` - Azure OpenAI full LLM redaction strategy
     - `azure_openai_fast.py` - Azure OpenAI fast extraction + replacement strategy
     - `validation.py` - Optional LLM-based validation
   - `pipeline.py` - Pipeline orchestration logic
   - `metrics.py` - Performance tracking and reporting
   - `retry.py` - Resilient retry logic with exponential backoff

### Legacy Scripts (Standalone)

- `convert-azure-di.py` - Standalone document conversion
- `redact-document-pii.py` - Standalone PII redaction

### Architecture

The project uses **Strategy pattern** for PII redaction and **Factory pattern** for service initialization:
- `ConversionFactory` - Creates configured Document Intelligence clients
- `create_redaction_strategy()` - Creates appropriate redaction strategy (Azure Language or Azure OpenAI)
- `DocumentValidator` - Optional LLM-based validation of redacted documents

This design enables multiple redaction approaches, easy testing, and extensibility.

## Supported Document Formats

- PDF
- Microsoft Word (`.docx`)
- Microsoft Excel (`.xlsx`)
- Microsoft PowerPoint (`.pptx`)
- Images (`.jpg`, `.jpeg`, `.png`, `.tiff`, `.bmp`)

## Prerequisites

- Python 3.10 or higher
- Azure subscription with:
  - Azure Document Intelligence resource
  - Azure AI Language resource (for `azure_language` strategy)
  - Azure OpenAI resource (for `azure_openai` strategy or validation)

## Installation

### 1. Install Dependencies

Using `uv` (recommended for this project):
```bash
uv pip install azure-ai-documentintelligence azure-ai-textanalytics python-dotenv openai
```

Or using standard pip:
```bash
pip install azure-ai-documentintelligence azure-ai-textanalytics python-dotenv openai
```

**For PDF Export Feature (Optional):**
```bash
pip install markdown weasyprint
```

On macOS, WeasyPrint requires Pango:
```bash
brew install pango
```

### 2. Configure Environment Variables

Create a `.env` file in the project root:

```env
# Azure Document Intelligence
DOCUMENTINTELLIGENCE_ENDPOINT=https://your-resource.cognitiveservices.azure.com/
DOCUMENTINTELLIGENCE_API_KEY=your-api-key

# Azure AI Language (for azure_language strategy)
AZURE_LANGUAGE_ENDPOINT=https://your-resource.cognitiveservices.azure.com/
AZURE_LANGUAGE_KEY=your-api-key

# Azure OpenAI (for azure_openai strategy or validation)
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_API_KEY=your-api-key
AZURE_OPENAI_DEPLOYMENT=gpt-4
```

## Usage

### Complete Pipeline (Recommended)

Process all documents through conversion, redaction, and optional validation stages:

```bash
# Basic usage (Azure Language strategy)
python main.py ./input ./output

# With Azure OpenAI strategy for redaction
python main.py ./input ./output --redaction-strategy azure_openai

# With Azure OpenAI Fast strategy (speed optimized)
python main.py ./input ./output --redaction-strategy azure_openai_fast

# With entity logging for azure_openai_fast (creates .ENTITIES.log files)
python main.py ./input ./output --redaction-strategy azure_openai_fast --enable-entity-logging

# With validation enabled
python main.py ./input ./output --validate

# Full example with all options
python main.py ./documents ./anonymized \
  --batch-size 10 \
  --language cs \
  --redaction-strategy azure_openai \
  --validate \
  --export-pdf \
  --report-file ./reports/run_$(date +%Y%m%d).csv \
  --log-level DEBUG
```

**Parameters:**
- `input_dir` - Directory containing documents to anonymize
- `output_dir` - Directory for final anonymized documents
- `--batch-size` - Number of documents to process concurrently (default: 5)
- `--language` - Language code for PII detection: `en` (English), `cs` (Czech), `de` (German), etc. (default: `en`)
- `--redaction-strategy` - Redaction method: `azure_language` (default), `azure_openai`, or `azure_openai_fast`
- `--enable-entity-logging` - Enable entity extraction logging for `azure_openai_fast` (creates `.ENTITIES.log` files in `output/log/`)
- `--validate` - Enable optional Stage 3: LLM-based validation for remaining PII
- `--export-pdf` - Enable optional Stage 4: Export anonymized files to PDF format
- `--report-file` - Custom path for CSV report (default: `<output_dir>/pipeline_report.csv`)
- `--no-report` - Disable CSV report generation
- `--no-checkpoint` - Disable incremental processing (process all files)
- `--clear-checkpoint` - Clear existing checkpoint and reprocess all files
- `--log-level` - Logging verbosity: DEBUG, INFO, WARNING, ERROR (default: INFO)

### Checkpoint Feature (Incremental Processing)

By default, the pipeline tracks completion status of first-level folders and automatically skips them on subsequent runs. This enables efficient resumable execution for large document sets.

```bash
# First run - processes all folders
python main.py ./input ./output

# Second run - only processes new/incomplete folders
python main.py ./input ./output

# Force reprocessing of all files
python main.py ./input ./output --clear-checkpoint

# Disable checkpoint (always process everything)
python main.py ./input ./output --no-checkpoint
```

**How it works:**
- Folders are marked complete only when ALL documents succeed in both conversion and redaction stages
- Checkpoint state is stored in `<output_dir>/.pipeline_checkpoint.json`
- Partial failures prevent folder completion, ensuring data consistency
- See `docs/CheckpointFeature.md` for detailed documentation

### Redaction Strategies

#### Azure AI Language (Default)
Fast, cost-effective PII detection using Azure's specialized service:
```bash
python main.py ./input ./output --redaction-strategy azure_language
```

**Best for:** Production workloads, common PII types, cost efficiency

#### Azure OpenAI
Context-aware LLM-based full redaction with token usage tracking:
```bash
python main.py ./input ./output --redaction-strategy azure_openai
```

**Best for:** Complex documents, context-sensitive PII, maximum accuracy

#### Azure OpenAI Fast (NEW)
Speed-optimized strategy using LLM for entity extraction + Python replacement:
```bash
python main.py ./input ./output --redaction-strategy azure_openai_fast

# With entity logging (creates .ENTITIES.log files for analysis)
python main.py ./input ./output --redaction-strategy azure_openai_fast --enable-entity-logging
```

**Best for:** Large document sets, structured content, cost optimization

**Features:**
- 60-80% cheaper than full LLM redaction (reduced completion tokens)
- 50-70% faster execution
- Two-phase approach: LLM identifies PII, Python performs replacement
- Optional entity logging for debugging and auditing
- Exact string matching (may miss variations)

**Entity Logging:**
When enabled with `--enable-entity-logging`, creates detailed logs showing all extracted PII entities:
```
output/
├── log/                              ← Entity extraction logs
│   ├── folder1/
│   │   └── file1.ENTITIES.log       ← Shows all PII found in file1
│   └── folder2/
│       └── file2.ENTITIES.log
├── folder1/
│   └── file1.md                      ← Redacted output
└── folder2/
    └── file2.md
```

See `utils/redaction/README.md` for detailed strategy comparison.

### Individual Components

#### Document Conversion Only

Convert documents to Markdown without PII redaction:

```bash
# Single file
python convert-azure-di.py document.pdf -o output.md

# Batch processing
python convert-azure-di.py --batch-dir ./documents --output-dir ./markdown
```

#### PII Redaction Only

Redact PII from existing Markdown files:

```bash
# Single file
python redact-document-pii.py document.md -o redacted.md

# Batch processing with Czech language
python redact-document-pii.py --batch-dir ./markdown --output-dir ./redacted --language cs
```

## Pipeline Architecture

The orchestration pipeline uses a modular design with **Strategy pattern** for flexible redaction methods.

### Configuration Layer

Configuration dataclasses encapsulate service settings:
- **ConversionConfig** - Document Intelligence endpoint and API key
- **RedactionConfig** - Strategy type and credentials (Language or OpenAI)
- **ValidationConfig** - Optional validation settings

**Factory Function** creates the appropriate strategy:
- `create_redaction_strategy(config)` → `AzureLanguageStrategy`, `AzureOpenAIStrategy`, or `AzureOpenAIFastStrategy`

### Pipeline Stages

**Stage 1: Document Conversion** (`utils/conversion.py`)
- Scans input directory for supported document formats
- Converts each document to Markdown using Azure Document Intelligence
- Stores intermediate Markdown files in a temporary directory
- Tracks page counts and conversion metrics
- Implements retry logic for resilience

**Stage 2: PII Redaction** (`utils/redaction/`)
- Processes converted Markdown files using selected strategy
- **Azure Language Strategy**: Fast, specialized PII detection service
- **Azure OpenAI Strategy**: Context-aware LLM with full document redaction and token tracking
- **Azure OpenAI Fast Strategy**: Speed-optimized LLM entity extraction + Python replacement
  - Optional entity logging: creates `.ENTITIES.log` files showing all extracted PII
  - Logs placed in `output/log/` with mirrored folder structure
- Handles large documents by chunking (5000 character safe limit)
- Outputs final anonymized documents to the target directory
- Tracks entity counts, categories, and token usage
- Implements retry logic for resilience

**Stage 3: PII Validation (Optional)** (`utils/redaction/validation.py`)
- LLM-based validation of redacted documents
- Checks for any remaining PII that might have been missed
- Reports findings with confidence levels
- Tracks token usage for validation
- Works with both redaction strategies

**Stage 4: PDF Export (Optional)** (`utils/pdf_export.py`)
- Converts anonymized Markdown files to professional PDF format
- Uses `markdown` library for Markdown→HTML conversion
- Uses `weasyprint` library for HTML→PDF rendering
- Preserves folder structure
- Includes default professional styling
- See `docs/PDFExportFeature.md` for detailed documentation

**Retry Logic** (`utils/retry.py`)
- Exponential backoff for Azure API calls
- Handles rate limits (429) and transient errors (500-599)
- Configurable retry attempts and delays

**Metrics Tracking** (`utils/metrics.py`)
- Pipeline performance statistics
- Success/failure rates per stage
- Processing times and entity counts

### Cleanup
- Automatically removes temporary files
- Preserves only the final anonymized documents

## Output & Metrics

The pipeline provides detailed metrics for each run:

```
ANONYMIZATION PIPELINE SUMMARY
======================================================================
Total input files: 6
Skipped (unsupported format): 0

Stage 1 - Document Conversion:
  Successful: 6
  Failed: 0
  Total pages: 42
  Duration: 45.32s

Stage 2 - PII Redaction:
  Successful: 6
  Failed: 0
  Entities redacted: 127
  Duration: 12.18s
  Tokens used: 45,280 (prompt: 38,150, completion: 7,130)

Stage 3 - PII Validation:
  Successful: 6
  Failed: 0
  Documents with PII found: 0
  Duration: 8.45s
  Tokens used: 32,100 (prompt: 28,500, completion: 3,600)

Stage 4 - PDF Export:
  Successful: 6
  Failed: 0
  Duration: 5.20s

Total pipeline duration: 71.25s
Average time per document: 11.88s
======================================================================
```

### Folder-Level Reporting

The pipeline also generates a **CSV report** tracking folder-level processing:

```
====================================================================================================
FOLDER-LEVEL PROCESSING SUMMARY
====================================================================================================
Folder                         Input    Output   Issues   Status     Duration  
----------------------------------------------------------------------------------------------------
IPR123                         3        3        0        ✓ OK       98.32s    
IPR456                         2        2        0        ✓ OK       98.32s    
====================================================================================================
Pipeline report written to: anonymized/pipeline_report.csv
  Folders processed: 2
  Total documents: 5/5 processed
  Folders without issues: 2/2
```

**CSV columns include:**
- Timestamp, folder name, duration
- Input/output document counts
- Success indicator and issue count
- Per-stage success/failure metrics

See `docs/ReportingFeature.md` for analysis examples and details.

## Supported PII Categories

The Azure AI Language service detects and redacts various PII categories including:

- Person names
- Email addresses
- Phone numbers
- Physical addresses
- Credit card numbers
- Social security numbers
- IP addresses
- URLs
- Dates of birth
- And more...

## Error Handling

The pipeline handles:
- Missing or invalid input files
- Unsupported file formats (skips with warning)
- Azure API errors with detailed messages
- Network timeouts and retries
- Partial batch failures (continues processing remaining files)

Failed files are logged with specific error messages while successful files continue processing.

## Performance Considerations

- **Batch Size**: Adjust `--batch-size` based on your Azure service tier and rate limits
- **Concurrency**: Default batch size of 5 provides good balance between speed and API limits
- **Large Documents**: Automatically chunks documents over 5000 characters to respect API constraints
- **Async Processing**: Uses async/await for efficient concurrent operations

## Language Support

The PII redaction supports multiple languages. Common language codes:

- `en` - English
- `cs` - Czech
- `de` - German
- `es` - Spanish
- `fr` - French
- `it` - Italian
- `pt` - Portuguese
- `nl` - Dutch
- `pl` - Polish

Refer to [Azure AI Language documentation](https://learn.microsoft.com/en-us/azure/ai-services/language-service/personally-identifiable-information/language-support) for the complete list.

## Project Structure

```
.
├── main.py                    # Pipeline entry point and CLI
├── utils/                     # Modular utility modules
│   ├── __init__.py           # Package marker
│   ├── conversion.py         # Document conversion (ConversionFactory)
│   ├── redaction/            # PII redaction strategies
│   │   ├── __init__.py      # Public API
│   │   ├── base.py          # RedactionStrategy abstract base
│   │   ├── config.py        # Configuration dataclasses
│   │   ├── factory.py       # Strategy factory
│   │   ├── azure_language.py    # Azure Language strategy
│   │   ├── azure_openai.py      # Azure OpenAI full LLM redaction
│   │   ├── azure_openai_fast.py # Azure OpenAI fast extraction + replacement
│   │   ├── validation.py        # LLM-based validation
│   │   └── README.md        # Strategy documentation
│   ├── pipeline.py           # Pipeline orchestration logic
│   ├── checkpoint.py         # Checkpoint management for incremental processing
│   ├── metrics.py            # Performance metrics tracking
│   ├── pdf_export.py         # PDF export functionality
│   ├── report.py             # CSV reporting and folder-level tracking
│   └── retry.py              # Resilient retry logic
├── convert-azure-di.py       # Standalone conversion script (legacy)
├── redact-document-pii.py    # Standalone redaction script (legacy)
├── tests/                    # Test suite
│   └── test_checkpoint.py   # Checkpoint functionality tests
├── docs/                     # Documentation
│   ├── CheckpointFeature.md # Checkpoint feature documentation
│   ├── PDFExportFeature.md  # PDF export feature documentation
│   ├── ReportingFeature.md  # CSV reporting feature documentation
│   ├── ImplementationLog_Checkpoint.md  # Implementation details
│   ├── ImplementationSummary_StrategyPattern.md
│   └── QuickReference_Strategies.md
├── .env                      # Environment variables (not in repo)
├── README.md                 # This file
├── AGENTS.md                 # Development guidelines
├── inp/                      # Example: input documents
└── anonymized/               # Example: final output directory
```

## Development

This project follows guidelines outlined in `AGENTS.md`. Key principles:

### Code Organization
- **Strategy Pattern**: Multiple PII redaction approaches through `RedactionStrategy` implementations
- **Factory Pattern**: Service initialization through `ConversionFactory` and `create_redaction_strategy()`
- **Configuration as Data**: Dataclasses for all configuration (`ConversionConfig`, `RedactionConfig`, `ValidationConfig`, `PipelineMetrics`)
- **Modular Design**: Separate modules for conversion, redaction strategies, validation, pipeline, metrics, and retry logic
- **Single Responsibility**: Each module handles one concern

### Best Practices
- Comprehensive docstrings for all public functions and classes
- Async/await for efficient Azure API calls
- Structured logging with appropriate levels (DEBUG, INFO, WARNING, ERROR)
- Exponential backoff retry logic for resilience
- Clean resource management with context managers
- Type hints throughout for better IDE support

### Testing & Extensibility
- Strategy pattern enables easy addition of new redaction methods
- Factory function simplifies mocking in tests
- Configuration objects enable easy test setup
- Modular design supports independent component testing
- Architecture supports multiple service providers

## License

See project license file for details.
