# http_client.py
import time
import requests
from typing import Dict, Any, Optional, List
import copy
from agentsight.config import Config
from agentsight.enums import Sender
from agentsight.exceptions import (
    ConversationApiException, 
    ConversationNetworkException, 
    InvalidConversationDataException,
    NotFoundException,
    UnauthorizedException,
    ForbiddenException
)
from agentsight.validators import (
    validate_action_data, 
    validate_button_data, 
    validate_conversation_id,
    validate_conversation_data,
    validate_feedback_data
)
from agentsight.helpers import (
    get_iso_timestamp, 
    prepare_form_data_payload_from_data
)
from agentsight.logging import logger, configure_logging
configure_logging()

class HTTPClient:
    """HTTP client for AgentSight API communication."""
    
    _MAX_RETRIES = 3
    _BACKOFF_BASE = 2
    _TIMEOUT = 15

    def __init__(self, config: Config):
        self.config = config
        self._setup_http_session()

    def _setup_http_session(self):
        """Setup the HTTP session with default headers and configuration."""
        self._session = requests.Session()
        self._session.headers.update({
            "Authorization": f"Api-Key {self.config.api_key}",
            "Content-Type": "application/json",
        })

    def send_payload(self, payload_type: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Send payload to the AgentSight backend.
        If attachments are present, sends them to /attachments endpoint separately.

        Args:
            payload_type (str): Type of payload ('full', 'question', 'answer', 'action', 'button', 'attachments')
            data (dict): Data to send

        Returns:
            dict: Response data from the API

        Raises:
            ConversationApiException: If API returns an error
            ConversationNetworkException: If network request fails
            InvalidConversationDataException: If data validation fails
        """
        # Validate data based on payload type
        if payload_type in ['full', 'question', 'answer']:
            if not validate_conversation_data(data):
                raise InvalidConversationDataException("Invalid conversation data provided.")
        elif payload_type == 'action':
            if not validate_action_data(data):
                raise InvalidConversationDataException("Invalid action data provided.")
        elif payload_type == 'button':
            if not validate_button_data(data):
                raise InvalidConversationDataException("Invalid button data provided.")
        elif payload_type == 'feedback':
            if not validate_feedback_data(data):
                raise InvalidConversationDataException("Invalid feedback data provided.")
        elif payload_type in ['attachments', 'conversation']:
            validate_conversation_id(data)

        # Determine the endpoint based on payload_type
        endpoint_map = {
            'full': f"{self.config.endpoint}/api/track/",
            'question': f"{self.config.endpoint}/api/track/",
            'answer': f"{self.config.endpoint}/api/track/",
            'action': f"{self.config.endpoint}/api/action_logs/",
            'button': f"{self.config.endpoint}/api/buttons/",
            'attachments': f"{self.config.endpoint}/api/attachments/",
            'conversation': f"{self.config.endpoint}/api/conversations/",
            'feedback': f"{self.config.endpoint}/api/conversation-feedbacks/"
        }
        
        endpoint = endpoint_map.get(payload_type, self.config.endpoint)

        # Determine timeout based on payload type
        timeout = self._TIMEOUT * 2 if payload_type == 'attachments' else self._TIMEOUT

        # # Special handling for attachments payload_type
        # if payload_type == 'attachments':
        #     payload = {
        #         "timestamp": get_iso_timestamp(),
        #         **data
        #     }

        #     logger.debug(f"Sending {payload_type} payload")

        #     return self._send_request_with_retries(
        #         endpoint,
        #         payload,
        #         payload_type,
        #         timeout=timeout
        #     )

        payload = {
            "timestamp": get_iso_timestamp(),
            **data
        }

        # Log with sanitized payload (truncate attachment data)
        logger.debug(f"Sending {payload_type} payload")
        sanitized_payload = self._sanitize_payload_for_logging(payload)
        logger.debug(f"Payload: {sanitized_payload}")

        return self._send_request_with_retries(
            endpoint,
            payload,
            payload_type,
            timeout=timeout
        )
    
    def _send_request_with_retries(
        self, 
        url: str, 
        payload: Dict[str, Any], 
        request_type: str, 
        timeout: Optional[int] = None
    ) -> Dict[str, Any]:
        if timeout is None:
            timeout = self._TIMEOUT
        
        # Send with retries
        for attempt in range(self._MAX_RETRIES):
            try:
                response = self._session.post(
                    url,
                    json=payload,
                    timeout=timeout
                )

                if response.status_code == 200 or response.status_code == 201:
                    logger.debug(f"✅ Successfully sent {request_type} request")
                    return response.json() if response.content else {}
                
                elif response.status_code >= 400:
                    error_data = {}
                    try:
                        error_data = response.json()
                        logger.debug(f"Error response data: {error_data}")
                    except:
                        pass

                    if error_data:
                        # Handle Django REST framework validation errors
                        if isinstance(error_data, dict):
                            if 'detail' in error_data:
                                api_error_message = error_data['detail']
                            else:
                                # Format field validation errors nicely
                                error_messages = []
                                for field, errors in error_data.items():
                                    if isinstance(errors, list):
                                        error_messages.append(f"{field}: {', '.join(errors)}")
                                    else:
                                        error_messages.append(f"{field}: {errors}")
                                api_error_message = "; ".join(error_messages)
                        else:
                            api_error_message = str(error_data)
                    else:
                        api_error_message = response.text or 'Unknown error'

                    error_message = f"API error for {request_type} ({response.status_code}): {api_error_message}"
                    logger.error(error_message)
                    
                    raise ConversationApiException(
                        error_message,
                        status_code=response.status_code,
                        response_data=error_data
                    )

            except requests.RequestException as e:
                if attempt == self._MAX_RETRIES - 1:
                    error_message = f"Network error for {request_type} after {self._MAX_RETRIES} attempts: {str(e)}"
                    logger.error(error_message)
                    raise ConversationNetworkException(error_message)

                # Exponential backoff
                wait_time = self._BACKOFF_BASE ** attempt
                logger.warning(f"{request_type} request failed (attempt {attempt + 1}), retrying in {wait_time}s: {str(e)}")
                time.sleep(wait_time)
                continue

        raise ConversationNetworkException(f"Failed to send {request_type} after {self._MAX_RETRIES} attempts")
    
    def send_form_data_payload(
        self, 
        attachments: List[Dict[str, Any]],
        conversation_id: str,
        sender: Optional[Sender] = Sender.USER.value,
        metadata: Optional[Dict[str, Any]] = None,
        timestamp: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Send attachments as multipart/form-data from file data.
        
        Args:
            attachments (List[dict]): List of processed attachment info
            
        Returns:
            dict: Response data from the API
        """
        files = prepare_form_data_payload_from_data(attachments, conversation_id, sender, metadata, timestamp)
        logger.debug(f"Sending attachments form-data payload from data with {len(attachments)} attachment(s)")

        # Temporarily remove Content-Type header
        original_headers = self._session.headers.copy()
        if 'Content-Type' in self._session.headers:
            del self._session.headers['Content-Type']

        try:
            # Send with retries
            for attempt in range(self._MAX_RETRIES):
                try:
                    # Reset all file positions before sending
                    for key, value in files.items():
                        if key.startswith('attachment_') and hasattr(value[1], 'seek'):
                            value[1].seek(0)
                    
                    response = self._session.post(
                        f"{self.config.endpoint}/api/attachments/",
                        files=files,
                        timeout=self._TIMEOUT * 3
                    )

                    if response.status_code == 200 or response.status_code == 201:
                        logger.debug(f"✅ Successfully sent attachments form-data payload from data")
                        return response.json() if response.content else {}
                    
                    elif response.status_code >= 400:
                        error_data = {}
                        try:
                            error_data = response.json()
                            logger.debug(f"Error response data: {error_data}")
                        except:
                            pass

                        if error_data:
                            # Handle Django REST framework validation errors
                            if isinstance(error_data, dict):
                                if 'detail' in error_data:
                                    api_error_message = error_data['detail']
                                else:
                                    # Format field validation errors nicely
                                    error_messages = []
                                    for field, errors in error_data.items():
                                        if isinstance(errors, list):
                                            error_messages.append(f"{field}: {', '.join(errors)}")
                                        else:
                                            error_messages.append(f"{field}: {errors}")
                                    api_error_message = "; ".join(error_messages)
                            else:
                                api_error_message = str(error_data)
                        else:
                            api_error_message = response.text or 'Unknown error'

                        error_message = f"API error for attachments ({response.status_code}): {api_error_message}"
                        
                        raise ConversationApiException(
                            error_message,
                            status_code=response.status_code,
                            response_data=error_data
                        )

                except requests.RequestException as e:
                    if attempt == self._MAX_RETRIES - 1:
                        error_message = f"Network error after {self._MAX_RETRIES} attempts: {str(e)}"
                        logger.error(error_message)
                        raise ConversationNetworkException(error_message)

                    wait_time = self._BACKOFF_BASE ** attempt
                    logger.warning(f"Request failed (attempt {attempt + 1}), retrying in {wait_time}s: {str(e)}")
                    time.sleep(wait_time)
                    continue

            raise ConversationNetworkException(f"Failed to send attachments after {self._MAX_RETRIES} attempts")
        
        finally:
            # Restore original headers
            self._session.headers.update(original_headers)

    def send_form_data_payload_with_message(
        self,
        attachments: List[Dict[str, Any]],
        message_id: int,
        conversation_id: str,
        sender: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Send attachments as form-data linked to a specific message.
        
        Args:
            attachments: List of attachment data
            message_id: Database ID of the message
            conversation_id: Database ID of the conversation
            sender: 'end_user' or 'agent'
            metadata: Optional metadata
        """
        files = prepare_form_data_payload_from_data(
            attachments, 
            conversation_id, 
            sender, 
            metadata
        )
        
        # Add message_id to the form data
        files['message'] = (None, str(message_id))
        
        logger.debug(f"Sending attachments form-data for message {message_id}")

        # Temporarily remove Content-Type header
        original_headers = self._session.headers.copy()
        if 'Content-Type' in self._session.headers:
            del self._session.headers['Content-Type']

        try:
            for attempt in range(self._MAX_RETRIES):
                try:
                    # Reset file positions
                    for key, value in files.items():
                        if key.startswith('attachment_') and hasattr(value[1], 'seek'):
                            value[1].seek(0)
                    
                    response = self._session.post(
                        f"{self.config.endpoint}/api/attachments/",
                        files=files,
                        timeout=self._TIMEOUT * 3
                    )

                    if response.status_code in [200, 201]:
                        logger.debug(f"✅ Successfully sent attachments for message {message_id}")
                        return response.json() if response.content else {}
                    
                    elif response.status_code >= 400:
                        error_data = {}
                        try:
                            error_data = response.json()
                            logger.debug(f"Error response data: {error_data}")
                        except:
                            pass

                        if error_data:
                            # Handle Django REST framework validation errors
                            if isinstance(error_data, dict):
                                if 'detail' in error_data:
                                    api_error_message = error_data['detail']
                                else:
                                    # Format field validation errors nicely
                                    error_messages = []
                                    for field, errors in error_data.items():
                                        if isinstance(errors, list):
                                            error_messages.append(f"{field}: {', '.join(errors)}")
                                        else:
                                            error_messages.append(f"{field}: {errors}")
                                    api_error_message = "; ".join(error_messages)
                            else:
                                api_error_message = str(error_data)
                        else:
                            api_error_message = response.text or 'Unknown error'

                        error_message = f"API error for attachments ({response.status_code}): {api_error_message}"
                        
                        raise ConversationApiException(
                            error_message,
                            status_code=response.status_code,
                            response_data=error_data
                        )
                    
                except requests.RequestException as e:
                    if attempt == self._MAX_RETRIES - 1:
                        error_message = f"Network error after {self._MAX_RETRIES} attempts: {str(e)}"
                        logger.error(error_message)
                        raise ConversationNetworkException(error_message)

                    wait_time = self._BACKOFF_BASE ** attempt
                    logger.warning(f"Request failed (attempt {attempt + 1}), retrying in {wait_time}s: {str(e)}")
                    time.sleep(wait_time)
                    continue

            raise ConversationNetworkException(f"Failed to send attachments after {self._MAX_RETRIES} attempts")

        finally:
            self._session.headers.update(original_headers)
    
    def _sanitize_payload_for_logging(self, payload: Dict[str, Any], max_attachment_preview: int = 100) -> Dict[str, Any]:
        """
        Create a sanitized copy of payload for logging by truncating attachment data.
        
        Args:
            payload: The payload to sanitize
            max_attachment_preview: Maximum characters to show from attachment data
            
        Returns:
            Sanitized copy of payload safe for logging
        """
        # Deep copy to avoid modifying original
        sanitized = copy.deepcopy(payload)
        
        def truncate_attachment_data(obj):
            """Recursively find and truncate attachment data"""
            if isinstance(obj, dict):
                # Handle direct attachment data
                if 'data' in obj and isinstance(obj['data'], (str, bytes)):
                    original_length = len(obj['data'])
                    if original_length > max_attachment_preview:
                        preview = str(obj['data'])[:max_attachment_preview]
                        obj['data'] = f"{preview}... [truncated, total length: {original_length}]"
                
                # Recursively process all dict values
                for key, value in obj.items():
                    if key == 'attachments' and isinstance(value, list):
                        # Process each attachment in the list
                        for attachment in value:
                            truncate_attachment_data(attachment)
                    elif isinstance(value, (dict, list)):
                        truncate_attachment_data(value)
            
            elif isinstance(obj, list):
                for item in obj:
                    truncate_attachment_data(item)
        
        truncate_attachment_data(sanitized)
        return sanitized
    
    def send_payload(self, payload_type: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Send payload to the AgentSight backend.
        If attachments are present, sends them to /attachments endpoint separately.

        Args:
            payload_type (str): Type of payload ('full', 'question', 'answer', 'action', 'button', 'attachments')
            data (dict): Data to send

        Returns:
            dict: Response data from the API

        Raises:
            ConversationApiException: If API returns an error
            ConversationNetworkException: If network request fails
            InvalidConversationDataException: If data validation fails
        """
        # Validate data based on payload type
        if payload_type in ['full', 'question', 'answer']:
            if not validate_conversation_data(data):
                raise InvalidConversationDataException("Invalid conversation data provided.")
        elif payload_type == 'action':
            if not validate_action_data(data):
                raise InvalidConversationDataException("Invalid action data provided.")
        elif payload_type == 'button':
            if not validate_button_data(data):
                raise InvalidConversationDataException("Invalid button data provided.")
        elif payload_type == 'feedback':
            if not validate_feedback_data(data):
                raise InvalidConversationDataException("Invalid feedback data provided.")
        elif payload_type in ['attachments', 'conversation']:
            validate_conversation_id(data)
            # Attachments validation is already done in track_attachments method

        # Determine the endpoint based on payload_type
        endpoint_map = {
            'full': f"{self.config.endpoint}/api/track/",
            'question': f"{self.config.endpoint}/api/track/",
            'answer': f"{self.config.endpoint}/api/track/",
            'action': f"{self.config.endpoint}/api/action_logs/",
            'button': f"{self.config.endpoint}/api/buttons/",
            'attachments': f"{self.config.endpoint}/api/attachments/",
            'conversation': f"{self.config.endpoint}/api/conversations/",
            'feedback': f"{self.config.endpoint}/api/conversation-feedbacks/"
        }
        
        endpoint = endpoint_map.get(payload_type, self.config.endpoint)

        # Determine timeout based on payload type
        timeout = self._TIMEOUT * 2 if payload_type == 'attachments' else self._TIMEOUT

        # Build payload
        payload = {
            "timestamp": get_iso_timestamp(),
            **data
        }

        # Log with sanitized payload (truncate attachment data)
        logger.debug(f"Sending {payload_type} payload")
        sanitized_payload = self._sanitize_payload_for_logging(payload)
        logger.debug(f"Payload: {sanitized_payload}")

        return self._send_request_with_retries(
            endpoint,
            payload,
            payload_type,
            timeout=timeout
        )

    def get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Send a GET request to the AgentSight API.
        
        Args:
            path (str): API endpoint path (e.g., '/api/conversations/')
            params (dict, optional): Query parameters
            
        Returns:
            dict: Response data from the API
            
        Raises:
            NotFoundException: If resource not found (404)
            UnauthorizedException: If authentication fails (401)
            ForbiddenException: If access is forbidden (403)
            ConversationApiException: If API returns other error
            ConversationNetworkException: If network request fails
        """
        url = f"{self.config.endpoint}{path}"
        
        logger.debug(f"Sending GET request to {path}")
        if params:
            logger.debug(f"Query parameters: {params}")

        return self._send_get_request_with_retries(url, params)

    def _send_get_request_with_retries(
        self,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        timeout: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Send GET request with retry logic.
        
        Args:
            url (str): Full URL to send request to
            params (dict, optional): Query parameters
            timeout (int, optional): Request timeout in seconds
            
        Returns:
            dict: Response data from the API
        """
        if timeout is None:
            timeout = self._TIMEOUT

        for attempt in range(self._MAX_RETRIES):
            try:
                response = self._session.get(
                    url,
                    params=params,
                    timeout=timeout
                )

                # Success responses
                if response.status_code in [200, 201]:
                    logger.debug(f"✅ Successfully received GET response from {url}")
                    return response.json() if response.content else {}

                # Handle specific error status codes
                elif response.status_code == 404:
                    error_message = "Resource not found"
                    try:
                        error_data = response.json()
                        if 'detail' in error_data:
                            error_message = error_data['detail']
                    except:
                        pass
                    
                    logger.error(f"Resource not found (404): {url}")
                    raise NotFoundException(error_message)

                elif response.status_code == 401:
                    error_message = "Invalid or missing API key"
                    try:
                        error_data = response.json()
                        if 'detail' in error_data:
                            error_message = error_data['detail']
                    except:
                        pass
                    
                    logger.error(f"Unauthorized (401): {error_message}")
                    raise UnauthorizedException(error_message)

                elif response.status_code == 403:
                    error_message = "Access forbidden - not authorized to access this resource"
                    try:
                        error_data = response.json()
                        if 'detail' in error_data:
                            error_message = error_data['detail']
                    except:
                        pass
                    
                    logger.error(f"Forbidden (403): {error_message}")
                    raise ForbiddenException(error_message)

                # Handle other error status codes
                elif response.status_code >= 400:
                    error_data = {}
                    try:
                        error_data = response.json()
                        logger.debug(f"Error response data: {error_data}")
                    except:
                        pass

                    if error_data:
                        if isinstance(error_data, dict):
                            if 'detail' in error_data:
                                api_error_message = error_data['detail']
                            else:
                                # Format field validation errors
                                error_messages = []
                                for field, errors in error_data.items():
                                    if isinstance(errors, list):
                                        error_messages.append(f"{field}: {', '.join(str(e) for e in errors)}")
                                    else:
                                        error_messages.append(f"{field}: {errors}")
                                api_error_message = "; ".join(error_messages)
                        else:
                            api_error_message = str(error_data)
                    else:
                        api_error_message = response.text or 'Unknown error'

                    error_message = f"API error ({response.status_code}): {api_error_message}"
                    logger.error(error_message)
                    
                    raise ConversationApiException(
                        error_message,
                        status_code=response.status_code,
                        response_data=error_data
                    )

            except (NotFoundException, UnauthorizedException, ForbiddenException):
                # Don't retry on these specific errors - they won't succeed on retry
                raise
                
            except ConversationApiException:
                # Don't retry on API errors (client errors usually won't succeed on retry)
                raise
                
            except requests.RequestException as e:
                if attempt == self._MAX_RETRIES - 1:
                    error_message = f"Network error after {self._MAX_RETRIES} attempts: {str(e)}"
                    logger.error(error_message)
                    raise ConversationNetworkException(error_message)

                # Exponential backoff for network errors
                wait_time = self._BACKOFF_BASE ** attempt
                logger.warning(f"GET request failed (attempt {attempt + 1}), retrying in {wait_time}s: {str(e)}")
                time.sleep(wait_time)
                continue

        raise ConversationNetworkException(f"Failed to send GET request after {self._MAX_RETRIES} attempts")

    def patch(
        self,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Send a PATCH request to the AgentSight API.
        
        Args:
            path (str): API endpoint path
            params (dict, optional): Query parameters
            data (dict, optional): JSON data to send in body
            
        Returns:
            dict: Response data from the API
        """
        url = f"{self.config.endpoint}{path}"
        
        logger.debug(f"Sending PATCH request to {path}")
        if params:
            logger.debug(f"Query parameters: {params}")
        if data:
            logger.debug(f"Request data: {data}")

        return self._send_request_with_method(
            method='PATCH',
            url=url,
            params=params,
            data=data
        )

    def post(
        self,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Send a POST request to the AgentSight API.
        
        Args:
            path (str): API endpoint path
            params (dict, optional): Query parameters
            data (dict, optional): JSON data to send in body
            
        Returns:
            dict: Response data from the API
        """
        url = f"{self.config.endpoint}{path}"
        
        logger.debug(f"Sending POST request to {path}")
        if params:
            logger.debug(f"Query parameters: {params}")
        if data:
            logger.debug(f"Request data: {data}")

        return self._send_request_with_method(
            method='POST',
            url=url,
            params=params,
            data=data
        )

    def delete(
        self,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Send a DELETE request to the AgentSight API.
        
        Args:
            path (str): API endpoint path
            params (dict, optional): Query parameters
            data (dict, optional): JSON data to send in body
            
        Returns:
            dict: Response data from the API
        """
        url = f"{self.config.endpoint}{path}"
        
        logger.debug(f"Sending DELETE request to {path}")
        if params:
            logger.debug(f"Query parameters: {params}")

        return self._send_request_with_method(
            method='DELETE',
            url=url,
            params=params,
            data=data
        )

    def _send_request_with_method(
        self,
        method: str,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None,
        timeout: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Send request with specified HTTP method and retry logic.
        
        Args:
            method (str): HTTP method (GET, POST, PATCH, DELETE, etc.)
            url (str): Full URL to send request to
            params (dict, optional): Query parameters
            data (dict, optional): JSON data to send
            timeout (int, optional): Request timeout in seconds
            
        Returns:
            dict: Response data from the API
        """
        if timeout is None:
            timeout = self._TIMEOUT

        for attempt in range(self._MAX_RETRIES):
            try:
                response = self._session.request(
                    method=method,
                    url=url,
                    params=params,
                    json=data,
                    timeout=timeout
                )

                # Success responses
                if response.status_code in [200, 201, 204]:
                    logger.debug(f"✅ Successfully received {method} response from {url}")
                    return response.json() if response.content else {}

                # Handle specific error status codes
                elif response.status_code == 404:
                    error_message = "Resource not found"
                    try:
                        error_data = response.json()
                        if 'detail' in error_data:
                            error_message = error_data['detail']
                    except:
                        pass
                    
                    logger.error(f"Resource not found (404): {url}")
                    raise NotFoundException(error_message)

                elif response.status_code == 401:
                    error_message = "Invalid or missing API key"
                    try:
                        error_data = response.json()
                        if 'detail' in error_data:
                            error_message = error_data['detail']
                    except:
                        pass
                    
                    logger.error(f"Unauthorized (401): {error_message}")
                    raise UnauthorizedException(error_message)

                elif response.status_code == 403:
                    error_message = "Access forbidden - not authorized to access this resource"
                    try:
                        error_data = response.json()
                        if 'detail' in error_data:
                            error_message = error_data['detail']
                    except:
                        pass
                    
                    logger.error(f"Forbidden (403): {error_message}")
                    raise ForbiddenException(error_message)

                # Handle other error status codes
                elif response.status_code >= 400:
                    error_data = {}
                    try:
                        error_data = response.json()
                        logger.debug(f"Error response data: {error_data}")
                    except:
                        pass

                    if error_data:
                        if isinstance(error_data, dict):
                            if 'detail' in error_data:
                                api_error_message = error_data['detail']
                            else:
                                # Format field validation errors
                                error_messages = []
                                for field, errors in error_data.items():
                                    if isinstance(errors, list):
                                        error_messages.append(f"{field}: {', '.join(str(e) for e in errors)}")
                                    else:
                                        error_messages.append(f"{field}: {errors}")
                                api_error_message = "; ".join(error_messages)
                        else:
                            api_error_message = str(error_data)
                    else:
                        api_error_message = response.text or 'Unknown error'

                    error_message = f"API error ({response.status_code}): {api_error_message}"
                    logger.error(error_message)
                    
                    raise ConversationApiException(
                        error_message,
                        status_code=response.status_code,
                        response_data=error_data
                    )

            except (NotFoundException, UnauthorizedException, ForbiddenException):
                # Don't retry on these specific errors
                raise
                
            except ConversationApiException:
                # Don't retry on API errors
                raise
                
            except requests.RequestException as e:
                if attempt == self._MAX_RETRIES - 1:
                    error_message = f"Network error after {self._MAX_RETRIES} attempts: {str(e)}"
                    logger.error(error_message)
                    raise ConversationNetworkException(error_message)

                # Exponential backoff for network errors
                wait_time = self._BACKOFF_BASE ** attempt
                logger.warning(f"{method} request failed (attempt {attempt + 1}), retrying in {wait_time}s: {str(e)}")
                time.sleep(wait_time)
                continue

        raise ConversationNetworkException(f"Failed to send {method} request after {self._MAX_RETRIES} attempts")
