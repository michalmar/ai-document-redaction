"""Configuration for PII redaction strategies."""

from dataclasses import dataclass
from typing import Literal


@dataclass
class RedactionConfig:
    """
    Configuration for PII redaction.
    
    Args:
        strategy_type: Redaction strategy to use ("azure_language", "azure_openai", or "azure_openai_fast")
        language: Document language code (e.g., "en", "cs", "de")
        max_chunk_size: Maximum characters per chunk for Azure Language (default: 5000)
        max_chunk_size_openai: Maximum characters per chunk for Azure OpenAI LLM (default: 100000)
        enable_entity_logging: Enable entity extraction logging for azure_openai_fast strategy (default: False)
        
        # Azure AI Language fields (required if strategy_type == "azure_language")
        language_endpoint: Azure Language endpoint URL
        language_api_key: Azure Language API key
        
        # Azure OpenAI fields (required if strategy_type == "azure_openai")
        openai_endpoint: Azure OpenAI endpoint URL
        openai_api_key: Azure OpenAI API key
        openai_deployment: Azure OpenAI deployment/model name
        openai_api_version: Azure OpenAI API version
    """
    strategy_type: Literal["azure_language", "azure_openai", "azure_openai_fast"]
    language: str = "en"
    max_chunk_size: int = 5000
    max_chunk_size_openai: int = 100000
    enable_entity_logging: bool = False
    
    # Azure AI Language fields
    language_endpoint: str | None = None
    language_api_key: str | None = None
    
    # Azure OpenAI fields
    openai_endpoint: str | None = None
    openai_api_key: str | None = None
    openai_deployment: str | None = None
    openai_api_version: str = "2024-08-01-preview"
    
    def validate(self):
        """Validate configuration based on selected strategy."""
        if self.strategy_type == "azure_language":
            if not self.language_endpoint:
                raise ValueError("language_endpoint is required for azure_language strategy")
            if not self.language_api_key:
                raise ValueError("language_api_key is required for azure_language strategy")
        elif self.strategy_type in ("azure_openai", "azure_openai_fast"):
            if not self.openai_endpoint:
                raise ValueError(f"openai_endpoint is required for {self.strategy_type} strategy")
            if not self.openai_api_key:
                raise ValueError(f"openai_api_key is required for {self.strategy_type} strategy")
            if not self.openai_deployment:
                raise ValueError(f"openai_deployment is required for {self.strategy_type} strategy")
        else:
            raise ValueError(f"Unknown strategy_type: {self.strategy_type}")


@dataclass
class ValidationConfig:
    """
    Configuration for optional LLM-based PII validation.
    
    Args:
        enabled: Whether to run validation stage
        openai_endpoint: Azure OpenAI endpoint URL
        openai_api_key: Azure OpenAI API key
        openai_deployment: Azure OpenAI deployment/model name
        openai_api_version: Azure OpenAI API version
        max_chunk_size: Maximum characters per chunk
    """
    enabled: bool = False
    openai_endpoint: str | None = None
    openai_api_key: str | None = None
    openai_deployment: str | None = None
    openai_api_version: str = "2024-08-01-preview"
    max_chunk_size: int = 5000
    
    def validate(self):
        """Validate configuration if validation is enabled."""
        if self.enabled:
            if not self.openai_endpoint:
                raise ValueError("openai_endpoint is required when validation is enabled")
            if not self.openai_api_key:
                raise ValueError("openai_api_key is required when validation is enabled")
            if not self.openai_deployment:
                raise ValueError("openai_deployment is required when validation is enabled")
