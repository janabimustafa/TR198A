DOMAIN = "tr198a_fan"

ATTR_REMOTE          = "remote_entity_id"
ATTR_HANDSET_ID      = "handset_id"      # 13-bit int or hex str
ATTR_SPEED           = "speed"           # 0-10
ATTR_DIRECTION       = "direction"       # "forward"/"reverse"
ATTR_TIMER           = "timer"           # 2/4/8/None
ATTR_BREEZE          = "breeze"          # 1/2/3/None
ATTR_LIGHT           = "light_on"        # bool
ATTR_POWER           = "power_on"        # bool (speed>0)

SERVICE_PAIR         = "pair"
SERVICE_LIGHT_TOGGLE = "light_toggle"
SERVICE_DIM_UP       = "dim_up"
SERVICE_DIM_DOWN     = "dim_down"

# default values
DEF_STATE = {
    ATTR_SPEED: 0,
    ATTR_DIRECTION: "reverse",
    ATTR_TIMER: None,
    ATTR_BREEZE: None,
    ATTR_LIGHT: False,
}