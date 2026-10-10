              .extern campaignLocal
;;; HUD fields use the art and palette assignments from tools/build_ui.py.
;;; SHR palettes 1..12 each serve one status-bar row.
;;; Mutation handlers call this directly; an idle frame does no HUD work.
;;; Only changed fields paint. Decimal subtraction occurs on HUD events.
#include "memmap.inc"
#include "game.inc"
#include "campaign.inc"
#ifdef CAMPAIGN_SPEAR
#include "logic.inc"
#endif
              .section gamecode, text, root, noreorder
              .public InitHUD, UpdateHUD
              .extern hudDirty, health, ammo, keys, lives, score, weapon
              .extern RefreshFlash

InitHUD:      lda ##65535
              ldx ##38
clearHudCache:sta abs:.word0 (hudOld),x
              dex
              dex
              bpl clearHudCache
              lda ##1
              sta abs:.word0 (hudDirty)
              sep #0x20
              ldx ##39
statusSCB:    lda abs:.word0 (uiRows),x
              sta long:SHR_SCB + 160,x
              dex
              bpl statusSCB
              rep #0x20
              php
              sei
              ldx ##382
statusPalette:lda abs:.word0 (uiPal),x
              sta long:PALBUF+0x20,x       ; palettes 1-12, published with the view
              dex
              dex
              bpl statusPalette
              plp
              jsl long:RefreshFlash
              lda ##0
              ldx ##25600
              jsr abs:.word0 (HudPic)
              jmp abs:.word0 (UpdateHUD)

UpdateHUD:    lda abs:.word0 (hudDirty)
              bne dirtyHUD
              rts
dirtyHUD:     stz abs:.word0 (hudDirty)
              lda abs:.word0 (levelIndex)
              cmp abs:.word0 (hudOld)
              beq hudScore
              sta abs:.word0 (hudOld)
              asl a
              tax
              lda long:campaignLocal,x
#ifdef WOLF_SPEAR
              cpx ##40
              bne hudFloorNumber
              lda ##18
hudFloorNumber:
#endif
              ldx ##28168
              ldy ##2
              jsr abs:.word0 (HudNumber)
hudScore:     lda abs:.word0 (score)
              cmp abs:.word0 (hudOld+2)
              bne paintScore
              lda abs:.word0 (score+2)
              cmp abs:.word0 (hudOld+4)
              beq hudLives
paintScore:   lda abs:.word0 (score)
              sta abs:.word0 (hudOld+2)
              sta dp:AI_X
              lda abs:.word0 (score+2)
              sta abs:.word0 (hudOld+4)
              sta dp:AI_Y
              jsr abs:.word0 (HudScore)
hudLives:     lda abs:.word0 (lives)
              cmp abs:.word0 (hudOld+6)
              beq hudHealth
              sta abs:.word0 (hudOld+6)
              ldx ##28216
              ldy ##1
              jsr abs:.word0 (HudNumber)
hudHealth:    lda abs:.word0 (health)
              cmp abs:.word0 (hudOld+8)
#ifdef WOLF_SPEAR
              beq hudHealthFace
#else
              beq hudAmmo
#endif
              sta abs:.word0 (hudOld+8)
              ldx ##28244
              ldy ##3
              jsr abs:.word0 (HudNumber)
#ifdef WOLF_SPEAR
              .public hudHealthFace, hudFace
hudHealthFace:
              lda abs:.word0 (health)
              beq hudDeadFace
              lda long:LOGIC_BASE+V_ouchface
              bne hudOuchFace
              lda long:LOGIC_BASE+V_gotgatgun
              bne hudGunFace
              lda abs:.word0 (health)
#else
              lda abs:.word0 (health)
              beq hudDeadFace
#endif
              sta dp:AI_TMP
              lda ##100
              sec
              sbc dp:AI_TMP
              lsr a
              lsr a
              lsr a
              lsr a
              sta dp:AI_TMP
              asl a
              clc
              adc dp:AI_TMP
#ifdef WOLF_SPEAR
              adc ##19
              adc long:LOGIC_BASE+V_faceframe
#else
              adc ##20                  ; middle face in each original band
#endif
              bra hudFace
#ifdef WOLF_SPEAR
hudOuchFace:  lda ##42
              bra hudFace
hudGunFace:   lda ##41
              bra hudFace
#endif
hudDeadFace:  lda ##40
hudFace:
#ifdef WOLF_SPEAR
              cmp abs:.word0 (hudOld+16)
              beq hudAmmo
              sta abs:.word0 (hudOld+16)
#endif
              ldx ##26308
              jsr abs:.word0 (HudPic)
hudAmmo:      lda abs:.word0 (ammo)
              cmp abs:.word0 (hudOld+10)
              beq hudKeys
              sta abs:.word0 (hudOld+10)
              ldx ##28268
              ldy ##2
              jsr abs:.word0 (HudNumber)
hudKeys:      lda abs:.word0 (keys)
              cmp abs:.word0 (hudOld+12)
              beq hudWeapon
              sta abs:.word0 (hudOld+12)
              bit ##1
              beq hudNoGold
              lda ##6
              bra hudGold
hudNoGold:    lda ##5
hudGold:      ldx ##26360
              jsr abs:.word0 (HudPic)
              lda abs:.word0 (keys)
              bit ##2
              beq hudNoSilver
              lda ##7
              bra hudSilver
hudNoSilver:  lda ##43                  ; the empty key converted for the lower place
hudSilver:    ldx ##28920
              jsr abs:.word0 (HudPic)
hudWeapon:    lda abs:.word0 (weapon)
              cmp abs:.word0 (hudOld+14)
              beq hudFinished
              sta abs:.word0 (hudOld+14)
              inc a
              ldx ##27008
              jsr abs:.word0 (HudPic)
hudFinished:  rts

;;; One SHR word. Y indexes the picture in bank $0B and X is the screen byte.
HUDWORD .macro src, col
              lda abs:\src,y
              sta long:(SHR+\col),x
              .endm

;;; A is a picture index, X its screen byte offset. Data is preconverted;
;;; 16-bit stores copy two adjacent original pixels without a frame buffer.
HudPic:       stx dp:SP_OLD
              asl a
              sta dp:SP_TMP
              asl a
              clc
              adc dp:SP_TMP
              tax
              lda abs:.word0 (uiPics),x
              sta dp:ENTRY
              lda ##11
              sta dp:ENTRY+2
              lda abs:.word0 (uiPics+2),x
              sta dp:SP_RUNS
              lda abs:.word0 (uiPics+4),x
              sta dp:SP_LIMIT
              ldx dp:SP_OLD
              lda dp:SP_RUNS
              cmp ##4
              bne hudWide
              jmp abs:.word0 (hudBlitDigit)
hudWide:      cmp ##12
              bne hudNotFace
              jmp abs:.word0 (hudBlitFace)
hudNotFace:   cmp ##24
              bne hudBackground
              jmp abs:.word0 (hudBlitWeapon)
;;; Four nops keep HudPic the same length, so the code after it stays put.
hudBackground:
              nop
              nop
              nop
              nop
              ldy ##0
              jmp abs:.word0 (hudBlitRows)

HudNumber:    sta dp:SP_EXTRA
              stx dp:SP_NEW
              sty dp:SP_N
              stz dp:SP_SIGN
numberDigit:  lda dp:SP_N
              dec a
              asl a
              tax
              lda abs:.word0 (smallDivisors),x
              sta dp:SP_END
              stz dp:SP_ROW
              lda dp:SP_EXTRA
digitSubtract:cmp dp:SP_END
              bcc digitReady
              sec
              sbc dp:SP_END
              inc dp:SP_ROW
              bra digitSubtract
digitReady:   sta dp:SP_EXTRA
              lda dp:SP_ROW
              bne significantDigit
              lda dp:SP_SIGN
              bne significantDigit
              lda dp:SP_N
              cmp ##1
              beq significantDigit
              lda ##8
              bra paintDigit
significantDigit:
              inc dp:SP_SIGN
              lda dp:SP_ROW
              clc
              adc ##9
paintDigit:   ldx dp:SP_NEW
              jsr abs:.word0 (HudPic)
              lda dp:SP_NEW
              clc
              adc ##4
              sta dp:SP_NEW
              dec dp:SP_N
              bne numberDigit
              rts

HudScore:     lda ##28184
              sta dp:SP_NEW
              stz dp:SP_SIGN
              stz dp:SP_N
scoreDigit:   ldx dp:SP_N
              lda abs:.word0 (scoreDivisors),x
              sta dp:AI_XL
              lda abs:.word0 (scoreDivisors+2),x
              sta dp:AI_XH
              stz dp:SP_ROW
scoreSubtract:lda dp:AI_Y
              cmp dp:AI_XH
              bcc scoreReady
              bne scoreEnough
              lda dp:AI_X
              cmp dp:AI_XL
              bcc scoreReady
scoreEnough:  lda dp:AI_X
              sec
              sbc dp:AI_XL
              sta dp:AI_X
              lda dp:AI_Y
              sbc dp:AI_XH
              sta dp:AI_Y
              inc dp:SP_ROW
              bra scoreSubtract
scoreReady:   lda dp:SP_ROW
              cmp ##10
              bcc lastScoreDigit
              sec
              sbc ##10
              sta dp:SP_ROW
              bra scoreReady
lastScoreDigit:
              lda dp:SP_ROW
              bne scoreSignificant
              lda dp:SP_SIGN
              bne scoreSignificant
              lda dp:SP_N
              cmp ##20
              beq scoreSignificant
              lda ##8
              bra paintScoreDigit
scoreSignificant:
              inc dp:SP_SIGN
              lda dp:SP_ROW
              clc
              adc ##9
paintScoreDigit:
              ldx dp:SP_N
              cmp abs:.word0 (hudOld+18),x
              beq sameScoreDigit
              sta abs:.word0 (hudOld+18),x
              ldx dp:SP_NEW
              jsr abs:.word0 (HudPic)
sameScoreDigit:
              lda dp:SP_NEW
              clc
              adc ##4
              sta dp:SP_NEW
              lda dp:SP_N
              clc
              adc ##4
              sta dp:SP_N
              cmp ##24
              bcc scoreDigit
              rts


;;; Fixed shapes skip the row loop. Bank $0B holds the pictures; the
;;; interrupt saves DBR, and plb restores the caller's bank. This section
;;; stays out of the sprite code so those addresses do not move.
              .section hudfast, text, root
hudBlitRows:  lda dp:SP_RUNS
              lsr a
              sta dp:SP_TMP
hudWords:     lda [ENTRY],y
              sta long:SHR,x
              iny
              iny
              inx
              inx
              dec dp:SP_TMP
              bne hudWords
              txa
              clc
              adc ##160
              sec
              sbc dp:SP_RUNS
              tax
              dec dp:SP_LIMIT
              bne hudBlitRows
              rts
hudBlitDigit: ldy dp:ENTRY
              phb
              pea #0x0b0b
              plb
              plb
              HUDWORD 0, 0
              HUDWORD 2, 2
              HUDWORD 4, 160
              HUDWORD 6, 162
              HUDWORD 8, 320
              HUDWORD 10, 322
              HUDWORD 12, 480
              HUDWORD 14, 482
              HUDWORD 16, 640
              HUDWORD 18, 642
              HUDWORD 20, 800
              HUDWORD 22, 802
              HUDWORD 24, 960
              HUDWORD 26, 962
              HUDWORD 28, 1120
              HUDWORD 30, 1122
              HUDWORD 32, 1280
              HUDWORD 34, 1282
              HUDWORD 36, 1440
              HUDWORD 38, 1442
              HUDWORD 40, 1600
              HUDWORD 42, 1602
              HUDWORD 44, 1760
              HUDWORD 46, 1762
              HUDWORD 48, 1920
              HUDWORD 50, 1922
              HUDWORD 52, 2080
              HUDWORD 54, 2082
              HUDWORD 56, 2240
              HUDWORD 58, 2242
              HUDWORD 60, 2400
              HUDWORD 62, 2402
              plb
              rts
hudBlitFace:  ldy dp:ENTRY
              phb
              pea #0x0b0b
              plb
              plb
              HUDWORD 0, 0
              HUDWORD 2, 2
              HUDWORD 4, 4
              HUDWORD 6, 6
              HUDWORD 8, 8
              HUDWORD 10, 10
              HUDWORD 12, 160
              HUDWORD 14, 162
              HUDWORD 16, 164
              HUDWORD 18, 166
              HUDWORD 20, 168
              HUDWORD 22, 170
              HUDWORD 24, 320
              HUDWORD 26, 322
              HUDWORD 28, 324
              HUDWORD 30, 326
              HUDWORD 32, 328
              HUDWORD 34, 330
              HUDWORD 36, 480
              HUDWORD 38, 482
              HUDWORD 40, 484
              HUDWORD 42, 486
              HUDWORD 44, 488
              HUDWORD 46, 490
              HUDWORD 48, 640
              HUDWORD 50, 642
              HUDWORD 52, 644
              HUDWORD 54, 646
              HUDWORD 56, 648
              HUDWORD 58, 650
              HUDWORD 60, 800
              HUDWORD 62, 802
              HUDWORD 64, 804
              HUDWORD 66, 806
              HUDWORD 68, 808
              HUDWORD 70, 810
              HUDWORD 72, 960
              HUDWORD 74, 962
              HUDWORD 76, 964
              HUDWORD 78, 966
              HUDWORD 80, 968
              HUDWORD 82, 970
              HUDWORD 84, 1120
              HUDWORD 86, 1122
              HUDWORD 88, 1124
              HUDWORD 90, 1126
              HUDWORD 92, 1128
              HUDWORD 94, 1130
              HUDWORD 96, 1280
              HUDWORD 98, 1282
              HUDWORD 100, 1284
              HUDWORD 102, 1286
              HUDWORD 104, 1288
              HUDWORD 106, 1290
              HUDWORD 108, 1440
              HUDWORD 110, 1442
              HUDWORD 112, 1444
              HUDWORD 114, 1446
              HUDWORD 116, 1448
              HUDWORD 118, 1450
              HUDWORD 120, 1600
              HUDWORD 122, 1602
              HUDWORD 124, 1604
              HUDWORD 126, 1606
              HUDWORD 128, 1608
              HUDWORD 130, 1610
              HUDWORD 132, 1760
              HUDWORD 134, 1762
              HUDWORD 136, 1764
              HUDWORD 138, 1766
              HUDWORD 140, 1768
              HUDWORD 142, 1770
              HUDWORD 144, 1920
              HUDWORD 146, 1922
              HUDWORD 148, 1924
              HUDWORD 150, 1926
              HUDWORD 152, 1928
              HUDWORD 154, 1930
              HUDWORD 156, 2080
              HUDWORD 158, 2082
              HUDWORD 160, 2084
              HUDWORD 162, 2086
              HUDWORD 164, 2088
              HUDWORD 166, 2090
              HUDWORD 168, 2240
              HUDWORD 170, 2242
              HUDWORD 172, 2244
              HUDWORD 174, 2246
              HUDWORD 176, 2248
              HUDWORD 178, 2250
              HUDWORD 180, 2400
              HUDWORD 182, 2402
              HUDWORD 184, 2404
              HUDWORD 186, 2406
              HUDWORD 188, 2408
              HUDWORD 190, 2410
              HUDWORD 192, 2560
              HUDWORD 194, 2562
              HUDWORD 196, 2564
              HUDWORD 198, 2566
              HUDWORD 200, 2568
              HUDWORD 202, 2570
              HUDWORD 204, 2720
              HUDWORD 206, 2722
              HUDWORD 208, 2724
              HUDWORD 210, 2726
              HUDWORD 212, 2728
              HUDWORD 214, 2730
              HUDWORD 216, 2880
              HUDWORD 218, 2882
              HUDWORD 220, 2884
              HUDWORD 222, 2886
              HUDWORD 224, 2888
              HUDWORD 226, 2890
              HUDWORD 228, 3040
              HUDWORD 230, 3042
              HUDWORD 232, 3044
              HUDWORD 234, 3046
              HUDWORD 236, 3048
              HUDWORD 238, 3050
              HUDWORD 240, 3200
              HUDWORD 242, 3202
              HUDWORD 244, 3204
              HUDWORD 246, 3206
              HUDWORD 248, 3208
              HUDWORD 250, 3210
              HUDWORD 252, 3360
              HUDWORD 254, 3362
              HUDWORD 256, 3364
              HUDWORD 258, 3366
              HUDWORD 260, 3368
              HUDWORD 262, 3370
              HUDWORD 264, 3520
              HUDWORD 266, 3522
              HUDWORD 268, 3524
              HUDWORD 270, 3526
              HUDWORD 272, 3528
              HUDWORD 274, 3530
              HUDWORD 276, 3680
              HUDWORD 278, 3682
              HUDWORD 280, 3684
              HUDWORD 282, 3686
              HUDWORD 284, 3688
              HUDWORD 286, 3690
              HUDWORD 288, 3840
              HUDWORD 290, 3842
              HUDWORD 292, 3844
              HUDWORD 294, 3846
              HUDWORD 296, 3848
              HUDWORD 298, 3850
              HUDWORD 300, 4000
              HUDWORD 302, 4002
              HUDWORD 304, 4004
              HUDWORD 306, 4006
              HUDWORD 308, 4008
              HUDWORD 310, 4010
              HUDWORD 312, 4160
              HUDWORD 314, 4162
              HUDWORD 316, 4164
              HUDWORD 318, 4166
              HUDWORD 320, 4168
              HUDWORD 322, 4170
              HUDWORD 324, 4320
              HUDWORD 326, 4322
              HUDWORD 328, 4324
              HUDWORD 330, 4326
              HUDWORD 332, 4328
              HUDWORD 334, 4330
              HUDWORD 336, 4480
              HUDWORD 338, 4482
              HUDWORD 340, 4484
              HUDWORD 342, 4486
              HUDWORD 344, 4488
              HUDWORD 346, 4490
              HUDWORD 348, 4640
              HUDWORD 350, 4642
              HUDWORD 352, 4644
              HUDWORD 354, 4646
              HUDWORD 356, 4648
              HUDWORD 358, 4650
              HUDWORD 360, 4800
              HUDWORD 362, 4802
              HUDWORD 364, 4804
              HUDWORD 366, 4806
              HUDWORD 368, 4808
              HUDWORD 370, 4810
              HUDWORD 372, 4960
              HUDWORD 374, 4962
              HUDWORD 376, 4964
              HUDWORD 378, 4966
              HUDWORD 380, 4968
              HUDWORD 382, 4970
              plb
              rts
hudBlitWeapon:
              ldy dp:ENTRY
              phb
              pea #0x0b0b
              plb
              plb
              HUDWORD 0, 0
              HUDWORD 2, 2
              HUDWORD 4, 4
              HUDWORD 6, 6
              HUDWORD 8, 8
              HUDWORD 10, 10
              HUDWORD 12, 12
              HUDWORD 14, 14
              HUDWORD 16, 16
              HUDWORD 18, 18
              HUDWORD 20, 20
              HUDWORD 22, 22
              HUDWORD 24, 160
              HUDWORD 26, 162
              HUDWORD 28, 164
              HUDWORD 30, 166
              HUDWORD 32, 168
              HUDWORD 34, 170
              HUDWORD 36, 172
              HUDWORD 38, 174
              HUDWORD 40, 176
              HUDWORD 42, 178
              HUDWORD 44, 180
              HUDWORD 46, 182
              HUDWORD 48, 320
              HUDWORD 50, 322
              HUDWORD 52, 324
              HUDWORD 54, 326
              HUDWORD 56, 328
              HUDWORD 58, 330
              HUDWORD 60, 332
              HUDWORD 62, 334
              HUDWORD 64, 336
              HUDWORD 66, 338
              HUDWORD 68, 340
              HUDWORD 70, 342
              HUDWORD 72, 480
              HUDWORD 74, 482
              HUDWORD 76, 484
              HUDWORD 78, 486
              HUDWORD 80, 488
              HUDWORD 82, 490
              HUDWORD 84, 492
              HUDWORD 86, 494
              HUDWORD 88, 496
              HUDWORD 90, 498
              HUDWORD 92, 500
              HUDWORD 94, 502
              HUDWORD 96, 640
              HUDWORD 98, 642
              HUDWORD 100, 644
              HUDWORD 102, 646
              HUDWORD 104, 648
              HUDWORD 106, 650
              HUDWORD 108, 652
              HUDWORD 110, 654
              HUDWORD 112, 656
              HUDWORD 114, 658
              HUDWORD 116, 660
              HUDWORD 118, 662
              HUDWORD 120, 800
              HUDWORD 122, 802
              HUDWORD 124, 804
              HUDWORD 126, 806
              HUDWORD 128, 808
              HUDWORD 130, 810
              HUDWORD 132, 812
              HUDWORD 134, 814
              HUDWORD 136, 816
              HUDWORD 138, 818
              HUDWORD 140, 820
              HUDWORD 142, 822
              HUDWORD 144, 960
              HUDWORD 146, 962
              HUDWORD 148, 964
              HUDWORD 150, 966
              HUDWORD 152, 968
              HUDWORD 154, 970
              HUDWORD 156, 972
              HUDWORD 158, 974
              HUDWORD 160, 976
              HUDWORD 162, 978
              HUDWORD 164, 980
              HUDWORD 166, 982
              HUDWORD 168, 1120
              HUDWORD 170, 1122
              HUDWORD 172, 1124
              HUDWORD 174, 1126
              HUDWORD 176, 1128
              HUDWORD 178, 1130
              HUDWORD 180, 1132
              HUDWORD 182, 1134
              HUDWORD 184, 1136
              HUDWORD 186, 1138
              HUDWORD 188, 1140
              HUDWORD 190, 1142
              HUDWORD 192, 1280
              HUDWORD 194, 1282
              HUDWORD 196, 1284
              HUDWORD 198, 1286
              HUDWORD 200, 1288
              HUDWORD 202, 1290
              HUDWORD 204, 1292
              HUDWORD 206, 1294
              HUDWORD 208, 1296
              HUDWORD 210, 1298
              HUDWORD 212, 1300
              HUDWORD 214, 1302
              HUDWORD 216, 1440
              HUDWORD 218, 1442
              HUDWORD 220, 1444
              HUDWORD 222, 1446
              HUDWORD 224, 1448
              HUDWORD 226, 1450
              HUDWORD 228, 1452
              HUDWORD 230, 1454
              HUDWORD 232, 1456
              HUDWORD 234, 1458
              HUDWORD 236, 1460
              HUDWORD 238, 1462
              HUDWORD 240, 1600
              HUDWORD 242, 1602
              HUDWORD 244, 1604
              HUDWORD 246, 1606
              HUDWORD 248, 1608
              HUDWORD 250, 1610
              HUDWORD 252, 1612
              HUDWORD 254, 1614
              HUDWORD 256, 1616
              HUDWORD 258, 1618
              HUDWORD 260, 1620
              HUDWORD 262, 1622
              HUDWORD 264, 1760
              HUDWORD 266, 1762
              HUDWORD 268, 1764
              HUDWORD 270, 1766
              HUDWORD 272, 1768
              HUDWORD 274, 1770
              HUDWORD 276, 1772
              HUDWORD 278, 1774
              HUDWORD 280, 1776
              HUDWORD 282, 1778
              HUDWORD 284, 1780
              HUDWORD 286, 1782
              HUDWORD 288, 1920
              HUDWORD 290, 1922
              HUDWORD 292, 1924
              HUDWORD 294, 1926
              HUDWORD 296, 1928
              HUDWORD 298, 1930
              HUDWORD 300, 1932
              HUDWORD 302, 1934
              HUDWORD 304, 1936
              HUDWORD 306, 1938
              HUDWORD 308, 1940
              HUDWORD 310, 1942
              HUDWORD 312, 2080
              HUDWORD 314, 2082
              HUDWORD 316, 2084
              HUDWORD 318, 2086
              HUDWORD 320, 2088
              HUDWORD 322, 2090
              HUDWORD 324, 2092
              HUDWORD 326, 2094
              HUDWORD 328, 2096
              HUDWORD 330, 2098
              HUDWORD 332, 2100
              HUDWORD 334, 2102
              HUDWORD 336, 2240
              HUDWORD 338, 2242
              HUDWORD 340, 2244
              HUDWORD 342, 2246
              HUDWORD 344, 2248
              HUDWORD 346, 2250
              HUDWORD 348, 2252
              HUDWORD 350, 2254
              HUDWORD 352, 2256
              HUDWORD 354, 2258
              HUDWORD 356, 2260
              HUDWORD 358, 2262
              HUDWORD 360, 2400
              HUDWORD 362, 2402
              HUDWORD 364, 2404
              HUDWORD 366, 2406
              HUDWORD 368, 2408
              HUDWORD 370, 2410
              HUDWORD 372, 2412
              HUDWORD 374, 2414
              HUDWORD 376, 2416
              HUDWORD 378, 2418
              HUDWORD 380, 2420
              HUDWORD 382, 2422
              HUDWORD 384, 2560
              HUDWORD 386, 2562
              HUDWORD 388, 2564
              HUDWORD 390, 2566
              HUDWORD 392, 2568
              HUDWORD 394, 2570
              HUDWORD 396, 2572
              HUDWORD 398, 2574
              HUDWORD 400, 2576
              HUDWORD 402, 2578
              HUDWORD 404, 2580
              HUDWORD 406, 2582
              HUDWORD 408, 2720
              HUDWORD 410, 2722
              HUDWORD 412, 2724
              HUDWORD 414, 2726
              HUDWORD 416, 2728
              HUDWORD 418, 2730
              HUDWORD 420, 2732
              HUDWORD 422, 2734
              HUDWORD 424, 2736
              HUDWORD 426, 2738
              HUDWORD 428, 2740
              HUDWORD 430, 2742
              HUDWORD 432, 2880
              HUDWORD 434, 2882
              HUDWORD 436, 2884
              HUDWORD 438, 2886
              HUDWORD 440, 2888
              HUDWORD 442, 2890
              HUDWORD 444, 2892
              HUDWORD 446, 2894
              HUDWORD 448, 2896
              HUDWORD 450, 2898
              HUDWORD 452, 2900
              HUDWORD 454, 2902
              HUDWORD 456, 3040
              HUDWORD 458, 3042
              HUDWORD 460, 3044
              HUDWORD 462, 3046
              HUDWORD 464, 3048
              HUDWORD 466, 3050
              HUDWORD 468, 3052
              HUDWORD 470, 3054
              HUDWORD 472, 3056
              HUDWORD 474, 3058
              HUDWORD 476, 3060
              HUDWORD 478, 3062
              HUDWORD 480, 3200
              HUDWORD 482, 3202
              HUDWORD 484, 3204
              HUDWORD 486, 3206
              HUDWORD 488, 3208
              HUDWORD 490, 3210
              HUDWORD 492, 3212
              HUDWORD 494, 3214
              HUDWORD 496, 3216
              HUDWORD 498, 3218
              HUDWORD 500, 3220
              HUDWORD 502, 3222
              HUDWORD 504, 3360
              HUDWORD 506, 3362
              HUDWORD 508, 3364
              HUDWORD 510, 3366
              HUDWORD 512, 3368
              HUDWORD 514, 3370
              HUDWORD 516, 3372
              HUDWORD 518, 3374
              HUDWORD 520, 3376
              HUDWORD 522, 3378
              HUDWORD 524, 3380
              HUDWORD 526, 3382
              HUDWORD 528, 3520
              HUDWORD 530, 3522
              HUDWORD 532, 3524
              HUDWORD 534, 3526
              HUDWORD 536, 3528
              HUDWORD 538, 3530
              HUDWORD 540, 3532
              HUDWORD 542, 3534
              HUDWORD 544, 3536
              HUDWORD 546, 3538
              HUDWORD 548, 3540
              HUDWORD 550, 3542
              HUDWORD 552, 3680
              HUDWORD 554, 3682
              HUDWORD 556, 3684
              HUDWORD 558, 3686
              HUDWORD 560, 3688
              HUDWORD 562, 3690
              HUDWORD 564, 3692
              HUDWORD 566, 3694
              HUDWORD 568, 3696
              HUDWORD 570, 3698
              HUDWORD 572, 3700
              HUDWORD 574, 3702
              plb
              rts

              .section gamedata, data, root
              .public levelIndex
levelIndex:   .word 0
;;; The fields of the last paint, then at hudOld+18 the picture of each score digit (one word every four bytes).
hudOld:       .space 40
smallDivisors:.word 1,10,100
scoreDivisors:.word 34464,1,10000,0,1000,0,100,0,10,0,1,0
#include "ui.inc"
