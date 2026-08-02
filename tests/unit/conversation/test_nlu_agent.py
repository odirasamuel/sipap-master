"""Unit tests for NLU Agent.

Tests the Claude-based natural language understanding agent that parses
WhatsApp user messages into structured RequestIntent objects.

Following TDD methodology - these tests are written BEFORE implementation.
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from sipap.conversation.nlu_agent import NLUAgent, RequestIntent


class TestRequestIntentModel:
    """Test the RequestIntent Pydantic model."""

    def test_batch_prediction_intent_creation(self):
        """Test creating a batch_prediction intent with accumulated odds."""
        intent = RequestIntent(
            intent_type="batch_prediction",
            confidence=0.9,
            target_odds=20.0,
            accumulation_mode=True,
            quality_threshold="highest",
            sort_by="ev",
            original_query="I need 20 odds with highest positive outcome",
            extracted_entities={
                "target_odds": 20.0,
                "accumulation_mode": True,
                "quality_terms": ["highest", "positive outcome"],
            },
        )

        assert intent.intent_type == "batch_prediction"
        assert intent.confidence == 0.9
        assert intent.target_odds == 20.0
        assert intent.accumulation_mode is True
        assert intent.quality_threshold == "highest"
        assert intent.sort_by == "ev"

    def test_single_prediction_intent_creation(self):
        """Test creating a single_prediction intent."""
        intent = RequestIntent(
            intent_type="single_prediction",
            confidence=0.95,
            home_team="Arsenal",
            away_team="Chelsea",
            markets=["1X2"],
            original_query="What do you think about Arsenal vs Chelsea",
            extracted_entities={
                "home_team": "Arsenal",
                "away_team": "Chelsea",
            },
        )

        assert intent.intent_type == "single_prediction"
        assert intent.home_team == "Arsenal"
        assert intent.away_team == "Chelsea"
        assert intent.markets == ["1X2"]

    def test_track_results_intent_creation(self):
        """Test creating a track_results intent."""
        intent = RequestIntent(
            intent_type="track_results",
            confidence=0.85,
            original_query="Any updates on your selections?",
            extracted_entities={},
        )

        assert intent.intent_type == "track_results"
        assert intent.confidence == 0.85


class TestNLUAgentRealUserMessages:
    """Test NLU agent with 15 real user messages from sample-user-messages.md."""

    @pytest.fixture
    def nlu_agent(self):
        """Create NLU agent instance for testing."""
        logger = MagicMock()
        return NLUAgent(logger=logger)

    @pytest.mark.asyncio
    async def test_message_1_batch_20_odds_highest_positive(self, nlu_agent):
        """Test: 'I need 20 odds of matches with highest positive or success outcome'

        Business Logic: "20 odds" = accumulated odds target (sum of bookmaker odds >= 20)
        """
        message = "I need 20 odds of matches with highest positive or success outcome"

        intent = await nlu_agent.parse_user_message(message)

        assert intent.intent_type == "batch_prediction"
        assert intent.target_odds == 20.0  # Accumulated odds target
        assert intent.accumulation_mode is True
        assert intent.quality_threshold == "highest"
        assert intent.confidence >= 0.7
        # Should default to "ev" for sorting
        assert intent.sort_by == "ev"

    @pytest.mark.asyncio
    async def test_message_2_sure_30_odds_all_sports(self, nlu_agent):
        """Test: 'Can i get sure 30 odds in the world of sports'"""
        message = "Can i get sure 30 odds in the world of sports"

        intent = await nlu_agent.parse_user_message(message)

        assert intent.intent_type == "batch_prediction"
        assert intent.target_odds == 30.0
        assert intent.accumulation_mode is True
        assert intent.quality_threshold in ["highest", "high"]  # "sure" indicates high quality
        assert intent.confidence >= 0.7

    @pytest.mark.asyncio
    async def test_message_3_multiple_leagues_today(self, nlu_agent):
        """Test: 'Best possible outcome for today matches in Premier league, LaLiga, Bundesliga...'"""
        message = "I need the best posible outcome for today matches in the following leagues; Premier league, LaLiga, Bundesliga, Scotish, Netherlands, Portugal, Belgium, Turkey."

        intent = await nlu_agent.parse_user_message(message)

        assert intent.intent_type == "batch_prediction"
        assert intent.leagues is not None
        assert "Premier League" in intent.leagues or "EPL" in str(intent.leagues)
        assert "LaLiga" in intent.leagues or "La Liga" in str(intent.leagues)
        assert "Bundesliga" in intent.leagues
        # Should extract date as today
        assert intent.date_range is not None
        assert intent.confidence >= 0.7

    @pytest.mark.asyncio
    async def test_message_4_sure_30_odds_football(self, nlu_agent):
        """Test: 'Can i get sure 30 odds in the world of Football'"""
        message = "Can i get sure 30 odds in the world of Footbal"

        intent = await nlu_agent.parse_user_message(message)

        assert intent.intent_type == "batch_prediction"
        assert intent.target_odds == 30.0
        assert intent.accumulation_mode is True
        assert intent.quality_threshold in ["highest", "high"]
        assert intent.confidence >= 0.7

    @pytest.mark.asyncio
    async def test_message_5_date_range_august_3_to_10(self, nlu_agent):
        """Test: 'Compile best possible matches within 3rd-10th August, 2026'"""
        message = "Compile best possible matches selection with highest suucess outcome within 3rd of August, 2026 to 10th of August, 2026."

        intent = await nlu_agent.parse_user_message(message)

        assert intent.intent_type == "batch_prediction"
        assert intent.date_range is not None
        assert "start" in intent.date_range
        assert "end" in intent.date_range
        # Should parse to 2026-08-03 and 2026-08-10
        assert "2026-08-03" in intent.date_range["start"]
        assert "2026-08-10" in intent.date_range["end"]
        assert intent.quality_threshold in ["highest", "high"]
        assert intent.confidence >= 0.7

    @pytest.mark.asyncio
    async def test_message_6_sure_50_odds_date_range(self, nlu_agent):
        """Test: 'Can i get sure 50 odds between 7/3/2026 - 7/10/2026?'"""
        message = "Can i get sure 50 odds of matches between 7/3/2026 - 7/10/2026?"

        intent = await nlu_agent.parse_user_message(message)

        assert intent.intent_type == "batch_prediction"
        assert intent.target_odds == 50.0  # No need to cap at 30 for accumulated odds
        assert intent.accumulation_mode is True
        assert intent.date_range is not None
        assert intent.quality_threshold in ["highest", "high"]
        assert intent.confidence >= 0.7

    @pytest.mark.asyncio
    async def test_message_7_10_sure_odds_all_sports(self, nlu_agent):
        """Test: 'Across all sports, pick out selections of 10 sure odds'"""
        message = "Across all sports, pick out selections of 10 sure odds."

        intent = await nlu_agent.parse_user_message(message)

        assert intent.intent_type == "batch_prediction"
        assert intent.target_odds == 10.0
        assert intent.accumulation_mode is True
        assert intent.quality_threshold in ["highest", "high"]
        assert intent.confidence >= 0.7

    @pytest.mark.asyncio
    async def test_message_8_best_selections_today(self, nlu_agent):
        """Test: 'What are the best possible selections to go for today?'"""
        message = "What are the best possible selections to go for today?"

        intent = await nlu_agent.parse_user_message(message)

        assert intent.intent_type == "batch_prediction"
        # "best selections" without explicit number - target_odds may be None or default
        if intent.target_odds:
            assert intent.target_odds >= 1.0
            assert intent.accumulation_mode is True
        assert intent.date_range is not None  # Should extract "today"
        assert intent.quality_threshold in ["high", "highest"]
        assert intent.confidence >= 0.7

    @pytest.mark.asyncio
    async def test_message_9_fixtures_top_leagues_weekend(self, nlu_agent):
        """Test: 'What are the available matches in the top leagues this weekend?'"""
        message = "What are the available matches in the top leagues this weekeend?"

        intent = await nlu_agent.parse_user_message(message)

        # Could be batch_prediction or show_fixtures - both acceptable
        assert intent.intent_type in ["batch_prediction", "show_fixtures"]
        if intent.date_range:
            # Should extract weekend dates
            assert "start" in intent.date_range
            assert "end" in intent.date_range
        assert intent.confidence >= 0.7

    @pytest.mark.asyncio
    async def test_message_10_fixtures_today(self, nlu_agent):
        """Test: 'What are the fixtures available today?'"""
        message = "What are the fixtures available today?"

        intent = await nlu_agent.parse_user_message(message)

        # Could be batch_prediction or show_fixtures
        assert intent.intent_type in ["batch_prediction", "show_fixtures"]
        assert intent.date_range is not None
        assert intent.confidence >= 0.7

    @pytest.mark.asyncio
    async def test_message_11_30_sure_odds_today(self, nlu_agent):
        """Test: '1 need 30 sure odds today'"""
        message = "1 need 30 sure odds today."

        intent = await nlu_agent.parse_user_message(message)

        assert intent.intent_type == "batch_prediction"
        assert intent.target_odds == 30.0
        assert intent.accumulation_mode is True
        assert intent.quality_threshold in ["highest", "high"]
        assert intent.date_range is not None
        assert intent.confidence >= 0.7

    @pytest.mark.asyncio
    async def test_message_12_track_results_updates(self, nlu_agent):
        """Test: 'Any updates on the results of your suggested selections?'"""
        message = "Any updates on the results of your suggested selections?"

        intent = await nlu_agent.parse_user_message(message)

        assert intent.intent_type == "track_results"
        assert intent.confidence >= 0.7

    @pytest.mark.asyncio
    async def test_message_13_track_results_wrong_predictions(self, nlu_agent):
        """Test: 'What do you think happened with the wrong predictions?'"""
        message = "What do you think happened with the wrong predictions?"

        intent = await nlu_agent.parse_user_message(message)

        assert intent.intent_type == "track_results"
        assert intent.confidence >= 0.7

    @pytest.mark.asyncio
    async def test_message_14_single_multiple_fixtures(self, nlu_agent):
        """Test: 'What do you think about Man Utd vs Chelsea, Real Madrid vs Atletico...'"""
        message = "What do you think about these fixtures/games, and what are your predictions; Man Utd vs Chelsea, Real Madrid vs Atletico Madrid, AZ Akmaar vs Ajax, Benfica vs Porto, Galatasaray vs Fernabache, Brighton vs Ipswich, Napoli vs Roma."

        intent = await nlu_agent.parse_user_message(message)

        # Could parse as batch_prediction (multiple matches) or single_prediction (first match)
        assert intent.intent_type in ["batch_prediction", "single_prediction"]
        if intent.intent_type == "single_prediction":
            # Should extract at least first match
            assert intent.home_team is not None
            assert intent.away_team is not None
        assert intent.confidence >= 0.7

    @pytest.mark.asyncio
    async def test_message_15_10_matches_very_high_success(self, nlu_agent):
        """Test: 'Give me 10 matches today with very high success chance'"""
        message = "Give me 10 matches today with prediction that has a very high success chance of being correct."

        intent = await nlu_agent.parse_user_message(message)

        assert intent.intent_type == "batch_prediction"
        assert intent.target_odds == 10.0
        assert intent.accumulation_mode is True
        assert intent.quality_threshold == "highest"  # "very high success chance"
        assert intent.date_range is not None
        assert intent.confidence >= 0.7


class TestNLUAgentFallback:
    """Test fallback behavior from Claude to regex parser."""

    @pytest.fixture
    def nlu_agent(self):
        """Create NLU agent instance for testing."""
        logger = MagicMock()
        return NLUAgent(logger=logger)

    @pytest.mark.asyncio
    async def test_claude_failure_falls_back_to_regex(self, nlu_agent):
        """Test that Claude failure triggers regex fallback."""
        message = "Show me Arsenal vs Chelsea prediction"

        # Mock Claude to fail
        with patch.object(
            nlu_agent, "_parse_with_claude", side_effect=Exception("Claude API error")
        ):
            intent = await nlu_agent.parse_user_message(message)

        # Should still parse via regex fallback
        assert intent.intent_type in ["single_prediction", "get_prediction"]
        assert intent.confidence > 0  # Regex should have some confidence

    @pytest.mark.asyncio
    async def test_low_confidence_tries_regex(self, nlu_agent):
        """Test that low Claude confidence triggers regex fallback."""
        message = "Show me Arsenal vs Chelsea prediction"

        # Mock Claude to return low confidence
        low_confidence_intent = RequestIntent(
            intent_type="unknown",
            confidence=0.3,
            original_query=message,
            extracted_entities={},
        )

        with patch.object(
            nlu_agent, "_parse_with_claude", return_value=low_confidence_intent
        ):
            intent = await nlu_agent.parse_user_message(message)

        # Should try regex fallback due to low confidence
        # Regex should parse this better than "unknown"
        assert intent.confidence >= 0.3  # Should be at least as good as Claude


class TestNLUAgentContextResolution:
    """Test conversation context resolution."""

    @pytest.fixture
    def nlu_agent(self):
        """Create NLU agent instance for testing."""
        logger = MagicMock()
        return NLUAgent(logger=logger)

    @pytest.mark.asyncio
    async def test_context_fills_missing_teams(self, nlu_agent):
        """Test that conversation context fills in missing team names."""
        message = "How about tomorrow?"
        context = {
            "last_home_team": "Arsenal",
            "last_away_team": "Chelsea",
        }

        intent = await nlu_agent.parse_user_message(message, conversation_context=context)

        # Should use teams from context
        if intent.home_team:
            assert intent.home_team == "Arsenal"
        if intent.away_team:
            assert intent.away_team == "Chelsea"
        # Should extract date
        assert intent.date_range is not None

    @pytest.mark.asyncio
    async def test_explicit_teams_override_context(self, nlu_agent):
        """Test that explicit teams override conversation context."""
        message = "What about Liverpool vs Manchester United?"
        context = {
            "last_home_team": "Arsenal",
            "last_away_team": "Chelsea",
        }

        intent = await nlu_agent.parse_user_message(message, conversation_context=context)

        # Should use teams from message, not context
        if intent.home_team:
            assert intent.home_team in ["Liverpool", "Man United", "Manchester United"]


class TestNLUAgentLeagueMapping:
    """Test league name recognition and mapping."""

    @pytest.fixture
    def nlu_agent(self):
        """Create NLU agent instance for testing."""
        logger = MagicMock()
        return NLUAgent(logger=logger)

    @pytest.mark.asyncio
    async def test_premier_league_variations(self, nlu_agent):
        """Test various ways of mentioning Premier League."""
        messages = [
            "Show me Premier League matches",
            "Give me EPL fixtures",
            "What about English league matches",
        ]

        for message in messages:
            intent = await nlu_agent.parse_user_message(message)
            if intent.leagues:
                # Should map to standard "Premier League"
                assert any("Premier" in league or "EPL" in league for league in intent.leagues)

    @pytest.mark.asyncio
    async def test_laliga_variations(self, nlu_agent):
        """Test various ways of mentioning LaLiga."""
        messages = [
            "Show me LaLiga matches",
            "Give me La Liga fixtures",
            "What about Spanish league",
        ]

        for message in messages:
            intent = await nlu_agent.parse_user_message(message)
            if intent.leagues:
                assert any("LaLiga" in league or "Liga" in league or "Spanish" in league for league in intent.leagues)


class TestNLUAgentDateParsing:
    """Test temporal reference parsing."""

    @pytest.fixture
    def nlu_agent(self):
        """Create NLU agent instance for testing."""
        logger = MagicMock()
        return NLUAgent(logger=logger)

    @pytest.mark.asyncio
    async def test_today_parsing(self, nlu_agent):
        """Test parsing 'today' to current date."""
        message = "Give me matches today"

        intent = await nlu_agent.parse_user_message(message)

        assert intent.date_range is not None
        # Should be today's date
        today = datetime.now().date().isoformat()
        if "start" in intent.date_range:
            assert intent.date_range["start"] == today

    @pytest.mark.asyncio
    async def test_tomorrow_parsing(self, nlu_agent):
        """Test parsing 'tomorrow' to next day."""
        message = "Give me matches tomorrow"

        intent = await nlu_agent.parse_user_message(message)

        assert intent.date_range is not None
        tomorrow = (datetime.now() + timedelta(days=1)).date().isoformat()
        if "start" in intent.date_range:
            assert intent.date_range["start"] == tomorrow

    @pytest.mark.asyncio
    async def test_explicit_date_parsing(self, nlu_agent):
        """Test parsing explicit dates like '3rd of August, 2026'."""
        message = "Matches on 3rd of August, 2026"

        intent = await nlu_agent.parse_user_message(message)

        if intent.date_range:
            # Should extract 2026-08-03
            date_str = intent.date_range.get("start", "")
            assert "2026-08-03" in date_str or "August" in str(intent.extracted_entities)


class TestNLUAgentQualityThresholds:
    """Test quality threshold mapping."""

    @pytest.fixture
    def nlu_agent(self):
        """Create NLU agent instance for testing."""
        logger = MagicMock()
        return NLUAgent(logger=logger)

    @pytest.mark.asyncio
    async def test_highest_quality_terms(self, nlu_agent):
        """Test that 'sure', 'highest positive' map to 'highest' threshold."""
        messages = [
            "Give me sure odds",
            "I need highest positive outcome",
            "Very high success chance",
        ]

        for message in messages:
            intent = await nlu_agent.parse_user_message(message)
            if intent.quality_threshold:
                assert intent.quality_threshold in ["highest", "high"]

    @pytest.mark.asyncio
    async def test_high_quality_terms(self, nlu_agent):
        """Test that 'best possible', 'good chance' map to 'high' threshold."""
        messages = [
            "Give me best possible matches",
            "I need good chance selections",
        ]

        for message in messages:
            intent = await nlu_agent.parse_user_message(message)
            if intent.quality_threshold:
                assert intent.quality_threshold in ["high", "highest"]

    @pytest.mark.asyncio
    async def test_default_quality_threshold(self, nlu_agent):
        """Test default quality threshold when not specified."""
        message = "Give me 10 matches today"

        intent = await nlu_agent.parse_user_message(message)

        # Should default to "high" or None (will use system default)
        assert intent.quality_threshold in ["high", "highest", None]
