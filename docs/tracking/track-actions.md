---
outline: deep
---

# Track Action Method

The `track_action()` method allows you to log specific functions, tools, or operations that your AI agent uses directly in the process of generating an answer. This tracks the "work" your agent performs during answer generation, such as function calls, tool usage, or computational steps.

## Action Management

AgentSight automatically creates new actions the first time it encounters a new action name. Once created, all subsequent tracking with that action name contributes to the same action's analytics. 

This means **action names serve as unique identifiers** - changing an action name will create a separate action category, and you'll lose the ability to track historical data under the previous name.

:::info Action Name
For optimal analytics continuity, maintain consistent action naming conventions across your application. Consider using standardized naming patterns like `calculator_add`, `weather_lookup`, or `database_search` rather than dynamic or variable names. 

If you are using functions, methods or tools, you can also use those as action name.
:::

While action names should remain consistent in your code, you can customize how they appear in the dashboard by setting display names. This allows you to use technical naming conventions in your implementation while presenting user-friendly labels to you and your clients in the analytics interface.

## Method Signature

```python
def track_action(
    action_name: str,
    started_at: Optional[str] = None,
    ended_at: Optional[str] = None,
    duration_ms: Optional[int] = None,
    tools_used: Optional[Dict[str, Any]] = None,
    response: Optional[str] = None,
    error_msg: Optional[str] = None,
    conversation_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
```

## Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `action_name` | `str` | Yes | The name of the function/tool/operation performed |
| `started_at` | `str` | No | When the action started (ISO timestamp) |
| `ended_at` | `str` | No | When the action ended (ISO timestamp) |
| `duration_ms` | `int` | No | Duration of the action in milliseconds |
| `tools_used` | `Dict[str, Any]` | No | Details about the tools or functions used |
| `response` | `str` | No | Result or output from the action |
| `error_msg` | `str` | No | Error message if the action failed |
| `metadata` | `Dict[str, Any]` | No | Additional contextual information |

## Complete Usage Example

### Mathematical Function Tracking

```python
# Track a calculation used in answer generation
tracker.track_action(
    action_name="calculator_multiply",
    started_at="2024-01-15T10:30:00Z",
    ended_at="2024-01-15T10:30:00.050Z",
    duration_ms=50,
    tools_used={
        "function": "multiply",
        "parameters": {"a": 12, "b": 5}
    },
    response="60"
)
```

### Weather API Function Call

```python
# Track weather lookup function used in response
tracker.track_action(
    action_name="weather_lookup",
    duration_ms=800,
    tools_used={
        "api": "OpenWeatherMap",
        "location": "San Francisco, CA",
        "parameters": {"units": "metric"}
    },
    response="Temperature: 18°C, Conditions: Sunny",
    metadata={
        "location_query": "San Francisco",
        "units": "celsius"
    }
)
```

### Database Query Function

```python
# Track database search used to generate answer
tracker.track_action(
    action_name="database_search",
    started_at="2024-01-15T10:30:00Z",
    ended_at="2024-01-15T10:30:00.200Z",
    duration_ms=200,
    tools_used={
        "database": "user_orders",
        "query_type": "SELECT",
        "filters": {"user_id": "123", "status": "active"}
    },
    response="Found 3 active orders"
)
```

## Return Value

The method returns a dictionary containing the API response:

```python
{
    "status": "success",
    "conversation_id": "generated_or_provided_id",
    "timestamp": "2024-01-15T10:30:00Z",
    "action_name": "calculator_add",
    "message": "Action tracked successfully"
}
```

## Use Cases
- **Function Call Tracking:** Monitor which functions your agent calls most frequently during answer generation.
- **Tool Usage Analytics:** Track external API calls, database queries, or computational tools used in responses.
- **Performance Monitoring:** Measure the execution time of different functions to optimize agent performance.
- **Error Detection:** Identify failed function calls that might affect answer quality.

## Important Notes

:::info Answer Generation Context
Actions represent the "work" your agent performs to generate answers. Track each function call, tool usage, or computational step that contributes to the final response.
:::

:::tip Performance Insights
Including `duration_ms` and detailed `tools_used` information provides valuable insights into which functions impact response times.
:::

:::tip Best Practices
- Use descriptive action names that clearly indicate the function or tool used
- Track both successful and failed function calls
- Include timing information for performance analysis
- Use consistent naming conventions for similar functions across your application
:::
