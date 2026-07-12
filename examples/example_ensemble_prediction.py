"""Example 3: Ensemble Prediction with Quality Gates

Demonstrates the full orchestration system:
- Multiple agent predictions
- Ensemble calculation (weighted average)
- Quality gate enforcement
- Final recommendation

This shows how SoccerOrchestrator coordinates all agents.
"""

from sipap.sports.soccer.orchestrator import SoccerOrchestrator


def main():
    """Run ensemble prediction example."""
    print("=" * 70)
    print("EXAMPLE 3: Ensemble Prediction with Quality Gates")
    print("=" * 70)
    print()

    # Initialize orchestrator
    orchestrator = SoccerOrchestrator()

    # Simulate predictions from all 5 agents
    # In production, these would come from actual agent calls
    agent_predictions = [
        {
            "agent": "statistical",
            "prediction": {
                "market": "1X2",
                "outcome": "home_win",
                "probability": 0.67,
                "confidence": 72
            },
            "reasoning": "Poisson model strongly favors home team (67% probability). "
                        "Home xG of 2.3 vs away xG of 1.4. Elo rating difference of 150 points. "
                        "Home team form score: 13.5/15 (excellent).",
            "evidence": [
                "Home team averages 2.1 goals/game (league avg: 1.5)",
                "Away team concedes 1.3 goals/game",
                "Elo rating: Home 1850 vs Away 1700 (+150)",
                "Home form: 4W-1D in last 5 (13.5/15 points)"
            ]
        },
        {
            "agent": "ml",
            "prediction": {
                "market": "1X2",
                "outcome": "home_win",
                "probability": 0.70,
                "confidence": 75
            },
            "reasoning": "XGBoost model predicts home win with 70% probability. "
                        "Top features: Elo difference (0.35 importance), form differential (0.25), "
                        "home goals/game (0.20). Model confidence: 75/100.",
            "evidence": [
                "Model trained on 10,000+ historical matches",
                "Feature importance: Elo diff (35%), form (25%), attack (20%)",
                "Historical accuracy: 62% on similar matches",
                "Model version: v2.1"
            ]
        },
        {
            "agent": "form",
            "prediction": {
                "market": "1X2",
                "outcome": "home_win",
                "probability": 0.64,
                "confidence": 68
            },
            "reasoning": "Home team showing excellent recent form with strong momentum. "
                        "4 wins in last 5 matches (13.5/15 form score). "
                        "Away team mixed form: 2W-1D-2L (7.0/15 form score). Momentum trending up for home.",
            "evidence": [
                "Home team: W-W-W-D-W (momentum: UP)",
                "Away team: L-L-D-W-W (momentum: STABLE)",
                "Form differential: +6.5 points in favor of home",
                "Home unbeaten in 5 matches"
            ]
        },
        {
            "agent": "market",
            "prediction": {
                "market": "1X2",
                "outcome": "draw",
                "probability": 0.48,
                "confidence": 55
            },
            "reasoning": "Betting markets suggest closer contest than other metrics. "
                        "Current odds: Home 1.95, Draw 3.50, Away 4.20 (implied 51% home win). "
                        "Slight odds movement towards draw in last 24h suggests value bet on draw.",
            "evidence": [
                "Implied probability from odds: 51% home, 29% draw, 24% away",
                "Odds movement: Home odds drifted from 1.85 to 1.95",
                "Sharp money on draw (3.50 → 3.40 in 6h)",
                "Public heavily on home win (72% of bets)"
            ]
        },
        {
            "agent": "news",
            "prediction": {
                "market": "1X2",
                "outcome": "home_win",
                "probability": 0.61,
                "confidence": 65
            },
            "reasoning": "News sentiment favors home team. No major injuries for home side, "
                        "full squad available. Away team missing key midfielder (6-week injury). "
                        "Home manager confident in pre-match press conference.",
            "evidence": [
                "Home team: Full strength squad available",
                "Away team: Key midfielder ruled out (6 weeks)",
                "Manager sentiment: Positive for home, cautious for away",
                "Recent transfer: Home signed striker (£50M)"
            ]
        }
    ]

    print("AGENT PREDICTIONS")
    print("-" * 70)
    print()

    for pred in agent_predictions:
        print(f"{pred['agent'].upper()} AGENT:")
        print(f"  Outcome: {pred['prediction']['outcome'].replace('_', ' ').title()}")
        print(f"  Probability: {pred['prediction']['probability']:.2%}")
        print(f"  Confidence: {pred['prediction']['confidence']}/100")
        print(f"  Reasoning: {pred['reasoning'][:120]}...")
        print()

    # Calculate ensemble
    print("=" * 70)
    print("ENSEMBLE CALCULATION")
    print("=" * 70)
    print()

    ensemble = orchestrator._calculate_ensemble(agent_predictions, "1X2")

    print("Weighted Average Calculation:")
    print(f"  Statistical (25%): 0.67 × 0.25 = 0.1675")
    print(f"  ML (30%):          0.70 × 0.30 = 0.2100")
    print(f"  Form (20%):        0.64 × 0.20 = 0.1280")
    print(f"  Market (15%):      0.48 × 0.15 = 0.0720")
    print(f"  News (10%):        0.61 × 0.10 = 0.0610")
    print(f"  " + "-" * 40)
    print(f"  ENSEMBLE:                        = {ensemble['probability']:.4f}")
    print()

    print("Agent Agreement Analysis:")
    print(f"  Standard Deviation: {0.08:.4f}")  # Approximate
    print(f"  Agreement Confidence: {ensemble['confidence']:.0f}/100")
    print()

    outcome_votes = {}
    for pred in agent_predictions:
        outcome = pred['prediction']['outcome']
        outcome_votes[outcome] = outcome_votes.get(outcome, 0) + 1

    print("Outcome Voting:")
    for outcome, count in outcome_votes.items():
        print(f"  {outcome.replace('_', ' ').title()}: {count}/5 agents")
    print()

    print(f"Majority Outcome: {ensemble['outcome'].replace('_', ' ').title()} ({outcome_votes[ensemble['outcome']]}/5 agents)")
    print()

    # Apply quality gates
    print("=" * 70)
    print("QUALITY GATES")
    print("=" * 70)
    print()

    final_prediction = orchestrator._apply_quality_gates(ensemble, agent_predictions)

    print("Gate 1: Minimum Confidence (55%)")
    confidence_status = "✅ PASS" if ensemble['confidence'] >= 55 else "❌ FAIL"
    print(f"  Current: {ensemble['confidence']:.0f}/100 → {confidence_status}")
    print()

    print("Gate 2: Minimum Probability (50%)")
    probability_status = "✅ PASS" if ensemble['probability'] >= 0.50 else "❌ FAIL"
    print(f"  Current: {ensemble['probability']:.2%} → {probability_status}")
    print()

    print("Gate 3: Agent Consensus (3/5 minimum)")
    max_consensus = max(outcome_votes.values())
    consensus_status = "✅ PASS" if max_consensus >= 3 else "❌ FAIL"
    print(f"  Current: {max_consensus}/5 agents agree → {consensus_status}")
    print()

    print(f"Overall Quality Gate: {final_prediction['quality_gate']}")
    print()

    # Final recommendation
    print("=" * 70)
    print("FINAL PREDICTION")
    print("=" * 70)
    print()

    print(f"Market: {final_prediction['market']}")
    print(f"Outcome: {final_prediction['outcome'].replace('_', ' ').title()}")
    print(f"Probability: {final_prediction['probability']:.2%}")
    print(f"Confidence: {final_prediction['confidence']:.0f}/100")
    print()
    print(f"Quality Gate: {final_prediction['quality_gate']}")
    print(f"Recommendation: {final_prediction['recommendation']}")
    print()

    # Evidence summary
    print("=" * 70)
    print("SUPPORTING EVIDENCE")
    print("=" * 70)
    print()

    evidence_count = 0
    for pred in agent_predictions:
        for evidence in pred.get("evidence", [])[:2]:  # Top 2 from each agent
            evidence_count += 1
            print(f"{evidence_count}. {evidence}")

    print()

    # Demonstrate failure scenario
    print("=" * 70)
    print("QUALITY GATE FAILURE EXAMPLE")
    print("=" * 70)
    print()

    # Low confidence scenario
    low_confidence_predictions = [
        {
            "agent": "statistical",
            "prediction": {"outcome": "home_win", "probability": 0.52},
            "reasoning": "Marginal statistical advantage",
            "evidence": []
        },
        {
            "agent": "ml",
            "prediction": {"outcome": "draw", "probability": 0.48},
            "reasoning": "ML model uncertain",
            "evidence": []
        },
        {
            "agent": "form",
            "prediction": {"outcome": "away_win", "probability": 0.51},
            "reasoning": "Slight away form advantage",
            "evidence": []
        },
        {
            "agent": "market",
            "prediction": {"outcome": "draw", "probability": 0.49},
            "reasoning": "Markets suggest even match",
            "evidence": []
        },
        {
            "agent": "news",
            "prediction": {"outcome": "home_win", "probability": 0.50},
            "reasoning": "No clear sentiment",
            "evidence": []
        }
    ]

    low_ensemble = orchestrator._calculate_ensemble(low_confidence_predictions, "1X2")
    failed = orchestrator._apply_quality_gates(low_ensemble, low_confidence_predictions)

    print("Scenario: Agents heavily disagree on outcome")
    print(f"  Confidence: {low_ensemble['confidence']:.0f}/100")
    print(f"  Quality Gate: {failed['quality_gate']}")
    print(f"  Reason: {failed['reason']}")
    print(f"  Recommendation: {failed['recommendation']}")
    print()

    # Summary
    print("=" * 70)
    print("SUMMARY - Ensemble System")
    print("=" * 70)
    print()
    print("The ensemble system provides robust predictions through:")
    print()
    print("1. Multi-Agent Coordination:")
    print("   - 5 specialized agents with different approaches")
    print("   - Statistical, ML, Form, Market, News perspectives")
    print("   - Each agent provides probability + confidence + reasoning")
    print()
    print("2. Weighted Ensemble:")
    print("   - Agents weighted by historical accuracy")
    print("   - ML (30%) > Statistical (25%) > Form (20%) > Market (15%) > News (10%)")
    print("   - Confidence based on agent agreement (low std dev = high confidence)")
    print()
    print("3. Quality Gates:")
    print("   - Minimum 55% confidence threshold")
    print("   - Minimum 50% probability threshold")
    print("   - Minimum 3/5 agent consensus required")
    print("   - Failed predictions blocked from reaching users")
    print()
    print("4. Transparency:")
    print("   - Full reasoning from each agent")
    print("   - Supporting evidence preserved")
    print("   - Quality gate status visible")
    print()
    print("This ensures only high-quality predictions reach users.")
    print()


if __name__ == "__main__":
    main()
