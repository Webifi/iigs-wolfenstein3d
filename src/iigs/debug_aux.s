;;; Native diagnostics use the current floor's resident art and fixed memory
;;; pools. There is no DOS EMS/XMS page manager and no debug disk prefetch.
#include "memmap.inc"
#include "logic.inc"
#include "frontend.inc"
#include "asset_constants.inc"
#include "sprite_layout.inc"
              .section debugaux, text, root, noreorder
              .public DebugCounts, DebugFacing, DebugMemory, DebugShapes
              .extern DebugSetText, DebugAppendText, DebugNumber, DebugChar, DebugDialog, DebugAck, DebugUiCall
              .extern playValid, spriteFrame, debugSpriteEnd, viewPal, soundAt
DTHUMB        .equ UI_BOXBUF+1024
DWALLS        .equ DOORWALL+8

DebugCounts:  lda ##.word0 (dStatics)
              jsr abs:.word0 (dSet)
              lda long:LOGIC_BASE+V_laststat
              sec
              sbc ##STATICS
              lsr a
              lsr a
              lsr a
              jsl long:DebugNumber
              lda ##.word0 (dUsed)
              jsr abs:.word0 (dAppend)
              lda ##0
              sta long:dCount
              ldx ##STATICS
dStaticLoop:  txa
              cmp long:LOGIC_BASE+V_laststat
              bcs dStaticDone
              lda long:LOGIC_BASE+2,x
              cmp ##65535
              beq dStaticNext
              lda long:dCount
              inc a
              sta long:dCount
dStaticNext:  txa
              clc
              adc ##8
              tax
              bra dStaticLoop
dStaticDone:  lda long:dCount
              jsl long:DebugNumber
              lda ##.word0 (dDoors)
              jsr abs:.word0 (dAppend)
              lda long:LOGIC_BASE+V_doornum
              jsl long:DebugNumber
              lda ##0
              sta long:dCount
              sta long:dActive
              lda long:LOGIC_BASE+OBJLIST+O_NEXT
dActorLoop:   beq dActorDone
              tax
              lda long:dCount
              inc a
              sta long:dCount
              lda long:LOGIC_BASE+O_ACTIVE,x
              beq dActorNext
              lda long:dActive
              inc a
              sta long:dActive
dActorNext:   lda long:LOGIC_BASE+O_NEXT,x
              bra dActorLoop
dActorDone:   lda ##.word0 (dActors)
              jsr abs:.word0 (dAppend)
              lda long:dCount
              jsl long:DebugNumber
              lda ##.word0 (dActiveText)
              jsr abs:.word0 (dAppend)
              lda long:dActive
              jsl long:DebugNumber
              jmp long:DebugAck
DebugFacing:  lda ##.word0 (dX)
              jsr abs:.word0 (dSet)
              lda long:LOGIC_BASE+OBJLIST+O_X
              jsl long:DebugNumber
              lda ##.word0 (dY)
              jsr abs:.word0 (dAppend)
              lda long:LOGIC_BASE+OBJLIST+O_Y
              jsl long:DebugNumber
              lda ##.word0 (dAngle)
              jsr abs:.word0 (dAppend)
              lda long:LOGIC_BASE+OBJLIST+O_ANGLE
              jsl long:DebugNumber
              jmp long:DebugAck
DebugMemory:  lda ##.word0 (dMemory)
              jsr abs:.word0 (dSet)
              lda ##128
              sta long:dCount
              ldx ##15
dBankByte:    lda long:BI_BANKS,x
              and ##255
              ldy ##8
dBankBit:     lsr a
              bcc dBankNext
              pha
              lda long:dCount
              clc
              adc ##64
              sta long:dCount
              pla
dBankNext:    dey
              bne dBankBit
              dex
              bpl dBankByte
              lda long:dCount
              jsl long:DebugNumber
              lda ##.word0 (dCache)
              jsr abs:.word0 (dAppend)
              lda long:playValid
              lsr a
              jsl long:DebugNumber
              lda ##.word0 (dFixed)
              jsr abs:.word0 (dAppend)
              jmp long:DebugAck

dSet:        ldx ##.byte2 dStatics
              jsl long:DebugSetText
              rts
dAppend:     ldx ##.byte2 dStatics
              jsl long:DebugAppendText
              rts

;;; W/S/D/I select walls, sprites, resident effects or effect information.
;;; Left/Right select within the category. Enter/L need no paging on this port.
DebugShapes:  lda ##0
              sta long:dKind
              sta long:dPage
              lda ##.word0 (debugSpriteEnd)
              sec
              sbc ##.word0 (spriteFrame)
              lsr a
              sec
              sbc ##20                    ; weapon poses have no world-column header
              sta long:dSprites
dShapePage:   lda ##.word0 (dPageText)
              jsr abs:.word0 (dSet)
              lda long:dPage
              jsl long:DebugNumber
              lda long:dKind
              cmp ##1
              beq dShapeSprite
              cmp ##2
              beq dShapeSound
              cmp ##3
              beq dShapeInfo
              lda ##DWALLS
              sta long:dLimit
              lda ##.word0 (dWallText)
              bra dShapeTitle
dShapeSprite: lda long:dSprites
              sta long:dLimit
              lda ##.word0 (dSpriteText)
              bra dShapeTitle
dShapeSound:  lda ##87
              sta long:dLimit
              lda ##.word0 (dSoundText)
              bra dShapeTitle
dShapeInfo:   lda ##1
              sta long:dLimit
              lda ##.word0 (dSoundInfo)
dShapeTitle:  jsr abs:.word0 (dAppend)
              jsl long:DebugDialog
              jsr abs:.word0 (dGrayMap)
              lda ##0
              ldx ##2046
dThumbClear:  sta long:DTHUMB,x
              dex
              dex
              bpl dThumbClear
              lda long:dKind
              beq dDrawWall
              cmp ##1
              beq dDrawSprite
              jsr abs:.word0 (dEffect)
              bra dDrawDone
dDrawWall:    jsr abs:.word0 (dWall)
              bra dDrawDone
dDrawSprite:  jsr abs:.word0 (dSprite)
dDrawDone:    jsr abs:.word0 (dBlit)
dShapeKey:    ldx ##6
              jsl long:DebugUiCall
              cmp ##K_ESC
              bne dShapeNotExit
              rtl
dShapeNotExit:cmp ##K_LEFT
              beq dShapeLeft
              cmp ##K_RIGHT
              beq dShapeRight
              cmp ##0x0d
              beq dSelectWall
              cmp ##1
              beq dSelectSprite
              cmp ##2
              beq dSelectSound
              cmp ##0x22
              beq dSelectInfo
              bra dShapeKey
dSelectWall:  lda ##0
              bra dSelect
dSelectSprite:lda ##1
              bra dSelect
dSelectSound: lda ##2
              bra dSelect
dSelectInfo:  lda ##3
dSelect:      sta long:dKind
              lda ##0
              sta long:dPage
              jmp abs:.word0 (dShapePage)
dShapeLeft:   lda long:dPage
              beq dShapeKey
              dec a
              sta long:dPage
              jmp abs:.word0 (dShapePage)
dShapeRight:  lda long:dPage
              inc a
              cmp long:dLimit
              bcs dShapeKey
              sta long:dPage
              jmp abs:.word0 (dShapePage)

;;; Fit the floor's 16 source colors to the gray palette currently in slot 15.
dGrayMap:     ldy ##0
dGrayColor:   tya
              asl a
              tax
              lda long:viewPal,x
              jsr abs:.word0 (dIntensity)
              sta long:dTarget
              lda ##65535
              sta long:dBest
              ldx ##0
dGraySlot:    lda long:SHR_PAL+480,x
              jsr abs:.word0 (dIntensity)
              sec
              sbc long:dTarget
              bpl dGrayPositive
              eor ##65535
              inc a
dGrayPositive:cmp long:dBest
              bcs dGrayNext
              sta long:dBest
              txa
              lsr a
              sta long:dInk
dGrayNext:    inx
              inx
              cpx ##32
              bcc dGraySlot
              tya
              tax
              lda long:dInk
              sep #0x20
              sta long:dMap,x
              rep #0x20
              iny
              cpy ##16
              bcc dGrayColor
              rts
dIntensity:   pha
              and ##15
              sta long:dSum
              pla
              lsr a
              lsr a
              lsr a
              lsr a
              pha
              and ##15
              clc
              adc long:dSum
              sta long:dSum
              pla
              lsr a
              lsr a
              lsr a
              lsr a
              and ##15
              clc
              adc long:dSum
              rts

;;; Each wall token names four light pointers; use the brightest source pair.
dWall:        lda long:dPage
              xba
              tax
              lda long:WALL_COLUMNS+2,x
              bne dWallPresent
              ldy ##64
dWallProbe:   lda long:WALL_COLUMNS,x
              bne dWallPresent
              inx
              inx
              inx
              inx
              dey
              bne dWallProbe
              rts
dWallPresent: lda ##0
              sta long:dColumn
dWallColumn:  lda long:dPage
              xba
              sta long:dOffset
              lda long:dColumn
              asl a
              asl a
              ora long:dOffset
              tax
              lda long:WALL_COLUMNS,x
              clc
              adc ##12
              tax
              lda long:WALL_LIGHT_POINTERS,x
              sta long:dPixelRead+1
              lda long:WALL_LIGHT_POINTERS+2,x
              xba
              sep #0x20
              sta long:dPixelRead+3
              rep #0x20
              lda ##0
              sta long:dTop
              lda ##64
              sta long:dBottom
              jsr abs:.word0 (dColumnPixels)
              lda long:dColumn
              inc a
              sta long:dColumn
              cmp ##64
              bcc dWallColumn
              rts

;;; Sprite run endpoints are original texel coordinates; offsets are corrected
;;; by top*2, exactly as in the native scaler. Empty frame slots show no sprite.
dSprite:      lda long:dPage
              asl a
              tax
              lda long:spriteFrame,x
              bne dSpriteHave
              lda long:dPage
              beq dSpriteHave
              rts
dSpriteHave:  sta long:dFrame
              tax
              lda long:SPRITE_CMDS+SPR_COMMAND_BANK,x
              sep #0x20
              sta long:dRunRead+3
              rep #0x20
              lda long:SPRITE_CMDS+SPR_LIGHT_BANKS+2,x
              xba
              sep #0x20
              sta long:dPixelRead+3
              rep #0x20
              lda ##0
              sta long:dColumn
dSpriteColumn:
              lda long:dColumn
              asl a
              clc
              adc long:dFrame
              tax
              lda long:SPRITE_CMDS,x
              sta long:dRunAt
dSpriteRun:   lda long:dRunAt
              tax
dRunRead:     lda long:0,x
              beq dSpriteNextColumn
              pha
              and ##255
              sta long:dTop
              pla
              xba
              and ##255
              sta long:dBottom
              txa
              clc
              adc ##8
              tax
              jsr abs:.word0 (dReadRun)
              sta long:dPixelRead+1
              jsr abs:.word0 (dColumnPixels)
              lda long:dRunAt
              clc
              adc ##SPR_RUN_BYTES
              sta long:dRunAt
              bra dSpriteRun
dSpriteNextColumn:
              lda long:dColumn
              inc a
              sta long:dColumn
              cmp ##64
              bcc dSpriteColumn
              rts
dReadRun:     phb
              sep #0x20
              lda long:dRunRead+3
              pha
              plb
              rep #0x20
              lda abs:0,x
              plb
              rts

;;; dTop..dBottom is one column's visible run. Buffer pixels remain 4-bit.
dColumnPixels:
              lda long:dTop
              cmp ##64
              bcs dColumnDone
              asl a
              tax
dColumnPixel: phx
dPixelRead:   lda long:0,x
              and ##15
              tax
              lda long:dMap,x
              and ##15
              sta long:dInk
              pla
              pha
              asl a
              asl a
              asl a
              asl a
              sta long:dOffset
              lda long:dColumn
              lsr a
              clc
              adc long:dOffset
              tax
              lda long:dColumn
              bit ##1
              bne dPixelOdd
              lda long:dInk
              asl a
              asl a
              asl a
              asl a
              sta long:dInk
              lda long:DTHUMB,x
              and ##15
              bra dPixelPut
dPixelOdd:    lda long:DTHUMB,x
              and ##240
dPixelPut:    ora long:dInk
              sep #0x20
              sta long:DTHUMB,x
              rep #0x20
              plx
              inx
              inx
              txa
              lsr a
              cmp long:dBottom
              bcc dColumnPixel
dColumnDone:  rts

;;; Effects are already converted to DOC samples. Show their descriptor and
;;; residency instead of pretending the original VSWAP sound pages are loaded.
dEffect:      lda long:dKind
              cmp ##3
              bne dEffectOne
              lda ##.word0 (dEffectInfo)
              jsr abs:.word0 (dSet)
              lda ##87
              jsl long:DebugNumber
              jmp abs:.word0 (dEffectShow)
dEffectOne:   lda ##.word0 (dEffectText)
              jsr abs:.word0 (dSet)
              lda long:dPage
              jsl long:DebugNumber
              lda ##.word0 (dBytesText)
              jsr abs:.word0 (dAppend)
              lda long:dPage
              asl a
              asl a
              asl a
              asl a
              tax
              lda long:SFX_BASE+4,x
              jsl long:DebugNumber
              lda ##.word0 (dDocText)
              jsr abs:.word0 (dAppend)
              lda long:dPage
              asl a
              tax
              lda long:soundAt,x
              cmp ##65535
              beq dEffectAbsent
              jsl long:DebugNumber
              bra dEffectShow
dEffectAbsent:lda ##.word0 (dNo)
              jsr abs:.word0 (dAppend)
dEffectShow:  jsl long:DebugDialog
              rts

dBlit:        lda long:dKind
              cmp ##2
              bcs dBlitDone
              ldx ##0
              ldy ##0
dBlitRow:     sep #0x20
              lda #15
              sta long:SHR_SCB+88,x
              rep #0x20
              phx
              ldx ##0
dBlitByte:    txa
              clc
              adc long:dDest
              pha
              tya
              tax
              lda long:DTHUMB,x
              plx
              sep #0x20
              sta long:SHR+88*160+64,x
              rep #0x20
              iny
              txa
              sec
              sbc long:dDest
              inc a
              tax
              cpx ##32
              bcc dBlitByte
              lda long:dDest
              clc
              adc ##160
              sta long:dDest
              plx
              inx
              cpx ##64
              bcc dBlitRow
              lda ##0
              sta long:dDest
dBlitDone:    rts

dCount:       .word 0
dActive:      .word 0
dKind:        .word 0
dPage:        .word 0
dLimit:       .word 0
dSprites:     .word 0
dColumn:      .word 0
dOffset:      .word 0
dTop:         .word 0
dBottom:      .word 0
dFrame:       .word 0
dRunAt:       .word 0
dDest:        .word 0
dTarget:      .word 0
dSum:         .word 0
dBest:        .word 0
dInk:         .word 0
dMap:         .space 16
dStatics:     .asciz "Total statics :"
dUsed:        .asciz "\nIn use statics:"
dDoors:       .asciz "\nDoors         :"
dActors:      .asciz "\nTotal actors  :"
dActiveText:  .asciz "\nActive actors :"
dX:           .asciz "X:"
dY:           .asciz "\nY:"
dAngle:       .asciz "\nA:"
dMemory:      .asciz "Memory Usage\n------------\nTotal RAM (k):"
dCache:       .asciz "\nPlay cache (k):"
dFixed:       .asciz "\nFixed pools; no DOS heap"
dPageText:    .asciz " Page #"
dWallText:    .asciz " (Wall)\nCurrent floor\n\n\n\n\n\n"
dSpriteText:  .asciz " (Sprite)\nCurrent floor\n\n\n\n\n\n"
dSoundText:   .asciz " (Sound)"
dSoundInfo:   .asciz " (Sound Info)"
dEffectText:  .asciz "Sound #"
dBytesText:   .asciz "\nSample bytes:"
dDocText:     .asciz "\nDOC page:"
dNo:          .asciz "No"
dEffectInfo:  .asciz "Sound Info\nNative DOC effects:"

#ifdef WOLF_SPEAR
              .public debugFaces
debugFaces:   .incbin "build/assets/debug-faces.bin"
#endif

#define BUSY_PREFIX_DATA 1
#include "busy_signs.inc"
