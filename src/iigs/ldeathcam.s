;;; Boss replay state and camera placement. Screen transitions run outside
;;; the simulation batch; thinkerless waits keep the completed boss visible.
#include "logic.inc"
#include "logic_dp.inc"
#if !defined(WOLF_SPEAR)
              .section registeredlogic, text, root, noreorder
              .public A_StartDeathCam, DeathCamPosition
              .extern NewState, ProjectileAim, ProjectileFraction
PLAYER        .equ OBJLIST

A_StartDeathCam:
              ldx dp:L_OB
              stx abs:V_deathcam_actor
              lda abs:V_deathcam_phase
              cmp ##2
              beq cameraReplayDone
              lda ##1
              sta abs:V_deathcam_phase
              sta abs:V_victoryflag
              lda ##s_deathcam
              sta abs:PLAYER+O_STATE
              stz abs:PLAYER+O_TICS
              bra cameraWait
cameraReplayDone:
              inc abs:V_deathcam_phase
cameraWait:   lda abs:O_CLASS,x
              asl a
              tax
              lda long:cameraWaitStates,x
              tay
              ldx dp:L_OB
              jmp abs:.word0 (NewState)
cameraWaitStates:
              .word 0,0,0,0,0,0,0,0,s_schabbwaitcam,0,0,0,0,0,0,0,s_hitlerwaitcam,0,s_giftwaitcam,s_fatwaitcam
cameraReplayStates:
              .word 0,0,0,0,0,0,0,0,s_schabbdeathcam,0,0,0,0,0,0,0,s_hitlerdeathcam,0,s_giftdeathcam,s_fatdeathcam

;;; JSL, keeps the caller's P/DB/D. Original kill coordinates set the camera
;;; angle, then a PLAYERSIZE box moves away from the boss until walls clear.
DeathCamPosition:
              php
              rep #0x30
              phb
              phd
              pea #LOGICBANK*257
              plb
              plb
              lda ##LOGICDP
              tcd
              lda abs:V_killx
              sta abs:PLAYER+O_X
              lda abs:V_killx_hi
              sta abs:PLAYER+O_X+2
              lda abs:V_killy
              sta abs:PLAYER+O_Y
              lda abs:V_killy_hi
              sta abs:PLAYER+O_Y+2
              ldx abs:V_deathcam_actor
              stx dp:L_OB
              jsr abs:.word0 (ProjectileAim)
              clc
              adc ##180
              cmp ##360
              bcc cameraAngle
              sbc ##360
cameraAngle:  sta abs:PLAYER+O_ANGLE
              lda ##0x4000
              sta dp:L_MOVE
              lda ##1
              sta dp:L_MOVE+2
cameraPlace:  lda abs:PLAYER+O_ANGLE
              asl a
              asl a
              clc
              adc ##SINTAB+360
              tay
              jsr abs:.word0 (ProjectileFraction)
              ldx dp:L_OB
              lda abs:O_X,x
              sec
              sbc dp:L_PB
              sta abs:PLAYER+O_X
              lda abs:O_X+2,x
              sbc dp:L_PB+2
              sta abs:PLAYER+O_X+2
              tya
              sec
              sbc ##360
              tay
              jsr abs:.word0 (ProjectileFraction)
              ldx dp:L_OB
              lda abs:O_Y,x
              clc
              adc dp:L_PB
              sta abs:PLAYER+O_Y
              lda abs:O_Y+2,x
              adc dp:L_PB+2
              sta abs:PLAYER+O_Y+2
              lda dp:L_MOVE
              clc
              adc ##0x1000
              sta dp:L_MOVE
              bcc cameraCheck
              inc dp:L_MOVE+2
cameraCheck:  jsr abs:.word0 (cameraWalls)
              bcc cameraPlace
              lda abs:PLAYER+O_X+1
              sta abs:V_plux
              lda abs:PLAYER+O_Y+1
              sta abs:V_pluy
              lda abs:PLAYER+O_X+2
              sta abs:PLAYER+O_TILEX
              lda abs:PLAYER+O_Y+2
              sta abs:PLAYER+O_TILEY
              lda ##1
              sta dp:L_VISDIRTY
              ldx dp:L_OB
              lda abs:O_CLASS,x
              asl a
              tax
              lda long:cameraReplayStates,x
              tay
              ldx dp:L_OB
              jsr abs:.word0 (NewState)
              lda ##2
              sta abs:V_deathcam_phase
              pld
              plb
              plp
              rtl

cameraWalls:  lda abs:PLAYER+O_X
              cmp ##0x5800
              lda abs:PLAYER+O_X+2
              sbc ##0
              sta dp:L_XL
              lda abs:PLAYER+O_X
              cmp ##0xa800
              lda abs:PLAYER+O_X+2
              adc ##0
              sta dp:L_XH
              lda abs:PLAYER+O_Y
              cmp ##0x5800
              lda abs:PLAYER+O_Y+2
              sbc ##0
              sta dp:L_YL
              lda abs:PLAYER+O_Y
              cmp ##0xa800
              lda abs:PLAYER+O_Y+2
              adc ##0
              sta dp:L_YH
              lda dp:L_YL
              sta dp:L_Y
cameraWallRow:lda dp:L_XL
              sta dp:L_X
cameraWallCell:
              lda dp:L_X
              asl a
              asl a
              asl a
              asl a
              asl a
              asl a
              clc
              adc dp:L_Y
              asl a
              tay
              lda abs:ACTORAT,y
              beq cameraCellClear
              cmp ##OBJLIST
              bcc cameraBlocked
cameraCellClear:
              inc dp:L_X
              lda dp:L_XH
              cmp dp:L_X
              bcs cameraWallCell
              inc dp:L_Y
              lda dp:L_YH
              cmp dp:L_Y
              bcs cameraWallRow
              sec
              rts
cameraBlocked:clc
              rts
#endif
