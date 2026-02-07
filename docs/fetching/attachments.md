---
outline: deep
---

# Fetch Conversation Attachments

The `fetch_conversation_attachments()` method allows you to retrieve all attachments from a conversation, organized by message. This provides a focused view of all files, images, and documents shared during a conversation.

## Method Signature

```python
agentsight_api.fetch_conversation_attachments(
    conversation_id: Union[int, str]
)
```

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `conversation_id` | string or integer | **Yes** | Conversation ID (string) or database ID (integer) |

## Usage Example

```python
from agentsight import agentsight_api

# Fetch attachments by string conversation_id
attachments = agentsight_api.fetch_conversation_attachments("conv-abc-123") # or database ID

print(f"Total attachments: {attachments['total_attachments']}")
print(f"Messages with attachments: {len(attachments['messages'])}")
```

## What's Included

The response contains:

- **Conversation Info**: conversation_id, database ID
- **Total Count**: Total number of attachments
- **Messages**: Only messages that have attachments
- **Attachment Details**: 
  - File URL (CDN link)
  - Filename
  - MIME type
  - File size in bytes
  - Attachment type (image, document, text, etc.)
  - Message and attachment IDs

## Response Structure

```python
attachments = agentsight_api.fetch_conversation_attachments("conv-123")

# Complete response structure:
{
    "conversation_id": "conv-abc-123",
    "conversation": 42,
    "total_attachments": 5,
    "messages": [
        {
            "message_id": 105,
            "sender": "end_user",
            "timestamp": "2024-01-15T10:31:00Z",
            "attachments": [
                {
                    "id": 201,
                    "type": "image",
                    "filename": "screenshot.png",
                    "mime_type": "image/png",
                    "size_bytes": 245680,
                    "file_url": "https://cdn.agentsight.io/files/conv-123/screenshot.png"
                },
                {
                    "id": 202,
                    "type": "document",
                    "filename": "report.pdf",
                    "mime_type": "application/pdf",
                    "size_bytes": 1048576,
                    "file_url": "https://cdn.agentsight.io/files/conv-123/report.pdf"
                }
            ]
        },
        {
            "message_id": 108,
            "sender": "agent",
            "timestamp": "2024-01-15T10:33:00Z",
            "attachments": [
                {
                    "id": 203,
                    "type": "document",
                    "filename": "instructions.pdf",
                    "mime_type": "application/pdf",
                    "size_bytes": 524288,
                    "file_url": "https://cdn.agentsight.io/files/conv-123/instructions.pdf"
                }
            ]
        }
    ]
}
```

## Attachment Types

The `type` field indicates the file category:

| Type | Common MIME Types | Examples |
|------|-------------------|----------|
| `image` | `image/*` | PNG, JPEG, GIF, SVG |
| `document` | `application/pdf`, `application/msword` | PDF, DOC, DOCX, XLS |
| `text` | `text/*` | TXT, CSV, MD |
| `audio` | `audio/*` | MP3, WAV, OGG |
| `video` | `video/*` | MP4, AVI, MOV |
