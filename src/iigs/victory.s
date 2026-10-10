;;; BJ's victory run, and the episode tally and ENDART drawers.
;;; Thinks run with D = $1100 and DB = $28. The drawers are JSL: they
;;; switch DB to this bank, draw, and restore it. The pages are lumps of the menu file (tools/art_lumps.py).
#include "memmap.inc"
#include "logic.inc"
#include "campaign.inc"
#include "gray.inc"
#include "logic_dp.inc"
#include "logic_sounds.inc"
#include "menu.inc"
#include "pages.inc"
              .section logiccode, text, root, noreorder
              .public SpawnBJVictory, T_BJRun, T_BJJump, T_BJYell, T_BJDone
              .public VictorySpin, VictoryShow, EndShow, PageEnter, PageLeave
              .extern GetNewActor, Rnd, CellOfX, NewState, sfxEvent
              .extern MoveObj, SelectPathDir, ratioTable, InitFlash
              .extern lumpTable, CopyMenuBlocks, PalBlack, WaitBlank, screenBlack, PublishVictoryPals
              .extern streamLump, BindFullPicture
              .extern layTimeX, layTimeY, laySecX, layRatioR
              .extern layKillY, laySecretY, layTreasY

PLAYER        .equ OBJLIST

;;; VictoryTile. The exit cell is already the player's tile. X is that
;;; map index, so it comes back. O_ACTIVE is set because a new actor is
;;; skipped while its area is clear, and ConnectAreas does not run again.
#ifdef WOLF_SPEAR
SpawnBJVictory:
T_BJRun:
T_BJJump:
T_BJYell:
T_BJDone:     rts
#else
SpawnBJVictory:
              phx
              phy
              lda dp:L_OB
              pha
              jsr abs:.word0 (GetNewActor)
              stx dp:L_OB
              lda abs:PLAYER+O_TILEX
              sta abs:O_TILEX,x
              lda abs:PLAYER+O_TILEY
              inc a
              sta abs:O_TILEY,x
              lda ##0x8000
              sta abs:O_X,x
              sta abs:O_Y,x
              lda abs:O_TILEX,x
              sta abs:O_X+2,x
              lda abs:O_TILEY,x
              sta abs:O_Y+2,x
              ldy ##s_bjrun1
              jsr abs:.word0 (NewState)
              ldx dp:L_OB
              jsr abs:.word0 (Rnd)
              and ##255
              sta dp:L_T
              tax
              lda abs:DIV12,x
              and ##255
              sta dp:L_U
              asl a
              asl a
              sta dp:L_V
              lda dp:L_U
              asl a
              asl a
              asl a
              clc
              adc dp:L_V
              sta dp:L_V
              lda dp:L_T
              sec
              sbc dp:L_V
              ldx dp:L_OB
              sta abs:O_TICS,x
              lda abs:PLAYER+O_X
              sta abs:O_X,x
              lda abs:PLAYER+O_X+2
              sta abs:O_X+2,x
              lda abs:PLAYER+O_Y
              sta abs:O_Y,x
              lda abs:PLAYER+O_Y+2
              sta abs:O_Y+2,x
              lda ##2
              sta abs:O_DIR,x
              lda ##14
              sta abs:O_CLASS,x
              lda ##6
              sta abs:O_TEMP2,x
              lda ##1
              sta abs:O_ACTIVE,x
              lda ##0xffff
              sta abs:O_MARKED,x
              lda abs:O_TILEY,x
              asl a
              asl a
              asl a
              asl a
              asl a
              asl a
              ora abs:O_TILEX,x
              tay
              lda abs:MAP0,y
              and ##255
              sec
              sbc ##107
              ldx dp:L_OB
              sta abs:O_AREA,x
              jsr abs:.word0 (CellOfX)
              txa
              sta abs:ACTORAT,y
              pla
              sta dp:L_OB
              ply
              plx
              rts

;;; X arrives as the think index. 2048*tics stays 32 bits: a batched tic
;;; count of 64 is 131072.
T_BJRun:      ldx dp:L_OB
              lda abs:V_tics
              sta dp:L_MOVE
              stz dp:L_MOVE+2
              ldy ##11
bjScale:      asl dp:L_MOVE
              rol dp:L_MOVE+2
              dey
              bne bjScale
bjRunLoop:    lda dp:L_MOVE
              ora dp:L_MOVE+2
              beq bjRunOut
              ldx dp:L_OB
              lda abs:O_DIST+2,x
              bmi bjSnap
              cmp dp:L_MOVE+2
              bcc bjSnap
              bne bjStep
              lda abs:O_DIST,x
              cmp dp:L_MOVE
              bcc bjSnap
              beq bjSnap
bjStep:       jsr abs:.word0 (MoveObj)
bjRunOut:     rts
bjSnap:       lda abs:O_TILEX,x
              sta abs:O_X+2,x
              lda ##0x8000
              sta abs:O_X,x
              lda abs:O_TILEY,x
              sta abs:O_Y+2,x
              lda ##0x8000
              sta abs:O_Y,x
              lda dp:L_MOVE
              sec
              sbc abs:O_DIST,x
              sta dp:L_MOVE
              lda dp:L_MOVE+2
              sbc abs:O_DIST+2,x
              sta dp:L_MOVE+2
              stx dp:L_OB
              jsr abs:.word0 (SelectPathDir)
              ldx dp:L_OB
              dec abs:O_TEMP2,x
              bne bjRunLoop
              ldy ##s_bjjump1
              jsr abs:.word0 (NewState)
              rts

;;; 680*tics. 680*64 fits in 16 bits; the high word is kept anyway.
T_BJJump:     ldx dp:L_OB
              lda abs:V_tics
              sta dp:L_PA
              stz dp:L_PA+2
              stz dp:L_MOVE
              stz dp:L_MOVE+2
              ldy ##3
bjJump8:      asl dp:L_PA
              rol dp:L_PA+2
              dey
              bne bjJump8
              jsr abs:.word0 (bjAdd)
              jsr abs:.word0 (bjShift2)
              jsr abs:.word0 (bjAdd)
              jsr abs:.word0 (bjShift2)
              jsr abs:.word0 (bjAdd)
              jsr abs:.word0 (bjShift2)
              jsr abs:.word0 (bjAdd)
              ldx dp:L_OB
              jsr abs:.word0 (MoveObj)
              rts
bjShift2:     asl dp:L_PA
              rol dp:L_PA+2
              asl dp:L_PA
              rol dp:L_PA+2
              rts
bjAdd:        lda dp:L_MOVE
              clc
              adc dp:L_PA
              sta dp:L_MOVE
              lda dp:L_MOVE+2
              adc dp:L_PA+2
              sta dp:L_MOVE+2
              rts

;;; The normal event publisher starts the yell after the actor pass.
T_BJYell:     lda ##YEAHSND
              sta long:bjYell
              sta long:sfxEvent
              sta abs:V_sound
              rts

T_BJDone:     lda ##6
              sta abs:V_playstate
              rts

#endif
;;; Face 270 and pull north of the exit. Runs only while the flag is set.
VictorySpin:  lda abs:V_tics
              asl a
              clc
              adc abs:V_tics
              sta dp:L_T
              lda abs:PLAYER+O_ANGLE
              cmp ##270
              beq spinY
              bcc spinAdd
              sec
              sbc dp:L_T
              cmp ##270
              bcs spinStore
              lda ##270
              bra spinStore
spinAdd:      clc
              adc dp:L_T
              cmp ##270
              bcc spinStore
              beq spinStore
              lda ##270
spinStore:    sta abs:PLAYER+O_ANGLE
spinY:        lda abs:PLAYER+O_TILEY
              sec
              sbc ##5
              dec a
              sta dp:L_PA+2
              lda ##0xd000
              sta dp:L_PA
              lda abs:PLAYER+O_Y+2
              cmp dp:L_PA+2
              bcc spinOut
              bne spinMove
              lda abs:PLAYER+O_Y
              cmp dp:L_PA
              bcc spinOut
              beq spinOut
spinMove:     lda abs:V_tics
              sta dp:L_PB
              stz dp:L_PB+2
              ldy ##12
spinScale:    asl dp:L_PB
              rol dp:L_PB+2
              dey
              bne spinScale
              lda abs:PLAYER+O_Y
              sec
              sbc dp:L_PB
              sta abs:PLAYER+O_Y
              lda abs:PLAYER+O_Y+2
              sbc dp:L_PB+2
              sta abs:PLAYER+O_Y+2
              bcc spinClamp
              cmp dp:L_PA+2
              bcc spinClamp
              bne spinOut
              lda abs:PLAYER+O_Y
              cmp dp:L_PA
              bcs spinOut
spinClamp:    lda dp:L_PA
              sta abs:PLAYER+O_Y
              lda dp:L_PA+2
              sta abs:PLAYER+O_Y+2
spinOut:      rts

;;; JSL. DB returns as it arrived. A is unused. The eight floor ratios
;;; are averaged here so the flow bank stays the screen machine.
VictoryShow:  php
              rep #0x30
              phb
              pea #0x0202
              plb
              plb
              jsl long:InitFlash
              phk
              plb
              jsr abs:.word0 (AverageRatios)
              lda ##LUMP_VICTORY
              ldx ##1                       ; the status bar stays
              jsr abs:.word0 (PageShow)
              bcs showFailed
              jsr abs:.word0 (DrawTime)
              jsr abs:.word0 (DrawRatios)
showOK:       plb
              plp
              clc
              rtl
showFailed:   plb
              plp
              sec
              rtl

;;; JSL. A is the ending page, 0 through endCount-1.
EndShow:      php
              rep #0x30
              phb
              phk
              plb
              and ##255
              clc
              adc ##LUMP_END1
              ldx ##0                       ; the whole screen
              jsr abs:.word0 (PageShow)
              bcs showFailed
              bra showOK

;;; A = the lump, X = 1: only rows 0-159 and the palettes 0, 13, 14 and 15 (the status bar stays), X = 0: the whole
;;; screen. The page comes from the menu cache; CopyMenuBlocks works on the page of the menus, which is kept here.
;;; The colors of the page are black until its pixels are in. DBR is this bank.
PageShow:     sta long:vicA
              txa
              sta long:vicB
              jsr abs:.word0 (PageEnter)
              lda long:vicA
              asl a
              asl a
              asl a
              tax
              lda long:lumpTable,x          ; the first block of the lump
              sta long:vicC
              lda long:vicB
              bne pageRows
              jsl long:PalBlack
              jsr abs:.word0 (PageGray)
              bcc pageGrayOK
              jmp abs:.word0 (pageFailed)
pageGrayOK:
              lda long:vicC
              sta dp:CM_BLK
              lda ##63
              sta dp:CM_CNT
              lda ##0x2000
              sta dp:CM_DOFF
              lda ##0xe1
              sta dp:CM_DBNK
              jsl long:CopyMenuBlocks       ; pixels and SCBs while black
              bcc pageReadPalette
              jmp abs:.word0 (pageFailed)
pageReadPalette:
              lda ##1
              sta dp:CM_CNT
              lda ##PAGE_STAGE
              sta dp:CM_DOFF
              lda ##PAGE_STAGE_BANK
              sta dp:CM_DBNK
              jsl long:CopyMenuBlocks
              bcc pagePublish
              jmp abs:.word0 (pageFailed)
pagePublish:  jsl long:WaitBlank
              ldx ##PAGE_STAGE
              ldy ##0x9e00
              lda ##511
              phb
              .byte 0x54, 0xe1, PAGE_STAGE_BANK
              plb
              lda long:vicA
              sta long:streamLump
              jsl long:BindFullPicture
              lda ##0
              sta long:screenBlack
              jmp abs:.word0 (pageDone)
pageRows:     jsl long:WaitBlank
              lda ##0
              ldx ##30
pageBlack0:   sta long:SHR_PAL,x
              dex
              dex
              bpl pageBlack0
              ldx ##94
pageBlack13:  sta long:SHR_PAL+0x1a0,x
              dex
              dex
              bpl pageBlack13
              lda long:vicC
              sta dp:CM_BLK
              lda ##50
              sta dp:CM_CNT
              lda ##0x2000
              sta dp:CM_DOFF
              lda ##0xe1
              sta dp:CM_DBNK
              jsl long:CopyMenuBlocks       ; the 160 rows
              bcs pageFailed
              lda long:vicC
              clc
              adc ##VICTORY_DIGITS_BLOCK
              sta dp:CM_BLK
              lda ##VICTORY_DIGITS_BLOCKS
              sta dp:CM_CNT
              lda ##PAGE_STAGE
              sta dp:CM_DOFF
              lda ##PAGE_STAGE_BANK
              sta dp:CM_DBNK
              jsl long:CopyMenuBlocks       ; the digit tables and pictures
              bcs pageFailed
              lda long:vicC
              clc
              adc ##62
              sta dp:CM_BLK
              lda ##2
              sta dp:CM_CNT
              lda ##PAGE_STAGE + 512 * VICTORY_DIGITS_BLOCKS
              sta dp:CM_DOFF
              lda ##PAGE_STAGE_BANK
              sta dp:CM_DBNK
              jsl long:CopyMenuBlocks       ; the row palettes and the palettes of the record
              bcs pageFailed
              ldx ##PAGE_STAGE + 512 * VICTORY_DIGITS_BLOCKS + 256
              ldy ##0x9d00
              lda ##159
              phb
              .byte 0x54, 0xe1, PAGE_STAGE_BANK        ; MVN: bank $41 to bank $E1, the palettes of the 160 rows
              plb
              jsl long:PublishVictoryPals
pageDone:     jsr abs:.word0 (PageLeave)
              clc
              rts
pageFailed:   jsr abs:.word0 (PageLeave)
              sec
              rts

;;; Ending records append their offline gray packet after the 64 SHR blocks.
;;; Only the current page's records occupy the fixed page window in bank $3B.
PageGray:     lda long:vicA
              cmp ##LUMP_END1
              bcs grayRead
              clc
              rts
grayRead:     lda long:vicC
              clc
              adc ##64
              sta dp:CM_BLK
              lda ##1
              sta dp:CM_CNT
              lda ##PAGE_STAGE
              sta dp:CM_DOFF
              lda ##PAGE_STAGE_BANK
              sta dp:CM_DBNK
              jsl long:CopyMenuBlocks
              bcs grayReadDone
              lda ##GRAY_PAGE_BLOCKS
              sta dp:CM_CNT
              lda ##.word0 (GRAY_PAGE_DATA)
              sta dp:CM_DOFF
              lda ##0x3b
              sta dp:CM_DBNK
              jsl long:CopyMenuBlocks
              bcs grayReadDone
              phb
              ldx ##PAGE_STAGE
              ldy ##OFF_PIC + 256
              lda ##63
              .byte 0x54, 0x3b, PAGE_STAGE_BANK
              plb
              clc
grayReadDone: rts

;;; Keep the page of the menus' direct page (bank 0, $1100) and take it for CopyMenuBlocks, and give it back. The
;;; direct page register goes in a variable: these are subroutines.
PageEnter:    tdc
              sta long:pageD
              ldx ##0x1100
              ldy ##.word0 (pageSave)
              lda ##255
              phb
              .byte 0x54, 0x02, 0x00        ; MVN: bank 0 to bank 2
              plb
              lda ##0x1100
              tcd
              rts
PageLeave:    ldx ##.word0 (pageSave)
              ldy ##0x1100
              lda ##255
              phb
              .byte 0x54, 0x00, 0x02        ; MVN: bank 2 to bank 0
              plb
              lda long:pageD
              tcd
              rts

AverageRatios:
              lda ##0
              sta long:vicKill
              sta long:vicSecret
              sta long:vicTreas
              sta long:vicTime
              sta long:vicTime+2
              sta long:vicMin
              ldx ##0
#ifdef WOLF_SPEAR
              ldy ##CAMPAIGN_RATIO_BYTES/8
#else
              ldy ##8
#endif
avgLoop:      lda long:ratioTable,x
              clc
              adc long:vicKill
              sta long:vicKill
              lda long:ratioTable+2,x
              clc
              adc long:vicSecret
              sta long:vicSecret
              lda long:ratioTable+4,x
              clc
              adc long:vicTreas
              sta long:vicTreas
              lda long:ratioTable+6,x
              clc
              adc long:vicTime
              sta long:vicTime
              lda long:vicTime+2
              adc ##0
              sta long:vicTime+2
              txa
              clc
              adc ##8
              tax
              dey
              bne avgLoop
#ifdef WOLF_SPEAR
              lda long:vicKill
              jsr abs:.word0 (spearAverage)
              sta long:vicKill
              lda long:vicSecret
              jsr abs:.word0 (spearAverage)
              sta long:vicSecret
              lda long:vicTreas
              jsr abs:.word0 (spearAverage)
              sta long:vicTreas
#else
              lda long:vicKill
              lsr a
              lsr a
              lsr a
              sta long:vicKill
              lda long:vicSecret
              lsr a
              lsr a
              lsr a
              sta long:vicSecret
              lda long:vicTreas
              lsr a
              lsr a
              lsr a
              sta long:vicTreas
#endif
avg60:        lda long:vicTime+2
              bne avg60Sub
              lda long:vicTime
              cmp ##60
              bcc avg60Done
avg60Sub:     lda long:vicTime
              sec
              sbc ##60
              sta long:vicTime
              lda long:vicTime+2
              sbc ##0
              sta long:vicTime+2
              lda long:vicMin
              inc a
              sta long:vicMin
              bra avg60
avg60Done:    lda long:vicMin
              cmp ##100
              bcc avg60Keep
              lda ##99
              sta long:vicMin
              sta long:vicTime
avg60Keep:    rts

DrawTime:     lda abs:.word0 (layTimeX)
              sta long:vicX
              lda abs:.word0 (layTimeY)
              sta long:vicY
              lda long:vicMin
              jsr abs:.word0 (drawPair)
              lda abs:.word0 (laySecX)
              sta long:vicX
              lda abs:.word0 (layTimeY)
              sta long:vicY
              lda long:vicTime
              jsr abs:.word0 (drawPair)
              rts

;;; A = 0..99. Two digits, tens at vicX.
drawPair:     sta long:vicA
              ldx ##0
pairTens:     lda long:vicA
              cmp ##10
              bcc pairReady
              sec
              sbc ##10
              sta long:vicA
              inx
              bra pairTens
pairReady:    txa
              jsr abs:.word0 (DrawDigit)
              lda long:vicX
              clc
              adc ##16
              sta long:vicX
              lda long:vicA
              jsr abs:.word0 (DrawDigit)
              rts

DrawRatios:   lda abs:.word0 (layKillY)
              sta long:vicY
              lda long:vicKill
              jsr abs:.word0 (drawRight)
              lda abs:.word0 (laySecretY)
              sta long:vicY
              lda long:vicSecret
              jsr abs:.word0 (drawRight)
              lda abs:.word0 (layTreasY)
              sta long:vicY
              lda long:vicTreas
              jsr abs:.word0 (drawRight)
              rts

;;; A = value. Right edge is layRatioR. Digits sit on the stack, MSD on top.
drawRight:    ldx ##0
              cmp ##0
              bne rightLoop
              pha
              inx
              bra rightPlace
rightLoop:    sta long:vicA
              ldy ##0
rightSub:     lda long:vicA
              cmp ##10
              bcc rightRem
              sec
              sbc ##10
              sta long:vicA
              iny
              bra rightSub
rightRem:     lda long:vicA
              pha
              inx
              tya
              bne rightLoop
rightPlace:   txa
              asl a
              asl a
              asl a
              asl a
              sta long:vicA
              lda abs:.word0 (layRatioR)
              sec
              sbc long:vicA
              sta long:vicX
rightPop:     pla
              jsr abs:.word0 (DrawDigit)
              lda long:vicX
              clc
              adc ##16
              sta long:vicX
              dex
              bne rightPop
              rts

;;; A = digit. vicX and vicY are the top left (x even). X is kept. The 16 rows of a digit are in the staging area as
;;; 8 bytes of nibbles, each the number of one of the 6 teals of the lettering, after a table of 16 nibbles for each
;;; palette that says which color of the palette takes the place of each teal. Each row goes through the table of the
;;; palette that the row has on the screen.
DrawDigit:    phx
              and ##15
              xba
              lsr a                         ; 128 bytes a digit
              clc
              adc ##PAGE_STAGE + 256
              sta long:vicOff
              lda long:vicY
              pha
              jsr abs:.word0 (screenOf)
              tya
              sta long:vicS
              lda ##16
              sta long:vicN
digitRow:     lda long:vicY
              tax
              lda long:SHR_SCB,x           ; the palette of this row
              and ##15
              asl a
              asl a
              asl a
              asl a
              clc
              adc ##PAGE_STAGE
              sta long:vicMap
              lda ##8
              sta long:vicC
digitByte:    lda long:vicOff
              tax
              lda long:SNAP_PIX,x
              and ##255
              sta long:digA
              lsr a
              lsr a
              lsr a
              lsr a
              clc
              adc long:vicMap
              tax
              lda long:SNAP_PIX,x
              and ##15
              asl a
              asl a
              asl a
              asl a
              sta long:digB
              lda long:digA
              and ##15
              clc
              adc long:vicMap
              tax
              lda long:SNAP_PIX,x
              and ##15
              ora long:digB
              pha
              lda long:vicS
              tax
              pla
              sep #0x20
              sta long:SHR,x
              rep #0x20
              inx
              txa
              sta long:vicS
              lda long:vicOff
              inc a
              sta long:vicOff
              lda long:vicC
              dec a
              sta long:vicC
              bne digitByte
              lda long:vicS
              clc
              adc ##152
              sta long:vicS
              lda long:vicY
              inc a
              sta long:vicY
              lda long:vicN
              dec a
              sta long:vicN
              beq digitDone
              jmp abs:.word0 (digitRow)
digitDone:    pla
              sta long:vicY
              plx
              rts

;;; Y = vicY*160 + vicX/2. X is kept.
screenOf:     phx
              lda long:vicY
              asl a
              asl a
              asl a
              asl a
              asl a
              sta long:digB
              lda long:vicY
              asl a
              asl a
              asl a
              asl a
              asl a
              asl a
              asl a
              clc
              adc long:digB
              sta long:digB
              lda long:vicX
              lsr a
              clc
              adc long:digB
              tay
              plx
              rts

              .section gamedata, data, root
              .public bjYell
bjYell:       .word 0
vicKill:      .word 0
vicSecret:    .word 0
vicTreas:     .word 0
vicTime:      .word 0, 0
vicMin:       .word 0
vicX:         .word 0
vicY:         .word 0
vicN:         .word 0
vicOff:       .word 0
vicS:         .word 0
vicMap:       .word 0
vicA:         .word 0
vicB:         .word 0
vicC:         .word 0
digA:         .word 0
digB:         .word 0
pageSave:     .space 256
pageD:        .word 0

#ifdef WOLF_SPEAR
              .section logiccode, text, root, noreorder
spearAverage: ldx ##0
spearDivide:  cmp ##CAMPAIGN_RATIO_BYTES/8
              bcc spearDivided
              sbc ##CAMPAIGN_RATIO_BYTES/8
              inx
              bra spearDivide
spearDivided: txa
              rts
#endif
