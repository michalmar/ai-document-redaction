# PII Redaction Strategies

This package provides flexible PII redaction with multiple strategies.

## Architecture

- **Strategy Pattern**: Each redaction method is a separate strategy implementing `RedactionStrategy`
- **Factory**: `create_redaction_strategy()` instantiates the correct strategy based on config
- **Validation**: Optional LLM-based validation to check for remaining PII

## Strategies

### Azure AI Language (`azure_language`)
Uses Azure AI Language PII recognition service.
- Fast and cost-effective
- High accuracy for common PII types
- Returns entity categories

### Azure OpenAI (`azure_openai`)
Uses LLM for context-aware PII detection.
- More flexible and context-aware
- Higher cost (token-based)
- Returns entity categories and token usage

## Usage

```python
from utils.redaction import RedactionConfig, create_redaction_strategy

# Azure Language strategy
config = RedactionConfig(
    strategy_type="azure_language",
    language="en",
    language_endpoint="https://...",
    language_api_key="..."
)

# Azure OpenAI strategy
config = RedactionConfig(
    strategy_type="azure_openai",
    language="en",
    openai_endpoint="https://...",
    openai_api_key="...",
    openai_deployment="gpt-4"
)

# Use strategy
strategy = create_redaction_strategy(config)
async with strategy:
    result = await strategy.redact_document("input.md", "output.md")
    print(f"Entities redacted: {result.entities_redacted}")
    if result.metadata:
        print(f"Token usage: {result.metadata.get('tokens_used', 0)}")
```

## Validation

Optional Stage 3 validation checks redacted documents for remaining PII:

```python
from utils.redaction import ValidationConfig
from utils.redaction.validation import DocumentValidator

config = ValidationConfig(
    enabled=True,
    openai_endpoint="https://...",
    openai_api_key="...",
    openai_deployment="gpt-4"
)

validator = DocumentValidator(config)
async with validator:
    result = await validator.validate_document("redacted.md")
    if result.has_pii:
        print(f"PII found: {result.pii_categories}")
```

## Files

- `base.py` - Abstract `RedactionStrategy` and common utilities
- `config.py` - `RedactionConfig` and `ValidationConfig` dataclasses
- `factory.py` - Factory for creating strategies
- `azure_language.py` - Azure AI Language strategy implementation
- `azure_openai.py` - Azure OpenAI LLM strategy implementation
- `validation.py` - LLM-based validation for redacted documents
