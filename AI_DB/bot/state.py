from __future__ import annotations
from typing import Dict

_attach_targets: Dict[int, int] = {}


def set_attach_target(user_id: int, listing_id: int) -> None:
	_attach_targets[user_id] = listing_id


def pop_attach_target(user_id: int) -> int | None:
	return _attach_targets.pop(user_id, None)


def get_attach_target(user_id: int) -> int | None:
	return _attach_targets.get(user_id)