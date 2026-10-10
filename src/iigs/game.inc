;;; Gameplay projections share the paused menu frame. Menu composition marks
;;; them cold; PrepareSprites rebuilds them before the next rendered picture.

#include "memmap.inc"
PX .equ 0x00
PY .equ 0x02
ANGLE .equ 0x04

VISSTAMP .equ 0x5a
