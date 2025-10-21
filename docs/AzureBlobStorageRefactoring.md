# Azure Blob Storage Input Refactoring

## Summary

Refactored Azure Blob Storage CLI parameters to support **container/folder** format, making it simpler and more intuitive to specify both container and folder path in a single parameter.

## Changes

### Removed Parameters
- `--input-prefix` - No longer needed (parsed from `--input-container`)
- `--output-prefix` - No longer needed (parsed from `--output-container`)

### Modified Parameters
- `--input-container` - Now accepts `container` or `container/folder` or `container/folder/subfolder`
- `--output-container` - Now accepts `container` or `container/folder` or `container/folder/subfolder`

## Usage Examples

### Before (Old Format)
```bash
python main.py \
  --storage-mode azure_blob \
  --storage-account mystorageacct \
  --input-container data-converted \
  --input-prefix proj2 \
  --output-container data-anonym \
  --output-prefix proj2 \
  --stage redact
```

### After (New Format)
```bash
python main.py \
  --storage-mode azure_blob \
  --storage-account mystorageacct \
  --input-container data-converted/proj2 \
  --output-container data-anonym/proj2 \
  --stage redact
```

## Parsing Logic

The container/folder path is parsed as follows:

| Input | Container | Prefix |
|-------|-----------|--------|
| `mycontainer` | `mycontainer` | `` (empty) |
| `mycontainer/folder` | `mycontainer` | `folder` |
| `mycontainer/folder/subfolder` | `mycontainer` | `folder/subfolder` |
| `data-converted/proj2` | `data-converted` | `proj2` |

## Implementation Details

### Parsing Function
```python
def parse_container_path(path: str) -> tuple[str, str]:
    parts = path.split('/', 1)
    container = parts[0]
    prefix = parts[1] if len(parts) > 1 else ""
    return container, prefix
```

### Affected Components
- `main.py` - CLI argument parsing and storage config construction
- Checkpoint clearing logic - Updated to parse container/folder for output container

## Backwards Compatibility

⚠️ **Breaking Change**: This refactoring removes `--input-prefix` and `--output-prefix` parameters. Users must update their scripts to use the new `container/folder` format.

## Benefits

1. **Simpler CLI** - Two parameters instead of four
2. **More intuitive** - Natural path-like syntax
3. **Consistent with filesystem conventions** - Similar to specifying directories
4. **Easier to read** - Clear visual separation of container and folder
5. **Flexible** - Supports any folder depth (folder/subfolder/...)
