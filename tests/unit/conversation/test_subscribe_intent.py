"""Unit tests for subscribe intent recognition in NLU."""

import pytest
from sipap.conversation.nlu_agent import NLUAgent, SUBSCRIBE_PATTERNS
import re


class TestSubscribePatterns:
    """Tests for SUBSCRIBE_PATTERNS regex matching."""

    def test_simple_subscribe(self) -> None:
        """Test 'subscribe' is matched."""
        message = "subscribe"
        assert any(re.search(p, message.lower()) for p in SUBSCRIBE_PATTERNS)

    def test_want_to_subscribe(self) -> None:
        """Test 'i want to subscribe' is matched."""
        message = "i want to subscribe"
        assert any(re.search(p, message.lower()) for p in SUBSCRIBE_PATTERNS)

    def test_sign_me_up(self) -> None:
        """Test 'sign me up' is matched."""
        message = "sign me up"
        assert any(re.search(p, message.lower()) for p in SUBSCRIBE_PATTERNS)

    def test_get_subscription(self) -> None:
        """Test 'get subscription' is matched."""
        message = "get subscription"
        assert any(re.search(p, message.lower()) for p in SUBSCRIBE_PATTERNS)

    def test_buy_subscription(self) -> None:
        """Test 'buy subscription' is matched."""
        message = "buy subscription"
        assert any(re.search(p, message.lower()) for p in SUBSCRIBE_PATTERNS)

    def test_start_subscription(self) -> None:
        """Test 'start subscription' is matched."""
        message = "start subscription"
        assert any(re.search(p, message.lower()) for p in SUBSCRIBE_PATTERNS)

    def test_renew_subscription(self) -> None:
        """Test 'renew subscription' is matched."""
        message = "renew subscription"
        assert any(re.search(p, message.lower()) for p in SUBSCRIBE_PATTERNS)

    def test_renew_my_subscription(self) -> None:
        """Test 'renew my subscription' is matched."""
        message = "renew my subscription"
        assert any(re.search(p, message.lower()) for p in SUBSCRIBE_PATTERNS)

    def test_upgrade(self) -> None:
        """Test 'upgrade' is matched."""
        message = "upgrade"
        assert any(re.search(p, message.lower()) for p in SUBSCRIBE_PATTERNS)

    def test_upgrade_my_plan(self) -> None:
        """Test 'upgrade my plan' is matched."""
        message = "upgrade my plan"
        assert any(re.search(p, message.lower()) for p in SUBSCRIBE_PATTERNS)

    def test_non_subscribe_not_matched(self) -> None:
        """Test non-subscribe messages are NOT matched."""
        non_subscribe_messages = [
            "give me 20 odds",
            "btts picks from premier league",
            "arsenal vs chelsea prediction",
            "what is subscription",  # Contains "subscription" but not a request
            "cancel subscription",   # This should NOT match subscribe patterns
        ]

        for message in non_subscribe_messages:
            matches = any(re.search(p, message.lower()) for p in SUBSCRIBE_PATTERNS)
            assert not matches, f"'{message}' should NOT match subscribe patterns"


class TestNLUSubscribeDetection:
    """Tests for NLU agent subscribe detection."""

    @pytest.fixture
    def nlu(self) -> NLUAgent:
        """Create NLU agent without Claude (regex-only mode)."""
        return NLUAgent(use_claude=False)

    def test_is_subscribe_request_true(self, nlu: NLUAgent) -> None:
        """Test _is_subscribe_request returns True for subscribe messages."""
        messages = [
            "subscribe",
            "Subscribe",
            "SUBSCRIBE",
            "i want to subscribe",
            "sign me up",
            "get subscription",
        ]

        for msg in messages:
            assert nlu._is_subscribe_request(msg), f"'{msg}' should be detected as subscribe"

    def test_is_subscribe_request_false(self, nlu: NLUAgent) -> None:
        """Test _is_subscribe_request returns False for non-subscribe messages."""
        messages = [
            "give me 20 odds",
            "btts picks",
            "cancel subscription",
            "hello",
        ]

        for msg in messages:
            assert not nlu._is_subscribe_request(msg), f"'{msg}' should NOT be detected as subscribe"

    @pytest.mark.asyncio
    async def test_parse_subscribe_intent(self, nlu: NLUAgent) -> None:
        """Test parse_user_message returns subscribe intent."""
        intent = await nlu.parse_user_message("subscribe")

        assert intent.intent_type == "subscribe"
        assert intent.confidence == 1.0
        assert intent.original_query == "subscribe"

    @pytest.mark.asyncio
    async def test_parse_sign_me_up_intent(self, nlu: NLUAgent) -> None:
        """Test 'sign me up' parses as subscribe intent."""
        intent = await nlu.parse_user_message("sign me up")

        assert intent.intent_type == "subscribe"
        assert intent.confidence == 1.0
