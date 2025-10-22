"""Utility functions for Lock Code Manager."""

from __future__ import annotations


def generate_entity_unique_id(
    entry_id: str,
    slot_key: str | int,
    entity_key: str,
) -> str:
    """
    Generate unique ID for standard slot entities.

    Standard entities include: name, PIN, enabled, active, number_of_uses, events.

    Args:
        entry_id: Config entry ID
        slot_key: Slot number/key
        entity_key: Entity type key (e.g., "name", "pin", "enabled", "active")

    Returns:
        Unique ID in format: {entry_id}|{slot_key}|{entity_key}

    """
    return f"{entry_id}|{slot_key}|{entity_key}"


def generate_lock_entity_unique_id(
    entry_id: str,
    slot_key: str | int,
    entity_key: str,
    lock_entity_id: str,
) -> str:
    """
    Generate unique ID for lock-specific entities.

    Lock-specific entities include: code sensors, in-sync binary sensors.

    Args:
        entry_id: Config entry ID
        slot_key: Slot number/key
        entity_key: Entity type key (e.g., "code", "in_sync")
        lock_entity_id: Lock entity ID

    Returns:
        Unique ID in format: {entry_id}|{slot_key}|{entity_key}|{lock_entity_id}

    """
    return f"{entry_id}|{slot_key}|{entity_key}|{lock_entity_id}"


def generate_slot_device_identifier(
    entry_id: str,
    slot_key: str | int,
) -> tuple[str, str]:
    """
    Generate device identifier for a code slot.

    Args:
        entry_id: Config entry ID
        slot_key: Slot number/key

    Returns:
        Device identifier tuple in format: (DOMAIN, "{entry_id}|{slot_key}")

    """
    from .const import DOMAIN

    return (DOMAIN, f"{entry_id}|{slot_key}")
