# http_client.py
import time
import requests
from typing import Dict, Any, Optional, List
import json
from agentsight.config import Config
from agentsight.enums import Sender
from agentsight.exceptions import (
    ConversationApiException, 
    ConversationNetworkException, 
    InvalidConversationDataException
)
from agentsight.validators import (
    validate_action_data, 
    validate_button_data, 
    validate_conversation_id,
    validate_conversation_data
)
from agentsight.helpers import (
    get_iso_timestamp, 
    format_conversation_metadata,
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
        }
        
        endpoint = endpoint_map.get(payload_type, self.config.endpoint)

        # Determine timeout based on payload type
        timeout = self._TIMEOUT * 2 if payload_type == 'attachments' else self._TIMEOUT

        # Special handling for attachments payload_type
        if payload_type == 'attachments':
            # For attachments, send directly to attachments endpoint
            payload = {
                "timestamp": get_iso_timestamp(),
                **data
            }
            
            # Format metadata
            if "metadata" in payload:
                payload["metadata"] = format_conversation_metadata(payload["metadata"])

            logger.debug(f"Sending {payload_type} payload")

            return self._send_request_with_retries(
                endpoint,
                payload,
                payload_type,
                timeout=timeout
            )

        payload = {
            "timestamp": get_iso_timestamp(),
            **data
        }

        # Format metadata
        if "metadata" in payload:
            payload["metadata"] = format_conversation_metadata(payload["metadata"])

        logger.debug(f"Sending {payload_type} payload")
        logger.debug(f"Payload: {payload}")

        return self._send_request_with_retries(
            endpoint,
            payload,
            payload_type
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
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Send attachments as multipart/form-data from file data.
        
        Args:
            attachments (List[dict]): List of processed attachment info
            
        Returns:
            dict: Response data from the API
        """
        files = prepare_form_data_payload_from_data(attachments, conversation_id, sender, metadata)
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
