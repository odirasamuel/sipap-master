"""
Example: Web Fetching for News Intelligence

Demonstrates the web_fetch function used by the News Agent to gather
real-time information about injuries, suspensions, and team news.

Usage:
    python examples/example_web_fetch.py
"""

import asyncio

from sipap.tools.function.web import web_fetch


async def main() -> None:
    """Demonstrate web_fetch functionality for news gathering."""
    print("=" * 80)
    print("SIPAP Web Fetch Example - News Intelligence")
    print("=" * 80)
    print()

    # Example 1: Fetch BBC Sport team news
    print("Example 1: Fetching Arsenal Team News from BBC Sport")
    print("-" * 80)

    result = await web_fetch(
        url="https://www.bbc.com/sport/football/teams/arsenal",
        query="injury news and team updates"
    )

    if result["status"] == "success":
        print(f"✅ Successfully fetched: {result['title']}")
        print(f"📄 Content length: {len(result['content'])} characters")
        print(f"📅 Published: {result['published'] or 'Not available'}")
        print()
        print("Preview (first 500 chars):")
        print(result["content"][:500] + "...")
    else:
        print(f"❌ Error: {result['error']}")

    print()
    print("=" * 80)
    print()

    # Example 2: Fetch Sky Sports fixture preview
    print("Example 2: Fetching Match Preview from Sky Sports")
    print("-" * 80)

    result = await web_fetch(
        url="https://www.skysports.com/football",
        query="premier league fixtures and team news"
    )

    if result["status"] == "success":
        print(f"✅ Successfully fetched: {result['title']}")
        print(f"📄 Content length: {len(result['content'])} characters")
        print()
        print("Preview (first 500 chars):")
        print(result["content"][:500] + "...")
    else:
        print(f"❌ Error: {result['error']}")

    print()
    print("=" * 80)
    print()

    # Example 3: Demonstrate error handling
    print("Example 3: Error Handling - Invalid URL")
    print("-" * 80)

    result = await web_fetch(
        url="https://this-site-does-not-exist-12345.com",
        query="news"
    )

    print(f"Status: {result['status']}")
    print(f"Error: {result['error']}")
    print()

    print("=" * 80)
    print()

    # Example 4: Real-world usage - Injury check
    print("Example 4: Real-World Usage - Checking for Injuries")
    print("-" * 80)

    # News Agent would search multiple sources
    sources = [
        {
            "name": "BBC Sport",
            "url": "https://www.bbc.com/sport/football",
            "query": "Manchester City injury news"
        },
        # {
        #     "name": "Official Club Site",
        #     "url": "https://www.mancity.com/news",
        #     "query": "team news and injuries"
        # }
    ]

    for source in sources:
        print(f"\nSearching {source['name']}...")
        result = await web_fetch(url=source["url"], query=source["query"])

        if result["status"] == "success":
            # Check for injury keywords
            injury_keywords = ["injured", "injury", "ruled out", "sidelined", "doubt"]
            found_injuries = [kw for kw in injury_keywords if kw in result["content"].lower()]

            if found_injuries:
                print(f"  🚨 Potential injury news found (keywords: {', '.join(found_injuries)})")
            else:
                print(f"  ✅ No injury news detected")
        else:
            print(f"  ❌ Could not fetch: {result['error']}")

    print()
    print("=" * 80)
    print()

    # Summary
    print("How the News Agent Uses web_fetch:")
    print("-" * 80)
    print("""
    1. Receives match context (e.g., "Arsenal vs Chelsea on 2026-08-10")

    2. Searches primary news sources:
       - BBC Sport: https://www.bbc.com/sport/football
       - Sky Sports: https://www.skysports.com/football
       - ESPN: https://www.espn.com/soccer/
       - Official club sites (e.g., arsenal.com/news)

    3. Extracts key information:
       - Injuries (star player out, severity, return date)
       - Suspensions (red cards, yellow card accumulation)
       - Manager issues (sacked, under pressure, new appointment)
       - Team morale (controversies, transfers, winning streaks)

    4. Quantifies impact:
       - Star player injury: -10% to -15%
       - Key suspension: -5% to -10%
       - Manager sacked: -8% to -12%
       - New manager bounce: +5% to +8%

    5. Returns structured news_items with:
       - category (injury, suspension, manager, morale, transfer)
       - severity (critical, major, minor)
       - impact (probability adjustment)
       - description (evidence-based detail)

    6. Adjusts ensemble probability:
       - Statistical Agent (40%) + Form Agent (40%) = Baseline
       - News Agent (20%) applies impact_score adjustment
       - Example: 65% baseline - 10% injury = 55% final prediction
    """)

    print()
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
