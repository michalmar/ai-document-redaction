"""Factory for creating PII redaction strategies."""

from .base import RedactionStrategy
from .config import RedactionConfig
from .azure_language import AzureLanguageStrategy
from .azure_openai import AzureOpenAIStrategy
from .azure_openai_fast import AzureOpenAIFastStrategy


def create_redaction_strategy(config: RedactionConfig) -> RedactionStrategy:
    """
    Create a redaction strategy based on configuration.
    
    Args:
        config: RedactionConfig specifying strategy type and credentials
        
    Returns:
        Initialized RedactionStrategy instance
        
    Raises:
        ValueError: If strategy_type is unknown or config is invalid
    """
    config.validate()
    
    if config.strategy_type == "azure_language":
        return AzureLanguageStrategy(config)
    elif config.strategy_type == "azure_openai":
        return AzureOpenAIStrategy(config)
    elif config.strategy_type == "azure_openai_fast":
        return AzureOpenAIFastStrategy(config)
    else:
        raise ValueError(
            f"Unknown strategy_type: {config.strategy_type}. "
            f"Supported: 'azure_language', 'azure_openai', 'azure_openai_fast'"
        )
