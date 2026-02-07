# api_client.py
from typing import Optional, Dict, Any, Union, Literal

from agentsight.config import Config
from agentsight.http.client import HTTPClient
from agentsight.exceptions import NoApiKeyException

from threading import Lock
from datetime import datetime
from agentsight.logging import logger, configure_logging
configure_logging()

_UNSET = object()


class AgentSightAPI:
    """Client for fetching conversation data from AgentSight API."""
    
    _instance = None
    _instance_lock = Lock()

    def __new__(cls, *args, **kwargs):
        """Implement singleton pattern to ensure only one instance exists."""
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    # Use object.__new__(cls) instead of super()
                    cls._instance = object.__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(
        self,
        api_key: Optional[str] = None,
        endpoint: Optional[str] = None,
        config: Optional[Config] = None,
        **kwargs
    ):
        """Initialize the API client."""
        # Prevent re-initialization
        if self._initialized:
            return
            
        # Initialize config
        if config is None:
            config = Config()
            
        config.configure(
            api_key=api_key,
            endpoint=endpoint,
            **kwargs
        )
        self.config = config

        # Initialize HTTP client
        self._http_client = HTTPClient(self.config)

        # Validate API key
        if not self.config.api_key:
            raise NoApiKeyException()

        self._initialized = True
        logger.info("AgentSightAPI successfully initialized.")

    def configure(
        self,
        api_key: Optional[str] = _UNSET,
        endpoint: Optional[str] = _UNSET,
        **kwargs
    ):
        """
        Reconfigure the API client after initialization.
        
        Args:
            api_key: New API key (raises exception if None)
            endpoint: New endpoint URL
            **kwargs: Additional configuration parameters
            
        Raises:
            NoApiKeyException: If api_key is None or results in no API key
        """
        config_updates = {}
        
        # Only update if explicitly provided
        if api_key is not _UNSET:
            if api_key is None:
                raise NoApiKeyException("API key cannot be None")
            config_updates['api_key'] = api_key
        
        if endpoint is not _UNSET:
            config_updates['endpoint'] = endpoint
        
        config_updates.update(kwargs)
        
        # Apply configuration
        self.config.configure(**config_updates)
        
        # Reinitialize HTTP client
        self._http_client = HTTPClient(self.config)
        
        # Validate API key
        if not self.config.api_key:
            raise NoApiKeyException()
        
        logger.info("AgentSightAPI reconfigured.")

    def fetch_conversations(
        self,
        action_name: Optional[str] = None,
        conversation_id: Optional[str] = None,
        customer_id: Optional[str] = None,
        customer_ip_address: Optional[str] = None,
        device: Optional[str] = None,
        has_messages: Optional[bool] = None,
        language: Optional[str] = None,
        message_contains: Optional[str] = None,
        page: Optional[int] = None,
        page_size: Optional[int] = None,
        started_at_after: Optional[Union[str, datetime]] = None,
        started_at_before: Optional[Union[str, datetime]] = None,
        is_marked: Optional[bool] = None,
        name: Optional[str] = None,
        include_deleted: Optional[bool] = None,
        metadata: Optional[str] = None,
        has_feedback: Optional[bool] = None,
        feedback_sentiment: Optional[Literal['positive', 'neutral', 'negative']] = None,
        feedback_source: Optional[Literal['customer', 'platform']] = None,
        **extra_params
    ) -> Dict[str, Any]:
        """
        Fetch a list of conversations with optional filters.
        
        Args:
            action_name: Filter by action name
            conversation_id: Filter by conversation ID
            customer_id: Exact match for customer ID
            customer_ip_address: Filter by customer IP
            device: Filter by device type
            has_messages: Return only conversations with messages
            language: Filter by language
            message_contains: Search within message contents
            page: Page number for pagination
            page_size: Results per page
            started_at_after: Conversations started after this timestamp
            started_at_before: Conversations started before this timestamp
            is_marked: Filter by marked status
            name: Filter by conversation name (contains)
            include_deleted: Include deleted conversations (default: False)
            metadata: Filter by metadata (format: "key:value,key2:value2")
            has_feedback: Filter by feedback existence (True/False)
            feedback_sentiment: Filter by feedback sentiment ('positive', 'neutral', 'negative')
            feedback_source: Filter by feedback source ('customer', 'platform')
            **extra_params: Additional query parameters
            
        Returns:
            Dict containing paginated conversation results
        """
        params = {}
        
        # Build query parameters
        if action_name is not None:
            params['action_name'] = action_name
        if conversation_id is not None:
            params['conversation_id'] = conversation_id
        if customer_id is not None:
            params['customer_id'] = customer_id
        if customer_ip_address is not None:
            params['customer_ip_address'] = customer_ip_address
        if device is not None:
            params['device'] = device
        if has_messages is not None:
            params['has_messages'] = str(has_messages).lower()
        if language is not None:
            params['language'] = language
        if message_contains is not None:
            params['message_contains'] = message_contains
        if page is not None:
            params['page'] = page
        if page_size is not None:
            params['page_size'] = page_size
        if started_at_after is not None:
            params['started_at_after'] = self._format_datetime(started_at_after)
        if started_at_before is not None:
            params['started_at_before'] = self._format_datetime(started_at_before)
        if is_marked is not None:
            params['is_marked'] = str(is_marked).lower()
        if name is not None:
            params['name'] = name
        if include_deleted is not None:
            params['include_deleted'] = str(include_deleted).lower()
        if metadata is not None:
            params['metadata'] = metadata
        if has_feedback is not None:
            params['has_feedback'] = str(has_feedback).lower()
        if feedback_sentiment is not None:
            # Validate sentiment
            valid_sentiments = ['positive', 'neutral', 'negative']
            if feedback_sentiment not in valid_sentiments:
                raise ValueError(
                    f"feedback_sentiment must be one of {valid_sentiments}, got '{feedback_sentiment}'"
                )
            params['feedback_sentiment'] = feedback_sentiment
        if feedback_source is not None:
            # Validate source
            valid_sources = ['customer', 'platform']
            if feedback_source not in valid_sources:
                raise ValueError(
                    f"feedback_source must be one of {valid_sources}, got '{feedback_source}'"
                )
            params['feedback_source'] = feedback_source
        
        # Add any extra parameters
        params.update(extra_params)

        try:
            response = self._http_client.get(
                '/api/conversations/',
                params=params
            )
            logger.info(f"Successfully fetched conversations. Count: {response.get('count', 0)}")
            return response
        except Exception as e:
            logger.error(f"Failed to fetch conversations: {str(e)}")
            raise

    def fetch_conversation(self, conversation_id: Union[int, str]) -> Dict[str, Any]:
        """
        Fetch a single conversation by its database ID or conversation_id string.
        
        Args:
            conversation_id: Either:
                - Integer database ID (e.g., 42)
                - String conversation_id (e.g., "realistic-conv-2031")
                
        Returns:
            Dict containing conversation details including messages
            
        Raises:
            APIException: If the request fails
            NotFoundException: If conversation not found
            ValueError: If multiple conversations found (shouldn't happen with exact match)
            
        Example:
            ```python
            from agentsight import agentsight_api
            
            # Fetch by database ID
            conv = agentsight_api.fetch_conversation(42)
            
            # Fetch by conversation_id string
            conv = agentsight_api.fetch_conversation("realistic-conv-2031")
            ```
        """
        try:
            # If integer, use detail endpoint (faster, direct lookup)
            if isinstance(conversation_id, int):
                response = self._http_client.get(
                    f'/api/conversations/{conversation_id}/'
                )
                logger.info(f"Successfully fetched conversation with ID {conversation_id}")
                return response
            
            # If string, use list endpoint with conversation_id filter
            elif isinstance(conversation_id, str):
                response = self._http_client.get(
                    '/api/conversations/',
                    params={'conversation_id': conversation_id}
                )
                
                results = response.get('results', [])
                
                if not results:
                    from agentsight.exceptions import NotFoundException
                    raise NotFoundException(
                        f"Conversation with conversation_id '{conversation_id}' not found"
                    )
                
                if len(results) > 1:
                    logger.warning(
                        f"Multiple conversations found with conversation_id '{conversation_id}'. "
                        f"Returning first match."
                    )
                
                conversation = results[0]
                logger.info(f"Successfully fetched conversation with conversation_id '{conversation_id}'")
                return conversation
            
            else:
                raise ValueError(
                    f"conversation_id must be int or str, got {type(conversation_id).__name__}"
                )
                
        except Exception as e:
            logger.error(f"Failed to fetch conversation {conversation_id}: {str(e)}")
            raise

    def fetch_conversation_attachments(self, conversation_id: Union[int, str]) -> Dict[str, Any]:
        """
        Fetch attachments for a specific conversation.
        
        Args:
            conversation_id: Either integer database ID or string conversation_id
            
        Returns:
            Dict containing attachments organized by message
        """
        try:
            # If string, first get the database ID
            if isinstance(conversation_id, str):
                # Fetch the conversation to get its database ID
                conv = self.fetch_conversation(conversation_id)
                db_id = conv.get('id')
            else:
                db_id = conversation_id
            
            response = self._http_client.get(
                f'/api/conversations/{db_id}/attachments/'
            )
            logger.info(f"Successfully fetched attachments for conversation {conversation_id}")
            return response
        except Exception as e:
            logger.error(f"Failed to fetch attachments for conversation {conversation_id}: {str(e)}")
            raise

    def _format_datetime(self, dt: Union[str, datetime]) -> str:
        """Format datetime to ISO 8601 string if needed."""
        if isinstance(dt, datetime):
            return dt.isoformat()
        return dt


# Create a default global instance
agentsight_api = AgentSightAPI()