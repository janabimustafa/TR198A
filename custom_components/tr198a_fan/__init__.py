from __future__ import annotations
import logging
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """No YAML support; everything goes through UI config-flow."""
    return True

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Forward the entry to the fan & button platforms."""
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {}
    await hass.config_entries.async_forward_entry_setups(entry, {"fan", "button"})
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Remove the platforms when the entry is deleted."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, {"fan", "button"})
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unloaded