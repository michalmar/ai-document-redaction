# Pipeline Reporting Feature

## Overview

The pipeline reporting feature provides comprehensive folder-level tracking and CSV logging for each pipeline run. This enables analysis of processing performance, success rates, and issue identification across different document sets.

## Features

### Folder-Level Tracking

The reporting system tracks processing metrics at the **first-level folder** granularity:
- **Timestamp**: ISO 8601 timestamp when processing completed
- **Duration**: Total processing time for the folder (seconds)
- **Input/Output Counts**: Number of documents before and after processing
- **Success Indicator**: Boolean flag for folders processed without issues
- **Issue Count**: Total number of failures across all stages
- **Per-Stage Metrics**: Success/failure counts for conversion, redaction, validation, and PDF export

### CSV Export

All reports are automatically exported to a CSV file for further analysis:
- **Default location**: `<output_dir>/pipeline_report.csv`
- **Custom location**: Specify with `--report-file` flag
- **Append mode**: New runs append to existing report file
- **Excel-compatible**: Standard CSV format with headers

### Console Summary

A visual summary table is printed at the end of each run:

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

## Usage

### Basic Usage (Default Reporting)

Reporting is **enabled by default**:

```bash
python main.py ./inp ./anonymized
# Creates: ./anonymized/pipeline_report.csv
```

### Custom Report Location

Specify a custom path for the CSV report:

```bash
python main.py ./inp ./anonymized --report-file ./reports/run_2025_10_15.csv
```

### Disable Reporting

Disable CSV report generation:

```bash
python main.py ./inp ./anonymized --no-report
```

## CSV Format

### Column Definitions

| Column | Type | Description |
|--------|------|-------------|
| `timestamp` | ISO 8601 | When folder processing completed |
| `folder_name` | String | First-level folder name |
| `duration_seconds` | Float | Total processing time (seconds) |
| `input_document_count` | Integer | Number of documents in folder |
| `output_document_count` | Integer | Number successfully processed |
| `processed_without_issues` | Boolean | True if all stages succeeded |
| `issue_count` | Integer | Total failures across all stages |
| `conversion_success` | Integer | Successful conversions |
| `conversion_failed` | Integer | Failed conversions |
| `redaction_success` | Integer | Successful redactions |
| `redaction_failed` | Integer | Failed redactions |
| `validation_success` | Integer | Successful validations (if enabled) |
| `validation_failed` | Integer | Failed validations (if enabled) |
| `pdf_export_success` | Integer | Successful PDF exports (if enabled) |
| `pdf_export_failed` | Integer | Failed PDF exports (if enabled) |

### Example CSV

```csv
timestamp,folder_name,duration_seconds,input_document_count,output_document_count,processed_without_issues,issue_count,conversion_success,conversion_failed,redaction_success,redaction_failed,validation_success,validation_failed,pdf_export_success,pdf_export_failed
2025-10-15T12:28:54.147802,IPR123,98.32,3,3,True,0,3,0,3,0,0,0,0,0
2025-10-15T12:28:54.147823,IPR456,98.32,2,2,True,0,2,0,2,0,0,0,0,0
```

## Analysis Examples

### Excel Analysis

1. Open CSV in Excel or Google Sheets
2. Create pivot tables to analyze:
   - Processing time by folder
   - Success rates across runs
   - Common failure patterns
   - Performance trends over time

### Python Analysis

```python
import pandas as pd

# Load report
df = pd.read_csv('anonymized/pipeline_report.csv')

# Calculate success rate
df['success_rate'] = df['output_document_count'] / df['input_document_count']

# Find problematic folders
issues = df[df['issue_count'] > 0]

# Average processing time per document
df['time_per_doc'] = df['duration_seconds'] / df['input_document_count']

# Summary statistics
print(df.describe())
```

### Shell Analysis

```bash
# Count successful folders
grep "True" pipeline_report.csv | wc -l

# Find folders with issues
grep "False" pipeline_report.csv

# Calculate total documents processed
awk -F',' 'NR>1 {sum+=$5} END {print sum}' pipeline_report.csv
```

## Architecture

### Components

**`utils/report.py`** - Main reporting module

1. **FolderReport** (dataclass)
   - Holds all metrics for a single folder
   - Immutable data structure
   - Easy serialization to CSV

2. **ReportConfig** (dataclass)
   - Configuration for report generation
   - `enabled`: Toggle reporting on/off
   - `output_file`: Custom report path (optional)

3. **ReportManager** (class)
   - Collects folder reports during pipeline execution
   - Writes CSV file with append mode
   - Prints console summary table
   - Calculates aggregate statistics

### Integration Points

**Pipeline Integration** (`utils/pipeline.py`)

- Tracks folder-level start times
- Collects statistics from each stage
- Generates reports after all stages complete
- Writes CSV before cleanup

**CLI Integration** (`main.py`)

- `--report-file`: Custom report path
- `--no-report`: Disable reporting

## Design Decisions

### Folder-Level Granularity

Reports track **first-level folders** rather than individual files:
- **Rationale**: Most document sets are organized by project/case folders
- **Benefit**: Reduces noise while maintaining useful insights
- **Scalability**: Manageable report size even for thousands of documents

### Append Mode

CSV file uses append mode for multiple runs:
- **Rationale**: Build historical dataset over time
- **Benefit**: Track performance trends and regression analysis
- **Consideration**: File grows indefinitely (archive periodically)

### Success Indicator Logic

`processed_without_issues = True` requires:
1. Zero failures across all stages (`issue_count == 0`)
2. All input documents processed (`output_count == input_count`)

**Rationale**: Conservative definition ensures data quality

### Enabled by Default

Reporting is opt-out rather than opt-in:
- **Rationale**: Valuable for production monitoring
- **Minimal overhead**: Negligible performance impact
- **User control**: Easy to disable with `--no-report`

## Performance Impact

- **Memory**: ~200 bytes per folder report (negligible)
- **I/O**: Single CSV write at end (< 100ms typical)
- **CPU**: Minimal (simple aggregation)
- **Total Impact**: < 0.1% of pipeline duration

## Error Handling

### Report Write Failures

If CSV write fails:
- Error logged with details
- Pipeline continues successfully
- Processing results preserved
- Console summary still displayed

### Missing Data

If stage doesn't run (e.g., validation disabled):
- Counts default to 0
- CSV includes all columns
- Analysis tools see 0 values

## Future Enhancements

1. **JSON Output**: Alternative format for programmatic access
2. **Run-Level Metadata**: Pipeline configuration snapshot
3. **Cost Tracking**: Token usage and estimated costs
4. **Performance Alerts**: Threshold-based warnings
5. **Automatic Archiving**: Rotate old reports
6. **Dashboard Generation**: HTML summary page

## Troubleshooting

### Report Not Generated

**Problem**: No CSV file created

**Solutions**:
1. Check if `--no-report` flag was used
2. Verify write permissions on output directory
3. Check logs for write errors

### Incorrect Counts

**Problem**: Counts don't match expectations

**Solutions**:
1. Check for unsupported files (skipped before reporting)
2. Verify folder structure (only first-level counted)
3. Review checkpoint behavior (completed folders filtered out)

### Duplicate Entries

**Problem**: Same folder appears multiple times

**Cause**: Multiple pipeline runs append to same CSV

**Solution**: This is expected behavior for historical tracking

## Integration with Other Features

### Checkpoint System

- Completed folders (via checkpoint) are excluded from new runs
- Report only includes folders actually processed in current run
- Historical CSV shows all runs including re-processed folders

### Validation & PDF Export

- Optional stages (validation, PDF export) tracked when enabled
- Counts remain 0 when stages disabled
- `issue_count` includes failures from optional stages

### Multi-Batch Processing

- All batches within a folder aggregated into single report
- Duration covers entire folder processing time
- Stage counts reflect all batches combined

## Best Practices

1. **Archive Reports**: Periodically backup and truncate large CSV files
2. **Custom Paths**: Use dated filenames for different runs (`--report-file`)
3. **Version Control**: Don't commit CSV files (add to `.gitignore`)
4. **Monitoring**: Set up alerts for high `issue_count` values
5. **Analysis**: Regular review of `processed_without_issues` trends
