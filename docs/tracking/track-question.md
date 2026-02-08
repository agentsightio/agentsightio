---
outline: deep
---

<CopyMarkdownButton />

# Track Human Message Method

The `track_human_message()` method allows you to log individual user messages with optional file attachments.

## Method Signature

```python
def track_human_message(
    message: str,
    attachments: Optional[List[AttachmentInput]] = None,
    attachment_mode: Union[str, AttachmentMode] = AttachmentMode.BASE64,
    metadata: Optional[Dict[str, Any]] = None
) -> None:
```

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `message` | `str` | Yes | The user's question or input |
| `attachments` | `List[AttachmentInput]` | No | List of file attachments to include with the message |
| `attachment_mode` | `str \| AttachmentMode` | No | Sending mode: 'base64' (default) or 'form_data' |
| `metadata` | `Dict[str, Any]` | No | Additional contextual information |

## Attachment Input Format

Each attachment in the list should be a dictionary with the following structure:

### Base64 Mode (Default)
```python
{
    'filename': 'document.pdf',
    'mime_type': 'application/pdf',
    'data': 'base64_encoded_string_here'
}
```

### Form Data Mode
```python
{
    'filename': 'image.jpg',
    'data': file_bytes_or_file_object  # bytes, BytesIO, or file-like object
}
```

## Usage Examples

### Simple Message Without Attachments

```python
tracker.track_human_message(
    message="I'm experiencing issues with my account access",
    metadata={
        "department": "technical_support",
        "issue_type": "login_problem",
        "priority": "high"
    }
)
```

### Message with Single Attachment (Base64)

```python
import base64

# Read and encode file
with open('id_document.pdf', 'rb') as file:
    file_content = base64.b64encode(file.read()).decode('utf-8')

# Track message with attachment
tracker.track_human_message(
    message="Here is my ID document for verification",
    attachments=[{
        'filename': 'id_document.pdf',
        'mime_type': 'application/pdf',
        'data': file_content
    }],
    attachment_mode='base64',
    metadata={
        "document_type": "identification",
        "verification_required": True
    }
)
```

### Message with Single Attachment (Form Data)

```python
# Track message with binary file
with open('screenshot.png', 'rb') as file:
    file_bytes = file.read()

tracker.track_human_message(
    message="Here's a screenshot of the error I'm seeing",
    attachments=[{
        'filename': 'error_screenshot.png',
        'data': file_bytes
    }],
    attachment_mode='form_data',
    metadata={
        "issue_type": "bug_report",
        "screen": "login_page"
    }
)
```

### Message with Multiple Attachments

```python
import base64

# Prepare multiple attachments
attachments = []

# Add ID document
with open('passport.pdf', 'rb') as file:
    attachments.append({
        'filename': 'passport.pdf',
        'mime_type': 'application/pdf',
        'data': base64.b64encode(file.read()).decode('utf-8')
    })

# Add proof of address
with open('utility_bill.pdf', 'rb') as file:
    attachments.append({
        'filename': 'utility_bill.pdf',
        'mime_type': 'application/pdf',
        'data': base64.b64encode(file.read()).decode('utf-8')
    })

# Add bank statement
with open('bank_statement.pdf', 'rb') as file:
    attachments.append({
        'filename': 'bank_statement.pdf',
        'mime_type': 'application/pdf',
        'data': base64.b64encode(file.read()).decode('utf-8')
    })

# Track message with all documents
tracker.track_human_message(
    message="Here are all the verification documents you requested",
    attachments=attachments,
    attachment_mode='base64',
    metadata={
        "verification_type": "full_kyc",
        "document_count": len(attachments),
        "customer_tier": "premium"
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
