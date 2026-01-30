"""
Content extraction service for SeenIt backend
Extracts article title and body text from web pages using multiple strategies
"""

import re
import requests
from typing import Dict, Optional
from urllib.parse import urlparse
from html.parser import HTMLParser

#Maximum character length of an article
MAX_CHAR_LENGTH = 10000

#trying to import libraries which may not be installed
try:
    from readability import Document
    READABILITY_AVAILABLE = True
except ImportError:
    READABILITY_AVAILABLE = False
    print("Warning: readability-lxml not installed. Install with: pip install readability-lxml")

try:
    import trafilatura
    TRAFILATURA_AVAILABLE = True
except ImportError:
    TRAFILATURA_AVAILABLE = False
    print("Warning: trafilatura not installed. Install with: pip install trafilatura")


class SimpleHTMLParser(HTMLParser):
    """Simple HTML parser to extract text content"""
    def __init__(self):
        super().__init__()
        self.text_parts = []
        self.skip_tags = {'script', 'style', 'nav', 'header', 'footer', 'aside', 'noscript'}
        self.current_tag = None
        
    def handle_starttag(self, tag, attrs):
        self.current_tag = tag
        
    def handle_endtag(self, tag):
        self.current_tag = None
        
    def handle_data(self, data):
        if self.current_tag not in self.skip_tags:
            cleaned = data.strip()
            if cleaned:
                self.text_parts.append(cleaned)
    
    def get_text(self, max_length=10000):
        text = ' '.join(self.text_parts)
        # Normalize whitespace
        text = re.sub(r'\s+', ' ', text)
        return text[:max_length].strip()


def extract_with_readability(html_content: str, url: str) -> Optional[Dict[str, str]]:
    """Extract content using readability-lxml library"""
    if not READABILITY_AVAILABLE:
        return None
    
    try:
        doc = Document(html_content)
        title = doc.title()
        content = doc.summary()
        
        # Extract text from HTML content
        parser = SimpleHTMLParser()
        parser.feed(content)
        text = parser.get_text()
        
        if title and text:
            return {
                'title': title.strip(),
                'text': text
            }
    except Exception as e:
        print(f"Readability extraction failed: {e}")
    
    return None


def extract_with_trafilatura(html_content: str, url: str) -> Optional[Dict[str, str]]:
    """Extract content using trafilatura library"""
    if not TRAFILATURA_AVAILABLE:
        return None

    try:
        extracted = trafilatura.extract(
            html_content,
            include_comments=False,
            include_tables=False,
            favor_recall=True
        )

        if extracted:
            metadata = trafilatura.extract_metadata(html_content)
            title_text = metadata.title if metadata and metadata.title else ''

            return {
                'title': title_text.strip(),
                'text': extracted.strip()
            }
    except Exception as e:
        print(f"Trafilatura extraction failed: {e}")

    return None

def extract_with_simple_parser(html_content: str, url: str) -> Dict[str, str]:
    """Fallback: Simple HTML parsing"""
    parser = SimpleHTMLParser()
    parser.feed(html_content)
    text = parser.get_text()
    
    # Try to extract title from HTML
    title_match = re.search(r'<title[^>]*>(.*?)</title>', html_content, re.IGNORECASE | re.DOTALL)
    title = title_match.group(1).strip() if title_match else ''
    
    # Clean title (remove HTML entities and extra whitespace)
    title = re.sub(r'&[^;]+;', '', title)
    title = re.sub(r'\s+', ' ', title)
    title = title.replace(' - BBC News', '').replace(' - Reuters', '').strip()
    
    return {
        'title': title or 'Untitled',
        'text': text
    }


def extract_article_content(url: str, html_content: Optional[str] = None, 
                            timeout: int = 10) -> Dict[str, str]:
    """
    Extract article content from a URL
    
    Args:
        url: URL of the article
        html_content: Optional pre-fetched HTML content
        timeout: Request timeout in seconds
    
    Returns:
        Dictionary with 'title', 'text', 'url', 'domain', 'timestamp'
    """
    result = {
        'title': '',
        'text': '',
        'url': url,
        'domain': urlparse(url).netloc.replace('www.', ''),
        'timestamp': None
    }
    
    # Fetch HTML if not provided
    if html_content is None:
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            response = requests.get(url, headers=headers, timeout=timeout)
            response.raise_for_status()
            html_content = response.text
        except Exception as e:
            print(f"Failed to fetch URL {url}: {e}")
            return result
    
    # Try extraction methods in order of preference
    extracted = None
    
    # Method 1: Trafilatura (best for news articles)
    if TRAFILATURA_AVAILABLE:
        extracted = extract_with_trafilatura(html_content, url)
    
    # Method 2: Readability
    if not extracted and READABILITY_AVAILABLE:
        extracted = extract_with_readability(html_content, url)
    
    # Method 3: Simple parser (fallback)
    if not extracted:
        extracted = extract_with_simple_parser(html_content, url)
    
    if extracted:
        result['title'] = extracted.get('title', '').strip()
        result['text'] = extracted.get('text', '').strip()[:MAX_CHAR_LENGTH]
        result['timestamp'] = __import__('datetime').datetime.utcnow().isoformat() + 'Z'
    
    return result


def extract_from_html_file(file_path: str, url: str = '') -> Dict[str, str]:
    """Extract content from a local HTML file"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            html_content = f.read()
        return extract_article_content(url or f'file://{file_path}', html_content)
    except Exception as e:
        print(f"Failed to read file {file_path}: {e}")
        return {
            'title': '',
            'text': '',
            'url': url or file_path,
            'domain': '',
            'timestamp': None
        }


if __name__ == '__main__':
    # Test extraction
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python extract_content.py <url>")
        sys.exit(1)
    
    url = sys.argv[1]
    print(f"Extracting content from: {url}")
    
    result = extract_article_content(url)
    
    print("\n" + "="*50)
    print("TITLE:")
    print(result['title'])
    print("\n" + "="*50)
    print(f"TEXT ({len(result['text'])} characters):")
    print(result['text'][:500] + "..." if len(result['text']) > 500 else result['text'])
    print("\n" + "="*50)
