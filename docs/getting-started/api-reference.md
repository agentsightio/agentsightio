---
outline: deep
---

# API Reference

AgentSight provides a comprehensive REST API for retrieving, managing, and analyzing your AI agent conversation data. This reference is for developers using the API directly with any programming language or HTTP client.

> Note: if you want to use python lib go to [AgentSightAPI](../clients/api.md)

## Authentication

All requests require authentication using an **API Key**.

**Include your API key in the request header:**

```http
Authorization: Api-Key YOUR_API_KEY_HERE
```

Get your API key from the [AgentSight Dashboard](https://app.agentsight.io/).

**Authentication errors:**
- `401 Unauthorized` - Missing or invalid API key
- `403 Forbidden` - Valid API key but insufficient permissions

## Base URL

```
https://api.agentsight.io
```

<!-- ## Rate Limiting

- **Rate limit:** 1000 requests per minute per API key
- **Headers:** `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset` -->

## Conversations

### List Conversations

<span class="api-method get">GET</span> `/api/conversations/`

Retrieve a paginated list of conversations with powerful filtering options.

#### Query Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `page` | integer | Page number (default: 1) |
| `page_size` | integer | Results per page (default: 10, max: 100) |
| `conversation_id` | string | Exact match for conversation ID |
| `customer_id` | string | Exact match for customer ID |
| `customer_id__icontains` | string | Case-insensitive partial match for customer ID |
| `name` | string | Case-insensitive partial match for conversation name |
| `language` | string | Filter by language code (e.g., "en", "es") |
| `device` | string | Filter by device type (e.g., "desktop", "mobile") |
| `customer_ip_address` | string | Exact match for customer IP address |
| `is_marked` | boolean | Filter by marked/favorite status |
| `include_deleted` | boolean | Include soft-deleted conversations (default: false) |
| `started_at_after` | datetime | Conversations started after this timestamp (ISO 8601) |
| `started_at_before` | datetime | Conversations started before this timestamp (ISO 8601) |
| `has_messages` | boolean | Only conversations with messages |
| `message_contains` | string | Search within message contents |
| `action_name` | string | Filter by action name |
| `has_feedback` | boolean | Only conversations with feedback |
| `feedback_sentiment` | string | Filter by feedback sentiment: `positive`, `neutral`, `negative` |
| `feedback_source` | string | Filter by feedback source: `customer`, `platform` |
| `metadata` | string | Filter by metadata (format: `key:value,key2:value2`) |

#### Example Request

```bash
curl -X GET "https://api.agentsight.io/api/conversations/?feedback_sentiment=positive&page_size=10" \
  -H "Authorization: Api-Key YOUR_API_KEY"
```

#### Response

<details>
<summary><code>200 OK</code></summary>

```json
{
  "count": 245,
  "next": "https://api.agentsight.io/api/conversations/?page=2",
  "previous": null,
  "results": [
    {
      "id": 42,
      "conversation_id": "conv-abc-123",
      "name": "Password Reset Support",
      "customer_id": "user-456",
      "customer_ip_address": "203.0.113.42",
      "device": "desktop",
      "language": "en",
      "environment": "production",
      "is_marked": true,
      "is_deleted": false,
      "is_used": true,
      "started_at": "2024-01-15T10:30:00Z",
      "ended_at": "2024-01-15T10:35:00Z",
      "deleted_at": null,
      "metadata": {
        "session_id": "sess_xyz",
        "source": "web_chat"
      },
      "geo_location": {
        "ip_address": "203.0.113.42",
        "city": "New York",
        "country": "US",
        "timezone_name": "America/New_York"
      },
      "messages": [
        {
          "id": 101,
          "timestamp": "2024-01-15T10:30:05Z",
          "sender": "end_user",
          "content": "I can't log in to my account",
          "metadata": {
            "message_id": "msg_001"
          }
        },
        {
          "id": 102,
          "timestamp": "2024-01-15T10:30:08Z",
          "sender": "agent",
          "content": "I'll help you reset your password",
          "metadata": {
            "message_id": "msg_002",
            "model": "gpt-4"
          }
        }
      ],
      "feedbacks": [
        {
          "id": 5,
          "sentiment": "positive",
          "source": "customer",
          "comment": "Very helpful!",
          "created_at": "2024-01-15T10:35:00Z"
        }
      ]
    }
  ]
}
```

</details>

### Get Conversation

<span class="api-method get">GET</span> `/api/conversations/{id}/`

Retrieve a single conversation with all messages, actions, attachments, and feedback.

#### Path Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `id` | integer | Conversation database ID |

#### Example Request

```bash
curl -X GET "https://api.agentsight.io/api/conversations/42/" \
  -H "Authorization: Api-Key YOUR_API_KEY"
```

#### Response

<details>
<summary><code>200 OK</code></summary>

```json
{
  "id": 42,
  "conversation_id": "conv-abc-123",
  "name": "Password Reset Support",
  "customer_id": "user-456",
  "started_at": "2024-01-15T10:30:00Z",
  "ended_at": "2024-01-15T10:35:00Z",
  "messages": [
    {
      "id": 101,
      "timestamp": "2024-01-15T10:30:05Z",
      "sender": "end_user",
      "content": "I can't log in",
      "action_name": null,
      "attachments": [],
      "action_logs": [],
      "button": null,
      "metadata": {}
    },
    {
      "id": 102,
      "timestamp": "2024-01-15T10:30:08Z",
      "sender": "agent",
      "content": "Action database_lookup performed",
      "action_name": "database_lookup",
      "attachments": [],
      "action_logs": [
        {
          "id": 50,
          "started_at": "2024-01-15T10:30:07Z",
          "ended_at": "2024-01-15T10:30:08Z",
          "duration_ms": 150,
          "tools_used": {
            "database": "users_db",
            "query_type": "SELECT"
          },
          "response": "User found",
          "error_message": "",
          "metadata": {}
        }
      ],
      "button": null,
      "metadata": {}
    }
  ],
  "feedbacks": [],
  "geo_location": null
}
```

</details>

**Error Responses:**
- `404 Not Found` - Conversation doesn't exist or access denied

### Get Conversation Attachments

<span class="api-method get">GET</span> `/api/conversations/{id}/attachments/`

Retrieve all attachments from a conversation, organized by message.

#### Path Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `id` | integer | Conversation database ID |

#### Example Request

```bash
curl -X GET "https://api.agentsight.io/api/conversations/42/attachments/" \
  -H "Authorization: Api-Key YOUR_API_KEY"
```

#### Response

<details>
<summary><code>200 OK</code></summary>

```json
{
  "conversation_id": "conv-abc-123",
  "conversation": 42,
  "total_attachments": 3,
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
          "file_url": "https://cdn.agentsight.io/files/screenshot.png"
        },
        {
          "id": 202,
          "type": "document",
          "filename": "report.pdf",
          "mime_type": "application/pdf",
          "size_bytes": 1048576,
          "file_url": "https://cdn.agentsight.io/files/report.pdf"
        }
      ]
    }
  ]
}
```

</details>

### Mark Conversation

<span class="api-method post">POST</span> `/api/conversations/{id}/mark/`

Mark or unmark a conversation as favorite/important.

#### Path Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `id` | integer | Conversation database ID |

#### Request Body

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `is_marked` | boolean | Yes | `true` to mark, `false` to unmark |

#### Example Request

```bash
curl -X POST "https://api.agentsight.io/api/conversations/42/mark/" \
  -H "Authorization: Api-Key YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"is_marked": true}'
```

#### Response

<details>
<summary><code>200 OK</code></summary>

```json
{
  "id": 42,
  "conversation_id": "conv-abc-123",
  "is_marked": true
}
```

</details>

### Rename Conversation

<span class="api-method patch">PATCH</span> `/api/conversations/{id}/rename/`

Update the name of a conversation.

#### Path Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `id` | integer | Conversation database ID |

#### Request Body

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | Yes | New conversation name (max 255 characters) |

#### Example Request

```bash
curl -X PATCH "https://api.agentsight.io/api/conversations/42/rename/" \
  -H "Authorization: Api-Key YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"name": "Resolved: Password Reset"}'
```

#### Response

<details>
<summary><code>200 OK</code></summary>

```json
{
  "id": 42,
  "conversation_id": "conv-abc-123",
  "name": "Resolved: Password Reset"
}
```

</details>

### Update Conversation

<span class="api-method patch">PATCH</span> `/api/conversations/{id}/update/`

Update multiple fields of a conversation in one request.

#### Path Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `id` | integer | Conversation database ID |

#### Request Body

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Conversation name (max 255 chars) |
| `is_marked` | boolean | Mark as favorite |
| `customer_id` | string | Customer identifier |
| `device` | string | Device type |
| `language` | string | Language code |
| `metadata` | object | Custom metadata (JSON object) |

**Note:** All fields are optional. Only include fields you want to update.

#### Example Request

```bash
curl -X PATCH "https://api.agentsight.io/api/conversations/42/update/" \
  -H "Authorization: Api-Key YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "VIP Customer Support",
    "is_marked": true,
    "metadata": {
      "priority": "high",
      "assigned_to": "agent_007"
    }
  }'
```

#### Response

<details>
<summary><code>200 OK</code></summary>

```json
{
  "id": 42,
  "conversation_id": "conv-abc-123",
  "name": "VIP Customer Support",
  "is_marked": true,
  "metadata": {
    "priority": "high",
    "assigned_to": "agent_007"
  }
}
```

</details>

### Delete Conversation

<span class="api-method delete">DELETE</span> `/api/conversations/{id}/delete/`

Soft delete a conversation (sets `is_deleted=true`). The conversation can still be retrieved with `include_deleted=true` filter.

#### Path Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `id` | integer | Conversation database ID |

#### Example Request

```bash
curl -X DELETE "https://api.agentsight.io/api/conversations/42/delete/" \
  -H "Authorization: Api-Key YOUR_API_KEY"
```

#### Response

<details>
<summary><code>200 OK</code></summary>

```json
{
  "id": 42,
  "conversation_id": "conv-abc-123",
  "is_deleted": true,
  "deleted_at": "2024-01-15T11:00:00Z"
}
```

</details>

## Feedback

### Submit Feedback

<span class="api-method post">POST</span> `/api/conversation-feedbacks/`

Submit user feedback for a conversation.

#### Request Body

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `conversation_id` | string | Yes* | Conversation string ID |
| `conversation` | integer | Yes* | Conversation database ID |
| `sentiment` | string | Yes | `positive`, `neutral`, or `negative` |
| `comment` | string | No | User feedback comment (max 5000 chars) |
| `metadata` | object | No | Additional metadata |

**Note:** Provide either `conversation_id` (string) OR `conversation` (integer).

#### Example Request

```bash
curl -X POST "https://api.agentsight.io/api/conversation-feedbacks/" \
  -H "Authorization: Api-Key YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "conversation_id": "conv-abc-123",
    "sentiment": "positive",
    "comment": "Very helpful and fast response!",
    "metadata": {
      "rating": 5,
      "would_recommend": true
    }
  }'
```

#### Response

<details>
<summary><code>201 Created</code></summary>

```json
{
  "id": 10,
  "conversation": 42,
  "sentiment": "positive",
  "source": "customer",
  "comment": "Very helpful and fast response!",
  "metadata": {
    "rating": 5,
    "would_recommend": true
  },
  "created_at": "2024-01-15T10:40:00Z"
}
```

</details>

**Note:** `source` is automatically set to `customer` for API key requests.

## Common Response Codes

| Code | Description |
|------|-------------|
| `200 OK` | Request successful |
| `201 Created` | Resource created successfully |
| `400 Bad Request` | Invalid request parameters |
| `401 Unauthorized` | Missing or invalid API key |
| `403 Forbidden` | Insufficient permissions |
| `404 Not Found` | Resource not found |
| `429 Too Many Requests` | Rate limit exceeded |
| `500 Internal Server Error` | Server error |

## Pagination

All list endpoints support pagination:

```json
{
  "count": 245,
  "next": "https://api.agentsight.io/api/conversations/?page=3",
  "previous": "https://api.agentsight.io/api/conversations/?page=1",
  "results": [...]
}
```

**Parameters:**
- `page` - Page number (default: 1)
- `page_size` - Results per page (default: 10, max: 100)

## Filtering Examples

**Positive customer feedback from last 7 days:**
```
GET /api/conversations/?feedback_sentiment=positive&feedback_source=customer&started_at_after=2024-01-08T00:00:00Z
```

**Conversations with specific action:**
```
GET /api/conversations/?action_name=database_query
```

**Search message content:**
```
GET /api/conversations/?message_contains=password+reset
```

**Filter by metadata:**
```
GET /api/conversations/?metadata=priority:high,status:resolved
```

**Marked conversations on mobile:**
```
GET /api/conversations/?is_marked=true&device=mobile
```

## Timestamps

All timestamps use **ISO 8601 format** in UTC:

```
2024-01-15T10:30:00Z
```

<!-- ## Need Help?

- **Documentation:** [https://docs.agentsight.io](https://docs.agentsight.io)
- **Support:** support@agentsight.io
- **Discord:** [Join our community](https://discord.gg/agentsight) -->