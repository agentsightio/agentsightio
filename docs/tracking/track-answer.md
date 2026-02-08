---
outline: deep
---

<CopyMarkdownButton />

# Track Agent Message Method

The `track_agent_message()` method allows you to log individual AI agent responses with optional file attachments.

## Method Signature

```python
def track_agent_message(
    message: str,
    attachments: Optional[List[AttachmentInput]] = None,
    attachment_mode: Union[str, AttachmentMode] = AttachmentMode.BASE64,
    metadata: Optional[Dict[str, Any]] = None
) -> None:
```

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `message` | `str` | Yes | The AI agent's response |
| `attachments` | `List[AttachmentInput]` | No | List of file attachments to include with the message |
| `attachment_mode` | `str \| AttachmentMode` | No | Sending mode: 'base64' (default) or 'form_data' |
| `metadata` | `Dict[str, Any]` | No | Additional contextual information |

## Attachment Input Format

Each attachment in the list should be a dictionary with the following structure:

### Base64 Mode (Default)
```python
{
    'filename': 'guide.pdf',
    'mime_type': 'application/pdf',
    'data': 'base64_encoded_string_here'
}
```

### Form Data Mode
```python
{
    'filename': 'report.pdf',
    'data': file_bytes_or_file_object  # bytes, BytesIO, or file-like object
}
```

## Usage Examples

### Simple Message Without Attachments

```python
tracker.track_agent_message(
    message="Based on your requirements, I suggest using our Enterprise solution.",
    metadata={
        "consultation_stage": "recommendation",
        "product_category": "enterprise_software",
        "customer_segment": "large_business"
    }
)
```

### Message with Single Attachment (Base64)

```python
import base64

# Read and encode file
with open('user_guide.pdf', 'rb') as file:
    file_content = base64.b64encode(file.read()).decode('utf-8')

# Track agent message with attachment
tracker.track_agent_message(
    message="Here's the user guide you requested",
    attachments=[{
        'filename': 'user_guide.pdf',
        'mime_type': 'application/pdf',
        'data': file_content
    }],
    attachment_mode='base64',
    metadata={
        "document_type": "guide",
        "version": "2.1.0"
    }
)
```

### Message with Single Attachment (Form Data)

```python
# Track agent message with binary file
with open('invoice.pdf', 'rb') as file:
    file_bytes = file.read()

tracker.track_agent_message(
    message="I've generated your invoice for the current billing cycle",
    attachments=[{
        'filename': 'invoice_january_2024.pdf',
        'data': file_bytes
    }],
    attachment_mode='form_data',
    metadata={
        "document_type": "invoice",
        "billing_period": "2024-01",
        "auto_generated": True
    }
)
```

### Message with Multiple Attachments

```python
import base64

# Prepare multiple resource attachments
attachments = []

# Add setup guide
with open('setup_guide.pdf', 'rb') as file:
    attachments.append({
        'filename': 'setup_guide.pdf',
        'mime_type': 'application/pdf',
        'data': base64.b64encode(file.read()).decode('utf-8')
    })

# Add API documentation
with open('api_docs.pdf', 'rb') as file:
    attachments.append({
        'filename': 'api_documentation.pdf',
        'mime_type': 'application/pdf',
        'data': base64.b64encode(file.read()).decode('utf-8')
    })

# Add sample code
with open('example.py', 'rb') as file:
    attachments.append({
        'filename': 'sample_integration.py',
        'mime_type': 'text/x-python',
        'data': base64.b64encode(file.read()).decode('utf-8')
    })

# Track agent message with all resources
tracker.track_agent_message(
    message="Here are all the resources you'll need to get started with our API",
    attachments=attachments,
    attachment_mode='base64',
    metadata={
        "resource_type": "onboarding_package",
        "file_count": len(attachments),
        "customer_tier": "developer"
    }
)
```

## Important Notes

:::tip Choosing Between Methods
**Message with Attachments** (NEW):
```python
tracker.track_agent_message(
    message="Here are your resources",
    attachments=[...],
    attachment_mode='form_data'
)
```
✅ Files are linked to the specific message  
✅ Better context preservation

**Standalone Attachments** (ORIGINAL):
```python
tracker.track_attachments(
    attachments=[...],
    mode='form_data'
)
```
✅ Files are independent of messages  
✅ Agent sends files without accompanying text
:::

:::info Attachment Modes
**Base64 Mode (default)**

- Use Base64 mode for simple integrations and small numbers of files. It's easy to implement and works well when your data is already base64-encoded, but it results in larger payloads.

**Form-Data Mode**

- Use Form-Data mode for large files or high-volume uploads. It's more efficient and better for performance, especially when working with raw binary data, but requires multipart handling.
:::

:::warning Data Format Requirements
- **Base64 mode**: 
  - Expects base64-encoded strings in `data` field
  - Must include `filename` and `mime_type` fields
  - Use `base64.b64encode(bytes).decode('utf-8')`

- **Form data mode**: 
  - Expects bytes, BytesIO, or file-like objects in `data` field
  - Must include `filename` field
  - MIME type is auto-detected from filename
  - Use raw bytes: `file.read()` or `BytesIO(data)`
:::
