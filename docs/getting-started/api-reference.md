---
outline: deep
---

# Conversation API

After your data has been captured by AgentSight, you can use the Conversation API to retrieve it, including conversations, messages, attachments, and actions.

This API provides **read-only** access to your stored conversational data, allowing you to integrate insights into your own systems.

All endpoints listed below use the <span class="api-method get">GET</span> method and require authentication.

## Authentication

All requests to the Conversation API must be authenticated.  

- **API Key** - get your api key from Agentsight.io

Include a valid key with every request.

**Possible auth errors:**
- `401 Unauthorized` - missing or invalid credentials  
- `403 Forbidden` - authenticated, but not authorized to access the requested agent or resource

## Base URL
`https://api.agentsight.io`
<!-- | Environment | Base URL |
|--------------|-----------|
| Production | `https://api.agentsight.io` | -->

## Summary of Available GET Endpoints

| Method | Endpoint                               | Description                                    |
| ------ | -------------------------------------- | ---------------------------------------------- |
| `GET`  | `/api/conversations/`                  | List all conversations (paginated, filterable) |
| `GET`  | `/api/conversations/{id}/`             | Retrieve a single conversation by ID           |
| `GET`  | `/api/conversations/{id}/attachments/` | Retrieve attachments for a conversation        |

## List Conversations

<span class="api-method get">GET</span>  `/api/conversations/`

Retrieve a paginated list of conversations for the authenticated agent.

### Description
Consistently scopes requests to a single Agent, supporting both JWT and cookie authentication.

- For **API key**, the agent ID is taken from your credentials.

### Query Parameters

<!-- | `customer_id__icontains` | string | Case-insensitive match for customer ID | -->
<!-- | `is_favorite` | boolean | Return only favorite conversations | -->
| Name | Type | Description |
|------|------|--------------|
| `action_name` | string | Filter by action name |
| `conversation_id` | string | Filter by conversation ID |
| `customer_id` | string | Exact match for customer ID |
| `customer_ip_address` | string | Filter by customer IP |
| `device` | string | Filter by device type |
| `has_messages` | boolean | Return only conversations with messages |
| `language` | string | Filter by language |
| `message_contains` | string | Search within message contents |
| `page` | integer | Page number (pagination) |
| `page_size` | integer | Results per page |
| `started_at_after` | date-time | Conversations started after this timestamp |
| `started_at_before` | date-time | Conversations started before this timestamp |

### Response

<details>
<summary><code>200 OK</code></summary>

```json
{
  "count": 123,
  "next": "https://api.agentsight.io/api/conversations/?page=2",
  "previous": null,
  "results": [
    {
      "id": 1,
      "conversation_id": "abc123",
      "customer_id": "cust_001",
      "language": "en",
      "device": "desktop",
      "is_favorite": false,
      "is_used": true,
      "started_at": "2025-10-22T10:00:00Z",
      "ended_at": "2025-10-22T10:10:00Z",
      "geo_location": {
        "ip_address": "192.168.0.1",
        "city": "New York",
        "country": "US"
      },
      "messages": []
    }
  ]
}
```

</details>

**Error responses:**

* `401 Unauthorized`
* `403 Forbidden`
* `400 Bad Request` (invalid parameters)

## Retrieve Conversation by ID

<span class="api-method get">GET</span>  `/api/conversations/{id}/`

Retrieve details for a single conversation by its unique ID.

### Path Parameters

| Name | Type    | Description                                 |
| ---- | ------- | ------------------------------------------- |
| `id` | integer | Unique integer identifying the conversation |

### Response

<details>
<summary><code>200 OK</code></summary>

```json
{
  "id": 42,
  "conversation_id": "conv-42",
  "customer_id": "cust_123",
  "language": "en",
  "device": "mobile",
  "is_favorite": true,
  "started_at": "2025-10-22T09:00:00Z",
  "ended_at": "2025-10-22T09:05:00Z",
  "geo_location": {
    "ip_address": "203.0.113.45",
    "city": "London",
    "country": "UK"
  },
  "messages": [
    {
      "id": 1001,
      "timestamp": "2025-10-22T09:01:00Z",
      "sender": "end_user",
      "content": "Hello, I need help.",
      "attachments": []
    }
  ]
}
```

</details>

**Error responses:**

* `401 Unauthorized`
* `403 Forbidden`
* `404 Not Found` (conversation does not exist or unauthorized)

## Retrieve Conversation Attachments

<span class="api-method get">GET</span>  `/api/conversations/{id}/attachments/`

Retrieve attachments associated with a specific conversation.

### Path Parameters

| Name | Type    | Description                                 |
| ---- | ------- | ------------------------------------------- |
| `id` | integer | Unique integer identifying the conversation |

### Response

<details>
<summary><code>200 OK</code></summary>

```json
{
  "id": 42,
  "conversation_id": "conv-42",
  "messages": [
    {
      "id": 1001,
      "attachments": [
        {
          "id": 900,
          "type": "image",
          "file_url": "https://cdn.example.com/files/image.jpg",
          "filename": "image.jpg",
          "mime_type": "image/jpeg",
          "size_bytes": 204800
        }
      ]
    }
  ]
}
```

</details>

**Error responses:**

* `401 Unauthorized`
* `403 Forbidden`
* `404 Not Found`

## Notes

* All endpoints respect pagination (`page` / `page_size`).
* Query filters can be combined.
* All timestamps use **ISO 8601 UTC format**.
* Use the provided auth schemes for consistent scoping to a single agent.
