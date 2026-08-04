"""Tests for web fetching functions."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from sipap.tools.function.web import web_fetch


@pytest.mark.asyncio
async def test_web_fetch_successful():
    """Test successful web page fetch."""
    mock_html = """
    <html>
        <head><title>Test Article</title></head>
        <body>
            <article>
                <h1>Arsenal Team News</h1>
                <p>Arsenal's star striker ruled out with injury.</p>
                <p>Manager confirms absence for upcoming match.</p>
            </article>
            <script>console.log('ads');</script>
            <nav>Navigation menu</nav>
        </body>
    </html>
    """

    with patch("sipap.tools.function.web.httpx.AsyncClient") as mock_client:
        mock_response = MagicMock()
        mock_response.text = mock_html
        mock_response.status_code = 200

        mock_client_instance = AsyncMock()
        mock_client_instance.get.return_value = mock_response
        mock_client_instance.__aenter__.return_value = mock_client_instance
        mock_client_instance.__aexit__.return_value = AsyncMock()
        mock_client.return_value = mock_client_instance

        result = await web_fetch(
            url="https://www.bbc.com/sport/football/arsenal",
            query="injury news"
        )

        assert result["url"] == "https://www.bbc.com/sport/football/arsenal"
        assert "content" in result
        assert "Arsenal" in result["content"]
        assert "injury" in result["content"]
        assert "script" not in result["content"].lower()  # Scripts removed
        assert result["status"] == "success"


@pytest.mark.asyncio
async def test_web_fetch_invalid_url():
    """Test web fetch with invalid URL."""
    # Test with truly invalid URL (no protocol)
    result = await web_fetch(
        url="not-a-valid-url",
        query="news"
    )

    assert result["status"] == "error"
    assert "error" in result
    assert result["content"] == ""


@pytest.mark.asyncio
async def test_web_fetch_nonexistent_domain():
    """Test web fetch with nonexistent domain."""
    # This will fail at DNS resolution
    result = await web_fetch(
        url="https://this-domain-definitely-does-not-exist-12345.com",
        query="news"
    )

    assert result["status"] == "error"
    assert "error" in result
    assert result["content"] == ""


@pytest.mark.asyncio
async def test_web_fetch_cleans_html():
    """Test that HTML is properly cleaned."""
    mock_html = """
    <html>
        <body>
            <article>
                <p>Important news content here.</p>
            </article>
            <script>malicious_code();</script>
            <style>.ads { display: block; }</style>
            <nav><a href="/menu">Menu</a></nav>
            <footer>Footer content</footer>
        </body>
    </html>
    """

    with patch("sipap.tools.function.web.httpx.AsyncClient") as mock_client:
        mock_response = MagicMock()
        mock_response.text = mock_html
        mock_response.status_code = 200

        mock_client_instance = AsyncMock()
        mock_client_instance.get.return_value = mock_response
        mock_client_instance.__aenter__.return_value = mock_client_instance
        mock_client_instance.__aexit__.return_value = AsyncMock()
        mock_client.return_value = mock_client_instance

        result = await web_fetch(
            url="https://example.com/article",
            query="news"
        )

        # Content should contain article text
        assert "Important news content" in result["content"]

        # Should NOT contain scripts, styles, or navigation
        assert "<script>" not in result["content"]
        assert "<style>" not in result["content"]
        assert "Menu" not in result["content"]  # Nav removed


@pytest.mark.asyncio
async def test_web_fetch_extracts_metadata():
    """Test that metadata (title, published date) is extracted."""
    mock_html = """
    <html>
        <head>
            <title>Arsenal vs Chelsea Preview - BBC Sport</title>
            <meta property="article:published_time" content="2026-08-04T10:30:00Z">
        </head>
        <body>
            <article>
                <h1>Match Preview</h1>
                <p>Arsenal prepare to face Chelsea.</p>
            </article>
        </body>
    </html>
    """

    with patch("sipap.tools.function.web.httpx.AsyncClient") as mock_client:
        mock_response = MagicMock()
        mock_response.text = mock_html
        mock_response.status_code = 200

        mock_client_instance = AsyncMock()
        mock_client_instance.get.return_value = mock_response
        mock_client_instance.__aenter__.return_value = mock_client_instance
        mock_client_instance.__aexit__.return_value = AsyncMock()
        mock_client.return_value = mock_client_instance

        result = await web_fetch(
            url="https://www.bbc.com/sport/article",
            query="preview"
        )

        assert "title" in result
        assert "Arsenal vs Chelsea" in result["title"]
        assert "published" in result
        # Should extract date if available
