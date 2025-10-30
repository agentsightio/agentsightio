import mimetypes
import os
import zipfile
import io
import json
from typing import Union

def get_mime_type(source: Union[str, bytes]) -> str:
    """
    MIME type detection.

    Args:
        source (Union[str, bytes]): Either filename/path or file content as bytes

    Returns:
        str: MIME type string
    """
    if isinstance(source, str):
        return _get_mime_type_from_filename(source)
    elif isinstance(source, bytes):
        return _get_mime_type_from_blob_hybrid(source)
    else:
        return 'application/octet-stream'

def _get_mime_type_from_filename(filename: str) -> str:
    """Get mime type from filename using mimetypes library first, then fallback."""
    # First try with mimetypes library (built into Python)
    mime_type, _ = mimetypes.guess_type(filename)
    if mime_type is not None:
        return mime_type

    # Fallback: manual extension mapping
    ext = os.path.splitext(filename)[1].lower()
    return _get_mime_type_from_extension(ext)

def _get_mime_type_from_blob_hybrid(blob: bytes) -> str:
    """
    Hybrid approach: use enhanced manual detection.
    Keeps same robust detection for ZIP-based formats, images, PDFs, text, etc.
    """
    if len(blob) == 0:
        return 'application/octet-stream'

    try:
        # Use the enhanced manual detection (covers ZIP-based formats too)
        mime_type = _get_mime_type_from_blob_enhanced(blob)
        if mime_type and mime_type != 'application/octet-stream':
            return mime_type
    except Exception as e:
        # Keep a conservative fallback on unexpected errors
        print(f"Enhanced detection failed: {e}")

    # Final fallback
    return 'application/octet-stream'

def _get_mime_type_from_blob_enhanced(blob: bytes) -> str:
    """
    Enhanced manual mime type detection from file content.
    Handles complex formats like Office documents, OpenDocument, etc.
    """
    if len(blob) == 0:
        return 'application/octet-stream'

    # PDF - Most reliable detection
    if blob.startswith(b'%PDF-'):
        return 'application/pdf'

    # Image formats - Very reliable magic numbers
    if blob.startswith(b'\xff\xd8\xff'):
        return 'image/jpeg'
    if blob.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'image/png'
    if blob.startswith(b'GIF87a') or blob.startswith(b'GIF89a'):
        return 'image/gif'
    if blob.startswith(b'RIFF') and len(blob) > 12 and blob[8:12] == b'WEBP':
        return 'image/webp'
    if blob.startswith(b'BM'):
        return 'image/bmp'
    if blob.startswith(b'II*\x00') or blob.startswith(b'MM\x00*'):
        return 'image/tiff'
    if blob.startswith(b'\x00\x00\x01\x00'):
        return 'image/x-icon'

    # RTF - Clear text signature
    if blob.startswith(b'{\\rtf'):
        return 'application/rtf'

    # ZIP-based formats (Office documents, EPUB, etc.)
    if blob.startswith(b'PK\x03\x04') or blob.startswith(b'PK\x05\x06') or blob.startswith(b'PK\x07\x08'):
        return _detect_zip_based_format_safe(blob)

    # Audio formats
    if blob.startswith(b'ID3') or (len(blob) > 2 and blob[:2] == b'\xff\xfb'):
        return 'audio/mpeg'
    if blob.startswith(b'RIFF') and len(blob) > 12 and blob[8:12] == b'WAVE':
        return 'audio/wav'
    if blob.startswith(b'OggS'):
        return 'audio/ogg'

    # Video formats (ftyp at offset 4 is common for MP4/ISO BMFF)
    if len(blob) > 8 and blob[4:8] == b'ftyp':
        return 'video/mp4'

    # Text-based formats
    # Accept some common HTML starts (case-sensitive as bytes) - you may want to normalize if needed
    if blob.startswith(b'<!DOCTYPE html') or blob.startswith(b'<html'):
        return 'text/html'
    if blob.startswith(b'<?xml'):
        return 'text/xml'

    # Try to detect text-based formats by decoding
    try:
        # Try to decode as UTF-8 first, fallback to ignoring errors
        try:
            text_content = blob.decode('utf-8')
        except UnicodeDecodeError:
            text_content = blob.decode('utf-8', errors='ignore')

        # Check if it's actually readable text first
        if not _is_readable_text(text_content):
            # If it's not readable text, it's probably binary
            return 'application/octet-stream'

        # Now check for specific text formats in order of specificity
        if _is_json_content(text_content):
            return 'application/json'

        if _is_csv_content(text_content):
            return 'text/csv'

        if _is_markdown_content(text_content):
            return 'text/markdown'

        # If it's readable text but not any specific format, it's plain text
        return 'text/plain'

    except Exception:
        # If any text processing fails, treat as binary
        return 'application/octet-stream'

def _detect_zip_based_format_safe(blob: bytes) -> str:
    """
    Safely detect ZIP-based formats using only built-in zipfile module.
    Handles Office documents, OpenDocument, EPUB, etc.
    """
    try:
        zip_buffer = io.BytesIO(blob)
        with zipfile.ZipFile(zip_buffer, 'r') as zf:
            filenames = zf.namelist()

            # Check for EPUB first (most specific)
            if 'META-INF/container.xml' in filenames and 'mimetype' in filenames:
                try:
                    mimetype_content = zf.read('mimetype').decode('utf-8').strip()
                    if mimetype_content == 'application/epub+zip':
                        return 'application/epub+zip'
                except:
                    pass

            # Check for OpenDocument formats (before Office formats)
            if 'META-INF/manifest.xml' in filenames:
                odf_type = _detect_odf_format_safe(zf)
                if odf_type != 'application/zip':  # Only return if we found a specific ODF type
                    return odf_type

            # Microsoft Office Open XML formats - specific checks
            if any(f.startswith('xl/') for f in filenames) and 'xl/workbook.xml' in filenames:
                return 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'  # .xlsx

            if any(f.startswith('ppt/') for f in filenames) and 'ppt/presentation.xml' in filenames:
                return 'application/vnd.openxmlformats-officedocument.presentationml.presentation'  # .pptx

            if any(f.startswith('word/') for f in filenames) and 'word/document.xml' in filenames:
                return 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'  # .docx

            # Fallback: try [Content_Types].xml to infer
            if '[Content_Types].xml' in filenames:
                try:
                    content_types = zf.read('[Content_Types].xml').decode('utf-8')
                    if 'spreadsheetml' in content_types:
                        return 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
                    elif 'presentationml' in content_types:
                        return 'application/vnd.openxmlformats-officedocument.presentationml.presentation'
                    elif 'wordprocessingml' in content_types:
                        return 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
                except:
                    pass

    except (zipfile.BadZipFile, zipfile.LargeZipFile, ValueError, OSError):
        # If ZIP parsing fails, it's probably just a regular ZIP or corrupted
        pass
    except Exception:
        # Catch any other unexpected errors
        pass

    # Default to ZIP if we can't determine the specific format
    return 'application/zip'

def _detect_odf_format_safe(zip_file) -> str:
    """
    Safely detect OpenDocument format from ZIP file.
    """
    try:
        manifest_content = zip_file.read('META-INF/manifest.xml').decode('utf-8')

        if 'application/vnd.oasis.opendocument.spreadsheet' in manifest_content:
            return 'application/vnd.oasis.opendocument.spreadsheet'  # .ods
        elif 'application/vnd.oasis.opendocument.text' in manifest_content:
            return 'application/vnd.oasis.opendocument.text'  # .odt
        elif 'application/vnd.oasis.opendocument.presentation' in manifest_content:
            return 'application/vnd.oasis.opendocument.presentation'  # .odp

        filenames = zip_file.namelist()
        if 'content.xml' in filenames and 'styles.xml' in filenames:
            try:
                content_xml = zip_file.read('content.xml').decode('utf-8')
                if 'office:spreadsheet' in content_xml:
                    return 'application/vnd.oasis.opendocument.spreadsheet'
                elif 'office:text' in content_xml:
                    return 'application/vnd.oasis.opendocument.text'
                elif 'office:presentation' in content_xml:
                    return 'application/vnd.oasis.opendocument.presentation'
            except:
                pass

    except Exception:
        pass

    return 'application/zip'

def _is_json_content(text: str) -> bool:
    """Check if text content is valid JSON."""
    text = text.strip()
    if not text:
        return False

    # Must start and end with proper JSON delimiters
    if not ((text.startswith('{') and text.endswith('}')) or
            (text.startswith('[') and text.endswith(']'))):
        return False

    try:
        json.loads(text)
        return True
    except (json.JSONDecodeError, ValueError):
        return False

def _is_csv_content(text: str) -> bool:
    """Improved CSV detection with better heuristics."""
    text = text.strip()
    if not text:
        return False

    lines = text.split('\n')
    if len(lines) < 1:
        return False

    # Remove empty lines and get first 20 lines for analysis
    non_empty_lines = [line.strip() for line in lines if line.strip()]
    if len(non_empty_lines) < 1:
        return False

    # Take first 20 lines for analysis
    sample_lines = non_empty_lines[:20]

    # Check if lines contain commas
    lines_with_commas = [line for line in sample_lines if ',' in line]
    if len(lines_with_commas) < max(1, len(sample_lines) * 0.5):  # At least 50% of lines should have commas
        return False

    # Check for consistent comma counts
    comma_counts = [line.count(',') for line in lines_with_commas]
    if not comma_counts:
        return False

    # Calculate statistics
    avg_commas = sum(comma_counts) / len(comma_counts)
    if avg_commas < 1:  # Should have at least 1 comma per line on average
        return False

    # Check consistency - most lines should have similar comma counts
    max_deviation = max(2, avg_commas * 0.5)  # Allow some deviation
    consistent_lines = sum(1 for count in comma_counts if abs(count - avg_commas) <= max_deviation)
    consistency_ratio = consistent_lines / len(comma_counts)

    # Additional checks for CSV-like content
    first_line = sample_lines[0]

    # Check if first line looks like headers (no quotes around the whole line, reasonable length)
    if len(first_line) > 1000:  # Headers shouldn't be extremely long
        return False

    # Check for excessive special characters that would indicate it's not CSV
    special_chars = sum(1 for char in first_line if char in '{}[]<>|\\')
    if special_chars > len(first_line) * 0.1:  # More than 10% special chars
        return False

    return consistency_ratio >= 0.6  # 60% of lines should have consistent comma counts

def _is_markdown_content(text: str) -> bool:
    """Improved Markdown detection with better heuristics."""
    text = text.strip()
    if len(text) < 10:  # Too short to be meaningful markdown
        return False

    lines = text.split('\n')
    markdown_score = 0

    # Check for headers (strong indicators)
    header_patterns = [
        (r'^# ', 3),        # H1 headers
        (r'^## ', 3),       # H2 headers
        (r'^### ', 2),      # H3 headers
        (r'^#### ', 1),     # H4 headers
    ]

    for line in lines:
        line = line.strip()
        for pattern, score in header_patterns:
            if line.startswith(pattern.replace('^', '')):
                markdown_score += score
                break

    # Check for list items
    list_indicators = 0
    for line in lines:
        line = line.strip()
        if (line.startswith('- ') or line.startswith('* ') or line.startswith('+ ') or
            (len(line) > 3 and line[0].isdigit() and line[1:3] == '. ')):
            list_indicators += 1

    if list_indicators >= 2:  # At least 2 list items
        markdown_score += 2

    # Check for emphasis
    if '**' in text:
        bold_count = text.count('**') // 2  # Pairs of **
        markdown_score += min(bold_count, 2)

    if '*' in text and '**' not in text:
        italic_count = text.count('*') // 2  # Pairs of *
        markdown_score += min(italic_count, 1)

    # Check for links
    if '](' in text:
        link_count = text.count('](')
        markdown_score += min(link_count, 2)

    # Check for code blocks
    if '```' in text:
        code_block_count = text.count('```') // 2
        markdown_score += min(code_block_count * 2, 3)
    elif '`' in text:
        inline_code_count = text.count('`') // 2
        markdown_score += min(inline_code_count, 1)

    # Check for horizontal rules
    for line in lines:
        line = line.strip()
        if line == '---' or line == '***' or line.startswith('---') or line.startswith('***'):
            markdown_score += 1
            break

    # Check for blockquotes
    blockquote_count = sum(1 for line in lines if line.strip().startswith('> '))
    if blockquote_count > 0:
        markdown_score += 1

    # Penalty for CSV-like content (reduce false positives)
    if _looks_like_csv_structure(text):
        markdown_score -= 2

    # Need a minimum score to be considered markdown
    return markdown_score >= 3

def _looks_like_csv_structure(text: str) -> bool:
    """Helper to detect CSV-like structure to avoid false markdown positives."""
    lines = text.split('\n')[:5]  # Check first 5 lines
    comma_lines = [line for line in lines if ',' in line]

    if len(comma_lines) < 2:
        return False

    # Check if comma counts are similar (CSV characteristic)
    comma_counts = [line.count(',') for line in comma_lines]
    if not comma_counts:
        return False

    avg_commas = sum(comma_counts) / len(comma_counts)
    consistent_count = sum(1 for count in comma_counts if abs(count - avg_commas) <= 1)

    return consistent_count >= len(comma_counts) * 0.8  # 80% consistency

def _is_readable_text(text: str) -> bool:
    """Check if text appears to be readable (not binary data decoded as text)."""
    if len(text) == 0:
        return False

    # Check for high ratio of printable characters
    printable_chars = sum(1 for char in text if char.isprintable() or char in '\n\r\t')
    printable_ratio = printable_chars / len(text)

    if printable_ratio < 0.8:  # At least 80% printable for text files
        return False

    # Check for excessive null bytes or control characters
    null_bytes = text.count('\x00')
    if null_bytes > 0:  # Text files shouldn't have null bytes
        return False

    # Check for excessive control characters (except common ones)
    control_chars = sum(1 for char in text if ord(char) < 32 and char not in '\n\r\t')
    if control_chars > len(text) * 0.02:  # More than 2% control characters
        return False

    return True

def _get_mime_type_from_extension(ext: str) -> str:
    """Extended mime type mapping for extensions."""
    extension_map = {
        # Text types
        '.txt': 'text/plain',
        '.md': 'text/markdown',
        '.html': 'text/html',
        '.htm': 'text/html',
        '.css': 'text/css',
        '.csv': 'text/csv',
        '.xml': 'text/xml',
        '.js': 'text/javascript',
        '.rtf': 'application/rtf',

        # Image types
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.png': 'image/png',
        '.gif': 'image/gif',
        '.svg': 'image/svg+xml',
        '.webp': 'image/webp',
        '.bmp': 'image/bmp',
        '.ico': 'image/x-icon',
        '.tiff': 'image/tiff',
        '.tif': 'image/tiff',

        # Audio types
        '.mp3': 'audio/mpeg',
        '.wav': 'audio/wav',
        '.ogg': 'audio/ogg',
        '.aac': 'audio/aac',

        # Video types
        '.mp4': 'video/mp4',
        '.webm': 'video/webm',
        '.mov': 'video/quicktime',
        '.avi': 'video/x-msvideo',

        # Document types
        '.pdf': 'application/pdf',
        '.doc': 'application/msword',
        '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        '.xls': 'application/vnd.ms-excel',
        '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        '.ppt': 'application/vnd.ms-powerpoint',
        '.pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
        '.odt': 'application/vnd.oasis.opendocument.text',
        '.ods': 'application/vnd.oasis.opendocument.spreadsheet',
        '.odp': 'application/vnd.oasis.opendocument.presentation',

        # Archive types
        '.zip': 'application/zip',
        '.epub': 'application/epub+zip',

        # Other
        '.json': 'application/json',
    }

    return extension_map.get(ext, 'application/octet-stream')
