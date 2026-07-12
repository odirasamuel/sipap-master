"""Statistical analysis functions.

These are @tool decorated functions that agents can call.
They are NOT MCP servers - they are pure Python functions.
"""

from typing import Dict, List
from scipy.stats import poisson
from strands import tool


@tool
def poisson_model(home_avg_goals: float, away_avg_goals: float, league_avg_goals: float = 1.5) -> dict:
    """
    Calculate match outcome probabilities using Poisson distribution.

    Args:
        home_avg_goals: Home team's average goals per game
        away_avg_goals: Away team's average goals per game
        league_avg_goals: League average goals per game

    Returns:
        dict with home_win, draw, away_win probabilities
    """
    # Calculate expected goals with home advantage
    home_xg = (home_avg_goals / league_avg_goals) * league_avg_goals * 1.3
    away_xg = (away_avg_goals / league_avg_goals) * league_avg_goals

    # Poisson probabilities for 0-10 goals
    max_goals = 10
    home_probs = [poisson.pmf(i, home_xg) for i in range(max_goals)]
    away_probs = [poisson.pmf(i, away_xg) for i in range(max_goals)]

    # Calculate match outcome probabilities
    home_win = sum(
        home_probs[i] * away_probs[j]
        for i in range(max_goals)
        for j in range(max_goals)
        if i > j
    )

    draw = sum(home_probs[i] * away_probs[i] for i in range(max_goals))
    away_win = 1 - home_win - draw

    return {
        "home_win": round(home_win, 4),
        "draw": round(draw, 4),
        "away_win": round(away_win, 4),
        "home_xg": round(home_xg, 2),
        "away_xg": round(away_xg, 2)
    }


@tool
def xg_calculator(shots: List[Dict], league_avg_conversion: float = 0.10) -> float:
    """
    Calculate expected goals from shot data.

    Args:
        shots: List of shots with location and type
        league_avg_conversion: League average shot conversion rate

    Returns:
        Expected goals (xG)
    """
    xg_total = 0.0

    for shot in shots:
        # Base xG by location
        location_xg = {
            "box": 0.12,
            "six_yard": 0.35,
            "outside_box": 0.03,
            "penalty": 0.76
        }.get(shot.get("location", "box"), 0.05)

        # Adjust for shot type
        if shot.get("header"):
            location_xg *= 0.7
        elif shot.get("volley"):
            location_xg *= 0.8

        xg_total += location_xg

    return round(xg_total, 2)


@tool
def elo_rating(team_elo: int, opponent_elo: int) -> dict:
    """
    Calculate win probability based on Elo ratings.

    Args:
        team_elo: Team's Elo rating
        opponent_elo: Opponent's Elo rating

    Returns:
        dict with win_probability and elo_difference
    """
    elo_diff = team_elo - opponent_elo
    win_probability = 1 / (1 + 10 ** (-elo_diff / 400))

    return {
        "win_probability": round(win_probability, 4),
        "elo_difference": elo_diff,
        "team_elo": team_elo,
        "opponent_elo": opponent_elo
    }


@tool
def form_score(recent_results: List[str]) -> dict:
    """
    Calculate form score from recent results.

    Args:
        recent_results: List of results ["W", "D", "L", "W", "W"]

    Returns:
        dict with form_score (0-15 points) and momentum
    """
    points_map = {"W": 3, "D": 1, "L": 0}
    points = [points_map.get(r, 0) for r in recent_results]

    # Weight recent matches more (exponential decay)
    weights = [2.0, 1.5, 1.2, 1.0, 0.8]
    weighted_points = sum(p * w for p, w in zip(points, weights[:len(points)]))
    max_points = sum(3 * w for w in weights[:len(points)])

    form_score_value = (weighted_points / max_points) * 15  # Scale to 0-15

    # Momentum: trending up or down
    if len(points) >= 3:
        recent_avg = sum(points[:2]) / 2
        older_avg = sum(points[2:]) / len(points[2:])
        momentum = "up" if recent_avg > older_avg else "down" if recent_avg < older_avg else "stable"
    else:
        momentum = "unknown"

    return {
        "form_score": round(form_score_value, 2),
        "momentum": momentum,
        "recent_points": points,
        "weighted_score": round(weighted_points, 2)
    }
