;;; Spear-only actor actions, using the shared actor record and movement code.
              .public T_UShoot, A_Breathing, A_Dormant, A_StartAttack, A_Relaunch, A_Victory
              .extern T_Shoot, NewState
;;; L_OB is the attacking actor. The normal shot is followed by 10 points
;;; of contact damage when tileDistance is less than two.
T_UShoot:     jsr abs:.word0 (T_Shoot)
              ldx dp:L_OB
              jsr abs:.word0 (tileDistance)
              lda dp:L_DIST
              cmp ##2
              bcs spearActionDone
              lda ##10
              jmp abs:.word0 (TakeDamage)
A_Breathing:  lda ##ANGELTIREDSND
              jmp abs:.word0 (LogicSound)
A_Victory:    lda ##6
              sta abs:V_playstate
              rts
A_StartAttack:
              ldx dp:L_OB
              stz abs:O_TEMP2,x
              rts
A_Relaunch:   ldx dp:L_OB
              inc abs:O_TEMP2,x
              lda abs:O_TEMP2,x
              cmp ##3
              beq angelTired
              jsr abs:.word0 (Rnd)
              and ##1
              beq spearActionDone
              ldy ##s_angelchase1
              jmp abs:.word0 (NewState)
angelTired:   ldy ##s_angeltired
              jmp abs:.word0 (NewState)
spearActionDone:
              rts

;;; A dormant spectre cannot wake within one tile of the player on both
;;; axes. Its box extends 0x5800 in 16.16 units on each side and must contain
;;; no wall, door or shootable actor. Other actor marks do not block revival.
A_Dormant:    ldx dp:L_OB
              lda abs:O_X,x
              sec
              sbc abs:PLAYER+O_X
              sta dp:L_T
              lda abs:O_X+2,x
              sbc abs:PLAYER+O_X+2
              jsr abs:.word0 (spearOutsideTile)
              bcs dormantBox
              lda abs:O_Y,x
              sec
              sbc abs:PLAYER+O_Y
              sta dp:L_T
              lda abs:O_Y+2,x
              sbc abs:PLAYER+O_Y+2
              jsr abs:.word0 (spearOutsideTile)
              bcc spearActionDone
dormantBox:  lda abs:O_X,x
              sec
              sbc ##0x5800
              lda abs:O_X+2,x
              sbc ##0
              sta dp:L_XL
              lda abs:O_X,x
              clc
              adc ##0x5800
              lda abs:O_X+2,x
              adc ##0
              sta dp:L_XH
              lda abs:O_Y,x
              sec
              sbc ##0x5800
              lda abs:O_Y+2,x
              sbc ##0
              sta dp:L_YL
              lda abs:O_Y,x
              clc
              adc ##0x5800
              lda abs:O_Y+2,x
              adc ##0
              sta dp:L_YH
              lda dp:L_YL
              sta dp:L_Y
dormantRow:  lda dp:L_XL
              sta dp:L_X
dormantCell: lda dp:L_X
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
              beq dormantClear
              cmp ##OBJLIST
              bcc dormantBlocked
              tay
              lda abs:O_FLAGS,y
              bit ##1
              bne dormantBlocked
dormantClear:inc dp:L_X
              lda dp:L_XH
              cmp dp:L_X
              bcs dormantCell
              inc dp:L_Y
              lda dp:L_YH
              cmp dp:L_Y
              bcs dormantRow
              ldx dp:L_OB
              lda abs:O_FLAGS,x
              ora ##65
              and ##0xffef
              sta abs:O_FLAGS,x
              lda ##8
              sta abs:O_DIR,x
              ldy ##s_spectrewait1
              jmp abs:.word0 (NewState)
dormantBlocked:
              rts
;;; Carry set if signed A:L_T lies outside [-65536,65536].
spearOutsideTile:
              bmi outsideNegative
              cmp ##1
              bcc outsideNo
              bne outsideYes
              lda dp:L_T
              beq outsideNo
outsideYes:  sec
              rts
outsideNegative:
              cmp ##0xffff
              bne outsideYes
outsideNo:   clc
              rts
