import base64
import binascii
from typing import List, Dict, Any
from agentsight.exceptions import InvalidAttachmentException
from agentsight.enums import AttachmentMode
from agentsight.types import AttachmentInput
    
def validate_and_process_attachments_flexible(
    attachments: List[AttachmentInput], 
    mode: AttachmentMode
) -> List[Dict[str, Any]]:
    """
    Validate and process attachments based on mode.
    
    Args:
        attachments: List of attachment objects
        mode: AttachmentMode enum
        
    Returns:
        List[dict]: Processed attachment objects
        
    Raises:
        InvalidAttachmentException: If attachments are invalid
    """
    if not attachments:
        raise InvalidAttachmentException("Attachments list cannot be empty")
    
    if not isinstance(attachments, list):
        raise InvalidAttachmentException("Attachments must be provided as a list")
    
    processed_attachments = []
    
    for i, attachment in enumerate(attachments):
        if not isinstance(attachment, dict):
            raise InvalidAttachmentException(
                f"Attachment {i+1}: Must be a dictionary with required keys"
            )
        
        if mode == AttachmentMode.BASE64:
            # Original behavior for base64 mode
            required_keys = ['filename', 'mime_type', 'data']
            missing_keys = [key for key in required_keys if key not in attachment]
            if missing_keys:
                raise InvalidAttachmentException(
                    f"Attachment {i+1} missing required keys: {', '.join(missing_keys)}"
                )
            
            filename = attachment.get('filename')
            mime_type = attachment.get('mime_type')
            data = attachment.get('data')
            
            # Validate filename and mime_type
            if not filename or not isinstance(filename, str) or not filename.strip():
                raise InvalidAttachmentException(f"Attachment {i+1} has invalid or empty filename")
            
            if not mime_type or not isinstance(mime_type, str) or not mime_type.strip():
                raise InvalidAttachmentException(f"Attachment {i+1} has invalid or empty mime_type")
            
            # Validate base64 string
            if not isinstance(data, str):
                raise InvalidAttachmentException(f"Attachment {i+1}: In base64 mode, 'data' must be a base64 string")
            
            try:
                base64.b64decode(data, validate=True)
            except (binascii.Error, ValueError):
                raise InvalidAttachmentException(f"Attachment {i+1} '{filename}' has invalid base64 data")
            
            processed_attachments.append({
                'filename': filename,
                'mime_type': mime_type,
                'data': data
            })
        
        elif mode == AttachmentMode.FORM_DATA:
            # New simplified behavior for form data mode
            if 'data' not in attachment:
                raise InvalidAttachmentException(f"Attachment {i+1} missing required key: 'data'")
            
            data = attachment.get('data')
            
            # Validate that data is bytes or file-like object (not string)
            if isinstance(data, str):
                raise InvalidAttachmentException(
                    f"Attachment {i+1}: In form_data mode, 'data' must be bytes or file-like object, not string"
                )
            
            # Build processed attachment
            processed_attachment = {'data': data}
            
            # Add filename if provided, otherwise it will be auto-generated later
            if 'filename' in attachment:
                processed_attachment['filename'] = attachment['filename']
            
            # Add mime_type if provided, otherwise it will be auto-detected later
            if 'mime_type' in attachment or 'content_type' in attachment:
                processed_attachment['mime_type'] = attachment.get('mime_type') or attachment.get('content_type')
            
            # Include any other fields that were provided
            for key, value in attachment.items():
                if key not in ['data', 'filename', 'mime_type', 'content_type']:
                    processed_attachment[key] = value
            
            processed_attachments.append(processed_attachment)
        
        else:
            raise InvalidAttachmentException(f"Invalid mode: {mode}")
        
    return processed_attachments
