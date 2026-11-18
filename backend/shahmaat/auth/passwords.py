"""Password hashing with Argon2id (winner of the Password Hashing Competition).

Argon2id is deliberately slow and memory-hungry, so even if the database leaks,
guessing passwords offline costs an attacker a lot per guess. Parameters follow
OWASP's recommendation (19 MiB memory, 2 iterations, 1 lane).

Hashing runs in a worker thread so a burst of logins can't freeze the event loop
that is also running everyone's live games.
"""

from __future__ import annotations

import asyncio

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_hasher = PasswordHasher(time_cost=2, memory_cost=19 * 1024, parallelism=1)

# Verified against when the username doesn't exist, so "unknown user" and
# "wrong password" take the same time and can't be told apart.
_DUMMY_HASH = _hasher.hash("shahmaat-dummy-password-for-timing")


async def hash_password(password: str) -> str:
    return await asyncio.to_thread(_hasher.hash, password)


async def verify_password(stored_hash: str | None, password: str) -> bool:
    def _verify() -> bool:
        try:
            return _hasher.verify(stored_hash or _DUMMY_HASH, password) and stored_hash is not None
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False

    return await asyncio.to_thread(_verify)


def needs_rehash(stored_hash: str) -> bool:
    return _hasher.check_needs_rehash(stored_hash)
