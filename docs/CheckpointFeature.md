# Checkpoint Management

## Overview

The pipeline supports checkpoint-based incremental processing at the first-level folder granularity. This enables resumable execution for large document processing jobs.

## How It Works

1. **Folder-Level Tracking**: The pipeline tracks completion at the first-level subfolder level (e.g., `input_folder/IPR123/`, `input_folder/IPR456/`)

2. **Completion Criteria**: A folder is marked as completed only when ALL documents within it are successfully processed through both conversion and redaction stages

3. **Checkpoint Persistence**: Completion status is persisted in `.pipeline_checkpoint.json` in the output directory

4. **Automatic Resume**: On subsequent runs, folders already marked as completed are automatically skipped

## Usage

### Default Behavior (Checkpoint Enabled)
```bash
python main.py ./inp ./anonymized --batch-size 10 --language cs
```

On the first run, all folders are processed. On subsequent runs, only unprocessed or incomplete folders are processed.

### Disable Checkpointing
```bash
python main.py ./inp ./anonymized --no-checkpoint
```

Process all files regardless of previous completion status. No checkpoint file is created or consulted.

### Clear Checkpoint and Reprocess
```bash
python main.py ./inp ./anonymized --clear-checkpoint
```

Deletes the existing checkpoint file and reprocesses all folders from scratch.

## Checkpoint File Format

The checkpoint file (`.pipeline_checkpoint.json`) stores:

```json
{
  "version": "1.0",
  "last_updated": "2025-10-13T10:30:00",
  "completed_folders": ["IPR123", "IPR456"],
  "folder_details": {
    "IPR123": {
      "completed_at": "2025-10-13T10:25:00",
      "file_count": 5,
      "success_count": 5
    }
  }
}
```

## Partial Failures

If a folder has partial failures (e.g., 3 out of 5 files succeed):
- The folder is **NOT** marked as completed
- On the next run, all files in that folder are reprocessed
- This ensures data consistency - either a folder is fully processed or not at all

## Use Cases

1. **Large Document Sets**: Process thousands of documents across multiple runs without reprocessing completed folders

2. **Interrupted Executions**: Resume from where the pipeline stopped if interrupted (Ctrl+C, timeout, rate limits)

3. **Incremental Updates**: Add new folders to the input directory and run again - only new folders are processed

4. **Debugging**: Clear checkpoint when testing fixes for specific folders

## Implementation Details

- **Checkpoint Location**: `<output_dir>/.pipeline_checkpoint.json`
- **Granularity**: First-level folders only (e.g., `input/folder/` not `input/folder/subfolder/`)
- **Thread-Safe**: Single process writes; safe for sequential pipeline runs
- **Validation**: Folders with any failed documents are not marked complete

## Metrics

The pipeline metrics include checkpoint statistics:
- `skipped_checkpoint`: Number of files skipped due to completed folders
- This is reported in the final summary alongside other metrics
