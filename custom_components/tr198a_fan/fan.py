from __future__ import annotations
from typing import Any
import logging, asyncio
from homeassistant.components.fan import FanEntity, RestoreEntity, FanEntityFeature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.const import STATE_OFF

from .const import *
from .codec import build_operational_command

_LOGGER = logging.getLogger(__name__)

class Tr198aFan(FanEntity, RestoreEntity):
    _attr_supported_features = (
        FanEntityFeature.SET_SPEED | FanEntityFeature.DIRECTION
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

    # ─────── internal helpers ───────
    async def _tx(self, **kwargs):
        cmd = build_operational_command(self._handset_id, **kwargs)

        await self.hass.services.async_call(
            "remote",
            "send_command",
            {
                # ←––––  new style –––––→
                "target": {"entity_id": [self._remote_entity_id]},
                "command": [cmd],
            },
            blocking=True,
        )

    # ─────── FanEntity API ───────
    @property
    def percentage(self):
        return self._state[ATTR_SPEED]*10

    async def async_set_percentage(self, percentage: int):
        speed = round(percentage/10)
        await self._tx(speed=speed)
        self._state[ATTR_SPEED] = speed
        self.async_write_ha_state()

    async def async_turn_on(self, percentage: int | None = None, **kwargs):
        if percentage is None:
            percentage = 50
        await self.async_set_percentage(percentage)

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