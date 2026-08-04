"""Web fetching functions for news and content extraction.

These are @tool decorated functions that agents can call to fetch web content.
"""

from typing import Any

import httpx
from bs4 import BeautifulSoup
from strands import tool


@tool
async def web_fetch(url: str, query: str) -> dict[str, Any]:  # noqa: C901
    """
    Fetch and extract content from a web page.

    Fetches HTML from the given URL and extracts clean text content,
    removing scripts, ads, navigation, and other non-content elements.

    Args:
        url: The URL to fetch (e.g., "https://www.bbc.com/sport/football/arsenal")
        query: What to extract - helps focus on relevant content
               (e.g., "injury news", "team news", "match preview")

    Returns:
        dict with:
            - url: The fetched URL
            - content: Cleaned article text
            - title: Page/article title
            - published: Publication date if available
            - status: "success" or "error"
            - error: Error message if status is "error"

    Example:
        >>> result = await web_fetch(
        ...     url="https://www.bbc.com/sport/football/arsenal",
        ...     query="injury news"
        ... )
        >>> print(result["content"])
        "Arsenal's star striker ruled out with injury..."
    """
    try:
        # Fetch the web page
        async with httpx.AsyncClient(follow_redirects=True) as client:
            try:
                response = await client.get(url, timeout=10.0)
                response.raise_for_status()
            except (httpx.TimeoutException, TimeoutError) as e:
                raise TimeoutError(f"Request timeout: {str(e)}") from e

            # Parse HTML
            soup = BeautifulSoup(response.text, 'html.parser')

            # Extract title
            title = ""
            if soup.title:
                title = soup.title.string or ""
            elif soup.find('h1'):
                h1_tag = soup.find('h1')
                title = h1_tag.get_text(strip=True) if h1_tag else ""

            # Extract publication date
            published = ""
            # Try meta tag first
            meta_time = soup.find('meta', property='article:published_time')
            if meta_time and isinstance(meta_time.get('content'), str):
                published = str(meta_time.get('content'))
            # Try time tag
            elif soup.find('time'):
                time_tag = soup.find('time')
                if time_tag and isinstance(time_tag.get('datetime'), str):
                    published = str(time_tag.get('datetime'))

            # Remove unwanted elements
            for element in soup(['script', 'style', 'nav', 'header', 'footer',
                                'aside', 'form', 'iframe', 'noscript']):
                element.decompose()

            # Extract main content
            # Try to find article/main content first
            content_container = (
                soup.find('article') or
                soup.find('main') or
                soup.find('div', class_=['article', 'content', 'story', 'post']) or
                soup.body
            )

            if content_container:
                # Get all paragraphs and headings
                content_parts = []
                for element in content_container.find_all(['p', 'h1', 'h2', 'h3', 'li']):
                    text = element.get_text(strip=True)
                    if text and len(text) > 20:  # Filter out short/empty elements
                        content_parts.append(text)

                content = "\n\n".join(content_parts)
            else:
                content = soup.get_text(strip=True)

            # Clean up excessive whitespace
            content = " ".join(content.split())

            return {
                "url": url,
                "content": content,
                "title": title.strip(),
                "published": published,
                "status": "success"
            }

    except TimeoutError as e:
        return {
            "url": url,
            "content": "",
            "title": "",
            "published": "",
            "status": "error",
            "error": f"Request timeout: {str(e)}"
        }

    except httpx.HTTPStatusError as e:
        return {
            "url": url,
            "content": "",
            "title": "",
            "published": "",
            "status": "error",
            "error": f"HTTP error {e.response.status_code}: {str(e)}"
        }

    except Exception as e:
        return {
            "url": url,
            "content": "",
            "title": "",
            "published": "",
            "status": "error",
            "error": f"Failed to fetch: {str(e)}"
        }
