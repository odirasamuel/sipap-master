"""Example 1: Statistical Analysis Functions

Demonstrates the core statistical prediction functions:
- Poisson model for match outcome probabilities
- Expected Goals (xG) calculator
- Elo rating win probability
- Form score analysis

These functions power the Statistical Agent in the ensemble.
"""

from sipap.tools.function.statistical import (
    poisson_model,
    xg_calculator,
    elo_rating,
    form_score
)


def main():
    """Run statistical analysis examples."""
    print("=" * 70)
    print("EXAMPLE 1: Statistical Analysis Functions")
    print("=" * 70)
    print()

    # Example 1: Poisson Model
    print("1. POISSON MODEL - Arsenal vs Chelsea")
    print("-" * 70)

    arsenal_avg_goals = 2.1  # Arsenal averages 2.1 goals per game
    chelsea_avg_goals = 1.6  # Chelsea averages 1.6 goals per game
    league_avg = 1.5  # Premier League average

    result = poisson_model(
        home_avg_goals=arsenal_avg_goals,
        away_avg_goals=chelsea_avg_goals,
        league_avg_goals=league_avg
    )

    print(f"   Home Avg Goals: {arsenal_avg_goals}")
    print(f"   Away Avg Goals: {chelsea_avg_goals}")
    print(f"   League Average: {league_avg}")
    print()
    print(f"   PREDICTIONS:")
    print(f"   - Home Win: {result['home_win']:.2%} (probability: {result['home_win']})")
    print(f"   - Draw:     {result['draw']:.2%} (probability: {result['draw']})")
    print(f"   - Away Win: {result['away_win']:.2%} (probability: {result['away_win']})")
    print()
    print(f"   Expected Goals:")
    print(f"   - Arsenal (home): {result['home_xg']} xG")
    print(f"   - Chelsea (away): {result['away_xg']} xG")
    print()

    # Example 2: xG Calculator
    print("2. EXPECTED GOALS (xG) CALCULATOR - Match Shot Analysis")
    print("-" * 70)

    shots = [
        {"location": "penalty"},  # Penalty kick
        {"location": "six_yard"},  # Close-range shot
        {"location": "box"},  # Shot from inside the box
        {"location": "box", "header": True},  # Header from inside box
        {"location": "outside_box"},  # Long-range shot
        {"location": "box", "volley": True},  # Volley from inside box
    ]

    total_xg = xg_calculator(shots)

    print(f"   Total Shots: {len(shots)}")
    print(f"   Total xG: {total_xg}")
    print()
    print(f"   Shot Breakdown:")
    for i, shot in enumerate(shots, 1):
        location = shot.get("location", "box")
        modifiers = []
        if shot.get("header"):
            modifiers.append("header")
        if shot.get("volley"):
            modifiers.append("volley")

        modifier_str = f" ({', '.join(modifiers)})" if modifiers else ""
        print(f"   {i}. {location.replace('_', ' ').title()}{modifier_str}")

    print()

    # Example 3: Elo Rating
    print("3. ELO RATING - Team Strength Comparison")
    print("-" * 70)

    # Manchester City (strong team) vs Brighton (mid-table)
    city_elo = 1950  # Very strong team
    brighton_elo = 1650  # Mid-table team

    elo_result = elo_rating(team_elo=city_elo, opponent_elo=brighton_elo)

    print(f"   Manchester City: {city_elo} Elo")
    print(f"   Brighton:        {brighton_elo} Elo")
    print(f"   Difference:      {elo_result['elo_difference']} points")
    print()
    print(f"   Win Probability: {elo_result['win_probability']:.2%}")
    print()

    # Example 4: Form Score
    print("4. FORM SCORE - Recent Performance Analysis")
    print("-" * 70)

    # Team on a hot streak
    hot_form = ["W", "W", "W", "D", "W"]  # 4 wins, 1 draw in last 5
    hot_result = form_score(hot_form)

    print(f"   Hot Team - Last 5 Matches: {', '.join(hot_form)}")
    print(f"   Form Score: {hot_result['form_score']}/15")
    print(f"   Momentum: {hot_result['momentum'].upper()}")
    print(f"   Weighted Score: {hot_result['weighted_score']}")
    print()

    # Team in poor form
    poor_form = ["L", "L", "D", "L", "W"]  # 3 losses, 1 draw, 1 win
    poor_result = form_score(poor_form)

    print(f"   Poor Team - Last 5 Matches: {', '.join(poor_form)}")
    print(f"   Form Score: {poor_result['form_score']}/15")
    print(f"   Momentum: {poor_result['momentum'].upper()}")
    print(f"   Weighted Score: {poor_result['weighted_score']}")
    print()

    # Improving team
    improving_form = ["W", "W", "D", "L", "L"]  # Recent improvement
    improving_result = form_score(improving_form)

    print(f"   Improving Team - Last 5 Matches: {', '.join(improving_form)}")
    print(f"   Form Score: {improving_result['form_score']}/15")
    print(f"   Momentum: {improving_result['momentum'].upper()}")
    print(f"   Weighted Score: {improving_result['weighted_score']}")
    print()

    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print()
    print("These statistical functions provide the foundation for match predictions:")
    print()
    print("1. Poisson Model:")
    print("   - Calculates match outcome probabilities from goal-scoring rates")
    print("   - Accounts for home advantage (1.3x multiplier)")
    print("   - Returns probabilities for home win, draw, away win")
    print()
    print("2. xG Calculator:")
    print("   - Evaluates shot quality based on location and type")
    print("   - Penalty: 76% conversion | Six-yard: 35% | Box: 12%")
    print("   - Adjusts for headers (70%) and volleys (80%)")
    print()
    print("3. Elo Rating:")
    print("   - Standard chess-style rating system for team strength")
    print("   - 400-point difference ≈ 90% win probability")
    print("   - Updates based on match results")
    print()
    print("4. Form Score:")
    print("   - Weighted analysis of last 5 matches (W=3, D=1, L=0)")
    print("   - Recent matches weighted more heavily")
    print("   - Detects momentum (up/down/stable)")
    print()
    print("These functions are used by the Statistical Agent in the ensemble.")
    print()


if __name__ == "__main__":
    main()
