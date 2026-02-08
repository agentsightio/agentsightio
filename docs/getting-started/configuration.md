---
outline: deep
---

<CopyMarkdownButton />

# Environment Configuration

Set up AgentSight effortlessly with environment variables. Just add your API key to get started!

**.env**

```bash
AGENTSIGHT_API_KEY=your_api_key_here
```

Get your AgentSight API Key from the [AgentSight Dashboard](https://app.agentsight.io/).

## Additional Configuration Options

Customize AgentSight's behavior with these optional environment variables:

**.env**

```bash
# Environment Configuration
AGENTSIGHT_ENVIRONMENT=development # Options: production, development

# Logging Configuration
AGENTSIGHT_LOG_LEVEL=INFO  # Options: DEBUG, INFO, WARNING, ERROR, CRITICAL

# Token handler type
AGENTSIGHT_TOKEN_HANDLER_TYPE=llamaindex # Options: llamaindex
```

For more information on token handlers visit [Token handlers](../tracking/track-tokens.md)
