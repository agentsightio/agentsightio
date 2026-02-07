from typing import Dict, Any, List, Optional
from agentsight.helpers.conversation_utils import get_iso_timestamp
from agentsight.helpers.mime_types import get_mime_type
from io import BytesIO
from agentsight.enums import AttachmentMode, Sender
import json
    
def prepare_form_data_payload_from_data(
    attachments: List[Dict[str, Any]],
    conversation_id: str,
    sender: Optional[Sender] = Sender.USER.value,
    metadata: Optional[Dict[str, Any]] = None,
    timestamp: Optional[str] = None
) -> Dict[str, Any]:
    """
    Prepare form data payload from file data objects.
    
    Args:
        attachments (List[dict]): List of processed attachment info
        
    Returns:
        dict: Files dictionary for requests
    """
    files = {}
    
    # Add metadata as form fields
    files['timestamp'] = (None, timestamp or get_iso_timestamp())
    files['conversation'] = (None, conversation_id)
    files['sender'] = (None, sender)
    files['mode'] = (None, AttachmentMode.FORM_DATA.value)
    files['metadata'] = (None, json.dumps(metadata))
    
    # Add each attachment from data
    for i, attachment in enumerate(attachments):
        file_data = attachment['data']  # This is bytes or BytesIO
        
        # Get filename - either provided or auto-generated
        filename = attachment.get('filename')
        mime_type = attachment.get('mime_type')
        if not filename:
            # Auto-detect mime type and generate filename
            if not mime_type:
                mime_type = get_mime_type(file_data)

            filename = generate_filename_from_mime_type(mime_type, i)
        
        # If we still don't have mime_type, detect from data
        if not mime_type:
            mime_type = get_mime_type(file_data)
        
        # Convert to BytesIO if needed
        if isinstance(file_data, bytes):
            file_data = BytesIO(file_data)
        
        # Reset file position to beginning
        if hasattr(file_data, 'seek'):
            file_data.seek(0)
        
        files[f'attachment_{i}'] = (filename, file_data, mime_type)
    
    return files

def generate_filename_from_mime_type(mime_type: str, index: int) -> str:
    """
    Generate a filename based on mime type with comprehensive mapping.
    
    Args:
        mime_type (str): The MIME type of the file
        index (int): Index for generating unique filenames
        
    Returns:
        str: Generated filename with appropriate extension
    """
    # Comprehensive mime type to extension mapping
    mime_to_ext = {
        # Image formats
        'image/jpeg': '.jpg',
        'image/png': '.png',
        'image/gif': '.gif',
        'image/webp': '.webp',
        'image/bmp': '.bmp',
        'image/tiff': '.tiff',
        'image/tif': '.tif',
        'image/x-icon': '.ico',
        'image/svg+xml': '.svg',
        'image/avif': '.avif',
        'image/apng': '.apng',
        
        # Document formats
        'application/pdf': '.pdf',
        'application/rtf': '.rtf',
        'text/rtf': '.rtf',
        
        # Microsoft Office (Legacy)
        'application/msword': '.doc',
        'application/vnd.ms-excel': '.xls',
        'application/vnd.ms-powerpoint': '.ppt',
        
        # Microsoft Office (Open XML)
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document': '.docx',
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': '.xlsx',
        'application/vnd.openxmlformats-officedocument.presentationml.presentation': '.pptx',
        
        # OpenDocument formats
        'application/vnd.oasis.opendocument.text': '.odt',
        'application/vnd.oasis.opendocument.spreadsheet': '.ods',
        'application/vnd.oasis.opendocument.presentation': '.odp',
        'application/vnd.oasis.opendocument.graphics': '.odg',
        'application/vnd.oasis.opendocument.formula': '.odf',
        'application/vnd.oasis.opendocument.database': '.odb',
        
        # Archive formats
        'application/zip': '.zip',
        'application/x-rar-compressed': '.rar',
        'application/x-tar': '.tar',
        'application/gzip': '.gz',
        'application/x-7z-compressed': '.7z',
        'application/epub+zip': '.epub',
        
        # Audio formats
        'audio/mpeg': '.mp3',
        'audio/wav': '.wav',
        'audio/ogg': '.ogg',
        'audio/aac': '.aac',
        'audio/webm': '.weba',
        'audio/flac': '.flac',
        'audio/x-ms-wma': '.wma',
        
        # Video formats
        'video/mp4': '.mp4',
        'video/webm': '.webm',
        'video/quicktime': '.mov',
        'video/x-msvideo': '.avi',
        'video/x-matroska': '.mkv',
        'video/ogg': '.ogv',
        'video/x-flv': '.flv',
        'video/x-ms-wmv': '.wmv',
        
        # Text formats
        'text/plain': '.txt',
        'text/html': '.html',
        'text/css': '.css',
        'text/csv': '.csv',
        'text/xml': '.xml',
        'text/javascript': '.js',
        'text/markdown': '.md',
        'text/x-python': '.py',
        'text/x-java-source': '.java',
        'text/x-c': '.c',
        'text/x-c++': '.cpp',
        
        # Application formats
        'application/json': '.json',
        'application/xml': '.xml',
        'application/javascript': '.js',
        'application/x-javascript': '.js',
        'application/xhtml+xml': '.xhtml',
        'application/atom+xml': '.atom',
        'application/rss+xml': '.rss',
        
        # Email formats
        'message/rfc822': '.eml',
        'application/vnd.ms-outlook': '.msg',
        
        # Font formats
        'font/woff': '.woff',
        'font/woff2': '.woff2',
        'font/ttf': '.ttf',
        'font/otf': '.otf',
        'application/font-woff': '.woff',
        'application/font-woff2': '.woff2',
        'application/x-font-ttf': '.ttf',
        'application/x-font-otf': '.otf',
        
        # CAD formats
        'application/dwg': '.dwg',
        'application/dxf': '.dxf',
        
        # eBook formats
        'application/x-mobipocket-ebook': '.mobi',
        'application/vnd.amazon.ebook': '.azw',
        
        # Backup formats
        'application/vnd.ms-cab-compressed': '.cab',
        'application/x-stuffit': '.sit',
        
        # Database formats
        'application/x-sqlite3': '.sqlite',
        'application/vnd.sqlite3': '.sqlite3',
        
        # Programming/Config formats
        'application/x-yaml': '.yaml',
        'text/yaml': '.yml',
        'application/toml': '.toml',
        'text/x-ini': '.ini',
        'application/x-httpd-php': '.php',
        'application/x-ruby': '.rb',
        'application/x-perl': '.pl',
        'application/x-shell': '.sh',
        'application/x-powershell': '.ps1',
        'application/x-batch': '.bat',
        
        # Miscellaneous
        'application/octet-stream': '.bin',
        'application/x-binary': '.bin',
        'application/x-executable': '.exe',
        'application/x-msdos-program': '.exe',
        'application/x-msdownload': '.exe',
    }
    
    # Get extension from mime type, fallback to .bin for unknown types
    extension = mime_to_ext.get(mime_type, '.bin')
    
    # Handle special cases where mime type might have parameters
    if ';' in mime_type:
        base_mime_type = mime_type.split(';')[0].strip()
        extension = mime_to_ext.get(base_mime_type, extension)
    
    return f"attachment_{index}{extension}"
