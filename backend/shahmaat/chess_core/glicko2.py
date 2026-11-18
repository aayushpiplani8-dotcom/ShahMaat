"""Glicko-2 rating system (Mark Glickman, http://www.glicko.net/glicko/glicko2.pdf).

Compared with plain Elo, every player also has:
* RD (rating deviation): how sure we are about the rating. New players start at
  350, so their first games move the rating a lot; it shrinks as they play.
* volatility: how erratic the player's results are.

Each game is treated as its own rating period (the way Lichess does it), so the
rating updates right after the game instead of in nightly batches.
Step numbers below match the paper.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

SCALE = 173.7178
TAU = 0.5  # system constant: limits how fast volatility can change (paper suggests 0.3–1.2)
EPSILON = 1e-6
MIN_RD = 45.0  # never become 100 % certain, or ratings would freeze
MAX_RD = 350.0
MIN_RATING = 100.0


@dataclass(frozen=True, slots=True)
class Glicko:
    rating: float = 1500.0
    rd: float = 350.0
    volatility: float = 0.06


def _g(phi: float) -> float:
    return 1.0 / math.sqrt(1.0 + 3.0 * phi * phi / (math.pi * math.pi))


def _e(mu: float, mu_j: float, phi_j: float) -> float:
    return 1.0 / (1.0 + math.exp(-_g(phi_j) * (mu - mu_j)))


def update(player: Glicko, results: list[tuple[Glicko, float]], tau: float = TAU) -> Glicko:
    """New rating after games against `results` = [(opponent, score 1/0.5/0)]."""
    # Step 2: convert to the Glicko-2 scale
    mu = (player.rating - 1500.0) / SCALE
    phi = player.rd / SCALE
    sigma = player.volatility

    if not results:
        # Step 6 only: no games, uncertainty grows.
        phi_star = math.sqrt(phi * phi + sigma * sigma)
        return Glicko(player.rating, min(MAX_RD, phi_star * SCALE), sigma)

    opponents = [((o.rating - 1500.0) / SCALE, o.rd / SCALE, s) for o, s in results]

    # Step 3: estimated variance of the rating based only on game outcomes
    v_inv = 0.0
    for mu_j, phi_j, _ in opponents:
        e = _e(mu, mu_j, phi_j)
        v_inv += _g(phi_j) ** 2 * e * (1.0 - e)
    v = 1.0 / v_inv

    # Step 4: estimated improvement
    delta = v * sum(_g(phi_j) * (s - _e(mu, mu_j, phi_j)) for mu_j, phi_j, s in opponents)

    # Step 5: new volatility (Illinois algorithm)
    a = math.log(sigma * sigma)

    def f(x: float) -> float:
        ex = math.exp(x)
        num = ex * (delta * delta - phi * phi - v - ex)
        den = 2.0 * (phi * phi + v + ex) ** 2
        return num / den - (x - a) / (tau * tau)

    big_a = a
    if delta * delta > phi * phi + v:
        big_b = math.log(delta * delta - phi * phi - v)
    else:
        k = 1
        while f(a - k * tau) < 0:
            k += 1
        big_b = a - k * tau
    f_a, f_b = f(big_a), f(big_b)
    for _ in range(100):  # converges in a handful of steps; the cap guards against bad input
        if abs(big_b - big_a) <= EPSILON:
            break
        big_c = big_a + (big_a - big_b) * f_a / (f_b - f_a)
        f_c = f(big_c)
        if f_c * f_b <= 0:
            big_a, f_a = big_b, f_b
        else:
            f_a /= 2.0
        big_b, f_b = big_c, f_c
    new_sigma = math.exp(big_a / 2.0)

    # Step 6 + 7: new RD and rating
    phi_star = math.sqrt(phi * phi + new_sigma * new_sigma)
    new_phi = 1.0 / math.sqrt(1.0 / (phi_star * phi_star) + 1.0 / v)
    new_mu = mu + new_phi * new_phi * sum(
        _g(phi_j) * (s - _e(mu, mu_j, phi_j)) for mu_j, phi_j, s in opponents
    )

    # Step 8: back to the familiar scale
    return Glicko(
        rating=max(MIN_RATING, new_mu * SCALE + 1500.0),
        rd=min(MAX_RD, max(MIN_RD, new_phi * SCALE)),
        volatility=new_sigma,
    )


def rate_game(white: Glicko, black: Glicko, white_score: float) -> tuple[Glicko, Glicko]:
    """Both players' new ratings after one game (white_score: 1 win, 0.5 draw, 0 loss)."""
    return update(white, [(black, white_score)]), update(black, [(white, 1.0 - white_score)])


def is_provisional(rd: float) -> bool:
    """Shown with a '?' and kept off the leaderboard until we're reasonably sure."""
    return rd > 110.0
