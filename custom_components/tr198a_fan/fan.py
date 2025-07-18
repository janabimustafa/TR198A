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
from homeassistant.util.percentage import ranged_value_to_percentage, percentage_to_ranged_value
from homeassistant.util.scaling import int_states_in_range
import math
from .const import *
from .codec import build_operational_command

_LOGGER = logging.getLogger(__name__)
SPEED_RANGE: tuple[int, int] = (1, 9)       # 0 is *not* in the range
# List of user-facing preset names
PRESET_BREEZE = ["breeze_1", "breeze_2", "breeze_3"]

class Tr198aFan(FanEntity, RestoreEntity):
    _attr_supported_features = (
        FanEntityFeature.SET_SPEED 
        | FanEntityFeature.DIRECTION 
        | FanEntityFeature.TURN_ON 
        | FanEntityFeature.TURN_OFF
        | FanEntityFeature.PRESET_MODE 
    )
    _attr_preset_modes = PRESET_BREEZE
    _attr_translation_key = "tr198a_fan"
    # TR-198A has 9 discrete speeds (1-9) + 0 = off
    def __init__(self,
                 hass: HomeAssistant,
                 name: str,
                 remote_entity: str,
                 handset_id: int,
                 power_switch: str | None = None):
        self.hass = hass
        self._attr_name          = name
        self._attr_unique_id     = f"tr198a_{handset_id:04x}"
        self._remote_entity_id   = remote_entity
        self._handset_id         = handset_id
        self._state: dict[str, Any] = DEF_STATE.copy()
        self._state[ATTR_BREEZE] = None     # ensure key exists
        self._prev_speed: int = 5      # default «remembered» speed
        self._dev_id = (DOMAIN, f"{handset_id:04x}")
        self._power_switch_id    = power_switch
        self._attr_device_info = DeviceInfo(
            identifiers={self._dev_id},
            manufacturer="TR-198A",
            model="Ceiling-Fan Remote",
        )
        

    # ─────── internal helpers ───────
    async def _send_base64(self, cmd: str):
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

    # ───────────────── FULL‑STATE SENDER ─────────────────
    async def _send_state(self, *,
                          radio_repeats=None,
                          trailer_us=None,
                          **overrides):
        """
        Build & transmit a command that contains the **entire** current
        state, plus any *overrides* (speed change, light toggle …).
        """
        # Base = current remembered state
        base = dict(
            speed=self._state[ATTR_SPEED],
            direction=self._state[ATTR_DIRECTION],
            timer=self._state[ATTR_TIMER],
            breeze=self._state[ATTR_BREEZE],
            light_toggle=False,
        )
        base.update(overrides)                   # apply caller’s changes
        if radio_repeats is not None:
            base["radio_repeats"] = radio_repeats
        if trailer_us is not None:
            base["trailer_us"] = trailer_us

        cmd = build_operational_command(self._handset_id, **base)
        await self._ensure_power_on()  # ensure power switch is on
        await self._send_base64(cmd)
    async def _ensure_power_on(self) -> None:
        """
        If a power-switch is configured and currently OFF, turn it on and wait
        one state update (max 2 sec); skip otherwise.
        """
        if not self._power_switch_id:
            return

        if (state := self.hass.states.get(self._power_switch_id)) and state.state == "on":
            return

        await self.hass.services.async_call(
            "switch", "turn_on", {"entity_id": self._power_switch_id}, blocking=True
        )

        # wait briefly for the state machine to reflect the change (<= 2 s)
        try:
            # Poll the state for up to 2 s so we don’t race the next RF send
            for _ in range(20):          # 20 × 0.1 s = 2 s
                await asyncio.sleep(0.1)
                if (st := self.hass.states.get(self._power_switch_id)) and st.state == "on":
                    break
        except asyncio.TimeoutError:
            # Proceed anyway; most switches switch quickly
            pass
    # ─────── FanEntity API ───────
    @property
    def percentage(self):
        """Return current speed as 0-100 % (or None if off)."""
        return ranged_value_to_percentage(SPEED_RANGE, self._state[ATTR_SPEED])
    @property
    def speed_count(self) -> int:
        """Return number of discrete speeds the fan supports (excluding off)."""
        return int_states_in_range(SPEED_RANGE)

    async def async_set_percentage(self, percentage: int):
        # Convert 0-100 % → 1-9.  round UP to ensure >0 % becomes speed 1
        speed = math.ceil(percentage_to_ranged_value(SPEED_RANGE, percentage))
        speed = min(speed, SPEED_RANGE[1])  # clamp to max speed
        if speed > 0:
            self._prev_speed = speed # remember last running speed
        await self._send_state(speed=speed, breeze=None)
        self._state[ATTR_SPEED] = speed
        self._state[ATTR_BREEZE] = None  # reset breeze mode
        self.async_write_ha_state()

    async def async_turn_on(self, *positional, **kwargs):
        """
        HA can still pass legacy positional args (speed, percentage, preset),
        so we first look in **kwargs**, then fall back to the 2nd positional.
        If nothing is supplied, we restore the last remembered speed.
        """
        percentage = (
            kwargs.get("percentage")                 # new API
            or (positional[1] if len(positional) > 1 else None)  # old style
        )

        if percentage is not None:           # no value given → use remembered speed
            speed = math.ceil(percentage_to_ranged_value(SPEED_RANGE, percentage))
            speed = max(1, min(speed, SPEED_RANGE[1]))  # clamp to 1-9
        else:
            speed = self._prev_speed

        await self._send_state(speed=speed, breeze=None)
        self._state[ATTR_SPEED] = speed
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs):
        await self._send_state(speed=0, breeze=None)
        self._state[ATTR_SPEED] = 0
        self._state[ATTR_BREEZE] = None  # reset breeze mode
        self.async_write_ha_state()

    @property
    def direction(self):
        return self._state[ATTR_DIRECTION]

    async def async_set_direction(self, direction: str):
        if direction not in ("forward", "reverse"):
            raise ValueError(f"Invalid direction: {direction}")
        
        await self._send_state(direction=direction)
        self._state[ATTR_DIRECTION] = direction
        self.async_write_ha_state()
    @property
    def preset_mode(self) -> Optional[str]:
        lvl = self._state[ATTR_BREEZE]
        return None if lvl is None else PRESET_BREEZE[lvl - 1]

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set one of the three breeze modes."""
        if preset_mode not in PRESET_BREEZE:
            raise ValueError(f"Unsupported preset {preset_mode}")

        level = PRESET_BREEZE.index(preset_mode) + 1  # 1,2,3
        await self._send_state(breeze=level, speed=None)  # speed bits replaced
        self._state[ATTR_BREEZE] = level
        self.async_write_ha_state()
    # ─────── RestoreEntity ───────
    async def async_added_to_hass(self):
        if (state := await self.async_get_last_state()) is not None:
            self._state[ATTR_SPEED]     = int(state.attributes.get(ATTR_SPEED, 0))
            self._state[ATTR_DIRECTION] = state.attributes.get(ATTR_DIRECTION, "reverse")
            self._state[ATTR_BREEZE]    = state.attributes.get(ATTR_BREEZE)

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

async def async_setup_entry(
    hass, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    data = entry.data
    name        = data.get(CONF_NAME) or f"TR198A Fan {data['handset_id']:04X}"
    switch_id = entry.options.get("power_switch_entity_id") or data.get(
        "power_switch_entity_id"
    )
    fan = Tr198aFan(hass, name, data["remote_entity_id"], data["handset_id"], power_switch=switch_id,
)
    async_add_entities([fan])
    hass.data[DOMAIN][entry.entry_id]["fan_unique_id"] = fan.unique_id
    hass.data[DOMAIN][entry.entry_id]["fan_entity"]    = fan  # ← give buttons direct access