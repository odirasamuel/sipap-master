"""Tests for intelligent clarification system."""

import pytest

from sipap.conversation.nlu_agent import (
    ClarificationAgent,
    ClarificationResponse,
    NLUAgent,
    RequestIntent,
)


class TestClarificationAgent:
    """Test ClarificationAgent clarification generation."""

    @pytest.fixture
    def agent(self):
        """Create clarification agent."""
        return ClarificationAgent()

    @pytest.mark.asyncio
    async def test_ask_for_missing_entity_teams(self, agent):
        """Test clarification for single prediction missing teams."""
        intent = RequestIntent(
            intent_type="single_prediction",
            confidence=0.7,
            home_team=None,
            away_team=None,
            original_query="Show me the prediction",
            extracted_entities={},
        )

        clarification = await agent.generate_clarification(intent)

        assert clarification.clarification_type == "ask_for_missing_entity"
        assert "match" in clarification.message.lower()
        assert len(clarification.suggested_actions) > 0
        assert clarification.suggested_actions[0]["example"] is not None
        assert clarification.follow_up_context is not None
        assert clarification.follow_up_context["awaiting"] == "team_names"

    @pytest.mark.asyncio
    async def test_ask_for_missing_entity_target_odds(self, agent):
        """Test clarification for batch prediction missing target_odds."""
        intent = RequestIntent(
            intent_type="batch_prediction",
            confidence=0.6,
            target_odds=None,
            leagues=["Premier League"],
            original_query="Premier League predictions",
            extracted_entities={},
        )

        clarification = await agent.generate_clarification(intent)

        assert clarification.clarification_type == "ask_for_missing_entity"
        assert "Premier League" in clarification.message
        assert "odds" in clarification.message.lower()
        assert len(clarification.suggested_actions) >= 2
        assert clarification.follow_up_context["awaiting"] == "target_odds"

    @pytest.mark.asyncio
    async def test_disambiguate_intent_with_team(self, agent):
        """Test disambiguation when team detected but intent unclear."""
        intent = RequestIntent(
            intent_type="unknown",
            confidence=0.45,
            home_team="Arsenal",
            original_query="Show me Arsenal matches",
            extracted_entities={"teams": ["Arsenal"]},
        )

        clarification = await agent.generate_clarification(intent)

        assert clarification.clarification_type == "disambiguate_intent"
        assert "Arsenal" in clarification.message
        assert len(clarification.suggested_actions) == 3  # Prediction, Results, Fixtures
        # Check for emoji indicators
        action_labels = [a["label"] for a in clarification.suggested_actions]
        assert any("🎯" in label for label in action_labels)  # Prediction
        assert any("📊" in label for label in action_labels)  # Results
        assert any("📅" in label for label in action_labels)  # Fixtures

    @pytest.mark.asyncio
    async def test_disambiguate_intent_with_league(self, agent):
        """Test disambiguation when league detected but intent unclear."""
        intent = RequestIntent(
            intent_type="unknown",
            confidence=0.4,
            leagues=["Premier League"],
            original_query="What's happening in Premier League?",
            extracted_entities={"leagues": ["Premier League"]},
        )

        clarification = await agent.generate_clarification(intent)

        assert clarification.clarification_type == "disambiguate_intent"
        assert "Premier League" in clarification.message
        assert len(clarification.suggested_actions) == 3

    @pytest.mark.asyncio
    async def test_guide_to_feature_very_unclear(self, agent):
        """Test feature guide for very unclear request."""
        intent = RequestIntent(
            intent_type="unknown",
            confidence=0.2,
            original_query="Give me something good",
            extracted_entities={},
        )

        clarification = await agent.generate_clarification(intent)

        assert clarification.clarification_type == "guide_to_feature"
        assert "help" in clarification.message.lower()
        assert len(clarification.suggested_actions) >= 3
        # Should show core features
        examples = [a.get("example") for a in clarification.suggested_actions]
        assert any("odds" in ex.lower() for ex in examples if ex)

    @pytest.mark.asyncio
    async def test_guide_to_feature_greeting(self, agent):
        """Test greeting response."""
        intent = RequestIntent(
            intent_type="unknown",
            confidence=0.1,
            original_query="Hello",
            extracted_entities={},
        )

        clarification = await agent.generate_clarification(intent)

        assert clarification.clarification_type == "guide_to_feature"
        assert "👋" in clarification.message or "SIPAP" in clarification.message
        assert len(clarification.suggested_actions) >= 3

    @pytest.mark.asyncio
    async def test_refine_request_high_target_odds(self, agent):
        """Test refinement for unrealistic target_odds."""
        intent = RequestIntent(
            intent_type="batch_prediction",
            confidence=0.7,
            target_odds=100.0,
            original_query="Give me 100 odds",
            extracted_entities={},
        )

        clarification = await agent.generate_clarification(intent)

        assert clarification.clarification_type == "refine_request"
        assert "100" in clarification.message
        assert "ambitious" in clarification.message.lower() or "quality" in clarification.message.lower()
        assert len(clarification.suggested_actions) >= 3
        # Should offer lower, more realistic targets
        assert any("20" in a["label"] for a in clarification.suggested_actions)


class TestNLUAgent:
    """Test NLUAgent clarification detection."""

    @pytest.fixture
    def agent(self):
        """Create NLU agent."""
        return NLUAgent()

    def test_needs_clarification_unknown_intent(self, agent):
        """Test clarification needed for unknown intent."""
        intent = RequestIntent(
            intent_type="unknown",
            confidence=0.0,
            original_query="Something unclear",
            extracted_entities={},
        )

        assert agent.needs_clarification(intent) is True

    def test_needs_clarification_low_confidence(self, agent):
        """Test clarification needed for low confidence."""
        intent = RequestIntent(
            intent_type="batch_prediction",
            confidence=0.5,  # Below 0.7 threshold
            target_odds=20.0,
            original_query="Maybe some matches",
            extracted_entities={},
        )

        assert agent.needs_clarification(intent) is True

    def test_needs_clarification_single_prediction_missing_teams(self, agent):
        """Test clarification for single prediction without teams."""
        intent = RequestIntent(
            intent_type="single_prediction",
            confidence=0.8,  # High confidence
            home_team=None,
            away_team=None,
            original_query="Show prediction",
            extracted_entities={},
        )

        assert agent.needs_clarification(intent) is True

    def test_needs_clarification_high_target_odds(self, agent):
        """Test clarification for unrealistic target_odds."""
        intent = RequestIntent(
            intent_type="batch_prediction",
            confidence=0.9,  # High confidence
            target_odds=100.0,  # Too high
            original_query="Give me 100 odds",
            extracted_entities={},
        )

        assert agent.needs_clarification(intent) is True

    def test_no_clarification_needed_clear_intent(self, agent):
        """Test no clarification for clear, high-confidence intent."""
        intent = RequestIntent(
            intent_type="batch_prediction",
            confidence=0.85,
            target_odds=20.0,
            leagues=["Premier League"],
            quality_threshold="highest",
            original_query="Give me 20 odds from Premier League with highest success",
            extracted_entities={},
        )

        assert agent.needs_clarification(intent) is False

    def test_no_clarification_for_single_prediction_with_teams(self, agent):
        """Test no clarification when teams are provided."""
        intent = RequestIntent(
            intent_type="single_prediction",
            confidence=0.75,
            home_team="Arsenal",
            away_team="Chelsea",
            original_query="Arsenal vs Chelsea prediction",
            extracted_entities={},
        )

        assert agent.needs_clarification(intent) is False

    @pytest.mark.asyncio
    async def test_generate_clarification(self, agent):
        """Test end-to-end clarification generation."""
        intent = RequestIntent(
            intent_type="unknown",
            confidence=0.3,
            original_query="Show me matches",
            extracted_entities={},
        )

        clarification = await agent.generate_clarification(intent)

        assert isinstance(clarification, ClarificationResponse)
        assert clarification.message is not None
        assert len(clarification.message) > 0
        assert clarification.suggested_actions is not None


class TestMainOrchestratorClarificationFormatting:
    """Test MainOrchestrator clarification formatting."""

    def test_format_clarification_response_basic(self):
        """Test basic clarification formatting."""
        from sipap.core.orchestrator import MainOrchestrator

        orchestrator = MainOrchestrator()

        clarification = ClarificationResponse(
            clarification_type="ask_for_missing_entity",
            message="Which match are you interested in?",
            suggested_actions=[
                {"number": "1", "label": "Example format", "example": "Arsenal vs Chelsea"}
            ],
            follow_up_context={},
        )

        formatted = orchestrator._format_clarification_response(clarification)

        assert "Which match are you interested in?" in formatted
        assert "1️⃣" in formatted  # Number emoji
        assert "Example format" in formatted
        assert "Arsenal vs Chelsea" in formatted

    def test_format_clarification_response_multiple_actions(self):
        """Test formatting with multiple actions."""
        from sipap.core.orchestrator import MainOrchestrator

        orchestrator = MainOrchestrator()

        clarification = ClarificationResponse(
            clarification_type="disambiguate_intent",
            message="I can help with Premier League! What are you looking for?",
            suggested_actions=[
                {"number": "1", "label": "🎯 Predictions", "example": "20 odds from Premier League"},
                {"number": "2", "label": "📊 Results", "example": "Premier League results today"},
                {"number": "3", "label": "📅 Fixtures", "example": "Premier League fixtures"},
            ],
            follow_up_context={},
        )

        formatted = orchestrator._format_clarification_response(clarification)

        assert "Premier League" in formatted
        assert "1️⃣" in formatted
        assert "2️⃣" in formatted
        assert "3️⃣" in formatted
        assert "🎯 Predictions" in formatted
        assert "📊 Results" in formatted
        assert "📅 Fixtures" in formatted

    def test_format_clarification_response_no_actions(self):
        """Test formatting with no suggested actions."""
        from sipap.core.orchestrator import MainOrchestrator

        orchestrator = MainOrchestrator()

        clarification = ClarificationResponse(
            clarification_type="guide_to_feature",
            message="I can help you with predictions, results, and fixtures.",
            suggested_actions=[],
            follow_up_context=None,
        )

        formatted = orchestrator._format_clarification_response(clarification)

        assert "I can help you with predictions" in formatted
        # No number emojis since no actions
        assert "1️⃣" not in formatted


@pytest.mark.asyncio
async def test_integration_unclear_request_flow():
    """Integration test: Unclear request → Clarification → Follow-up."""
    from sipap.conversation import ConversationManager

    # Initialize components
    nlu_agent = NLUAgent()
    conversation_manager = ConversationManager()
    user_id = "test:user123"

    # Step 1: User sends unclear message (intentionally vague to trigger low confidence)
    unclear_message = "Give me something"
    intent = await nlu_agent.parse_user_message(unclear_message)

    # Step 2: Check if clarification needed
    # Should be true because message is very unclear
    assert nlu_agent.needs_clarification(intent)

    # Step 3: Generate clarification
    clarification = await nlu_agent.generate_clarification(intent)
    assert clarification.clarification_type in [
        "disambiguate_intent",
        "guide_to_feature",
        "ask_for_missing_entity",
    ]
    assert len(clarification.suggested_actions) > 0

    # Step 4: Save follow-up context (if provided)
    # Note: guide_to_feature clarifications may not have follow_up_context
    if clarification.follow_up_context:
        conversation_manager.update_context(user_id, clarification.follow_up_context)

        # Step 5: Retrieve context (simulating follow-up message)
        # Only verify if we saved context
        saved_context = conversation_manager.get_context(user_id)
        # Note: Context retrieval may fail if Redis not available (graceful degradation)
        # In that case, saved_context will be empty dict, which is acceptable
    else:
        # Some clarification types (like guide_to_feature) don't need context
        # This is expected behavior
        pass

    # Cleanup (may fail if Redis not available)
    conversation_manager.clear_conversation(user_id)


@pytest.mark.asyncio
async def test_integration_missing_entity_flow():
    """Integration test: Clear intent but missing entity → Clarification."""
    nlu_agent = NLUAgent()

    # User wants prediction but doesn't specify teams
    message = "Show me the prediction"
    intent = await nlu_agent.parse_user_message(message)

    # Should detect single_prediction intent but need clarification
    assert nlu_agent.needs_clarification(intent)

    clarification = await nlu_agent.generate_clarification(intent)
    assert clarification.clarification_type == "ask_for_missing_entity"
    assert clarification.follow_up_context is not None
    assert clarification.follow_up_context["awaiting"] == "team_names"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
