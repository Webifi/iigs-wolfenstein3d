;;; Exact constant wall bands skip unchanged rows in either painting mode.
;;; The dedicated tables and running code stay separate from the draw buffer.
#include "prepared.inc"
#include "memmap.inc"
              .extern EnsureGameplayAssets, viewWidth, viewTop, viewBottom, screenHold
              .extern tightDispatch, tightLoop, tightNext, tightRangeDone
              .extern tightWallEntry, tightLower, tightGrow, castMinHeight
              .extern viewScaleAddr, viewScaleBank, sourceAddr, oldSource
              .extern oldHeight, heightIndex, lightDelta, rowCodeBase
              .public WallPaintShow, WallPaintRefresh
              .public PaintingToggle, WallPaintToggle, wallPaintOn
              .public WallPaintLoad, WallPaintStore
              .extern PaintingDefault
              .public wallBandTemplate, wallBandTemplateEnd, wallBandBuildEntry

B_META        .equ WALL_PAINT_META
B_OLDKEY      .equ RAY
B_KEY         .equ MAPIDX
B_OLDH        .equ STEPX
B_HEIGHT      .equ STEPY
B_TOP         .equ DX
B_BOTTOM      .equ DY
B_LENGTH      .equ TX
B_LEFT        .equ TY
B_RIGHT       .equ DIST
B_HINDEX      .equ SIDE
B_NEW0        .equ FLAGS
B_TEMP        .equ MULW
B_BANKS       .equ PAGE
B_EP          .equ DIST
B_ROW         .equ ENTRY
B_SOURCE      .equ EXITP
B_OLDEP       .equ TX

              .section tailcode, text, root
wallPaintBridge: jmp long:WALL_PAINT_CODE

              .section debugaux, text, root
wallPaintOn:  .word 0
;;; The two choices are independent. Only menu changes make an automatic
;;; choice explicit; collecting or saving untouched defaults does not.
;;; Encodings differ by two, so changing both choices cannot cancel in the
;;; additive settings checksum that controls Save Settings availability.
PaintingToggle:
              lda long:bufferOn
              eor ##1
              sep #0x20
              sta long:SETTINGS_IN+S_DRAW_BUFFER
              rep #0x20
              jmp long:BufferSet
WallPaintToggle:
              lda long:wallPaintOn
              eor ##1
              sta long:wallPaintOn
              inc a
              asl a
              sep #0x20
              sta long:SETTINGS_IN+S_FAST_WALLS
              rep #0x20
              rtl

WallPaintLoad:
              lda long:SETTINGS_IN+S_FAST_WALLS
              and ##255
              cmp ##5
              bcc wallLoadExplicit
              jsl long:PaintingDefault
              bra wallLoadEnabled
wallLoadExplicit:
              lsr a
              lsr a
wallLoadEnabled:
              sta long:wallPaintOn
              lda long:SETTINGS_IN+S_DRAW_BUFFER
              and ##255
              cmp ##2
              bcc wallLoadBuffer
              lda ##0
wallLoadBuffer:
              jmp long:BufferSet
WallPaintStore:
              lda long:SETTINGS_IN+S_DRAW_BUFFER
              and ##255
              cmp ##2
              bcs wallStoreDone
              lda long:bufferOn
              sep #0x20
              sta long:SETTINGS_IN+S_DRAW_BUFFER
              rep #0x20
wallStoreDone:rtl

;;; Build after floor art is restored and before the view is drawn. Dispatch
;;; changes only here, so neither painting mode tests the option in its loop.
WallPaintShow:
              jsl long:EnsureGameplayAssets
              jmp long:WallPaintRefresh
WallPaintRefresh:
              php
              rep #0x30
              pha
              phx
              phy
              phd
              lda ##GAME_DP
              tcd
              lda ##.word0 (tightLoop)
              sta long:tightDispatch+1
              lda long:screenHold
              beq wallRefreshActive
              jmp abs:.word0 (wallRefreshDone)
wallRefreshActive:
              lda long:wallPaintOn
              bne wallRefreshEnabled
              jmp abs:.word0 (wallRefreshDone)
wallRefreshEnabled:
              ldx ##.word0 (wallBandTemplateEnd-wallBandTemplate-2)
wallCopyCode: lda long:wallBandTemplate,x
              sta long:WALL_PAINT_CODE,x
              dex
              dex
              bpl wallCopyCode
              lda long:viewWidth
              inc a
              and ##0xfffe
              dec a
              dec a
              sta long:WALL_PAINT_CODE+(wallBandGateHeight-wallBandTemplate)+1
              sta long:WALL_PAINT_CODE+(wallBandNewHeight-wallBandTemplate)+1
              sta long:WALL_PAINT_CODE+(wallBandOldHeight-wallBandTemplate)+1
              sta long:WALL_PAINT_CODE+(wallBandSourceHeight-wallBandTemplate)+1
              lda long:viewBottom
              sta long:WALL_PAINT_CODE+(wallBandBottom-wallBandTemplate)+1
              lda long:viewTop
              sta long:WALL_PAINT_CODE+(wallBandTop-wallBandTemplate)+1
              asl a
              sta long:WALL_PAINT_CODE+(wallBandRowStart-wallBandTemplate)+1
              jsl long:WALL_PAINT_CODE+(wallBandBuildEntry-wallBandTemplate)
              lda ##.word0 (wallPaintBridge)
              sta long:tightDispatch+1
wallRefreshDone:
              pld
              ply
              plx
              pla
              plp
              rtl

;;; D=GAME_DP and DBR=2. Only clean columns outside both frames' sprite and
;;; weapon bounds enter this loop. Both wall heights must cover the view;
;;; equal parity-color words then prove their projected overlap unchanged.
;;; The template occupies unused scaler-bank space in every edition. Only
;;; its copy in the reserved wall-painter region executes, after view setup.
              .section scale5, text, root
              .align 2
wallBandTemplate:
wallBandGate:
              lda abs:.word0 (castMinHeight)
wallBandGateHeight:
              cmp ##158
              bcs wallBandBanks
              jmp long:tightLoop
wallBandBanks:
              lda ##.byte2 (ENDPOINTS)
              sta dp:B_EP+2
              sta dp:B_OLDEP+2
              lda ##.byte2 (ROWCODE)
              sta dp:B_ROW+2
              stz dp:B_TOP
              stz dp:B_BOTTOM
wallBandLoop:
              lda abs:.word0 (heightIndex),x
              cmp abs:.word0 (oldHeight),x
              bne wallBandHeight
              lda abs:.word0 (sourceAddr),x
              cmp abs:.word0 (oldSource),x
              bne wallBandSource
wallBandNext:
              dec dp:PA_SX
              dex
              dex
              cpx dp:CASTPASS
              bne wallBandLoop
              jmp long:tightRangeDone
wallBandSource:
              ldy abs:.word0 (heightIndex),x
              jmp abs:.word0 (WALL_PAINT_CODE+(wallBandPrepare-wallBandTemplate))
wallBandHeight:
              tay
wallBandNewHeight:
              cpy ##158
              bcc wallBandHeightFallback
              lda abs:.word0 (oldHeight),x
wallBandOldHeight:
              cmp ##158
              bcc wallBandOldShort
              sta dp:B_OLDH
              tya
              sta abs:.word0 (oldHeight),x
              bra wallBandBegin
wallBandOldShort:
              tya
              sta abs:.word0 (oldHeight),x
              lda abs:.word0 (viewScaleAddr),y
              jmp long:tightWallEntry
wallBandHeightFallback:
              tya
              cmp abs:.word0 (oldHeight),x
              bcc wallBandHeightLower
              jmp long:tightGrow
wallBandHeightLower:
              jmp long:tightLower
wallBandFallback:
              lda abs:.word0 (viewScaleAddr),y
              jmp long:tightWallEntry
wallBandPrepare:
wallBandSourceHeight:
              cpy ##158
              bcc wallBandFallback
              lda abs:.word0 (oldHeight),x
              sta dp:B_OLDH
wallBandBegin:
              lda abs:.word0 (lightDelta),y
              cmp ##12
              bne wallBandFallback
              stx dp:WALL_COL
              sty dp:B_HEIGHT
              lda abs:.word0 (oldSource),x
              sta dp:B_OLDKEY
              lda abs:.word0 (sourceAddr),x
              sta abs:.word0 (oldSource),x
              sta dp:B_KEY
              ora ##12
              tax
              lda long:WALL_LIGHT_POINTERS,x
              sta dp:B_SOURCE
              lda long:WALL_LIGHT_POINTERS+2,x
              ora abs:.word0 (viewScaleBank),y
              sta dp:B_BANKS
;;; A larger custom floor can safely use the full painter beyond the table.
              lda dp:B_KEY
              cmp ##WALL_PAINT_META_SIZE*4
              bcs wallBandFull
              lsr a
              lsr a
              tax
              stx dp:B_TEMP
              lda long:B_META,x
              sta dp:B_NEW0
;;; The minimum height depends only on source-run length. Subtracting the
;;; packed endpoints gives that length in the low byte; one shared lookup
;;; replaces a duplicate minimum-height word for every wall token.
              xba
              sec
              sbc dp:B_NEW0
              and ##255
              asl a
              tax
              lda long:WALL_PAINT_CODE+(wallBandMinHeight-wallBandTemplate),x
              cmp dp:B_HEIGHT
              bcs wallBandFull
              lda dp:B_OLDKEY
              cmp ##WALL_PAINT_META_SIZE*4
              bcs wallBandFull
              ldx dp:B_TEMP
              lda long:B_META+2,x
              sta dp:B_NEW0+2
              lda dp:B_OLDKEY
              lsr a
              lsr a
              tax
              lda long:B_META+2,x
              cmp dp:B_NEW0+2
              beq wallBandKnown
wallBandFull:
              ldy dp:B_HEIGHT
              lda abs:.word0 (viewScaleAddr),y
              pha
              pei dp:PA_SX
              pei dp:B_SOURCE
              pei dp:B_BANKS
              pea #WALLOP-1
              ldx dp:WALL_COL
              jmp abs:.word0 (WALL_PAINT_CODE+(wallBandNext-wallBandTemplate))
wallBandKnown:
              tya
              lsr a
              xba
              sta dp:B_EP
              lda dp:B_OLDH
              lsr a
              xba
              sta dp:B_OLDEP
              lda ##0
              sep #0x20
              lda dp:B_NEW0
              tay
              lda [B_EP],y
              sta dp:B_TOP
              lda long:B_META,x
              tay
              lda [B_OLDEP],y
              cmp dp:B_TOP
              bcc wallBandLeft
              sta dp:B_TOP
wallBandLeft:
              lda dp:B_NEW0+1
              tay
              lda [B_EP],y
              sta dp:B_BOTTOM
              lda long:B_META+1,x
              tay
              lda [B_OLDEP],y
              cmp dp:B_BOTTOM
              bcs wallBandRight
              sta dp:B_BOTTOM
wallBandRight:
              lda dp:B_BOTTOM
              sec
              sbc dp:B_TOP
              bcc wallBandNoGap
              cmp #WALL_BAND_MIN_ROWS
              bcc wallBandNoGap
              rep #0x20
              ldy dp:B_HEIGHT
              bra wallBandMatched
wallBandNoGap:
              rep #0x20
              bra wallBandFull
wallBandMatched:
              lda abs:.word0 (rowCodeBase),y
              sta dp:B_ROW
              lda dp:B_BOTTOM
wallBandBottom:
              cmp ##160
              bcs wallBandUpper
              asl a
              tay
              lda [B_ROW],y
              dec a
              pha
              pei dp:PA_SX
              pei dp:B_SOURCE
              pei dp:B_BANKS
              pea #WALLOP-1
wallBandUpper:
              lda dp:B_TOP
wallBandTop:
              cmp ##0
              beq wallBandSkip
              asl a
              tay
              lda [B_ROW],y
              tax
wallBandRowStart:
              ldy ##0
              lda [B_ROW],y
              dec a
              pha
              pei dp:PA_SX
              pei dp:B_SOURCE
              phx
              pei dp:B_BANKS
              pea #CUTOP-1
wallBandSkip:
              ldx dp:WALL_COL
              jmp abs:.word0 (WALL_PAINT_CODE+(wallBandNext-wallBandTemplate))
wallBandEnd:


wallBandBuild:
              ldx ##0
              lda ##0
wallBandClear:
              sta long:B_META,x
              inx
              inx
              cpx ##WALL_PAINT_META_SIZE
              bcc wallBandClear
              ldx ##0
wallBandDirectory:
              stx dp:B_HINDEX
              lda long:WALL_COLUMNS,x
              cmp ##WALL_PAINT_META_SIZE*4
              bcs wallBandDirectoryNext
              bit ##15
              bne wallBandDirectoryNext
              sta dp:B_KEY
              lsr a
              lsr a
              tax
              lda long:B_META,x
              bne wallBandDirectoryNext
              lda dp:B_KEY
              ora ##12
              tax
              lda long:WALL_LIGHT_POINTERS,x
              sta dp:B_SOURCE
              lda long:WALL_LIGHT_POINTERS+2,x
              xba
              and ##255
              sta dp:B_SOURCE+2
              stz dp:B_HEIGHT
              stz dp:B_LENGTH
              ldy ##0
              lda [B_SOURCE],y
              sta dp:B_LEFT
wallBandSourceLoop:
              iny
              iny
              cpy ##128
              bcs wallBandSourceEnd
              lda [B_SOURCE],y
              cmp dp:B_LEFT
              beq wallBandSourceLoop
              pha
              tya
              lsr a
              jsr abs:.word0 (WALL_PAINT_CODE+(wallBandScore-wallBandTemplate))
              pla
              sta dp:B_LEFT
              bra wallBandSourceLoop
wallBandSourceEnd:
              lda ##64
              jsr abs:.word0 (WALL_PAINT_CODE+(wallBandScore-wallBandTemplate))
              lda dp:B_KEY
              lsr a
              lsr a
              tax
              lda dp:B_BOTTOM
              xba
              ora dp:B_TOP
              sta long:B_META,x
              lda dp:B_RIGHT
              sta long:B_META+2,x
wallBandDirectoryNext:
              ldx dp:B_HINDEX
              inx
              inx
              inx
              inx
              cpx ##WALL_COLUMNS_SIZE
              bcs wallBandBuildDone
              jmp abs:.word0 (WALL_PAINT_CODE+(wallBandDirectory-wallBandTemplate))
wallBandBuildDone:
              rts
wallBandScore:
              sta dp:B_TEMP
              cmp ##48
              bcc wallBandScoreEnd
              lda ##48
wallBandScoreEnd:
              sta dp:B_NEW0
              lda dp:B_HEIGHT
              cmp ##16
              bcs wallBandScoreStart
              lda ##16
wallBandScoreStart:
              sta dp:B_NEW0+2
              lda dp:B_NEW0
              sec
              sbc dp:B_NEW0+2
              bcc wallBandScoreDone
              cmp dp:B_LENGTH
              bcc wallBandScoreDone
              beq wallBandScoreDone
              sta dp:B_LENGTH
              lda dp:B_HEIGHT
              sta dp:B_TOP
              lda dp:B_TEMP
              sta dp:B_BOTTOM
              lda dp:B_LEFT
              sta dp:B_RIGHT
wallBandScoreDone:
              lda dp:B_TEMP
              sta dp:B_HEIGHT
              rts
wallBandBuildEntry:
              jsr abs:.word0 (WALL_PAINT_CODE+(wallBandBuild-wallBandTemplate))
              rtl
wallBandMinHeight:
#include "wall_band_minimum.inc"
              .align 2
wallBandTemplateEnd:
