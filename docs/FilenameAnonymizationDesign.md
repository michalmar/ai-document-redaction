# Filename & Folder Anonymization - Design Document

## 1. Overview

**Problem**: Filenames and folder names may contain PII (e.g., `John_Doe_Contract.pdf`, `IROP_JohnDoe_2024/`) that must be anonymized alongside document content.

**Solution**: Implement a **Pre-Stage 0** that detects and anonymizes PII in both filenames and folder names using Azure AI services, generating deterministic hash-based identifiers while maintaining bidirectional mapping for auditability.

---

## 2. Core Requirements (Updated)

✅ **Detection Strategies**: Azure AI Language (default) + Azure OpenAI (optional)  
❌ **No Pattern-Based**: Removed to ensure high accuracy  
✅ **Folder-Level**: First-level folder names anonymized alongside filenames  
✅ **Hash-Based Naming**: SHA-256 deterministic hashing only  
✅ **Bidirectional Mapping**: Persistent JSON mapping for reverse lookup  
✅ **Pipeline Integration**: Pre-Stage 0 before existing conversion/redaction stages  

---

## 3. Detection Strategies (Azure Only)

### Strategy 1: Azure AI Language (Default)
- **Service**: Azure Text Analytics PII Detection
- **Method**: Reuse existing `TextAnalyticsClient` from redaction pipeline
- **API Call**: `recognize_pii_entities()` on filename/folder strings
- **Advantages**:
  - Same service already used for document redaction (consistent results)
  - Lower cost than OpenAI
  - Supports 10+ languages (align with `--language` flag)
  - Fast batch processing (up to 10 documents per call)
- **Entity Types Detected**: Person names, organization names, phone numbers, SSNs, dates, addresses, emails, etc.
- **Confidence Threshold**: Only anonymize if confidence ≥ 0.8 (configurable)

### Strategy 2: Azure OpenAI (Optional)
- **Service**: Azure OpenAI GPT-4 / GPT-3.5
- **Method**: Prompt-based PII detection
- **Prompt Template**:
  ```
  You are a PII detection system. Analyze the following filename or folder name for personally identifiable information.
  
  Text: "{filename_or_foldername}"
  
  Return a JSON object with:
  - "contains_pii": boolean (true if ANY PII detected)
  - "entities": array of detected PII strings
  - "confidence": float 0-1
  
  PII types to detect: person names, SSNs, phone numbers, dates of birth, addresses, email addresses, organization-specific IDs.
  
  Example:
  Text: "John_Doe_SSN_123-45-6789_Report.pdf"
  Response: {"contains_pii": true, "entities": ["John_Doe", "123-45-6789"], "confidence": 0.95}
  ```
- **Advantages**:
  - More flexible for complex/ambiguous cases
  - Better at understanding context (e.g., "MartinSmith" vs. "SmithsonianMuseum")
  - Can detect organization-specific ID patterns
- **Disadvantages**:
  - Higher cost per request
  - Slower latency
  - Requires careful prompt engineering to avoid hallucinations

**Configuration Flag**: `--filename-detection-strategy` (choices: `azure_language`, `azure_openai`)

---

## 4. Anonymization Scheme: Partial Hash Replacement

### Strategy: Replace Only PII Portions

Instead of replacing entire filenames/folders, we **selectively replace only the detected PII entities** with hash-based placeholders, preserving non-PII context.

### Hash Generation Algorithm

```python
def anonymize_with_partial_replacement(
    original: str, 
    entities: List[Dict], 
    preserve_extension: bool = True
) -> str:
    """
    Replace only PII entities in filename/folder with hash-based placeholders.
    
    Args:
        original: Original filename or folder name
        entities: List of detected PII entities with text and offsets
        preserve_extension: If True, preserve file extension (default)
    
    Returns:
        Partially anonymized name (e.g., "offer_a3f8c92b_letter.pdf")
    
    Algorithm:
        1. Extract extension (if file)
        2. Sort entities by offset (right-to-left for safe replacement)
        3. For each entity:
           a. Generate 8-char hash from entity text
           b. Replace entity span with hash
        4. Reattach extension
    """
    import hashlib
    
    # Extract extension if file
    if preserve_extension and '.' in original:
        name, ext = original.rsplit('.', 1)
    else:
        name = original
        ext = None
    
    # If no entities, return original
    if not entities:
        return original
    
    # Sort entities by offset (descending) for safe replacement
    sorted_entities = sorted(entities, key=lambda e: e['offset'], reverse=True)
    
    # Replace each entity with its hash
    result = name
    for entity in sorted_entities:
        entity_text = entity['text']
        offset = entity['offset']
        length = entity['length']
        
        # Generate 8-char deterministic hash for this entity
        hash_obj = hashlib.sha256(entity_text.encode('utf-8'))
        hash_hex = hash_obj.hexdigest()[:8]
        
        # Replace entity span with hash
        result = result[:offset] + hash_hex + result[offset + length:]
    
    # Reattach extension
    if ext:
        return f"{result}.{ext}"
    else:
        return result


**Path Transformation Example**:
```python
# Original file tuples
[
  (Path("inp/Client_JaneDoe_2024/offer_john_doe.pdf"), Path("Client_JaneDoe_2024/offer_john_doe.pdf")),
  (Path("inp/Client_JaneDoe_2024/invoice.pdf"), Path("Client_JaneDoe_2024/invoice.pdf")),
  (Path("inp/IROP123/report.pdf"), Path("IROP123/report.pdf"))
]

# After folder + filename anonymization (partial replacement)
[
  (Path("inp/Client_JaneDoe_2024/offer_john_doe.pdf"), Path("Client_a1b2c3d4_2024/offer_7a3f8c92.pdf")),
  (Path("inp/Client_JaneDoe_2024/invoice.pdf"), Path("Client_a1b2c3d4_2024/invoice.pdf")),
  (Path("inp/IROP123/report.pdf"), Path("IROP123/report.pdf"))  # No PII
]

# Note: "Client_JaneDoe_2024" → "Client_a1b2c3d4_2024" (only "JaneDoe" replaced)
#       "offer_john_doe.pdf" → "offer_7a3f8c92.pdf" (only "john_doe" replaced)
```
**Properties**:
- **Context Preservation**: Non-PII parts remain readable (e.g., "offer", "letter", "contract")
- **Deterministic**: Same PII entity always generates same hash
- **Collision-Resistant**: 8-char hex = 4 billion unique values (sufficient for most cases)
- **Selective Replacement**: Only detected PII is anonymized
### File 1: `.mappings/filename_mapping.json`

```json
{
  "version": "1.0",
  "created_at": "2025-10-31T14:30:00Z",
  "detection_strategy": "azure_language",
  "confidence_threshold": 0.8,
  "hash_length": 8,
  "mappings": [
    {
      "original_filename": "offer_john_doe_letter.pdf",
      "anonymized_filename": "offer_7a3f8c92_letter.pdf",
      "relative_path": "Client_JaneDoe/offer_john_doe_letter.pdf",
      "anonymized_relative_path": "Client_a1b2c3d4/offer_7a3f8c92_letter.pdf",
      "contained_pii": true,
      "detected_entities": [
        {
          "text": "john_doe",
          "category": "Person",
          "confidence": 0.92,
          "offset": 6,
          "length": 8,
          "hash": "7a3f8c92"
        }
      ],
      "entity_replacements": [
        {"original": "john_doe", "hash": "7a3f8c92"}
      ],
      "hash_algorithm": "sha256",
      "anonymized_at": "2025-10-31T14:30:05Z"
    },
    {
      "original_filename": "SSN_123-45-6789_Report.docx",
      "anonymized_filename": "SSN_e5f6a7b8_Report.docx",
      "relative_path": "IROP123/SSN_123-45-6789_Report.docx",
      "anonymized_relative_path": "IROP123/SSN_e5f6a7b8_Report.docx",
      "contained_pii": true,
      "detected_entities": [
        {
          "text": "123-45-6789",
          "category": "USSocialSecurityNumber",
          "confidence": 0.99,
          "offset": 4,
          "length": 11,
          "hash": "e5f6a7b8"
        }
      ],
      "entity_replacements": [
        {"original": "123-45-6789", "hash": "e5f6a7b8"}
      ],
      "hash_algorithm": "sha256",
      "anonymized_at": "2025-10-31T14:30:06Z"
    },
    {
      "original_filename": "Report_Q3_2024.pdf",
      "anonymized_filename": "Report_Q3_2024.pdf",
      "relative_path": "IROP123/Report_Q3_2024.pdf",
      "anonymized_relative_path": "IROP123/Report_Q3_2024.pdf",
      "contained_pii": false,
      "detected_entities": [],
      "entity_replacements": [],
      "hash_algorithm": null,
      "anonymized_at": "2025-10-31T14:30:07Z"
    }
  ]
}
```

### File 2: `.mappings/folder_mapping.json`

```json
{
  "version": "1.0",
  "created_at": "2025-10-31T14:30:00Z",
  "detection_strategy": "azure_language",
  "confidence_threshold": 0.8,
  "hash_length": 8,
  "mappings": [
    {
      "original_folder": "Client_JaneDoe_2024",
      "anonymized_folder": "Client_a1b2c3d4_2024",
      "contained_pii": true,
      "detected_entities": [
        {
          "text": "JaneDoe",
          "category": "Person",
@dataclass
class AnonymizationConfig:
    """Configuration for filename/folder anonymization."""
    enabled: bool = True  # Enabled by default (opt-out)
    detection_strategy: DetectionStrategy = DetectionStrategy.AZURE_LANGUAGE
    confidence_threshold: float = 0.8
    hash_length: int = 8  # Length of hash for PII replacement
    language: str = "en"
    preserve_extensions: bool = True
    anonymize_all_folders: bool = True  # Recursively anonymize all folder levels
    
    # Azure AI Language credentials
    language_endpoint: Optional[str] = None
    language_api_key: Optional[str] = None
    
    # Azure OpenAI credentials
    openai_endpoint: Optional[str] = None
    openai_api_key: Optional[str] = None
    openai_deployment: Optional[str] = None
      "detected_entities": [],
      "entity_replacements": [],
      "file_count": 10,
      "hash_algorithm": null,
      "anonymized_at": "2025-10-31T14:30:02Z"
    }
  ]
}
```

### File 3: `.mappings/entity_hash_map.json` (Global Entity Cache)

```json
{
  "version": "1.0",
  "created_at": "2025-10-31T14:30:00Z",
  "hash_algorithm": "sha256",
  "hash_length": 8,
  "entities": {
    "john_doe": "7a3f8c92",
    "JaneDoe": "a1b2c3d4",
    "123-45-6789": "e5f6a7b8"
  }
}
```

**Storage Location**: All files written to `output_dir/.mappings/` subfolder
      "original_filename": "John_Doe_Contract_2024.pdf",
      "anonymized_filename": "a3f8c92b4e1d5f6.pdf",
      "relative_path": "Client_JohnDoe/John_Doe_Contract_2024.pdf",
      "anonymized_relative_path": "7b2d91e5a8f3c4d0/a3f8c92b4e1d5f6.pdf",
      "contained_pii": true,
      "detected_entities": [
        {"text": "John_Doe", "category": "Person", "confidence": 0.92}
      ],
      "hash_algorithm": "sha256",
      "anonymized_at": "2025-10-31T14:30:05Z"
    },
    {
      "original_filename": "Report_Q3_2024.pdf",
      "anonymized_filename": "Report_Q3_2024.pdf",
      "relative_path": "IROP123/Report_Q3_2024.pdf",
      "anonymized_relative_path": "IROP123/Report_Q3_2024.pdf",
      "contained_pii": false,
      "detected_entities": [],
      "hash_algorithm": null,
      "anonymized_at": "2025-10-31T14:30:06Z"
    }
  ]
}
```

### File 2: `.folder_mapping.json`

```json
{
  "version": "1.0",
  "created_at": "2025-10-31T14:30:00Z",
  "detection_strategy": "azure_language",
  "confidence_threshold": 0.8,
  "mappings": [
    {
      "original_folder": "Client_JohnDoe",
      "anonymized_folder": "7b2d91e5a8f3c4d0",
      "contained_pii": true,
      "detected_entities": [
        {"text": "JohnDoe", "category": "Person", "confidence": 0.89}
      ],
      "file_count": 25,
      "hash_algorithm": "sha256",
      "anonymized_at": "2025-10-31T14:30:01Z"
    },
    {
      "original_folder": "IROP123",
      "anonymized_folder": "IROP123",
      "contained_pii": false,
      "detected_entities": [],
      "file_count": 10,
      "hash_algorithm": null,
      "anonymized_at": "2025-10-31T14:30:02Z"
    }
  ]
}
```

**Storage Location**: Both files written to `output_dir/` root

**Security**: Mapping files contain original names (PII) - recommend restricting permissions (chmod 600) or optional encryption in future phase

---

## 7. Architecture Components

### New Module: `utils/filename_anonymizer.py`

```python
"""Filename and folder PII anonymization using Azure AI services."""

from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple, Dict, Optional
from enum import Enum

class DetectionStrategy(Enum):
    AZURE_LANGUAGE = "azure_language"
    AZURE_OPENAI = "azure_openai"

@dataclass
class AnonymizationConfig:
    """Configuration for filename/folder anonymization."""
    enabled: bool = False
    detection_strategy: DetectionStrategy = DetectionStrategy.AZURE_LANGUAGE
    confidence_threshold: float = 0.8
    language: str = "en"
    preserve_extensions: bool = True
    
    # Azure AI Language credentials
    language_endpoint: Optional[str] = None
    language_api_key: Optional[str] = None
    
    # Azure OpenAI credentials
    openai_endpoint: Optional[str] = None
    openai_api_key: Optional[str] = None
    openai_deployment: Optional[str] = None

@dataclass
class DetectionResult:
    """Result of PII detection on a single string."""
    text: str
    contains_pii: bool
### New Arguments in `main.py`

```python
parser.add_argument(
    "--no-anonymize-filenames",
    dest="no_anonymize_filenames",
    action="store_true",
    help="Disable filename and folder PII anonymization (enabled by default)"
)

parser.add_argument(
    "--filename-detection-strategy",
    dest="filename_detection_strategy",
    choices=["azure_language", "azure_openai"],
    default="azure_language",
    help="PII detection strategy for filenames/folders (default: azure_language)"
)

parser.add_argument(
    "--filename-confidence-threshold",
    dest="filename_confidence_threshold",
    type=float,
    default=0.8,
    help="Confidence threshold for PII detection in filenames (0.0-1.0, default: 0.8)"
)

parser.add_argument(
    "--filename-hash-length",
    dest="filename_hash_length",
    type=int,
    default=8,
    choices=[6, 8, 10, 12, 16],
    help="Length of hash used for PII replacement (default: 8 chars)"
)
```     file_tuples: List[Tuple[Path, Path]]
    ) -> Tuple[List[Tuple[Path, Path]], Dict[str, str]]:
### Example Usage

```bash
# Default: Filename anonymization ENABLED by default
python main.py ./inp ./out

# Disable filename anonymization explicitly
python main.py ./inp ./out --no-anonymize-filenames

# Use Azure OpenAI for more flexible detection
python main.py ./inp ./out \
  --filename-detection-strategy azure_openai

# Adjust confidence threshold (lower = more sensitive)
python main.py ./inp ./out \
  --filename-confidence-threshold 0.7

# Full pipeline with filename anonymization (default enabled)
python main.py ./inp ./out \
  --filename-detection-strategy azure_language \
  --redaction-strategy azure_openai \
  --validate \
  --export-pdf

# Azure Blob Storage mode (anonymization works seamlessly)
python main.py \
  --storage-mode azure_blob \
  --storage-account mystorageacct \
  --input-container mycontainer/input \
  --output-container mycontainer/output \
  --filename-detection-strategy azure_language
```ss AzureOpenAIDetector:
    """PII detection using Azure OpenAI."""
    async def detect_batch(self, texts: List[str], threshold: float) -> List[DetectionResult]:
        pass
```

---

## 8. Pipeline Integration (Updated Flow)

### Integration Point in `execute_pipeline()`

```python
async def execute_pipeline(
    input_dir: str,
    output_dir: str,
| **Edge Case** | **Handling** |
|---------------|--------------|
| **Duplicate hash collisions** | Very rare with 8-char SHA-256; if detected, append `_2` suffix: `offer_a3f8c92b_v2.pdf` |
| **Overlapping entities** | Use longest entity span; skip overlapping shorter entities |
| **Multiple occurrences of same PII** | Same entity → same hash consistently (e.g., "john" always → "7a3f8c92") |
| **Entity spans word boundaries** | Azure API returns exact offsets; use those for precise replacement |
| **Non-ASCII filenames (Czech, etc.)** | UTF-8 encode before hashing; preserve Unicode in mappings and output |
| **Very long filenames (>255 chars)** | Partial replacement reduces length; if still too long, log warning |
| **Files with no extension** | Partial replacement works on entire name; no extension added |
| **Nested folders with PII** | Recursively anonymize all folder levels (e.g., `Client_John/Projects_Jane/` → `Client_7a3f8c92/Projects_a1b2c3d4/`) |
| **Azure API rate limiting** | Use exponential backoff (reuse existing `retry_with_backoff()`) |
| **Azure API failure** | Log error at WARNING level; skip anonymization for failed batch; continue with original names |
| **Empty folder names** | Skip anonymization; log warning |
| **Checkpoint with pre-anonymized names** | Detect mismatch via metadata in mapping file; warn user to clear checkpoint or mappings |
| **Re-running pipeline** | Load existing mapping files; reuse entity hashes for consistency; only detect new files |
    
    # Existing: Collect input files
    input_file_tuples, skipped, folder_total_counts, folder_unsupported_counts = \
        collect_input_files(input_dir, ...)
    
    # NEW: Pre-Stage 0 - Anonymize filenames and folders (ENABLED BY DEFAULT)
    if not anonymization_config or anonymization_config.enabled:
        anonymizer = FilenameAnonymizer(anonymization_config, Path(output_dir))
        
        try:
            async with anonymizer:
                logger.info("="*70)
                logger.info("PRE-STAGE 0: Filename & Folder Anonymization")
                logger.info("="*70)
                logger.info(f"Detection strategy: {anonymization_config.detection_strategy.value}")
                
                # Step 1: Anonymize folder names
                input_file_tuples, folder_mapping = await anonymizer.anonymize_folders(
                    input_file_tuples
                )
                logger.info(f"Anonymized {len([f for f in folder_mapping.values() if f != folder_mapping.keys()])} folders with PII")
                
                # Step 2: Anonymize filenames
                input_file_tuples, filename_mapping = await anonymizer.anonymize_filenames(
                    input_file_tuples
                )
                logger.info(f"Anonymized {len([f for f in filename_mapping.values() if f != filename_mapping.keys()])} filenames with PII")
                
                # Step 3: Save mappings
                anonymizer.save_mappings(filename_mapping, folder_mapping)
                logger.info(f"Mappings saved to {output_dir}")
                
        except Exception as e:
            logger.error(f"Filename anonymization failed: {e}")
            raise
    
    # Existing: Apply checkpoint filtering (now uses anonymized names)
    if checkpoint:
        input_file_tuples, skipped_checkpoint = checkpoint.filter_pending_files(input_file_tuples)
    
    # Existing: Continue with Stage 1 (Conversion), Stage 2 (Redaction), etc.
    # All subsequent stages now reference anonymized filenames and folder names
    ...
```

---

## 9. CLI Arguments (Updated)

### New Arguments in `main.py`

```python
parser.add_argument(
    "--anonymize-filenames",
    dest="anonymize_filenames",
    action="store_true",
    help="Enable filename and folder PII anonymization (Pre-Stage 0)"
)

parser.add_argument(
    "--filename-detection-strategy",
    dest="filename_detection_strategy",
## 14. Implementation Phases

### Phase 1: Core Anonymization (MVP) ✅ COMPLETE
**Status**: Completed October 31, 2025  
**Deliverables**:
- ✅ `utils/filename_anonymizer.py` module with partial replacement algorithm
- ✅ Azure AI Language detection strategy (batch processing)
- ✅ Partial hash-based naming for files (context preservation)
- ✅ Recursive folder anonymization (all levels)
- ✅ Entity hash cache (`.mappings/entity_hash_map.json`)
- ✅ Mapping persistence (`.mappings/` subfolder)
- ✅ Integration into `execute_pipeline()` as Pre-Stage 0
- ✅ CLI arguments (`--no-anonymize-filenames`, `--filename-detection-strategy`, etc.)
- ✅ Unit tests for partial replacement logic (20/26 tests passing)

**Documentation**: See `docs/Phase1_ImplementationComplete.md`  
**Actual Effort**: 2 days

### Phase 2: Azure OpenAI Strategy ✅ COMPLETE
**Status**: Completed October 31, 2025  
**Deliverables**:
- ✅ Azure OpenAI client integration with async support
- ✅ Prompt engineering for filename PII detection with entity offsets
- ✅ JSON structured output parsing
- ✅ Strategy routing (`detect_pii()` method)
- ✅ Configuration flag integration (`--filename-detection-strategy azure_openai`)
- ✅ Unit tests for OpenAI strategy (4 new tests, 26/26 total passing)
- ✅ Confidence threshold filtering
- ✅ Comprehensive documentation

**Documentation**: See `docs/Phase2_ImplementationComplete.md`  
**Actual Effort**: 2 days

### Phase 3: Azure Blob Storage Integration ✅ COMPLETE
**Status**: Completed October 31, 2025  
**Deliverables**:
- ✅ Async blob upload method (`save_mappings_to_blob()`)
- ✅ Async blob download method (`load_entity_cache_from_blob()`)
- ✅ Storage adapter integration in `FilenameAnonymizer`
- ✅ Pipeline integration for Azure Blob mode detection
- ✅ Prefix/folder path support for blob storage
- ✅ Entity cache consistency across blob runs
- ✅ Unit tests for blob operations (7 new tests, 33/33 total passing)
- ✅ Backward compatibility with local filesystem mode

**Documentation**: See `docs/Phase3_BlobStorageIntegration.md`  
**Actual Effort**: 2 days

### Phase 4: Additional Advanced Features (OPTIONAL)
**Deliverables**:
- Mapping file encryption with Azure Key Vault (`--encrypt-mappings`)
- Performance benchmarking report (Azure Language vs OpenAI)
- Cost tracking and estimation logging
- Batch optimization for OpenAI (multiple filenames per prompt)
- Integration tests with actual Azure APIs
- Update report manager to show original → anonymized mappings

**Estimated Effort**: 3-4 days

**Total Implemented Effort**: 6 days (Phases 1-3 complete)

### Batch Processing Strategy

**Azure AI Language**:
- API Limit: 10 documents per request
- Batch all folder names first (typically 10-50 folders)
- Batch filenames in groups of 10
- Expected throughput: ~500 filenames/sec

**Azure OpenAI**:
- API Limit: Sequential requests (rate-limited)
- Use `asyncio.gather()` with semaphore for concurrency
- Max concurrency: 10 requests
- Expected throughput: ~50 filenames/sec

### Caching Strategy

**Persistent Cache**: Store detection results in mapping files
- On re-run with same input directory:
  1. Load existing `.filename_mapping.json` and `.folder_mapping.json`
  2. Only detect PII for new/changed files
  3. Append new mappings to existing files

**Benefits**:
- Avoid redundant API calls
- Faster incremental processing
- Consistent hash generation across runs

## 15. Configuration Decisions ✅

Based on user confirmation:

1. **Default Behavior**: ✅ **Opt-out** (enabled by default, use `--no-anonymize-filenames` to disable)
   - Ensures PII protection by default
   - Aligns with security-first approach

2. **Confidence Threshold**: ✅ **0.8 (default)** - balanced recall/precision
   - User can adjust via `--filename-confidence-threshold` flag

3. **Folder Anonymization Scope**: ✅ **All folders recursively** (not just first-level)
   - More comprehensive PII protection
   - Handles nested structures like `Client_JohnDoe/2024_Projects/Jane_Report/`

4. **Mapping File Location**: ✅ **Separate `.mappings/` subfolder**
   - Cleaner output directory structure
   - Easy to secure/exclude from distributions
   - Contains: `filename_mapping.json`, `folder_mapping.json`, `entity_hash_map.json`

5. **Azure Blob Storage**: ✅ **Phase 1 support** (implement immediately)
   - Critical for production cloud deployments
   - Mapping files uploaded to `.mappings/` blob prefixivity
- **Risk**: Mapping files contain original filenames/folders (potential PII)
- **Mitigation**:
  1. Set restrictive permissions: `chmod 600 .filename_mapping.json .folder_mapping.json`
  2. Store in output directory (not shared publicly)
  3. Optionally encrypt (future enhancement: `--encrypt-mappings` flag)

### Audit Trail
- All anonymization actions logged at INFO level
- Mapping files include timestamps for compliance auditing
- Metadata tracks which detection strategy was used

### Data Residency
- Azure AI Language: Data processed in customer's Azure region
- Azure OpenAI: Verify region compliance for GDPR/CCPA

---

## 13. Testing Strategy

### Unit Tests (`tests/test_filename_anonymizer.py`)

### Unit Tests (`tests/test_filename_anonymizer.py`)

```python
class TestFilenameAnonymizer:
    def test_partial_hash_replacement_single_entity(self):
        """Single PII entity replaced with hash, rest preserved."""
        # offer_john_doe_letter.pdf → offer_7a3f8c92_letter.pdf
        
    def test_partial_hash_replacement_multiple_entities(self):
        """Multiple PII entities each replaced with their own hash."""
        # IROP_John_Doe_Jane_Smith.pdf → IROP_7a3f8c92_9d4e5f6a.pdf
        
    def test_hash_generation_deterministic(self):
        """Same PII entity produces same hash across calls."""
        
    def test_hash_preserves_extension(self):
        """Extension preserved after partial replacement."""
        
    def test_entity_cache_consistency(self):
        """Same entity uses same hash from cache."""
        
    def test_azure_language_detection_with_offsets(self):
        """Detects PII with correct character offsets."""
        
    def test_azure_openai_detection_accuracy(self):
        """Handles complex/ambiguous cases with entity extraction."""
        
    def test_recursive_folder_anonymization(self):
        """All folder levels anonymized, not just first-level."""
        
    def test_mapping_persistence_and_reload(self):
        """Mappings saved to .mappings/ and loaded correctly."""
        
    def test_batch_processing_efficiency(self):
        """Batch API calls reduce latency."""
        
    def test_overlapping_entities_handling(self):
        """Longer entity preferred when entities overlap."""
        
    def test_no_pii_filenames_unchanged(self):
        """Filenames without PII remain unchanged."""
```

### Integration Tests
1. End-to-end pipeline with filename anonymization enabled
2. Verify checkpoint consistency with anonymized names
3. Verify CSV reports use anonymized folder names
## 17. Summary

This design introduces a **Pre-Stage 0** filename and folder anonymization feature with **partial hash replacement**:

### **Core Innovation**: Partial Replacement vs. Full Replacement
- **Traditional Approach**: `offer_john_doe_letter.pdf` → `a3f8c92b4e1d5f6.pdf` (loses all context)
- **Our Approach**: `offer_john_doe_letter.pdf` → `offer_7a3f8c92_letter.pdf` (preserves semantic context)

### **Key Features**:
1. **Azure-only detection**: Azure AI Language (default) + Azure OpenAI (optional)
2. **Partial hash replacement**: Only PII entities replaced, non-PII context preserved
3. **Recursive folder anonymization**: All nested folders anonymized, not just first-level
4. **Entity hash cache**: Consistent hashing (same entity → same hash across all files)
5. **Bidirectional mapping**: JSON files in `.mappings/` subfolder for auditability
6. **Opt-out by default**: Enabled unless `--no-anonymize-filenames` specified
7. **Azure Blob Storage**: Full support from Phase 1 (mappings stored as blobs)
8. **Seamless integration**: Pre-processes file tuples before existing pipeline stages

### **Key Advantages**:
1. **Context Preservation**: Filenames remain human-readable (e.g., "offer_HASH_letter.pdf")
2. **High Accuracy**: Azure AI services with configurable confidence threshold
3. **Consistency**: Deterministic hashing ensures same PII → same hash
4. **Auditability**: Complete mapping files for compliance/debugging
5. **Performance**: Batch processing + entity cache for efficiency
6. **Security**: Early PII removal + separate mapping storage
7. **Compliance**: GDPR/CCPA-friendly approach with audit trail

### **Implementation Status**:
✅ **Design Approved**  
✅ **Configuration Decisions Finalized**  
✅ **Phase 1 Scope Defined** (4-5 days effort)  
✅ **Ready for Implementation**

**Next Steps**: Begin Phase 1 implementation of `utils/filename_anonymizer.py` and pipeline integration.
**Effort**: 3-4 days

### Phase 2: Folder Anonymization
**Deliverables**:
- Folder-level PII detection
- Folder mapping file (`.folder_mapping.json`)
- Update checkpoint manager to handle anonymized folder names
- Update report manager to display anonymized folders

**Effort**: 2 days

### Phase 3: Azure OpenAI Strategy
**Deliverables**:
- `AzureOpenAIDetector` implementation
- Prompt engineering for filename PII detection
- Configuration flag integration

**Effort**: 2 days

### Phase 4: Advanced Features
**Deliverables**:
- Mapping file encryption (`--encrypt-mappings`)
- Incremental detection (cache-based)
- Performance benchmarking report
- Azure Blob Storage full support

**Effort**: 2-3 days

**Total Estimated Effort**: 9-11 days

---

## 15. Open Questions for Confirmation

1. **Default Behavior**: Should `--anonymize-filenames` be opt-in (requires flag) or opt-out?
   - **Recommendation**: Opt-in to avoid breaking existing workflows
   - **Your Choice**: ?

2. **Confidence Threshold**: Is 0.8 a good default, or prefer higher (0.9) for precision?
   - **Recommendation**: 0.8 (balanced recall/precision)
   - **Your Choice**: ?

3. **Folder Anonymization Scope**: Only first-level folders, or recursive (all nested folders)?
   - **Recommendation**: First-level only (matches checkpoint granularity)
   - **Your Choice**: ?

4. **Mapping File Location**: Store in `output_dir/` root or separate `.mappings/` subfolder?
   - **Recommendation**: `output_dir/` root for simplicity
   - **Your Choice**: ?

5. **Azure Blob Storage**: Should anonymization work for blob mode immediately (Phase 1) or defer to Phase 4?
   - **Recommendation**: Phase 1 (critical for cloud deployments)
   - **Your Choice**: ?

---

## 16. Implementation Readiness Checklist

✅ **Design Approved**: Waiting for user confirmation  
✅ **Dependencies Identified**: Azure SDK already in `pyproject.toml`  
✅ **Integration Points Mapped**: `execute_pipeline()`, `collect_input_files()`  
✅ **Data Models Defined**: `AnonymizationConfig`, `DetectionResult`  
✅ **Error Handling Planned**: Retry logic, fallback strategies  
✅ **Testing Strategy Outlined**: Unit, integration, regression tests  
✅ **Documentation Structure**: Docstrings, mapping file schemas  

**Ready to implement upon approval.**

---

## 17. Summary

This revised design introduces a **Pre-Stage 0** filename and folder anonymization feature with:

- **Azure-only detection**: Azure AI Language (default) + Azure OpenAI (optional)
- **Hash-based naming**: SHA-256 deterministic hashing with extension preservation
- **Folder-level support**: First-level folder anonymization alongside filenames
- **Bidirectional mapping**: JSON files for auditability and reverse lookup
- **Seamless integration**: Pre-processes file tuples before existing pipeline stages
- **Production-ready**: Error handling, batch optimization, security considerations

**Key Advantages**:
1. High accuracy (Azure AI services)
2. Consistency (hash-based naming)
3. Auditability (persistent mappings)
4. Performance (batch processing)
5. Compliance (early PII removal)

**Next Steps**: Await user approval, then proceed with Phase 1 implementation.
