# Quick Reference: PII Redaction Strategies

## Command Examples

### Default (Azure AI Language)
```bash
python main.py ./inp ./anonymized --batch-size 7 --language cs
```

### Azure OpenAI Strategy
```bash
python main.py ./inp ./anonymized \
  --redaction-strategy azure_openai \
  --batch-size 5 \
  --language cs
```

### With Validation
```bash
python main.py ./inp ./anonymized --validate
```

### All Options
```bash
python main.py ./inp ./anonymized \
  --redaction-strategy azure_openai \
  --validate \
  --batch-size 5 \
  --language cs \
  --log-level DEBUG
```

## Environment Variables

### Always Required
```bash
DOCUMENTINTELLIGENCE_ENDPOINT=https://...
DOCUMENTINTELLIGENCE_API_KEY=...
```

### For Azure Language Strategy (default)
```bash
AZURE_LANGUAGE_ENDPOINT=https://...
AZURE_LANGUAGE_KEY=...
```

### For Azure OpenAI Strategy or Validation
```bash
AZURE_OPENAI_ENDPOINT=https://...
AZURE_OPENAI_API_KEY=...
AZURE_OPENAI_DEPLOYMENT=gpt-4
```

## Strategy Comparison

| Feature | Azure Language | Azure OpenAI |
|---------|---------------|--------------|
| Speed | Fast | Moderate |
| Cost | Low (per request) | Higher (per token) |
| Accuracy | High (specialized) | Very High (context-aware) |
| Token Tracking | No | Yes |
| Entity Categories | Yes | Yes |
| Best For | Production, high volume | Complex cases, quality focus |

## Output Metrics Example

### With Azure Language
```
Stage 2 - PII Redaction:
  Successful: 6
  Failed: 0
  Entities redacted: 127
  Duration: 12.18s
```

### With Azure OpenAI
```
Stage 2 - PII Redaction:
  Successful: 6
  Failed: 0
  Entities redacted: 134
  Duration: 18.45s
  Tokens used: 45,280 (prompt: 38,150, completion: 7,130)
```

### With Validation
```
Stage 3 - PII Validation:
  Successful: 6
  Failed: 0
  Documents with PII found: 0
  Duration: 8.45s
  Tokens used: 32,100 (prompt: 28,500, completion: 3,600)
```

## When to Use Each Strategy

**Azure Language (default)**:
- Production environments with high document volume
- Cost-sensitive deployments
- Standard PII types (names, emails, addresses, IDs)
- Fast turnaround required

**Azure OpenAI**:
- Complex document structures
- Domain-specific PII patterns
- Quality over speed priority
- Need for context-aware redaction
- Budget allows for LLM costs

**Validation (optional Stage 3)**:
- High-security requirements
- Regulatory compliance needs
- Quality assurance workflows
- Testing redaction effectiveness
- Can use with EITHER strategy

## Programmatic Usage

```python
from utils.redaction import RedactionConfig, create_redaction_strategy

# Create config
config = RedactionConfig(
    strategy_type="azure_openai",
    language="en",
    openai_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
    openai_api_key=os.environ["AZURE_OPENAI_API_KEY"],
    openai_deployment=os.environ["AZURE_OPENAI_DEPLOYMENT"]
)

# Use strategy
strategy = create_redaction_strategy(config)
async with strategy:
    result = await strategy.redact_document("input.md", "output.md")
    
    print(f"Success: {result.success}")
    print(f"Entities: {result.entities_redacted}")
    
    if result.metadata:
        print(f"Categories: {result.metadata['entity_categories']}")
        if "tokens_used" in result.metadata:
            print(f"Tokens: {result.metadata['tokens_used']}")
```

## Validation Usage

```python
from utils.redaction import ValidationConfig
from utils.redaction.validation import DocumentValidator

config = ValidationConfig(
    enabled=True,
    openai_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
    openai_api_key=os.environ["AZURE_OPENAI_API_KEY"],
    openai_deployment=os.environ["AZURE_OPENAI_DEPLOYMENT"]
)

validator = DocumentValidator(config)
async with validator:
    result = await validator.validate_document("redacted.md")
    
    if result.success:
        if result.has_pii:
            print(f"⚠ PII found: {result.pii_categories}")
            print(f"Details: {result.details}")
        else:
            print("✓ No PII detected")
        
        print(f"Tokens: {result.tokens_used}")
```
