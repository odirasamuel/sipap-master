"""Example 3: MCP Integration

Demonstrates MCP client usage and integration.

This example shows how to:
1. Create MCP clients using MCPFactory
2. Call MCP tools
3. Handle errors and retries
4. Check MCP server health

Usage:
    python examples/03_mcp_integration.py

Note: This example requires MCP servers to be running.
      For testing without servers, review the code to understand the patterns.
"""

import asyncio
import logging
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

# Add sipap to path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from sipap.factory.mcp import MCPFactory


async def main() -> None:
    """Run MCP integration example."""
    print("=" * 70)
    print("SIPAP Example 3: MCP Integration")
    print("=" * 70)
    print()

    # Initialize MCP factory
    print("Step 1: Initializing MCPFactory...")
    factory = MCPFactory()
    print(f"✓ Factory initialized for environment: {factory.environment}")
    print()

    # Get tool routing
    print("Step 2: Tool Routing Configuration")
    routing = factory.get_tool_routing()
    print(f"✓ {len(routing)} tools configured")

    # Display first 5 tools
    print("\nExample tool routes:")
    for i, (tool, server) in enumerate(list(routing.items())[:5]):
        print(f"  • {tool} → {server}")
    print()

    # Create MCP clients
    print("Step 3: Creating MCP Clients")
    try:
        data_mcp = factory.create("data")
        print(f"✓ Created data MCP client: {data_mcp.name}")
        print(f"  Base URL: {data_mcp.base_url}")
        print(f"  Timeout: {data_mcp.timeout}s")
        print(f"  Max Retries: {data_mcp.max_retries}")
        print()

        intelligence_mcp = factory.create("intelligence")
        print(f"✓ Created intelligence MCP client: {intelligence_mcp.name}")
        print(f"  Base URL: {intelligence_mcp.base_url}")
        print(f"  Timeout: {intelligence_mcp.timeout}s")
        print()

    except Exception as e:
        print(f"⚠️  Could not create MCP clients: {e}")
        print("   (This is expected if MCP servers are not running)")
        print()
        return

    # Health check
    print("Step 4: MCP Health Checks")
    try:
        health_status = await factory.health_check_all()

        for server, is_healthy in health_status.items():
            status = "✅ HEALTHY" if is_healthy else "❌ UNHEALTHY"
            print(f"  {server}: {status}")

        print()

    except Exception as e:
        print(f"⚠️  Health check failed: {e}")
        print("   (MCP servers may not be running)")
        print()

    # List tools
    print("Step 5: List Available Tools")
    try:
        tools = await data_mcp.list_tools()
        print(f"✓ Data MCP has {len(tools)} tools:")

        for tool in tools[:5]:  # Show first 5
            print(f"  • {tool.get('name')}: {tool.get('description', 'N/A')}")

        print()

    except Exception as e:
        print(f"⚠️  Failed to list tools: {e}")
        print("   (MCP server may not be running)")
        print()

    # Call a tool (example - will fail if server not running)
    print("Step 6: Example Tool Call (Mock)")
    print("   Attempting to call get_match_schedule...")
    print()

    try:
        result = await data_mcp.call_tool(
            "get_match_schedule",
            {"date": "2024-01-15"},
        )

        print("✓ Tool call successful!")
        print(f"  Result: {result}")
        print()

    except Exception as e:
        print(f"⚠️  Tool call failed: {e}")
        print("   (This is expected if MCP server is not running)")
        print()
        print("   To test MCP integration:")
        print("   1. Start sipap-data-mcp server")
        print("   2. Run this example again")
        print()

    # Cleanup
    print("Step 7: Cleanup")
    await factory.close_all()
    print("✓ Closed all MCP connections")
    print()

    print("=" * 70)
    print("MCP Integration Example Complete")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
