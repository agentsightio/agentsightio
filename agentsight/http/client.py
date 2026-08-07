# http_client.py
import time
import requests
from typing import Dict, Any, Optional
from agentsight.config import Config
from agentsight.exceptions import (
    ConversationApiException,
    ConversationNetworkException,
    NotFoundException,
    UnauthorizedException,
    ForbiddenException
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
