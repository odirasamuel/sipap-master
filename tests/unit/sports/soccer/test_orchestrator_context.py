"""Unit tests for SoccerOrchestrator context aggregation.

Tests verify that orchestrator calls correct MCP servers with correct
tool names and parameters for injuries and lineups.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from sipap.sports.soccer.orchestrator import SoccerOrchestrator


class TestContextAggregationMCPRouting:
    """Test that context aggregation calls correct MCP tools."""

    @pytest.mark.asyncio
    async def test_aggregate_context_calls_correct_mcp_tools(self):
        """Verify context aggregation calls correct MCP servers and tools."""

        # Setup orchestrator
        orchestrator = SoccerOrchestrator()

        # Mock MCP clients
        data_mcp = AsyncMock()
        intelligence_mcp = AsyncMock()

        # Mock MCPFactory to return our mock clients
        orchestrator.mcp_factory.create = MagicMock(
            side_effect=lambda name: data_mcp if name == "data" else intelligence_mcp
        )

        # Mock match details response from get_match_details
        data_mcp.call_tool.return_value = {
            "match": {
                "home_team_id": 100,
                "away_team_id": 200,
                "home_team": {"name": "Arsenal"},
                "away_team": {"name": "Chelsea"},
                "scheduled_at": "2024-08-15T19:00:00Z",
            }
        }

        # Execute
        await orchestrator.aggregate_context("12345")

        # Verify data_mcp.call_tool was called with correct arguments
        calls = data_mcp.call_tool.call_args_list
        tool_names = [call_obj[0][0] for call_obj in calls]

        # Assert injuries and lineups called on data MCP (not intelligence)
        assert "get_injuries" in tool_names, "get_injuries should be called on data MCP"
        assert "get_lineups" in tool_names, "get_lineups should be called on data MCP"

        # Assert called with fixture_id (not team_id)
        injuries_call = [c for c in calls if c[0][0] == "get_injuries"][0]
        assert injuries_call[0][1] == {"fixture_id": 12345}, \
            "get_injuries should be called with fixture_id as int"

        lineups_call = [c for c in calls if c[0][0] == "get_lineups"][0]
        assert lineups_call[0][1] == {"fixture_id": 12345}, \
            "get_lineups should be called with fixture_id as int"

        # Assert NOT called on intelligence MCP
        intelligence_calls = intelligence_mcp.call_tool.call_args_list
        intelligence_tool_names = [call_obj[0][0] for call_obj in intelligence_calls]
        assert "get_injury_reports" not in intelligence_tool_names, \
            "get_injury_reports is wrong tool name (should be get_injuries)"
        assert "get_injuries" not in intelligence_tool_names, \
            "get_injuries should not be called on intelligence MCP"
        assert "get_lineups" not in intelligence_tool_names, \
            "get_lineups should not be called on intelligence MCP"

    @pytest.mark.asyncio
    async def test_context_structure_has_injuries_and_lineups(self):
        """Verify context includes injuries and lineups at top level."""

        # Setup orchestrator
        orchestrator = SoccerOrchestrator()

        # Mock MCP clients
        data_mcp = AsyncMock()
        intelligence_mcp = AsyncMock()

        orchestrator.mcp_factory.create = MagicMock(
            side_effect=lambda name: data_mcp if name == "data" else intelligence_mcp
        )

        # Mock responses
        def data_mcp_side_effect(tool_name, params):
            if tool_name == "get_match_details":
                return {
                    "match": {
                        "home_team_id": 100,
                        "away_team_id": 200,
                        "home_team": {"name": "Arsenal"},
                        "away_team": {"name": "Chelsea"},
                        "scheduled_at": "2024-08-15T19:00:00Z",
                    }
                }
            elif tool_name == "get_injuries":
                return {
                    "injuries": [
                        {
                            "player_id": 1,
                            "player_name": "Player 1",
                            "team_id": 100,
                            "injury_type": "Muscle",
                        }
                    ]
                }
            elif tool_name == "get_lineups":
                return {
                    "lineups": {
                        "fixture_id": 12345,
                        "home_team_lineup": {"formation": "4-3-3"},
                        "away_team_lineup": {"formation": "4-2-3-1"},
                    }
                }
            else:
                return {}

        data_mcp.call_tool.side_effect = data_mcp_side_effect

        # Execute
        context = await orchestrator.aggregate_context("12345")

        # Verify structure
        assert "injuries" in context, "Context should have top-level 'injuries' key"
        assert "lineups" in context, "Context should have top-level 'lineups' key"

        # Verify injuries NOT in team-level (old structure)
        assert "injuries" not in context.get("home_team", {}), \
            "Injuries should not be in home_team (moved to top level)"
        assert "injuries" not in context.get("away_team", {}), \
            "Injuries should not be in away_team (moved to top level)"

        # Verify data structure
        assert context["injuries"]["injuries"][0]["player_name"] == "Player 1"
        assert context["lineups"]["lineups"]["fixture_id"] == 12345

    @pytest.mark.asyncio
    async def test_validate_context_quality_checks_injuries_and_lineups(self):
        """Verify context validation includes injuries and lineups as optional fields."""

        orchestrator = SoccerOrchestrator()

        # Context with all fields
        complete_context = {
            "fixture": {},
            "odds": {},
            "home_team": {"stats": {}, "form": {}},
            "away_team": {"stats": {}, "form": {}},
            "head_to_head": {},
            "weather": {},
            "injuries": {},
            "lineups": {},
        }

        result = orchestrator.validate_context_quality(complete_context)

        assert result["status"] == "PASSED"
        assert result["data_completeness"] == 100.0

        # Context missing injuries and lineups
        partial_context = {
            "fixture": {},
            "odds": {},
            "home_team": {"stats": {}, "form": {}},
            "away_team": {"stats": {}, "form": {}},
            "head_to_head": {},
            "weather": {},
            "injuries": None,
            "lineups": None,
        }

        result = orchestrator.validate_context_quality(partial_context)

        # Should still pass (injuries/lineups are optional)
        # Data completeness should be 80% (8/10 fields)
        assert result["status"] == "PASSED"
        assert result["data_completeness"] == 80.0
        assert "injuries" in result["missing_optional"]
        assert "lineups" in result["missing_optional"]

    @pytest.mark.asyncio
    async def test_graceful_degradation_when_injuries_lineups_fail(self):
        """Verify orchestrator handles injuries/lineups MCP failures gracefully."""

        orchestrator = SoccerOrchestrator()

        # Mock MCP clients
        data_mcp = AsyncMock()
        intelligence_mcp = AsyncMock()

        orchestrator.mcp_factory.create = MagicMock(
            side_effect=lambda name: data_mcp if name == "data" else intelligence_mcp
        )

        # Mock responses - injuries and lineups return exceptions
        def data_mcp_side_effect(tool_name, params):
            if tool_name == "get_match_details":
                return {
                    "match": {
                        "home_team_id": 100,
                        "away_team_id": 200,
                        "home_team": {"name": "Arsenal"},
                        "away_team": {"name": "Chelsea"},
                        "scheduled_at": "2024-08-15T19:00:00Z",
                    }
                }
            elif tool_name == "get_injuries":
                return Exception("Injuries MCP failed")
            elif tool_name == "get_lineups":
                return Exception("Lineups MCP failed")
            else:
                return {}

        data_mcp.call_tool.side_effect = data_mcp_side_effect

        # Execute - should not raise exception
        context = await orchestrator.aggregate_context("12345")

        # Verify injuries and lineups are None (graceful degradation)
        assert context["injuries"] is None, \
            "Injuries should be None when MCP call fails"
        assert context["lineups"] is None, \
            "Lineups should be None when MCP call fails"

        # Verify context validation still works
        result = orchestrator.validate_context_quality(context)
        # Should pass if critical fields present (fixture, odds, stats)
        # May fail if overall completeness < 70%, but should not crash
        assert result["status"] in ["PASSED", "FAILED"]
        assert "injuries" in result["missing_optional"]
        assert "lineups" in result["missing_optional"]


class TestContextAggregationParameters:
    """Test parameter conversion for MCP tool calls."""

    @pytest.mark.asyncio
    async def test_match_id_converted_to_integer_for_fixture_id(self):
        """Verify match_id string is converted to int for fixture_id parameter."""

        orchestrator = SoccerOrchestrator()

        # Mock MCP clients
        data_mcp = AsyncMock()
        intelligence_mcp = AsyncMock()

        orchestrator.mcp_factory.create = MagicMock(
            side_effect=lambda name: data_mcp if name == "data" else intelligence_mcp
        )

        # Mock match details
        data_mcp.call_tool.return_value = {
            "match": {
                "home_team_id": 100,
                "away_team_id": 200,
                "home_team": {"name": "Arsenal"},
                "away_team": {"name": "Chelsea"},
                "scheduled_at": "2024-08-15T19:00:00Z",
            }
        }

        # Execute with string match_id
        await orchestrator.aggregate_context("12345")

        # Verify integer conversion
        calls = data_mcp.call_tool.call_args_list
        injuries_call = [c for c in calls if c[0][0] == "get_injuries"][0]
        lineups_call = [c for c in calls if c[0][0] == "get_lineups"][0]

        # Assert fixture_id is integer
        assert injuries_call[0][1]["fixture_id"] == 12345
        assert isinstance(injuries_call[0][1]["fixture_id"], int)

        assert lineups_call[0][1]["fixture_id"] == 12345
        assert isinstance(lineups_call[0][1]["fixture_id"], int)
