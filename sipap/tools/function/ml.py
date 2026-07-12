"""Machine learning functions.

Simplified implementation for Phase 3 MVP.
Real XGBoost models will be integrated in later phases.

This provides the same interface but uses deterministic rules
instead of trained models for testing purposes.
"""

from typing import Dict, List
from strands import tool


@tool
def ml_predict(context: Dict, market: str = "1X2", model_version: str = "v2.1") -> dict:
    """
    ML model prediction (simplified implementation).

    Args:
        context: Match context with all features
        market: Betting market
        model_version: Model version

    Returns:
        dict with probability, confidence, model_version
    """
    # Extract features
    features = engineer_features(context)

    # Simplified prediction logic (deterministic rules)
    # In production, this would be: model.predict_proba([features])[0]

    # Calculate score differential from Elo and form
    home_score = features[0] + features[2] * 10  # home_elo + home_form * 10
    away_score = features[1] + features[3] * 10  # away_elo + away_form * 10

    # Normalize to probability (sigmoid-like function)
    score_diff = (home_score - away_score) / 1000
    probability = 1 / (1 + 2.718 ** (-score_diff))  # Basic sigmoid

    # Clamp to reasonable range
    probability = max(0.3, min(0.7, probability))

    # Create probability distribution (for binary classification)
    probabilities = [probability, 1 - probability]

    # Calculate confidence
    confidence = calculate_confidence(probabilities)

    return {
        "probability": round(probability, 4),
        "confidence": round(confidence, 2),
        "model_version": model_version
    }


def engineer_features(context: Dict) -> List[float]:
    """
    Extract features from context.

    Args:
        context: Match context dictionary

    Returns:
        List of numeric features
    """
    return [
        context['home_team']['elo_rating'],
        context['away_team']['elo_rating'],
        context['home_team']['form_score'],
        context['away_team']['form_score'],
        context['home_team']['goals_per_game'],
        context['away_team']['goals_per_game'],
        context['home_team']['goals_conceded_per_game'],
        context['away_team']['goals_conceded_per_game'],
        context['h2h']['home_wins_pct'],
        context.get('weather_impact_score', 0),
        context.get('days_since_last_match_home', 7),
        context.get('days_since_last_match_away', 7),
    ]


def calculate_confidence(probabilities: List[float]) -> float:
    """
    Calculate confidence from probability distribution.

    Args:
        probabilities: List of class probabilities

    Returns:
        Confidence score (0-100)
    """
    max_prob = max(probabilities)
    confidence = (max_prob - 0.5) * 2 * 100  # Scale to 0-100
    return round(confidence, 10)  # Round to avoid floating point precision issues
