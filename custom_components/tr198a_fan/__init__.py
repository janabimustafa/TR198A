from __future__ import annotations
import logging
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

async def async_setup(hass: HomeAssistant, _: dict) -> bool:
    return True                                    # YAML disabled

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {}
    # ← we forward to fan, button, AND light platforms
    await hass.config_entries.async_forward_entry_setups(entry, {"fan"})
    await hass.config_entries.async_forward_entry_setups(entry, {"button", "light"})
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, {"fan", "button", "light"})
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unloaded