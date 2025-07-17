from __future__ import annotations
from typing import Any
import logging, asyncio
from homeassistant.core import HomeAssistant
from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.const import CONF_NAME
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from .const import *
from .codec import build_operational_command

_LOGGER = logging.getLogger(__name__)

class Tr198aFan(FanEntity, RestoreEntity):
    _attr_supported_features = (
        FanEntityFeature.SET_SPEED | FanEntityFeature.DIRECTION | FanEntityFeature.TURN_ON | FanEntityFeature.TURN_OFF 
    )
    _speed_range = (1, 10)

    def __init__(self,
                 hass: HomeAssistant,
                 name: str,
                 remote_entity: str,
                 handset_id: int):
        self.hass = hass
        self._attr_name          = name
        self._attr_unique_id     = f"tr198a_{handset_id:04x}"
        self._remote_entity_id   = remote_entity
        self._handset_id         = handset_id
        self._state: dict[str, Any] = DEF_STATE.copy()
        self._prev_speed: int = 5      # default «remembered» speed
        self._dev_id = (DOMAIN, f"{handset_id:04x}")
        

    # ─────── internal helpers ───────
    async def async_send_base64(self, cmd: str):
        """Low-level helper used by both fan actions & buttons."""
        await self.hass.services.async_call(
            "remote",
            "send_command",
            {
                "entity_id": self._remote_entity_id,   # ← back to schema-approved key
                "command": [cmd],
            },
            blocking=True,
        )

    async def _tx(self, **kwargs):
        """Build packet, transmit, but don’t touch state."""
        cmd = build_operational_command(self._handset_id, **kwargs)
        await self.async_send_base64(cmd)

    # ─────── FanEntity API ───────
    @property
    def percentage(self):
        return self._state[ATTR_SPEED]*10

    async def async_set_percentage(self, percentage: int):
        speed = round(percentage/10)
        if speed > 0:
           self._prev_speed = speed   # remember last running speed
        await self._tx(speed=speed)
        self._state[ATTR_SPEED] = speed
        self.async_write_ha_state()

    async def async_turn_on(self, *positional, **kwargs):
        """Turn on to either:
           • percentage passed by HA (new API), or
           • remembered speed (fallback)."""
        # HA still sometimes calls (speed, percentage, preset_mode, ...)
        percentage = (
            kwargs.get("percentage")                 # new API
            or (positional[1] if len(positional) > 1 else None)  # old style
        )

        if percentage is None:           # no value given → use remembered speed
            percentage = self._prev_speed * 10

        await self.async_set_percentage(int(percentage))

    async def async_turn_off(self, **kwargs):
        await self._tx(speed=0)
        self._state[ATTR_SPEED] = 0
        self.async_write_ha_state()

    @property
    def direction(self):
        return self._state[ATTR_DIRECTION]

    async def async_set_direction(self, direction: str):
        await self._tx(direction=direction)
        self._state[ATTR_DIRECTION] = direction
        self.async_write_ha_state()

    # ─────── RestoreEntity ───────
    async def async_added_to_hass(self):
        if (state := await self.async_get_last_state()) is not None:
            self._state[ATTR_SPEED]     = int(state.attributes.get(ATTR_SPEED, 0))
            self._state[ATTR_DIRECTION] = state.attributes.get(ATTR_DIRECTION, "reverse")

    # ─────── state attributes ───────
    @property
    def extra_state_attributes(self):
        return {
            ATTR_SPEED: self._state[ATTR_SPEED],
            ATTR_DIRECTION: self._state[ATTR_DIRECTION],
            ATTR_TIMER: self._state[ATTR_TIMER],
            ATTR_BREEZE: self._state[ATTR_BREEZE],
            ATTR_LIGHT: self._state[ATTR_LIGHT],
            ATTR_HANDSET_ID: hex(self._handset_id),
        }
    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={self._dev_id},
            name=self._attr_name,
            manufacturer="TR-198A",
            model="Ceiling-Fan Remote",
            via_device=None,   # or point to your RM4’s device if you like
        )

async def async_setup_entry(
    hass, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    data = entry.data
    name        = data.get(CONF_NAME) or f"TR198A Fan {data['handset_id']:04X}"
    fan = Tr198aFan(hass, name, data["remote_entity_id"], data["handset_id"])
    async_add_entities([fan])
    hass.data[DOMAIN][entry.entry_id]["fan_unique_id"] = fan.unique_id
    hass.data[DOMAIN][entry.entry_id]["fan_entity"]    = fan  # ← give buttons direct access