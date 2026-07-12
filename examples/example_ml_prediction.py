"""Example 2: Machine Learning Prediction

Demonstrates the ML prediction engine:
- Feature engineering from match context
- ML model prediction (simplified for MVP)
- Confidence calculation

This powers the ML Agent in the ensemble.
"""

from sipap.tools.function.ml import (
    ml_predict,
    engineer_features,
    calculate_confidence
)


def main():
    """Run ML prediction examples."""
    print("=" * 70)
    print("EXAMPLE 2: Machine Learning Prediction")
    print("=" * 70)
    print()

    # Example: Liverpool vs Manchester United prediction
    print("MATCH: Liverpool (H) vs Manchester United (A)")
    print("-" * 70)
    print()

    # Build match context with all required features
    match_context = {
        "home_team": {
            "elo_rating": 1850,
            "form_score": 13.5,  # Strong form (4W, 1D)
            "goals_per_game": 2.3,
            "goals_conceded_per_game": 0.8
        },
        "away_team": {
            "elo_rating": 1780,
            "form_score": 9.0,  # Mixed form (2W, 1D, 2L)
            "goals_per_game": 1.7,
            "goals_conceded_per_game": 1.2
        },
        "h2h": {
            "home_wins_pct": 0.60  # Liverpool wins 60% of H2H matches
        },
        "weather_impact_score": 0.1,  # Minimal weather impact
        "days_since_last_match_home": 4,  # Liverpool rested
        "days_since_last_match_away": 3   # Man United rested
    }

    print("Match Context:")
    print("-" * 70)
    print()
    print("Liverpool (Home):")
    print(f"  - Elo Rating: {match_context['home_team']['elo_rating']}")
    print(f"  - Form Score: {match_context['home_team']['form_score']}/15")
    print(f"  - Goals/Game: {match_context['home_team']['goals_per_game']}")
    print(f"  - Conceded/Game: {match_context['home_team']['goals_conceded_per_game']}")
    print(f"  - Days Rest: {match_context['days_since_last_match_home']}")
    print()
    print("Manchester United (Away):")
    print(f"  - Elo Rating: {match_context['away_team']['elo_rating']}")
    print(f"  - Form Score: {match_context['away_team']['form_score']}/15")
    print(f"  - Goals/Game: {match_context['away_team']['goals_per_game']}")
    print(f"  - Conceded/Game: {match_context['away_team']['goals_conceded_per_game']}")
    print(f"  - Days Rest: {match_context['days_since_last_match_away']}")
    print()
    print("Head-to-Head:")
    print(f"  - Liverpool Win %: {match_context['h2h']['home_wins_pct']:.0%}")
    print()
    print("Conditions:")
    print(f"  - Weather Impact: {match_context['weather_impact_score']:.1f} (minimal)")
    print()

    # Step 1: Feature Engineering
    print("=" * 70)
    print("STEP 1: Feature Engineering")
    print("=" * 70)
    print()

    features = engineer_features(match_context)

    feature_names = [
        "home_elo",
        "away_elo",
        "home_form",
        "away_form",
        "home_goals_pg",
        "away_goals_pg",
        "home_conceded_pg",
        "away_conceded_pg",
        "h2h_home_wins",
        "weather_impact",
        "rest_days_home",
        "rest_days_away"
    ]

    print("Extracted Features:")
    for name, value in zip(feature_names, features):
        print(f"  {name:20s}: {value}")

    print()

    # Step 2: ML Prediction
    print("=" * 70)
    print("STEP 2: ML Model Prediction")
    print("=" * 70)
    print()

    prediction = ml_predict(match_context, market="1X2", model_version="v2.1")

    print("Model Prediction:")
    print(f"  - Market: {prediction['model_version']}")
    print(f"  - Probability: {prediction['probability']:.2%}")
    print(f"  - Confidence: {prediction['confidence']:.0f}/100")
    print()

    # Interpret the prediction
    if prediction['probability'] > 0.6:
        interpretation = "STRONG home win prediction"
    elif prediction['probability'] > 0.5:
        interpretation = "MODERATE home win prediction"
    else:
        interpretation = "LEAN towards home win"

    print(f"Interpretation: {interpretation}")
    print()

    # Step 3: Confidence Analysis
    print("=" * 70)
    print("STEP 3: Confidence Analysis")
    print("=" * 70)
    print()

    # Simulate different probability distributions for confidence examples
    examples = [
        {
            "name": "Very Confident",
            "probs": [0.85, 0.15],  # 85% vs 15%
            "scenario": "Clear favorite"
        },
        {
            "name": "Moderately Confident",
            "probs": [0.65, 0.35],  # 65% vs 35%
            "scenario": "Likely winner"
        },
        {
            "name": "Low Confidence",
            "probs": [0.52, 0.48],  # 52% vs 48%
            "scenario": "Tight match"
        }
    ]

    print("Confidence Levels for Different Scenarios:")
    print()

    for example in examples:
        conf = calculate_confidence(example["probs"])
        print(f"{example['name']} ({example['scenario']}):")
        print(f"  Probabilities: {example['probs'][0]:.0%} vs {example['probs'][1]:.0%}")
        print(f"  Confidence: {conf:.0f}/100")
        print()

    # Summary
    print("=" * 70)
    print("SUMMARY - ML Prediction Pipeline")
    print("=" * 70)
    print()
    print("The ML prediction engine follows a 3-step process:")
    print()
    print("1. Feature Engineering:")
    print("   - Extracts 12 features from match context")
    print("   - Normalizes data for model input")
    print("   - Includes team stats, form, H2H, conditions")
    print()
    print("2. Model Prediction:")
    print("   - Simplified deterministic model for MVP")
    print("   - Returns probability (0-1) and confidence (0-100)")
    print("   - Future: Real XGBoost model with 60%+ accuracy")
    print()
    print("3. Confidence Calculation:")
    print("   - Based on probability distribution certainty")
    print("   - High confidence: Clear probability separation")
    print("   - Low confidence: Close probabilities (uncertain)")
    print()
    print("The ML Agent uses this pipeline to generate predictions for the ensemble.")
    print()

    # Real-world application example
    print("=" * 70)
    print("REAL-WORLD APPLICATION")
    print("=" * 70)
    print()
    print(f"For Liverpool vs Manchester United:")
    print(f"  - ML Probability: {prediction['probability']:.2%}")
    print(f"  - ML Confidence: {prediction['confidence']:.0f}/100")
    print()
    print("This prediction will be combined with:")
    print("  - Statistical Agent (Poisson, xG, Elo)")
    print("  - Form Agent (momentum analysis)")
    print("  - Market Agent (odds sentiment)")
    print("  - News Agent (injuries, context)")
    print()
    print("To create a final ensemble prediction with quality gates.")
    print()


if __name__ == "__main__":
    main()
