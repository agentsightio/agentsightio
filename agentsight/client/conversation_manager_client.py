# conversation_manager.py
from typing import Optional, Dict, Any, Union
from threading import Lock

from agentsight.config import Config
from agentsight.http.client import HTTPClient
from agentsight.enums import Sentiment
from agentsight.exceptions import (
    NoApiKeyException,
    InvalidConversationDataException
)
from agentsight.logging import logger, configure_logging
configure_logging()

_UNSET = object()


class ConversationManager:
    """Client for managing and editing conversations in AgentSight."""
    
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
        """Initialize the conversation manager."""
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
        logger.info("ConversationManager successfully initialized.")

    def configure(
        self,
        api_key: Optional[str] = _UNSET,
        endpoint: Optional[str] = _UNSET,
        **kwargs
    ):
        """
        Reconfigure the conversation manager after initialization.
        
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
        
        logger.info("ConversationManager reconfigured.")

    def _resolve_conversation_pk(self, conversation_id: Union[int, str]) -> int:
        """
        Convert conversation_id (string or int) to database pk (int).
        """
        if isinstance(conversation_id, int):
            # Already a pk, return as-is
            return conversation_id
        
        if isinstance(conversation_id, str):
            # Use lightweight lookup endpoint to get pk
            try:
                response = self._http_client.get(
                    '/api/conversations/lookup/',
                    params={'conversation_id': conversation_id}
                )
                pk = response.get('id')
                
                if not pk:
                    raise ValueError(f"Could not resolve pk for conversation_id '{conversation_id}'")
                
                logger.debug(f"Resolved conversation_id '{conversation_id}' to pk {pk}")
                return pk
                
            except Exception as e:
                logger.error(f"Failed to resolve conversation_id '{conversation_id}': {e}")
                raise
        
        raise ValueError(
            f"conversation_id must be int or str, got {type(conversation_id).__name__}"
        )
    
    def submit_feedback(
        self,
        conversation_id: Union[int, str],
        sentiment: Union[Sentiment, str],
        comment: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Submit end-user feedback for a conversation.
        
        Args:
            conversation_id: Either string conversation_id or integer database pk
            sentiment: User's sentiment - 'positive', 'neutral', 'negative'
            comment: Optional feedback text (max 5000 characters)
            metadata: Optional additional metadata
        """
        if not conversation_id:
            raise ValueError("conversation_id is required")
        
        # Convert sentiment enum to string if needed
        if isinstance(sentiment, Sentiment):
            sentiment_value = sentiment.value
        else:
            sentiment_value = sentiment
            valid_sentiments = [s.value for s in Sentiment]
            if sentiment_value not in valid_sentiments:
                raise InvalidConversationDataException(
                    f"Invalid sentiment: '{sentiment_value}'. Must be one of: {', '.join(valid_sentiments)}"
                )
        
        # Validate comment length if provided
        if comment is not None:
            if not isinstance(comment, str):
                raise InvalidConversationDataException("Field 'comment' must be a string")
            if len(comment) > 5000:
                raise InvalidConversationDataException(
                    f"Field 'comment' cannot exceed 5000 characters (got {len(comment)})"
                )
        
        # Prepare feedback data
        feedback_data = {
            "sentiment": sentiment_value,
        }
        
        # Add the appropriate conversation field based on type
        if isinstance(conversation_id, str):
            feedback_data["conversation_id"] = conversation_id
            log_id = f"conversation_id '{conversation_id}'"
        else:
            feedback_data["conversation"] = conversation_id
            log_id = f"conversation pk {conversation_id}"
        
        if comment:
            feedback_data["comment"] = comment
        
        if metadata:
            feedback_data["metadata"] = metadata
        
        logger.info(f"Submitting feedback for {log_id}: sentiment={sentiment_value}")
        
        try:
            response = self._http_client.post(
                '/api/conversation-feedbacks/',
                data=feedback_data
            )
            logger.info(f"✅ Successfully submitted feedback for {log_id}")
            return response
        except Exception as e:
            logger.error(f"Failed to submit feedback for {log_id}: {str(e)}")
            raise
    
    def rename_conversation(
        self, 
        conversation_id: Union[int, str], 
        name: str
    ) -> Dict[str, Any]:
        """
        Rename a conversation.
        
        Args:
            conversation_id: Either string conversation_id or integer database pk
            name: New conversation name (max 255 characters)
        """
        if not conversation_id:
            raise ValueError("conversation_id is required")
        
        if not name or not isinstance(name, str):
            raise InvalidConversationDataException("Field 'name' must be a non-empty string")
        
        if len(name.strip()) == 0:
            raise InvalidConversationDataException("Field 'name' cannot be empty")
        
        if len(name) > 255:
            raise InvalidConversationDataException(
                f"Field 'name' cannot exceed 255 characters (got {len(name)})"
            )
        
        # Resolve to pk
        pk = self._resolve_conversation_pk(conversation_id)
        
        payload = {"name": name.strip()}
        
        try:
            response = self._http_client.patch(
                f'/api/conversations/{pk}/rename/',
                data=payload
            )
            logger.info(f"Successfully renamed conversation {pk} to '{name.strip()}'")
            return response
        except Exception as e:
            logger.error(f"Failed to rename conversation {pk}: {str(e)}")
            raise

    def mark_conversation(
        self, 
        conversation_id: Union[int, str], 
        is_marked: bool
    ) -> Dict[str, Any]:
        """
        Mark or unmark a conversation as favorite.
        
        Args:
            conversation_id: Either string conversation_id or integer database pk
            is_marked: True to mark, False to unmark
        """
        if not conversation_id:
            raise ValueError("conversation_id is required")
        
        # Resolve to pk
        pk = self._resolve_conversation_pk(conversation_id)
        
        payload = {"is_marked": bool(is_marked)}
        
        try:
            response = self._http_client.post(
                f'/api/conversations/{pk}/mark/',
                data=payload
            )
            logger.info(f"Successfully {'marked' if is_marked else 'unmarked'} conversation {pk}")
            return response
        except Exception as e:
            logger.error(f"Failed to mark conversation {pk}: {str(e)}")
            raise

    def delete_conversation(
        self, 
        conversation_id: Union[int, str]
    ) -> Dict[str, Any]:
        """
        Soft delete a conversation (sets is_deleted=True).
        
        Args:
            conversation_id: Either string conversation_id or integer database pk
        """
        if not conversation_id:
            raise ValueError("conversation_id is required")
        
        # Resolve to pk
        pk = self._resolve_conversation_pk(conversation_id)
        
        try:
            response = self._http_client.delete(
                f'/api/conversations/{pk}/delete/'
            )
            logger.info(f"Successfully deleted conversation {pk}")
            return response
        except Exception as e:
            logger.error(f"Failed to delete conversation {pk}: {str(e)}")
            raise

    def update_conversation(
        self,
        conversation_id: Union[int, str],
        name: Optional[str] = None,
        is_marked: Optional[bool] = None,
        customer_id: Optional[str] = None,
        device: Optional[str] = None,
        language: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Update multiple fields of a conversation in a single request.
        
        Args:
            conversation_id: Either string conversation_id or integer database pk
            name: New conversation name (max 255 characters)
            is_marked: Mark/unmark the conversation
            customer_id: Customer identifier
            device: Device type
            language: Language code
            metadata: Additional metadata as JSON
        """
        if not conversation_id:
            raise ValueError("conversation_id is required")
        
        # Build update payload with only provided fields
        update_data = {}
        
        if name is not None:
            if not isinstance(name, str):
                raise InvalidConversationDataException(
                    f"Field 'name' must be a string, got {type(name).__name__}"
                )
            if len(name.strip()) == 0:
                raise InvalidConversationDataException("Field 'name' cannot be empty")
            if len(name) > 255:
                raise InvalidConversationDataException(
                    f"Field 'name' cannot exceed 255 characters (got {len(name)})"
                )
            update_data['name'] = name.strip()
        
        if is_marked is not None:
            update_data['is_marked'] = bool(is_marked)
        
        if customer_id is not None:
            update_data['customer_id'] = str(customer_id)
        
        if device is not None:
            update_data['device'] = str(device)
        
        if language is not None:
            update_data['language'] = str(language)
        
        if metadata is not None:
            if not isinstance(metadata, dict):
                raise InvalidConversationDataException("Field 'metadata' must be a dictionary")
            update_data['metadata'] = metadata
        
        if not update_data:
            raise ValueError("At least one field must be provided for update")
        
        # Resolve to pk
        pk = self._resolve_conversation_pk(conversation_id)
        
        try:
            response = self._http_client.patch(
                f'/api/conversations/{pk}/update/',
                data=update_data
            )
            logger.info(f"Successfully updated conversation {pk}")
            return response
        except Exception as e:
            logger.error(f"Failed to update conversation {pk}: {str(e)}")
            raise

# Create a default global instance
conversation_manager = ConversationManager()