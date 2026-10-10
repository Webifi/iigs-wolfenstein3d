;;; Direct page of the exact logic: D = LOGICDP while it runs, DBR = $30.

L_XREC         .equ L_ANGLE
L_YREC         .equ L_DIST
L_MLO          .equ L_PD
L_MHI          .equ L_PD+2
L_MPTR         .equ L_V
;;; Ray scratch is dead throughout refreshActors and its projection helpers.
L_SROW         .equ L_XTILE
L_SEND         .equ L_YTILE
L_DCUR         .equ L_RAY               ; ray scratch is dead during world updates
#include "memmap.inc"
#include "sight.inc"

;;; Movement-box scratch is unused by ray setup and its multiplication helpers.
L_XUPLO        .equ L_XL
L_XUPHI        .equ L_XH
L_XDNLO        .equ L_YL
L_XDNHI        .equ L_YH
L_YUPLO        .equ L_X
L_YUPHI        .equ L_Y
L_YDNLO        .equ L_MOVE
L_YDNHI        .equ L_MOVE+2

L_RAYMPTR      .equ L_PARTIAL       ; the low byte stays zero through the ray pass
