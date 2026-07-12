"""Example 1: Basic Prediction Pipeline

Demonstrates the complete end-to-end prediction pipeline:
1. Initialize MainOrchestrator
2. Generate prediction for a match
3. Check quality gates
4. Evaluate expected value

Usage:
    python examples/01_basic_prediction.py
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

from sipap.core.orchestrator import MainOrchestrator


async def main() -> None:
    """Run basic prediction example."""
    print("=" * 70)
    print("SIPAP Example 1: Basic Prediction Pipeline")
    print("=" * 70)
    print()

    # Initialize orchestrator
    print("Step 1: Initializing MainOrchestrator...")
    orchestrator = MainOrchestrator()

    # Check supported sports
    sports = orchestrator.get_supported_sports()
    print(f"✓ Supported sports: {', '.join(sports)}")
    print()

    # Generate prediction
    print("Step 2: Generating prediction for Manchester United vs Liverpool...")
    print("        (Using mock data for MVP demonstration)")
    print()

    match_id = "Man_United_vs_Liverpool"
    market = "1X2"

    try:
        prediction = await orchestrator.predict(
            sport="soccer",
            match_id=match_id,
            market=market,
        )

        # Display results
        print("Step 3: Prediction Results")
        print("-" * 70)
        print(f"Match: {match_id}")
        print(f"Market: {market}")
        print()
        print(f"Predicted Outcome: {prediction.get('outcome')}")
        print(f"Probability: {prediction.get('probability', 0) * 100:.1f}%")
        print(f"Confidence: {prediction.get('confidence', 0):.0f}%")
        print()

        # Quality gate
        quality_gate = prediction.get("quality_gate")
        print(f"Quality Gate: {quality_gate}")

        # Expected Value
        ev = prediction.get("expected_value", {})
        print()
        print("Expected Value Analysis:")
        print(f"  Our Probability: {ev.get('our_probability', 0) * 100:.1f}%")
        print(f"  Implied Probability: {ev.get('implied_probability', 0) * 100:.1f}%")
        print(f"  Edge: {ev.get('edge', 0) * 100:.1f}%")
        print(f"  Expected Value: {ev.get('expected_value', 0) * 100:.1f}%")
        print(f"  Positive EV: {'Yes' if ev.get('is_positive_ev') else 'No'}")
        print()

        # Recommendation
        recommendation = prediction.get("recommendation")
        print(f"Recommendation: {recommendation}")
        print()

        # Reasoning
        print("Reasoning:")
        reasoning = prediction.get("reasoning", "")
        for line in reasoning.split(" | "):
            print(f"  • {line}")

        print()
        print("=" * 70)

        if quality_gate == "PASSED" and ev.get("is_positive_ev"):
            print("✅ SUCCESS: Positive EV opportunity identified!")
        elif quality_gate == "PASSED":
            print("⚠️  MARGINAL: Prediction passed quality gates but not +EV")
        else:
            print("❌ REJECTED: Prediction failed quality gates")

        print("=" * 70)

    except Exception as e:
        print(f"❌ Error: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())
