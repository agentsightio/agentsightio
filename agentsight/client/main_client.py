"""AgentSight Conversation Tracker - Main client for tracking chatbot and AI agent conversations."""

from typing import Optional, Dict, Any, Union, List, Literal
import copy
from threading import Lock

from agentsight.enums import LogLevel, AttachmentMode, Sender, TokenHandlerType, Sentiment
from agentsight.config import Config
from agentsight.exceptions import (
    NoApiKeyException,
    InvalidConversationDataException,
    NoDataToSendException,
    InvalidQuestionDataException,
    InvalidAnswerDataException
)
from agentsight.helpers import (
    generate_conversation_id,
    get_iso_timestamp
)
from agentsight.http.client import HTTPClient
from agentsight.validators import (
    validate_content_data,
    validate_and_process_attachments_flexible
)
from agentsight.token_handlers import (
    set_llamaindex_token_handler
)
from agentsight.types import AttachmentInput, TokenHandler
from agentsight.logging import logger, configure_logging
configure_logging()

_UNSET = object()

class ConversationTracker:
    """Main client class for tracking conversations with AgentSight, including automatic OpenAI token usage tracking."""
    _MAX_RETRIES = 3
    _BACKOFF_BASE = 2
    _TIMEOUT = 15
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
        conversation_id: Optional[str] = None,
        endpoint: Optional[str] = None,
        log_level: Optional[Union[LogLevel, str]] = None,
        config: Optional[Config] = None,
        **kwargs
    ):
        # Prevent re-initialization
        if self._initialized:
            return
            
        # Initialize config
        if config is None:
            config = Config()
            
        config.configure(
            api_key=api_key,
            endpoint=endpoint,
            conversation_id=conversation_id,
            log_level=log_level,
            **kwargs
        )
        self.config = config

        # Initialize HTTP client
        self._http_client = HTTPClient(self.config)

        # Initialize tracking storage (by conversation_id)
        self._tracked_data: Dict[str, Dict[str, List[Any]]] = {}
        self._lock = Lock()  # Thread safety for concurrent access

        # Validate API key
        if not self.config.api_key:
            raise NoApiKeyException()

        # Initialize token handler
        self._token_handler: Optional[Union[TokenHandler, Any]] = None
        self._patch_llm_clients()

        self._initialized = True
        logger.info("ConversationTracker successfully initialized.")

    def configure(
        self,
        api_key: Optional[str] = _UNSET,
        conversation_id: Optional[str] = _UNSET,
        endpoint: Optional[str] = _UNSET,
        log_level: Optional[Union[LogLevel, str]] = _UNSET,
        **kwargs
    ):
        """
        Reconfigure the tracker after initialization.
        
        Args:
            api_key: New API key (raises exception if None)
            conversation_id: New default conversation ID
            endpoint: New endpoint URL
            log_level: New log level
            **kwargs: Additional configuration parameters
        """
        config_updates = {}
        
        # Only update if explicitly provided
        if api_key is not _UNSET:
            if api_key is None:
                raise NoApiKeyException("API key cannot be None")
            config_updates['api_key'] = api_key
        
        if conversation_id is not _UNSET:
            config_updates['conversation_id'] = conversation_id
        
        if endpoint is not _UNSET:
            config_updates['endpoint'] = endpoint
        
        if log_level is not _UNSET:
            config_updates['log_level'] = log_level
        
        config_updates.update(kwargs)
        
        # Apply configuration
        self.config.configure(**config_updates)
        
        # Reinitialize HTTP client if endpoint or api_key changed
        if api_key is not _UNSET or endpoint is not _UNSET:
            self._http_client = HTTPClient(self.config)
        
        # Validate API key
        if not self.config.api_key:
            raise NoApiKeyException()
        
        logger.info("ConversationTracker reconfigured.")

    def track_human_message(
        self,
        message: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Track a message (stores in memory for later sending).

        Args:
            message (str): Users message
            metadata (dict, optional): Additional metadata
        """        
        data = {
            "content": message,
            "sender": Sender.USER.value,
            "conversation_id": self.config.conversation_id,
            "metadata": metadata or {}
        }

        if not validate_content_data(data):
            raise InvalidQuestionDataException("Invalid question data provided.")

        self._add_tracking_item('question', data)
        logger.info(f"Stored question for conversation: {self.config.conversation_id}")

    def track_agent_message(
        self,
        message: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Track an message (stores in memory for later sending).

        Args:
            message (str): The message provided
            metadata (dict, optional): Additional metadata
        """        
        data = {
            "content": message,
            "sender": Sender.AGENT.value,
            "conversation_id": self.config.conversation_id,
            "metadata": metadata or {}
        }

        if not validate_content_data(data):
            raise InvalidAnswerDataException("Invalid answer data provided.")

        self._add_tracking_item('answer', data)
        logger.info(f"Stored answer for conversation: {self.config.conversation_id}")

    def track_attachments(
        self,
        attachments: List[AttachmentInput],
        sender: Optional[Sender] = None,
        metadata: Optional[Dict[str, Any]] = None,
        mode: Union[str, AttachmentMode] = AttachmentMode.BASE64.value
    ) -> None:
        """
        Track attachments (stores in memory for later sending).
        
        Args:
            attachments: List of attachment objects
            sender (Sender, optional): Sender - 'end_user' (default) or 'agent'
            metadata (dict, optional): Additional metadata
            mode (str|AttachmentMode, optional): Sending mode - 'base64' (default) or 'form_data'
        """        
        # Convert string mode to enum
        if isinstance(mode, str):
            mode_map = {
                'base64': AttachmentMode.BASE64,
                'form_data': AttachmentMode.FORM_DATA,
                'form-data': AttachmentMode.FORM_DATA
            }
            if mode.lower() not in mode_map:
                raise ValueError(f"Invalid mode: {mode}. Must be 'base64' or 'form_data'")
            mode = mode_map[mode.lower()]

        # Validate and process attachments based on mode
        processed_attachments = validate_and_process_attachments_flexible(attachments, mode)

        data = {
            "attachments": processed_attachments,
            "metadata": metadata or {},
            "mode": mode.value,
            "sender": sender or Sender.USER.value,
            "conversation_id": self.config.conversation_id
        }

        self._add_tracking_item('attachments', data)
        logger.info(f"Stored {len(processed_attachments)} attachment(s) for conversation: {self.config.conversation_id}")

    def track_action(
        self,
        action_name: str,
        started_at: Optional[str] = None,
        ended_at: Optional[str] = None,
        duration_ms: Optional[int] = None,
        tools_used: Optional[Dict[str, Any]] = None,
        response: Optional[str] = None,
        error_msg: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Track a user action (stores in memory for later sending).

        Args:
            action_name (str): The name of the action performed
            started_at (str, optional): When the action started (ISO timestamp)
            ended_at (str, optional): When the action ended (ISO timestamp)
            duration_ms (int, optional): Duration of the action in milliseconds
            tools_used (Dict[str, Any], optional): Tools used during the action
            response (str, optional): Response or result from the action
            error_msg (str, optional): Error message if the action failed
            metadata (dict, optional): Additional metadata
        """        
        # Validate action_name specifically for better error message
        if not action_name or not action_name.strip():
            raise InvalidConversationDataException("Action name cannot be empty")

        # Build the data dictionary with all provided fields
        data = {
            "action_name": action_name,
            "conversation_id": self.config.conversation_id,
            "metadata": metadata or {}
        }

        # Add optional fields only if they are provided
        if started_at is not None:
            data["started_at"] = started_at
        if ended_at is not None:
            data["ended_at"] = ended_at
        if duration_ms is not None:
            data["duration_ms"] = duration_ms
        if tools_used is not None:
            data["tools_used"] = tools_used
        if response is not None:
            data["response"] = response
        if error_msg is not None:
            data["error_msg"] = error_msg

        self._add_tracking_item('action', data)
        logger.info(f"Stored action '{action_name}' for conversation: {self.config.conversation_id}")

    def track_button(
        self,
        button_event: str,
        label: str,
        value: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Track a button click (stores in memory for later sending).

        Args:
            button_event (str): Description of what this button is used for
            label (str): The button label/text displayed to the user
            value (str): The button value
            metadata (dict, optional): Additional metadata
        """        
        if not button_event or not button_event.strip():
            raise InvalidConversationDataException("Button event cannot be empty")
        if not label or not label.strip():
            raise InvalidConversationDataException("Button label cannot be empty")
        if not value or not value.strip():
            raise InvalidConversationDataException("Button value cannot be empty")

        data = {
            "button_event": button_event,
            "label": label,
            "value": value,
            "conversation_id": self.config.conversation_id,
            "metadata": metadata or {}
        }

        self._add_tracking_item('button', data)
        logger.info(f"Stored button click '{label}' for conversation: {self.config.conversation_id}")

    def track_token_usage(
        self,
        prompt_tokens: Optional[int] = 0,
        completion_tokens: Optional[int] = 0,
        total_tokens: Optional[int] = 0,
        embedding_tokens: Optional[int] = 0
    ) -> None:
        """
        Track and update cumulative token usage (stores in memory for later sending).

        Args:
            prompt_tokens (int, optional): Number of tokens consumed by the input prompt
            completion_tokens (int, optional): Number of tokens consumed by the model's generated output
            total_tokens (int, optional): Total number of tokens (prompt + completion) used in an interaction
            embedding_tokens (int, optional): Number of tokens used for generating embeddings
        """
        if self._token_handler is None:
            self._token_handler = TokenHandler()

        self._token_handler.prompt_llm_token_count = self._token_handler.prompt_llm_token_count + prompt_tokens
        self._token_handler.completion_llm_token_count = self._token_handler.completion_llm_token_count + completion_tokens
        self._token_handler.total_llm_token_count = self._token_handler.total_llm_token_count + total_tokens
        self._token_handler.total_embedding_token_count = self._token_handler.total_embedding_token_count + embedding_tokens

    def initialize_conversation(
        self,
        conversation_id: str,
        customer_id: Optional[str] = None,
        customer_ip_address: Optional[str] = None,
        device: Optional[Literal["desktop", "mobile"]] = None,
        source: Optional[str] = None,
        language: Optional[str] = None,
        name: Optional[str] = None,
        environment: Literal["production", "development"] = "development",
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Initialize and create a new conversation (sends immediately).

        Unlike tracking methods that only store data in memory for later sending,
        this method sends the conversation data to the backend right away.

        Args:
            conversation_id (str): Unique identifier for the conversation.
            customer_id (str, optional): Unique identifier for the customer.
            customer_ip_address (str, optional): IP address of the customer.
            device ("desktop" | "mobile", optional): Device information.
            source (str, optional): Source of the conversation (e.g., "web", "app").
            language (str, optional): Preferred language of the conversation.
            name (str, optional): Conversation name
            environment ("production" | "development", optional): Working environment
            metadata (dict, optional): Additional metadata about the conversation.
        """
        data = {
            "conversation_id": conversation_id,
            "customer_id": customer_id,
            "customer_ip_address": customer_ip_address,
            "device": device,
            "source": source,
            "language": language,
            "name": name,
            "environment": self.config.environment or environment,
            "metadata": metadata,
            "is_used": False
        }

        self._http_client.send_payload('conversation', data)

    def send_tracked_data(
        self
    ) -> Dict[str, Any]:
        """
        Send all tracked data for a conversation (flushes stored items).

        Sends all events and token usage stored in memory to the API in the order
        they were tracked. Token counters are reset and local memory is cleared
        after sending.

        Returns:
            dict: API responses with order preserved and a summary by item type
        """
        logger.debug(f"Start sending tracked data.")
        conv_id = self._get_or_generate_conversation_id()

        # Get a copy of the data to send
        with self._lock:
            if conv_id not in self._tracked_data:
                raise NoDataToSendException(f"No tracked data found for conversation: {conv_id}")
            
            if self._token_handler is not None:
                self._add_token_usage(conv_id)
                # here we need to reset the token counter
            
            items_to_send = copy.deepcopy(self._tracked_data[conv_id]['items'])
            
            # Clear data
            del self._tracked_data[conv_id]

        if not items_to_send:
            raise NoDataToSendException(f"No tracked data found for conversation: {conv_id}")

        logger.info(f"Sending {len(items_to_send)} tracked items for conversation: {conv_id}")

        # Send all data in order and collect responses
        responses = {
            'items': [],
            'summary': {'questions': 0, 'answers': 0, 'attachments': 0, 'actions': 0, 'buttons': 0, 'errors': 0}
        }

        conversation_id = None

        for i, item in enumerate(items_to_send):
            item_type = item['type']
            timestamp = item['timestamp']
            data = item['data']
            data['timestamp'] = timestamp

            if item_type != 'conversation':
                data['conversation'] = conversation_id

            try:
                if item_type == 'conversation':
                    response = self._http_client.send_payload('conversation', data)
                    conversation_id = response['id']
                elif item_type == 'question':
                    response = self._http_client.send_payload('question', data)
                    responses['summary']['questions'] += 1
                elif item_type == 'answer':
                    response = self._http_client.send_payload('answer', data)
                    responses['summary']['answers'] += 1
                elif item_type == 'attachments':
                    if data['mode'] == AttachmentMode.BASE64.value:
                        response = self._http_client.send_payload('attachments', data)
                    else:  # FORM_DATA mode
                        response = self._http_client.send_form_data_payload(data['attachments'], conversation_id, data['sender'], data['metadata'], timestamp)
                    responses['summary']['attachments'] += 1
                elif item_type == 'action':
                    response = self._http_client.send_payload('action', data)
                    responses['summary']['actions'] += 1
                elif item_type == 'button':
                    response = self._http_client.send_payload('button', data)
                    responses['summary']['buttons'] += 1
                else:
                    raise ValueError(f"Unknown item type: {item_type}")
                
                responses['items'].append({
                    'index': i,
                    'type': item_type,
                    'timestamp': timestamp,
                    'response': response,
                    'success': True
                })
                
                logger.debug(f"Sent {item_type} item {i+1}/{len(items_to_send)}")
                logger.debug(f"-"*60)
                
            except Exception as e:
                error_msg = str(e)
                logger.error(f"Error sending item {i+1}, type - {item_type}: {error_msg}")
                responses['summary']['errors'] += 1
                responses['items'].append({
                    'index': i,
                    'type': item_type,
                    'timestamp': timestamp,
                    'error': error_msg,
                    'success': False
                })

        logger.info(f"Completed sending tracked data. Summary: {responses['summary']}")
        return responses

    def get_tracked_data_summary(
        self
    ) -> Dict[str, Any]:
        """
        Get a detailed summary of all tracked data for a conversation with order preserved.
        
        Returns:
            dict: Contains 'items' (ordered list with details) and 'summary' (counts by type)
        """
        conv_id = self._get_conversation_id()
        
        with self._lock:
            if conv_id not in self._tracked_data:
                return {
                    'items': [],
                    'summary': {
                        'conversation': 0,
                        'questions': 0,
                        'answers': 0,
                        'attachments': 0,
                        'actions': 0,
                        'buttons': 0,
                        'total': 0
                    },
                    'conversation_id': conv_id
                }
            
            items = copy.deepcopy(self._tracked_data[conv_id]['items'])
            
            # Count items by type
            summary = {
                'conversation': 0,
                'questions': 0,
                'answers': 0,
                'attachments': 0,
                'actions': 0,
                'buttons': 0,
                'total': len(items)
            }
            
            # Add preview information to each item for easier debugging
            items_with_preview = []
            for idx, item in enumerate(items):
                item_copy = copy.deepcopy(item)
                item_type = item['type']
                data = item['data']
                
                # Count by type
                if item_type == 'conversation':
                    summary['conversation'] += 1
                elif item_type == 'question':
                    summary['questions'] += 1
                elif item_type == 'answer':
                    summary['answers'] += 1
                elif item_type == 'attachments':
                    summary['attachments'] += 1
                elif item_type == 'action':
                    summary['actions'] += 1
                elif item_type == 'button':
                    summary['buttons'] += 1
                
                # Add preview/summary for each item type
                preview = {}
                if item_type == 'conversation':
                    preview = {
                        'conversation_id': data.get('conversation_id'),
                        'customer_id': data.get('customer_id'),
                        'name': data.get('name'),
                        'environment': data.get('environment')
                    }
                elif item_type == 'question':
                    content = data.get('content', '')
                    preview = {
                        'content_preview': content[:100] + ('...' if len(content) > 100 else ''),
                        'sender': data.get('sender'),
                        'has_metadata': bool(data.get('metadata'))
                    }
                elif item_type == 'answer':
                    content = data.get('content', '')
                    preview = {
                        'content_preview': content[:100] + ('...' if len(content) > 100 else ''),
                        'sender': data.get('sender'),
                        'has_metadata': bool(data.get('metadata'))
                    }
                elif item_type == 'attachments':
                    attachments = data.get('attachments', [])
                    preview = {
                        'count': len(attachments),
                        'mode': data.get('mode'),
                        'sender': data.get('sender'),
                        'files': [
                            att.get('filename', 'unknown') 
                            for att in attachments[:3]  # Show first 3 files
                        ]
                    }
                    if len(attachments) > 3:
                        preview['files'].append(f'... and {len(attachments) - 3} more')
                elif item_type == 'action':
                    preview = {
                        'action_name': data.get('action_name'),
                        'duration_ms': data.get('duration_ms'),
                        'has_error': bool(data.get('error_msg')),
                        'has_response': bool(data.get('response'))
                    }
                elif item_type == 'button':
                    preview = {
                        'label': data.get('label'),
                        'value': data.get('value'),
                        'event': data.get('button_event')
                    }
                
                item_copy['index'] = idx
                item_copy['preview'] = preview
                items_with_preview.append(item_copy)
            
            return {
                'items': items_with_preview,
                'summary': summary,
                'conversation_id': conv_id
            }
        
    def get_token_usage(
        self
    ) -> Dict[str, int]:
        """
        Get current tracked token usage.

        Returns:
            dict: Token counts for prompt, completion, total, and embeddings.
                Empty dict if unavailable or an error occurs.
        """
        try:
            if self._token_handler is not None:
                return {
                    'prompt_tokens': self._token_handler.prompt_llm_token_count,
                    'completion_tokens': self._token_handler.completion_llm_token_count,
                    'total_tokens': self._token_handler.total_llm_token_count,
                    'embedding_tokens': self._token_handler.total_embedding_token_count
                }
        except Exception as e:
            print(f"❌ Failed to get token usage: {e}")
        return {}
    
    def get_or_create_conversation(
        self, 
        conversation_id: str,
        customer_id: Optional[str] = None,
        customer_ip_address: Optional[str] = None,
        device: Optional[Literal["desktop", "mobile"]] = None,
        source: Optional[str] = None,
        language: Optional[str] = None,
        name: Optional[str] = None,
        environment: Literal["production", "development"] = "development",
        metadata: Optional[Dict[str, Any]] = None
    ):
        """
        Store a conversation in memory for later sending.

        Adds a conversation tracking item with the given details to memory.
        The data will be sent later when `send_tracked_data` is called.

        Args:
            conversation_id (str): Unique identifier for the conversation
            customer_id (str, optional): Unique identifier for the customer
            customer_ip_address (str, optional): IP address of the customer
            device ("desktop" | "mobile", optional): Device information (e.g., "mobile", "desktop")
            source (str, optional): Source of the conversation (e.g., "web", "app")
            language (str, optional): Preferred language of the conversation
            name (str, optional): Conversation name
            environment ("production" | "development", optional): Working environment
            metadata (dict, optional): Additional metadata about the conversation
        """
        data = {
            "conversation_id": conversation_id,
            "customer_id": customer_id,
            "customer_ip_address": customer_ip_address,
            "device": device,
            "source": source,
            "language": language,
            "name": name,
            "is_used": True,
            "environment": self.config.environment or environment,
            "metadata": metadata
        }

        self.config.conversation_id = conversation_id
        self._add_tracking_item('conversation', data)
        logger.info(f"Stored conversation_id for get or create: {conversation_id}")

    # def configure(
    #     self,
    #     api_key: Optional[str] = None,
    #     conversation_id: Optional[str] = None,
    #     endpoint: Optional[str] = None,
    #     log_level: Optional[Union[LogLevel, str]] = None,
    #     **kwargs
    # ):
    #     """Reconfigure the tracker after initialization."""
    #     self.config.configure(
    #         api_key=api_key,
    #         endpoint=endpoint,
    #         conversation_id=conversation_id,
    #         log_level=log_level,
    #         **kwargs
    #     )
        
    #     # Reinitialize HTTP client if needed
    #     self._http_client = HTTPClient(self.config)
        
    #     # Re-validate API key
    #     if not self.config.api_key:
    #         raise NoApiKeyException()
        
    #     logger.info("ConversationTracker reconfigured.")

    def _reset_token_counters(self):
        """Reset token counters."""
        try:
            if hasattr(self, '_token_handler'):
                self._token_handler.reset_counts()
        except Exception as e:
            print(f"❌ Failed to reset token counters: {e}")
    
    def _get_or_generate_conversation_id(self, conversation_id: Optional[str] = None) -> str:
        """Get or generate conversation ID."""
        if conversation_id:
            self.config.conversation_id = conversation_id
            return conversation_id

        else:
            if self.config.conversation_id:
                return self.config.conversation_id
            else:  
                conversation_id = generate_conversation_id()
                self.config.conversation_id = conversation_id
                return conversation_id
            
    def _get_conversation_id(self) -> str:
        """Get conversation ID."""
        return self.config.conversation_id

    def _ensure_conversation_storage(self, conversation_id: str) -> None:
        """Ensure storage exists for a conversation."""
        if conversation_id not in self._tracked_data:
            self._tracked_data[conversation_id] = {
                'items': []  # Single ordered list with timestamps
            }

    def _add_tracking_item(self, item_type: str, data: Dict[str, Any]) -> None:
        """Add a tracking item to the ordered list."""
        tracking_item = {
            'type': item_type,
            'timestamp': get_iso_timestamp(),
            'data': data
        }
        
        with self._lock:
            self._ensure_conversation_storage(self.config.conversation_id)
            self._tracked_data[self.config.conversation_id]['items'].append(tracking_item)
    
    def _add_token_usage(self, conversation_id: str) -> None:
        """Add token usage as an action to tracked data before the last item."""
        data = {
            "action_name": "token_usage",
            "conversation_id": self.config.conversation_id,
            "metadata": self.get_token_usage()
        }
        
        # Insert before the last item (or at the end if only one item)
        if len(self._tracked_data[conversation_id]['items']) <= 1:
            # If 0 or 1 items, just append
            self._tracked_data[conversation_id]['items'].append({
                'type': 'action',
                'timestamp': get_iso_timestamp(),
                'data': data
            })
        else:
            # Insert before the last item
            tracking_item = {
                'type': 'action',
                'timestamp': get_iso_timestamp(),
                'data': data
            }
            self._tracked_data[conversation_id]['items'].insert(-1, tracking_item)

    def _patch_llm_clients(self):
        if self.config.token_handler:
            if self.config.token_handler == TokenHandlerType.LLAMAINDEX.value:
                self._token_handler = set_llamaindex_token_handler(self.config.log_level)

conversation_tracker = ConversationTracker()
