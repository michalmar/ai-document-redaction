# Implementation Log: Checkpoint Strategy

**Date**: October 13, 2025  
**Feature**: Pipeline checkpoint management for incremental processing  
**Status**: Completed

## Summary

Implemented a checkpoint strategy for the document anonymization pipeline that tracks completion status at the first-level folder granularity. This enables resumable execution for large document processing jobs, preventing reprocessing of already-completed folders.

## Architecture

### New Components

1. **`utils/checkpoint.py`** - Core checkpoint management module
   - `CheckpointManager` class: Manages checkpoint state persistence and folder tracking
   - Checkpoint file format: JSON-based, stored as `.pipeline_checkpoint.json` in output directory
   - Thread-safe for sequential pipeline runs

2. **`tests/test_checkpoint.py`** - Comprehensive test suite
   - Tests for checkpoint initialization, persistence, filtering, and clearing
   - Validates folder completion tracking and statistics

3. **`docs/CheckpointFeature.md`** - User-facing documentation
   - Usage examples and command-line options
   - Explanation of completion criteria and partial failure handling

4. **`adhoc_checkpoint_demo.py`** - Demonstration script
   - Shows checkpoint functionality in isolation
   - Disposable artifact per AGENTS.md Section 7

### Modified Components

1. **`utils/pipeline.py`**
   - Added `CheckpointManager` integration
   - Modified `run_conversion_stage()` to return per-folder statistics
   - Modified `run_redaction_stage()` to return per-folder statistics
   - Updated `execute_pipeline()` to:
     - Initialize checkpoint manager (optional via `enable_checkpoint` parameter)
     - Filter pending files based on completed folders
     - Mark folders as completed only when all files succeed
     - Track folder-level success/failure metrics

2. **`utils/metrics.py`**
   - Added `skipped_checkpoint` field to `PipelineMetrics`
   - Updated summary output to include checkpoint statistics

3. **`main.py`**
   - Added `--no-checkpoint` flag to disable checkpoint functionality
   - Added `--clear-checkpoint` flag to reset checkpoint and reprocess all files
   - Updated help text to explain checkpoint feature
   - Checkpoint enabled by default

## Design Decisions

### Folder-Level Granularity
- **Rationale**: Folders typically represent logical document groupings (e.g., projects, cases)
- **Benefit**: Atomic completion units - either a full folder is processed or none of it
- **Trade-off**: Individual file failures require reprocessing entire folder on retry

### Completion Criteria
- A folder is marked complete only when:
  1. All files in the folder pass conversion stage
  2. All files in the folder pass redaction stage
  3. Success count equals total file count
- **Rationale**: Ensures data consistency - no partial processing states
- **Benefit**: Simple recovery model - folders are either 100% complete or pending

### Checkpoint File Location
- Stored in output directory as `.pipeline_checkpoint.json`
- **Rationale**: Co-locates checkpoint with output, making cleanup straightforward
- **Benefit**: Output directory becomes self-contained processing unit

### Default Enabled
- Checkpoint enabled by default (must use `--no-checkpoint` to disable)
- **Rationale**: Most users benefit from incremental processing
- **Benefit**: Reduces cognitive load - "just works" for resumable processing

## Implementation Approach

Following AGENTS.md principles:

1. **Simplicity**: CheckpointManager is a focused, single-responsibility class
2. **Self-documenting**: Comprehensive docstrings on all public methods
3. **Explicit contracts**: Clear function signatures with return types
4. **Minimal surface area**: Small, cohesive module (< 200 lines)
5. **No progress comments**: Code speaks for itself; rationale in docstrings

## Testing Strategy

1. **Unit tests** (`test_checkpoint.py`):
   - Checkpoint initialization and persistence
   - Folder completion marking
   - File filtering logic
   - Statistics gathering
   - Clear functionality

2. **Integration testing** (manual):
   - Run pipeline on multi-folder input
   - Verify checkpoint file creation
   - Interrupt and resume
   - Clear checkpoint and verify reprocessing

## Usage Examples

### Normal incremental processing:
```bash
python main.py ./inp ./anonymized --batch-size 10 --language cs
# Run again - only new/incomplete folders processed
python main.py ./inp ./anonymized --batch-size 10 --language cs
```

### Force full reprocessing:
```bash
python main.py ./inp ./anonymized --clear-checkpoint
```

### Disable checkpoint:
```bash
python main.py ./inp ./anonymized --no-checkpoint
```

## Metrics Integration

New metrics tracked:
- `skipped_checkpoint`: Count of files skipped due to completed folders
- Displayed in pipeline summary output

## Future Enhancements (Not Implemented)

Potential improvements identified but deferred:
1. File-level checkpointing (finer granularity, more complex)
2. Concurrent pipeline execution safety (file locking)
3. Checkpoint versioning/migration (for future schema changes)
4. Checkpoint validation/repair (detect corrupted state)

## References

- Checkpoint module: `utils/checkpoint.py`
- Pipeline integration: `utils/pipeline.py` (lines with folder_stats tracking)
- CLI options: `main.py` (--no-checkpoint, --clear-checkpoint)
- User documentation: `docs/CheckpointFeature.md`
- Tests: `tests/test_checkpoint.py`
