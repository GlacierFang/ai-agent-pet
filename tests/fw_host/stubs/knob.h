#pragma once
#define PETD_EV_PRESS "press"
#define PETD_EV_ROT "rot"
#define PETD_EV_ROT_PRESS "rot_press"
typedef struct { const char *ev; int dir; int ms; int steps; } knob_event_t;
