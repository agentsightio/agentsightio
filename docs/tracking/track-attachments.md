---
outline: deep
---

# Track Attachments Method

The `track_attachments()` method allows you to log file attachments separately from your conversations. This is ideal for handling large files, multiple attachments, or when you need specialized file handling options.

## Method Signature

```python
def track_attachments(
    attachments: List[AttachmentInput],
    conversation_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    mode: Union[str, AttachmentMode] = AttachmentMode.BASE64
) -> Dict[str, Any]:
```

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `attachments` | `List[AttachmentInput]` | Yes | List of attachment objects |
| `conversation_id` | `str` | No | Unique identifier for the conversation (auto-generated if not provided) |
| `metadata` | `Dict[str, Any]` | No | Additional contextual information |
| `mode` | `str \| AttachmentMode` | No | Sending mode: 'base64' (default) or 'form_data' |

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
    'mime_type': 'image/jpeg',
    'data': file_bytes_or_file_object  # bytes, BytesIO, or file-like object
}
```

## Complete Usage Example

### Single File

#### Base64 Mode (Default)

```python
import base64

# Read and encode file
with open('document.pdf', 'rb') as file:
    file_content = base64.b64encode(file.read()).decode('utf-8')

# Track attachment
response = tracker.track_attachments(
    attachments=[{
        'filename': 'document.pdf',
        'mime_type': 'application/pdf',
        'data': file_content
    }]
)
```

#### Form Data Mode
```python
# Track attachment using form data mode
with open('image.jpg', 'rb') as file:
    file_bytes = file.read()

response = tracker.track_attachments(
    attachments=[{
        'filename': 'image.jpg',
        'mime_type': 'image/jpeg',
        'data': file_bytes  # bytes object
    }],
    mode='form_data'
)
```

### Multiple Attachments with Context
```python
from agentsight.enums import AttachmentMode

# Handle multiple files from a chatbot interaction
chatbot_files = [
    {'name': 'user_report.pdf', 'content': pdf_bytes, 'type': 'application/pdf'},
    {'name': 'screenshot.png', 'content': image_bytes, 'type': 'image/png'}
]

# Prepare attachments
attachments = []
for file_info in chatbot_files:
    attachments.append({
        'filename': file_info['name'],
        'mime_type': file_info['type'],
        'data': file_info['content']  # bytes
    })

# Track with full context
response = tracker.track_attachments(
    attachments=attachments,
    conversation_id="support_session_123",
    metadata={
        "source": "customer_upload",
        "category": "technical_support"
    },
    mode=AttachmentMode.FORM_DATA
)
```

## Attachment Modes

### BASE64 Mode
- **Best for**: Any file size, simple implementation
- **Pros**: No size limits, works with any file type, simple base64 encoding
- **Cons**: Increases payload size by ~33%

### FORM_DATA Mode
- **Best for**: Large files or when optimizing transfer size
- **Pros**: Efficient for large files, native binary transfer, better performance
- **Cons**: Slightly more complex handling

## Important Notes

:::tip Mode Selection
- Use **base64** for simple implementation and when you already have base64 data
- Use **form_data** for large files, better performance, or when working with bytes/streams
- The mode affects how the data should be prepared in the attachment object
:::

:::warning Data Format
- **Base64 mode**: Expects base64-encoded strings in the `data` field
- **Form data mode**: Expects bytes, BytesIO objects, or file-like objects in the `data` field
- Always match your data format to the selected mode
:::
