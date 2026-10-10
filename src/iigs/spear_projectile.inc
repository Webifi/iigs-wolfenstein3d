;;; L_OB identifies the shooter. ProjectileAim supplies a heading in
;;; degrees; copyOrigin gives the new actor the shooter's position. The Death
;;; Knight also fires a normal shot and alternates missile aim by +/-4 degrees.
;;; Angel shots use spark states; other shooters use the rocket state.
              .public T_Launch
              .extern T_Shoot
T_Launch:    ldx dp:L_OB
              jsr abs:.word0 (ProjectileAim)
              lda abs:O_CLASS,x
              cmp ##26
              bne spearLaunch
              lda dp:L_ANGLE
              pha
              jsr abs:.word0 (T_Shoot)
              pla
              ldx dp:L_OB
              ldy abs:O_STATE,x
              cpy ##s_deathshoot2
              bne knightRight
              sec
              sbc ##4
              bpl knightAngle
              clc
              adc ##360
              bra knightAngle
knightRight: clc
              adc ##4
              cmp ##360
              bcc knightAngle
              sbc ##360
knightAngle: sta dp:L_ANGLE
spearLaunch: jsr abs:.word0 (GetNewActor)
              jsr abs:.word0 (copyOrigin)
              lda ##s_rocket
              sta abs:O_STATE,x
              lda ##20
              sta abs:O_CLASS,x
              ldy dp:L_OB
              lda abs:O_CLASS,y
              cmp ##26
              bne spearAngelShot
              lda ##s_hrocket
              sta abs:O_STATE,x
              lda ##27
              sta abs:O_CLASS,x
              lda ##KNIGHTMISSILESND
              bra spearFireSound
spearAngelShot:
              cmp ##22
              bne spearRocketShot
              lda ##s_spark1
              sta abs:O_STATE,x
              lda ##28
              sta abs:O_CLASS,x
              lda ##ANGELFIRESND
              bra spearFireSound
spearRocketShot:
              lda ##MISSILEFIRESND
spearFireSound:
              jsr abs:.word0 (LogicSound)
              lda ##1
              sta abs:O_TICS,x
              sta abs:O_ACTIVE,x
              lda ##8
              sta abs:O_DIR,x
              lda dp:L_ANGLE
              sta abs:O_ANGLE,x
              lda ##0x2000
              sta abs:O_SPEED,x
              lda ##128
              sta abs:O_FLAGS,x
              rts
