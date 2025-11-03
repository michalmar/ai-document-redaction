"""Filename and folder PII anonymization using Azure AI services.

Provides partial hash replacement of PII entities in filenames and folder names
while preserving non-PII context for usability.
"""

import asyncio
import hashlib
import json
import logging
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Tuple, Dict, Optional, Set
from datetime import datetime
from enum import Enum

from azure.core.credentials import AzureKeyCredential
from azure.ai.textanalytics.aio import TextAnalyticsClient
from azure.ai.textanalytics import TextDocumentInput

from .retry import retry_with_backoff
from .storage.base import StorageAdapter

logger = logging.getLogger(__name__)


class DetectionStrategy(Enum):
    """PII detection strategy."""
    AZURE_LANGUAGE = "azure_language"


@dataclass
class AnonymizationConfig:
    """Configuration for filename/folder anonymization."""
    enabled: bool = True
    detection_strategy: DetectionStrategy = DetectionStrategy.AZURE_LANGUAGE
    confidence_threshold: float = 0.8
    hash_length: int = 8
    language: str = "en"
    preserve_extensions: bool = True
    anonymize_all_folders: bool = True
    
    # Azure AI Language credentials
    language_endpoint: Optional[str] = None
    language_api_key: Optional[str] = None


@dataclass
class PIIEntity:
    """Detected PII entity with position information."""
    text: str
    category: str
    confidence: float
    offset: int
    length: int
    hash: Optional[str] = None


@dataclass
class DetectionResult:
    """Result of PII detection on a single string."""
    original_text: str
    contains_pii: bool
    entities: List[PIIEntity]
    confidence: float


class FilenameAnonymizer:
    """Anonymize filenames and folder names containing PII using partial hash replacement."""
    
    def __init__(self, config: AnonymizationConfig, output_dir: Path, storage_adapter: Optional[StorageAdapter] = None):
        """
        Initialize anonymizer with configuration.
        
        Args:
            config: AnonymizationConfig with detection settings
            output_dir: Output directory where mapping files will be stored
            storage_adapter: Optional storage adapter for Azure Blob Storage integration
        """
        self.config = config
        self.output_dir = output_dir
        self.mappings_dir = output_dir / ".mappings"
        self.storage_adapter = storage_adapter
        
        # Entity hash cache for consistency (only used with Azure Language strategy)
        self.entity_hash_cache: Dict[str, str] = {}
        
        # Detection client
        self.client: Optional[TextAnalyticsClient] = None
        
        # Initialize Azure Language client (allow None credentials for unit testing)
        if config.language_endpoint and config.language_api_key:
            self.client = TextAnalyticsClient(
                endpoint=config.language_endpoint,
                credential=AzureKeyCredential(config.language_api_key)
            )
    
    async def __aenter__(self):
        """Async context manager entry."""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()
    
    async def close(self):
        """Close Azure Language client."""
        if self.client:
            await self.client.close()
    
    def generate_entity_hash(self, entity_text: str) -> str:
        """
        Generate deterministic hash for a PII entity.
        
        Args:
            entity_text: The PII string to hash
            
        Returns:
            Hex hash string of specified length
        """
        # Check cache first
        if entity_text in self.entity_hash_cache:
            return self.entity_hash_cache[entity_text]
        
        # Generate hash
        hash_obj = hashlib.sha256(entity_text.encode('utf-8'))
        entity_hash = hash_obj.hexdigest()[:self.config.hash_length]
        
        # Cache for consistency
        self.entity_hash_cache[entity_text] = entity_hash
        
        return entity_hash
    
    def apply_partial_replacement(
        self,
        original: str,
        entities: List[PIIEntity],
        preserve_extension: bool = True
    ) -> str:
        """
        Replace only PII entities in string with hash-based placeholders.
        
        Args:
            original: Original filename or folder name
            entities: List of detected PII entities with offsets
            preserve_extension: If True, preserve file extension
            
        Returns:
            Partially anonymized string (e.g., "offer_7a3f8c92_letter.pdf")
        """
        # If no entities, return original
        if not entities:
            return original
        
        # Extract extension if file
        ext = None
        name = original
        if preserve_extension and '.' in original:
            name, ext = original.rsplit('.', 1)
        
        # Sort entities by offset (descending) for safe replacement
        sorted_entities = sorted(entities, key=lambda e: e.offset, reverse=True)
        
        # Replace each entity with its hash
        result = name
        for entity in sorted_entities:
            # Generate hash for this entity
            entity_hash = self.generate_entity_hash(entity.text)
            entity.hash = entity_hash
            
            # Replace entity span with hash
            offset = entity.offset
            length = entity.length
            
            # Ensure offset is within bounds
            if offset >= 0 and offset + length <= len(result):
                result = result[:offset] + entity_hash + result[offset + length:]
            else:
                logger.warning(
                    f"Entity offset out of bounds: {entity.text} "
                    f"at {offset}:{offset+length} in '{name}' (len={len(name)})"
                )
        
        # Reattach extension
        if ext:
            return f"{result}.{ext}"
        else:
            return result
    
    async def detect_pii(
        self,
        texts: List[str],
        text_ids: Optional[List[str]] = None
    ) -> List[DetectionResult]:
        """Detect PII using Azure AI Language service.
        
        Args:
            texts: List of text strings to analyze
            text_ids: Optional list of IDs for texts (for logging)
            
        Returns:
            List of DetectionResult objects
        """
        return await self.detect_pii_azure_language(texts, text_ids)
    
    async def detect_pii_azure_language(
        self,
        texts: List[str],
        text_ids: Optional[List[str]] = None
    ) -> List[DetectionResult]:
        """
        Detect PII in batch using Azure AI Language service.
        
        Args:
            texts: List of text strings to analyze
            text_ids: Optional list of IDs for texts (for logging)
            
        Returns:
            List of DetectionResult objects
        """
        if not texts:
            return []
        
        # Require client for actual detection
        if not self.client:
            raise ValueError(
                "Azure Language client not initialized. "
                "Provide language_endpoint and language_api_key in config."
            )
        
        # Azure Language API has a limit of 5 documents per batch
        BATCH_SIZE = 5
        all_results = []
        
        # Process in batches
        for batch_start in range(0, len(texts), BATCH_SIZE):
            batch_end = min(batch_start + BATCH_SIZE, len(texts))
            batch_texts = texts[batch_start:batch_end]
            
            # Prepare documents for batch processing
            documents = [
                TextDocumentInput(id=str(batch_start + i), text=text)
                for i, text in enumerate(batch_texts)
            ]
            
            # Call Azure Language PII detection with retry
            success, response, error_msg = await retry_with_backoff(
                self._detect_pii_batch_inner,
                documents,
                self.client,
                self.config.language
            )
            
            if not success:
                logger.error(f"PII detection failed for batch {batch_start}-{batch_end}: {error_msg}")
                # Return empty results on failure for this batch
                batch_results = [
                    DetectionResult(
                        original_text=text,
                        contains_pii=False,
                        entities=[],
                        confidence=0.0
                    )
                    for text in batch_texts
                ]
                all_results.extend(batch_results)
                continue
            
            # Process results for this batch
            for i, text in enumerate(batch_texts):
                global_idx = batch_start + i
                doc_result = next((doc for doc in response if int(doc.id) == global_idx), None)
                
                if doc_result and not doc_result.is_error:
                    # Filter entities by confidence threshold and exclude PersonType category
                    filtered_entities = [
                        PIIEntity(
                            text=entity.text,
                            category=entity.category,
                            confidence=entity.confidence_score,
                            offset=entity.offset,
                            length=entity.length
                        )
                        for entity in doc_result.entities
                        if entity.confidence_score >= self.config.confidence_threshold
                        and entity.category != "PersonType"
                    ]
                    
                    # Remove overlapping entities (keep longest)
                    non_overlapping = self._remove_overlapping_entities(filtered_entities)
                    
                    all_results.append(DetectionResult(
                        original_text=text,
                        contains_pii=len(non_overlapping) > 0,
                        entities=non_overlapping,
                        confidence=max([e.confidence for e in non_overlapping]) if non_overlapping else 0.0
                    ))
                else:
                    # Handle error case
                    error_msg = doc_result.error.message if doc_result and doc_result.is_error else "Unknown error"
                    logger.warning(f"PII detection failed for text '{text}': {error_msg}")
                    all_results.append(DetectionResult(
                        original_text=text,
                        contains_pii=False,
                        entities=[],
                        confidence=0.0
                    ))
        
        return all_results
    
    @staticmethod
    async def _detect_pii_batch_inner(documents, client, language):
        """Inner method for PII detection with retry logic."""
        response = await client.recognize_pii_entities(
            documents,
            language=language
        )
        return response
    
    def _remove_overlapping_entities(self, entities: List[PIIEntity]) -> List[PIIEntity]:
        """
        Remove overlapping entities, keeping the longest ones.
        
        Args:
            entities: List of PII entities
            
        Returns:
            List of non-overlapping entities
        """
        if not entities:
            return []
        
        # Sort by length (descending), then by offset
        sorted_entities = sorted(entities, key=lambda e: (-e.length, e.offset))
        
        non_overlapping = []
        occupied_ranges: Set[Tuple[int, int]] = set()
        
        for entity in sorted_entities:
            entity_range = (entity.offset, entity.offset + entity.length)
            
            # Check if this entity overlaps with any already selected
            overlaps = False
            for start, end in occupied_ranges:
                if not (entity_range[1] <= start or entity_range[0] >= end):
                    overlaps = True
                    break
            
            if not overlaps:
                non_overlapping.append(entity)
                occupied_ranges.add(entity_range)
        
        # Sort back by offset for consistent replacement
        return sorted(non_overlapping, key=lambda e: e.offset)
    
    async def anonymize_filenames(
        self,
        file_tuples: List[Tuple[Path, Path]]
    ) -> Tuple[List[Tuple[Path, Path]], List[Dict]]:
        """
        Anonymize filenames containing PII using partial replacement.
        
        Args:
            file_tuples: List of (absolute_path, relative_path) tuples
            
        Returns:
            Tuple of (updated_file_tuples, filename_mappings)
        """
        if not file_tuples:
            return file_tuples, []
        
        logger.info(f"Analyzing {len(file_tuples)} filenames for PII...")
        
        # Extract filenames (just the name part, not full path)
        filenames = [relative_path.name for _, relative_path in file_tuples]
        
        # Azure Language: Entity-based detection with hash replacement
        detection_results = await self.detect_pii(filenames)
        
        updated_tuples = []
        mappings = []
        pii_count = 0
        
        for (abs_path, rel_path), detection in zip(file_tuples, detection_results):
            if detection.contains_pii:
                pii_count += 1
                
                # Apply partial replacement to filename
                original_filename = rel_path.name
                anonymized_filename = self.apply_partial_replacement(
                    original_filename,
                    detection.entities,
                    preserve_extension=self.config.preserve_extensions
                )
                
                # Build new relative path with anonymized filename
                new_rel_path = rel_path.parent / anonymized_filename
                
                # Create mapping entry
                entity_replacements = [
                    {"original": e.text, "hash": e.hash}
                    for e in detection.entities
                ]
                
                mappings.append({
                    "original_filename": original_filename,
                    "anonymized_filename": anonymized_filename,
                    "relative_path": str(rel_path),
                    "anonymized_relative_path": str(new_rel_path),
                    "contained_pii": True,
                    "detected_entities": [
                        {
                            "text": e.text,
                            "category": e.category,
                            "confidence": e.confidence,
                            "offset": e.offset,
                            "length": e.length,
                            "hash": e.hash
                        }
                        for e in detection.entities
                    ],
                    "entity_replacements": entity_replacements,
                    "hash_algorithm": "sha256",
                    "anonymized_at": datetime.now().isoformat()
                })
                
                updated_tuples.append((abs_path, new_rel_path))
            else:
                # No PII, keep original
                mappings.append({
                    "original_filename": rel_path.name,
                    "anonymized_filename": rel_path.name,
                    "relative_path": str(rel_path),
                    "anonymized_relative_path": str(rel_path),
                    "contained_pii": False,
                    "detected_entities": [],
                    "entity_replacements": [],
                    "hash_algorithm": None,
                    "anonymized_at": datetime.now().isoformat()
                })
                
                updated_tuples.append((abs_path, rel_path))
        
        logger.info(f"  Found {pii_count} files with PII entities (out of {len(file_tuples)} total)")
        
        return updated_tuples, mappings
    
    async def anonymize_folders(
        self,
        file_tuples: List[Tuple[Path, Path]]
    ) -> Tuple[List[Tuple[Path, Path]], List[Dict]]:
        """
        Anonymize folder names containing PII using partial replacement.
        
        Args:
            file_tuples: List of (absolute_path, relative_path) tuples
            
        Returns:
            Tuple of (updated_file_tuples, folder_mappings)
        """
        if not file_tuples:
            return file_tuples, []
        
        logger.info("Analyzing folders for PII...")
        
        # Extract unique folder paths (all levels if recursive)
        unique_folders: Dict[str, Set[Path]] = {}  # folder_name -> set of relative_paths using it
        
        for _, rel_path in file_tuples:
            # Get all folder components
            if self.config.anonymize_all_folders:
                # Recursive: all folder levels
                for i in range(len(rel_path.parts) - 1):  # Exclude filename
                    folder_name = rel_path.parts[i]
                    if folder_name not in unique_folders:
                        unique_folders[folder_name] = set()
                    unique_folders[folder_name].add(rel_path)
            else:
                # Only first-level folders
                if len(rel_path.parts) > 1:
                    folder_name = rel_path.parts[0]
                    if folder_name not in unique_folders:
                        unique_folders[folder_name] = set()
                    unique_folders[folder_name].add(rel_path)
        
        if not unique_folders:
            logger.info("  No folders found")
            return file_tuples, []
        
        logger.info(f"  Found {len(unique_folders)} unique folder names")
        
        folder_names = list(unique_folders.keys())
        folder_mapping: Dict[str, str] = {}  # original -> anonymized
        mappings = []
        pii_count = 0
        
        # Azure Language: Entity-based detection with hash replacement
        detection_results = await self.detect_pii(folder_names)
        
        for folder_name, detection in zip(folder_names, detection_results):
            if detection.contains_pii:
                pii_count += 1
                
                # Apply partial replacement
                anonymized_name = self.apply_partial_replacement(
                    folder_name,
                    detection.entities,
                    preserve_extension=False
                )
                
                folder_mapping[folder_name] = anonymized_name
                
                # Create mapping entry
                entity_replacements = [
                    {"original": e.text, "hash": e.hash}
                    for e in detection.entities
                ]
                
                mappings.append({
                    "original_folder": folder_name,
                    "anonymized_folder": anonymized_name,
                    "contained_pii": True,
                    "detected_entities": [
                        {
                            "text": e.text,
                            "category": e.category,
                            "confidence": e.confidence,
                            "offset": e.offset,
                            "length": e.length,
                            "hash": e.hash
                        }
                        for e in detection.entities
                    ],
                    "entity_replacements": entity_replacements,
                    "file_count": len(unique_folders[folder_name]),
                    "hash_algorithm": "sha256",
                    "anonymized_at": datetime.now().isoformat()
                })
            else:
                # No PII, keep original
                folder_mapping[folder_name] = folder_name
                
                mappings.append({
                    "original_folder": folder_name,
                    "anonymized_folder": folder_name,
                    "contained_pii": False,
                    "detected_entities": [],
                    "entity_replacements": [],
                    "file_count": len(unique_folders[folder_name]),
                    "hash_algorithm": None,
                    "anonymized_at": datetime.now().isoformat()
                })
        
        logger.info(f"  Found {pii_count} folders with PII entities (out of {len(unique_folders)} total)")
        
        # Apply folder name replacements to all file tuples
        updated_tuples = []
        for abs_path, rel_path in file_tuples:
            # Replace folder names in relative path
            new_parts = []
            for part in rel_path.parts:
                new_parts.append(folder_mapping.get(part, part))
            
            new_rel_path = Path(*new_parts) if new_parts else rel_path
            updated_tuples.append((abs_path, new_rel_path))
        
        return updated_tuples, mappings
    
    def save_mappings(
        self,
        filename_mappings: List[Dict],
        folder_mappings: List[Dict]
    ):
        """
        Persist mapping files to .mappings/ subfolder.
        
        Args:
            filename_mappings: List of filename mapping entries
            folder_mappings: List of folder mapping entries
        """
        # Create mappings directory
        self.mappings_dir.mkdir(parents=True, exist_ok=True)
        
        # Save filename mappings
        filename_mapping_file = self.mappings_dir / "filename_mapping.json"
        filename_data = {
            "version": "1.0",
            "created_at": datetime.now().isoformat(),
            "detection_strategy": self.config.detection_strategy.value,
            "confidence_threshold": self.config.confidence_threshold,
            "hash_length": self.config.hash_length,
            "mappings": filename_mappings
        }
        with open(filename_mapping_file, 'w', encoding='utf-8') as f:
            json.dump(filename_data, f, indent=2, ensure_ascii=False)
        
        # Save folder mappings
        folder_mapping_file = self.mappings_dir / "folder_mapping.json"
        folder_data = {
            "version": "1.0",
            "created_at": datetime.now().isoformat(),
            "detection_strategy": self.config.detection_strategy.value,
            "confidence_threshold": self.config.confidence_threshold,
            "hash_length": self.config.hash_length,
            "mappings": folder_mappings
        }
        with open(folder_mapping_file, 'w', encoding='utf-8') as f:
            json.dump(folder_data, f, indent=2, ensure_ascii=False)
        
        # Save entity hash cache (only for Azure Language strategy)
        if self.config.detection_strategy == DetectionStrategy.AZURE_LANGUAGE:
            entity_cache_file = self.mappings_dir / "entity_hash_map.json"
            entity_data = {
                "version": "1.0",
                "created_at": datetime.now().isoformat(),
                "hash_algorithm": "sha256",
                "hash_length": self.config.hash_length,
                "entities": self.entity_hash_cache
            }
            with open(entity_cache_file, 'w', encoding='utf-8') as f:
                json.dump(entity_data, f, indent=2, ensure_ascii=False)
            
            logger.info(f"Mappings saved to {self.mappings_dir}")
            logger.info(f"  - filename_mapping.json ({len(filename_mappings)} files)")
            logger.info(f"  - folder_mapping.json ({len(folder_mappings)} folders)")
            logger.info(f"  - entity_hash_map.json ({len(self.entity_hash_cache)} unique entities)")
        else:
            logger.info(f"Mappings saved to {self.mappings_dir}")
            logger.info(f"  - filename_mapping.json ({len(filename_mappings)} files)")
            logger.info(f"  - folder_mapping.json ({len(folder_mappings)} folders)")
    
    async def save_mappings_to_blob(
        self,
        filename_mappings: List[Dict],
        folder_mappings: List[Dict],
        prefix: str = ""
    ):
        """Save mapping files to Azure Blob Storage.
        
        Args:
            filename_mappings: List of filename mapping entries
            folder_mappings: List of folder mapping entries
            prefix: Optional blob prefix (folder path in container)
        """
        if not self.storage_adapter:
            raise ValueError("Storage adapter not configured for blob operations")
        
        # Build blob paths
        mappings_prefix = f"{prefix.rstrip('/')}/.mappings" if prefix else ".mappings"
        
        # Prepare filename mappings JSON
        filename_data = {
            "version": "1.0",
            "created_at": datetime.now().isoformat(),
            "detection_strategy": self.config.detection_strategy.value,
            "confidence_threshold": self.config.confidence_threshold,
            "hash_length": self.config.hash_length,
            "mappings": filename_mappings
        }
        filename_blob = f"{mappings_prefix}/filename_mapping.json"
        await self.storage_adapter.write_bytes(
            filename_blob,
            json.dumps(filename_data, indent=2, ensure_ascii=False).encode('utf-8')
        )
        
        # Prepare folder mappings JSON
        folder_data = {
            "version": "1.0",
            "created_at": datetime.now().isoformat(),
            "detection_strategy": self.config.detection_strategy.value,
            "confidence_threshold": self.config.confidence_threshold,
            "hash_length": self.config.hash_length,
            "mappings": folder_mappings
        }
        folder_blob = f"{mappings_prefix}/folder_mapping.json"
        await self.storage_adapter.write_bytes(
            folder_blob,
            json.dumps(folder_data, indent=2, ensure_ascii=False).encode('utf-8')
        )
        
        # Prepare entity cache JSON (only for Azure Language strategy)
        if self.config.detection_strategy == DetectionStrategy.AZURE_LANGUAGE:
            entity_data = {
                "version": "1.0",
                "created_at": datetime.now().isoformat(),
                "hash_algorithm": "sha256",
                "hash_length": self.config.hash_length,
                "entities": self.entity_hash_cache
            }
            entity_blob = f"{mappings_prefix}/entity_hash_map.json"
            await self.storage_adapter.write_bytes(
                entity_blob,
                json.dumps(entity_data, indent=2, ensure_ascii=False).encode('utf-8')
            )
            
            logger.info(f"Mappings uploaded to blob storage: {mappings_prefix}")
            logger.info(f"  - filename_mapping.json ({len(filename_mappings)} files)")
            logger.info(f"  - folder_mapping.json ({len(folder_mappings)} folders)")
            logger.info(f"  - entity_hash_map.json ({len(self.entity_hash_cache)} unique entities)")
        else:
            logger.info(f"Mappings uploaded to blob storage: {mappings_prefix}")
            logger.info(f"  - filename_mapping.json ({len(filename_mappings)} files)")
            logger.info(f"  - folder_mapping.json ({len(folder_mappings)} folders)")
    
    async def load_entity_cache_from_blob(self, prefix: str = ""):
        """Load entity hash cache from Azure Blob Storage if available.
        
        Only applicable for Azure Language strategy.
        
        Args:
            prefix: Optional blob prefix (folder path in container)
        """
        if self.config.detection_strategy != DetectionStrategy.AZURE_LANGUAGE:
            logger.debug("Entity cache not used with Azure OpenAI strategy")
            return
        
        if not self.storage_adapter:
            logger.debug("Storage adapter not configured, skipping blob cache load")
            return
        
        mappings_prefix = f"{prefix.rstrip('/')}/.mappings" if prefix else ".mappings"
        entity_blob = f"{mappings_prefix}/entity_hash_map.json"
        
        try:
            if await self.storage_adapter.exists(entity_blob):
                data = await self.storage_adapter.read_bytes(entity_blob)
                cache_data = json.loads(data.decode('utf-8'))
                
                if "entities" in cache_data:
                    self.entity_hash_cache = cache_data["entities"]
                    logger.info(f"Loaded entity cache from blob storage: {len(self.entity_hash_cache)} entities")
                else:
                    logger.warning(f"Entity cache blob exists but missing 'entities' key: {entity_blob}")
            else:
                logger.debug(f"No existing entity cache found in blob storage: {entity_blob}")
        except Exception as e:
            logger.warning(f"Failed to load entity cache from blob storage: {e}")
    
    def load_entity_cache(self):
        """Load existing entity hash cache if available for consistency across runs.
        
        Only applicable for Azure Language strategy.
        """
        if self.config.detection_strategy != DetectionStrategy.AZURE_LANGUAGE:
            logger.debug("Entity cache not used with Azure OpenAI strategy")
            return
        
        entity_cache_file = self.mappings_dir / "entity_hash_map.json"
        
        if entity_cache_file.exists():
            try:
                with open(entity_cache_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.entity_hash_cache = data.get("entities", {})
                    logger.info(f"Loaded entity cache: {len(self.entity_hash_cache)} entities")
            except Exception as e:
                logger.warning(f"Failed to load entity cache: {e}")
