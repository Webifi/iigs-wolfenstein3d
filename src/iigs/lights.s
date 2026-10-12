;;; Reduced-view ceiling lights. The linker places each fragment in a
;;; region tail already included by the corresponding code or data load.
#include "memmap.inc"
#include "game.inc"
#include "sprite_ids.inc"
#include "asset_constants.inc"
#include "picture_config.inc"
#include "logic.inc"
#include "sprite_layout.inc"
#include "sight.inc"
              .extern viewWidth, horizontalBase, scaleHeight, spriteFrame
              .extern staticsDone, trackProjection, PrepareSprites, projectObject, invalidateRange
              .extern lightHook, trackHook, prepareHook
              .extern castMinX, castMaxX, viewScaleTex
              .extern ddaNegTable
              .extern staticMarkWord, rayMarkWord, emptyMarkWord, openDoorWord, saveOpenWord
              .extern setViewInPlay, weaponViewIndex, UiLoadDone
;;; Fragments sit in block tails the base image already loads.
              .section tailflow, text, root
#if WOLF_PREPARED && !WOLF_TRUE_PIXELS
;;; Distant reduced-view samples step across a ceiling light's fixture. Wall
;;; columns stay as they are. This sprite alone gets one private sample row
;;; in the unused tail of the horizontal table, with its center texel on the
;;; drawn column nearest that center. Other sprites keep the shared row.
              .public keepSprite
keepSprite:   ldx dp:SP_SHAPE
              lda long:SPRITE_CMDS+SPR_GAP,x
              sta dp:SP_TMP
              and ##255
              beq keepSolid
              cmp ##255
              beq keepSolid
              lda ##1
              sta dp:SP_SIGN            ; a run counts only when its fixture is above the gap
              bra keepScan
keepSolid:    stz dp:SP_SIGN
              lda dp:SP_TMP
              bmi keepScan              ; a padded pool can mark columns that sample nothing
              lda dp:SP_N
              cmp dp:SP_LIMIT
              bcc keepSpriteOut         ; the inverse span already hit opaque art
keepScan:     jsr abs:.word0 (scanShows)
              bcs keepSpriteOut
              jsl long:fitLight
keepSpriteOut:rtl

;;; Carry set when a drawn column already shows what this sprite must keep.
;;; A silhouette column before the sprite's left edge is not one of its
;;; samples: that index underflows into the previous height and can look opaque.
scanShows:    lda dp:SP_N
              cmp dp:SP_LIMIT
              bcs scanMiss
              sta dp:SP_SCAN
              lda dp:SP_H
              lsr a
              sta dp:SP_TOP             ; pair width
scanColumn:   lda dp:SP_SCAN
              sec
              sbc dp:SP_LEFT
              bmi scanSkip
              cmp dp:SP_TOP
              bcs scanSkip
              clc
              ldx dp:SP_HI
              adc abs:.word0 (horizontalBase),x
              tax
              lda long:HORIZONTAL,x
              and ##255
              jsl long:columnLitFar
              bcs scanHit
scanSkip:     inc dp:SP_SCAN
              lda dp:SP_SCAN
              cmp dp:SP_LIMIT
              bcc scanColumn
scanMiss:     clc
              rts
scanHit:      sec
              rts

              .section logictail, text, root
              .public snapSubmitted
;;; The sprite was just projected. Its direct-page state is still that sprite.
snapNewest:   lda dp:SP_H
              cmp ##16
              bcs snapNewSkip
              lda dp:SP_COUNT
              dec a
              sta abs:.word0 (snapAt)
              jsr abs:.word0 (snapBody)
snapNewSkip:  rtl
;;; lightHold is a ceiling light the static walk already submitted.
snapSubmitted:ldx abs:.word0 (lightHold)
              txa
              sec
              sbc ##STATICS
              asl a
              asl a
              sta dp:SP_TMP
              ldy ##0
hitFind:      cpy dp:SP_COUNT
              bcs snapHeldDone
              tya
              asl a
              asl a
              asl a
              asl a
              tax
              lda long:SPR_RECORDS+8,x
              cmp dp:SP_TMP
              beq hitFound
              iny
              bra hitFind
hitFound:     lda long:SPR_RECORDS+10,x
              cmp ##16
              bcs snapHeldDone
              sty abs:.word0 (snapAt)
              lda long:SPR_RECORDS,x
              sta dp:SP_LEFT
              lda long:SPR_RECORDS+2,x
              sta dp:SP_RIGHT
              lda long:SPR_RECORDS+4,x
              sta dp:SP_HI
              lda long:SPR_RECORDS+6,x
              sta dp:SP_SHAPE
              lda long:SPR_RECORDS+8,x
              sta dp:SP_OBJ
              lda long:SPR_RECORDS+10,x
              sta dp:SP_H
              lda dp:SP_OBJ
              lsr a
              lsr a
              lsr a
              tax
              lda long:REMEMBERED,x
              sta dp:SP_N
              lda long:REMEMBERED+0x2,x
              sta dp:SP_LIMIT
              ldx dp:SP_HI
              lda abs:.word0 (viewScaleTex),x
              asl a
              clc
              adc dp:SP_SHAPE
              tax
              lda long:SPRITE_CMDS+SPR_CLIP,x
              sta dp:SP_BASE
              jsr abs:.word0 (snapBody)
snapHeldDone: rtl
snapBody:     ldx dp:SP_SHAPE
              lda long:SPRITE_CMDS+SPR_GAP,x
              sta dp:SP_TMP
              and ##255
              beq snapSolid
              cmp ##255
              bne snapDo
snapSolid:    lda dp:SP_TMP
              bmi snapDo
              lda dp:SP_N
              cmp dp:SP_LIMIT
              bcc snapBodyDone
snapDo:       lda dp:SP_N
              pha
              lda dp:SP_LIMIT
              pha
              jsl long:keepSprite
              pla
              sta dp:SP_SCAN
              pla
              cmp dp:SP_N
              bne snapSpan
              lda dp:SP_SCAN
              cmp dp:SP_LIMIT
              beq snapBodyDone
snapSpan:     lda abs:.word0 (snapAt)
              asl a
              tax
              lda dp:SP_LIMIT
              xba
              ora dp:SP_N
              sta long:SILHOUETTES,x
              lda dp:SP_OBJ
              lsr a
              lsr a
              lsr a
              tax
              lda dp:SP_N
              sta long:REMEMBERED,x
              lda dp:SP_LIMIT
              sta long:REMEMBERED+0x2,x
              cmp dp:SP_N
              bcc snapBodyDone
              beq snapBodyDone
              lda dp:SP_N
              sta dp:SP_TOP
              lda dp:SP_LIMIT
              sta dp:SP_BOT
              jsl long:callInvalidate
snapBodyDone: rts
              .byte 0
;;; A traced floor cell whose word is 0x8000|id belongs to ceiling light id-1.
;;; The trampoline already returned exact 0x8000. X and Y are the ray's cell
;;; word and error, and both survive. The walked cell is cleared after the
;;; note so later rays in this frame take the ordinary zero path.
              .section logictail, text, root
              .public lightNote
lightNote:    and ##0x7fff
              beq lightNoteOut
              cmp ##97
              bcs lightNoteOut
              phx
              stx abs:.word0 (noteCell)
              phy
              dec a
              sta abs:.word0 (noteTmp)
              and ##15
              asl a
              tax
              lda long:bitOne,x
              sta abs:.word0 (noteMask)
              lda abs:.word0 (noteTmp)
              lsr a
              lsr a
              lsr a
              lsr a
              asl a
              tax
              lda abs:.word0 (noteBits),x
              and abs:.word0 (noteMask)
              bne lightNoteZero
              lda abs:.word0 (noteCount)
              cmp ##64
              bcs lightNoteDone
              lda abs:.word0 (noteBits),x
              ora abs:.word0 (noteMask)
              sta abs:.word0 (noteBits),x
              lda abs:.word0 (noteTmp)
              asl a
              tax
              lda long:lightCell,x
              asl a
              tax
              lda dp:VISSTAMP
              sta long:VIS_STAMPS,x
              lda abs:.word0 (noteCount)
              tax
              lda abs:.word0 (noteTmp)
              sta abs:.word0 (noteIds),x
              inc abs:.word0 (noteCount)
              inc abs:.word0 (noteCount)
lightNoteZero:jsr abs:.word0 (zeroWalked)
lightNoteDone:ply
              plx
lightNoteOut: rts
;;; Remember the walked cell and make it zero for the rest of the cast.
zeroWalked:   lda abs:.word0 (clearCount)
              cmp ##64
              bcs zeroSkip
              asl a
              asl a
              tax
              lda abs:.word0 (noteCell)
              sta abs:.word0 (noteClear),x
              lda abs:.word0 (noteTmp)
              inc a
              ora ##0x8000
              sta abs:.word0 (noteClear+2),x
              inc abs:.word0 (clearCount)
              ldx abs:.word0 (noteCell)
              lda ##0
              sta long:TILE_MIRROR,x
zeroSkip:     rts
;;; Point every negative-tile branch at the note trampoline, or back at the
;;; plain stamp, and write the light sentinels only while the view is reduced.
              .section tailirq, text, root
              .public lightArm
lightArm:     rep #0x30
              phy
              lda abs:.word0 (viewWidth)
              cmp ##160
              bcc lightArmOn
              jsr abs:.word0 (restoreTiles)
              jsr abs:.word0 (disarmBras)
              jsl long:loudMarks
              bra lightArmOut
;;; Sentinels are planted first. Every remaining exact 0x8000 is another
;;; static or an open door, and the armed branch would tax each one. Zero
;;; keeps the same stamp-and-step path and lets the branch see only lights.
lightArmOn:   jsr abs:.word0 (applyTiles)
              jsl long:clearFixedMarks
              jsl long:quietMarks
              jsr abs:.word0 (armBras)
lightArmOut:  ply
              rtl
armBras:      lda abs:.word0 (brasOn)
              bne braDone
              lda ##1
              sta abs:.word0 (brasOn)
              ldx ##4
              bra braArm
disarmBras:   lda abs:.word0 (brasOn)
              beq braDone
              stz abs:.word0 (brasOn)
              ldx ##2
braArm:       stx abs:.word0 (armPick)
              ldx ##0
braLoop:      lda long:ddaNegTable,x
              beq braDone
              sta abs:.word0 (armNeg)
              phx
              txa
              clc
              adc abs:.word0 (armPick)
              tax
              lda long:ddaNegTable,x
              jsr abs:.word0 (pokeBra)
              plx
              txa
              clc
              adc ##6
              tax
              bra braLoop
braDone:      rts
;;; A = target. armNeg = bra opcode. Writes the signed displacement.
pokeBra:      sec
              sbc abs:.word0 (armNeg)
              sec
              sbc ##2
              sta abs:.word0 (noteTmp)
              lda abs:.word0 (armNeg)
              inc a
              phx
              tax
              sep #0x20
              lda abs:.word0 (noteTmp)
              sta long:WALL_CAST_BANK,x
              rep #0x30
              plx
              rts
applyTiles:   lda abs:.word0 (lightTilesOn)
              bne applyOut
              lda ##1
              sta abs:.word0 (lightTilesOn)
              ldy ##0
applyLoop:    cpy abs:.word0 (lightCount)
              bcs applyOut
              jsr abs:.word0 (loadLight)
              lda abs:.word0 (tileCell)
              asl a
              tax
              lda long:TILE_MIRROR,x
              cmp ##0x8000
              beq applyOwn
              cmp ##0
              bne applySides
applyOwn:     lda abs:.word0 (tileSent)
              sta long:TILE_MIRROR,x
applySides:   jsr abs:.word0 (markWest)
              jsr abs:.word0 (markEast)
              jsr abs:.word0 (markSouth)
              jsr abs:.word0 (markNorth)
              iny
              bra applyLoop
applyOut:     rts
restoreTiles: lda abs:.word0 (lightTilesOn)
              beq applyOut
              stz abs:.word0 (lightTilesOn)
              ldy ##0
restoreLoop:  cpy abs:.word0 (lightCount)
              bcs applyOut
              jsr abs:.word0 (loadLight)
              lda abs:.word0 (tileCell)
              asl a
              tax
              lda long:TILE_MIRROR,x
              cmp abs:.word0 (tileSent)
              bne restoreSides
              lda ##0x8000
              sta long:TILE_MIRROR,x
restoreSides: jsr abs:.word0 (clearWest)
              jsr abs:.word0 (clearEast)
              jsr abs:.word0 (clearSouth)
              jsr abs:.word0 (clearNorth)
              iny
              bra restoreLoop
loadLight:    tya
              asl a
              tax
              lda long:lightCell,x
              sta abs:.word0 (tileCell)
              tya
              inc a
              ora ##0x8000
              sta abs:.word0 (tileSent)
              rts
markWest:     lda abs:.word0 (tileCell)
              and ##0x0fc0
              beq sideOut
              lda abs:.word0 (tileCell)
              sec
              sbc ##64
              bra markCell
markEast:     lda abs:.word0 (tileCell)
              and ##0x0fc0
              cmp ##0x0fc0
              beq sideOut
              lda abs:.word0 (tileCell)
              clc
              adc ##64
              bra markCell
markSouth:    lda abs:.word0 (tileCell)
              and ##63
              beq sideOut
              lda abs:.word0 (tileCell)
              dec a
              bra markCell
markNorth:    lda abs:.word0 (tileCell)
              and ##63
              cmp ##63
              beq sideOut
              lda abs:.word0 (tileCell)
              inc a
markCell:     asl a
              tax
              lda long:TILE_MIRROR,x
              bne sideOut
              lda abs:.word0 (tileSent)
              sta long:TILE_MIRROR,x
sideOut:      rts
clearWest:    lda abs:.word0 (tileCell)
              and ##0x0fc0
              beq sideOut
              lda abs:.word0 (tileCell)
              sec
              sbc ##64
              bra clearCell
clearEast:    lda abs:.word0 (tileCell)
              and ##0x0fc0
              cmp ##0x0fc0
              beq sideOut
              lda abs:.word0 (tileCell)
              clc
              adc ##64
              bra clearCell
clearSouth:   lda abs:.word0 (tileCell)
              and ##63
              beq sideOut
              lda abs:.word0 (tileCell)
              dec a
              bra clearCell
clearNorth:   lda abs:.word0 (tileCell)
              and ##63
              cmp ##63
              beq sideOut
              lda abs:.word0 (tileCell)
              inc a
clearCell:    asl a
              tax
              lda long:TILE_MIRROR,x
              cmp abs:.word0 (tileSent)
              bne sideOut
              lda ##0
              sta long:TILE_MIRROR,x
              rts
;;; The static walk already submitted every noted light. Snap the short ones,
;;; then put the sentinels back for the next cast.
              .section logictail, text, root
              .public lightFinish
lightFinish:  lda abs:.word0 (noteCount)
              beq finishOut
              stz abs:.word0 (snapUsed)
              ldx ##0
finishLoop:   lda abs:.word0 (noteIds),x
              phx
              asl a
              tax
              lda long:lightRec,x
              sta abs:.word0 (lightHold)
              jsl long:snapSubmitted
              plx
              inx
              inx
              cpx abs:.word0 (noteCount)
              bcc finishLoop
              ldy abs:.word0 (clearCount)
              beq finishBits
              dey
finishRestore:tya
              asl a
              asl a
              tax
              lda abs:.word0 (noteClear+2),x
              pha
              lda abs:.word0 (noteClear),x
              tax
              pla
              sta long:TILE_MIRROR,x
              dey
              bpl finishRestore
finishBits:   stz abs:.word0 (clearCount)
              lda ##0
              ldx ##10
finishClear:  sta abs:.word0 (noteBits),x
              dex
              dex
              bpl finishClear
              stz abs:.word0 (noteCount)
finishOut:    rtl
;;; Exact 0x8000 markers take the ordinary empty step after this. Sentinels
;;; are 0x8001 and up, so they stay for the armed branch.
clearFixedMarks:
              rep #0x30
              ldx ##0
clearFixedNext:
              lda long:TILE_MIRROR,x
              cmp ##0x8000
              bne clearFixedStep
              lda ##0
              sta long:TILE_MIRROR,x
clearFixedStep:
              inx
              inx
              cpx ##8192
              bcc clearFixedNext
              rtl
quietMarks:   lda ##0
              bra storeMarkWords
loudMarks:    lda ##0x8000
storeMarkWords:
              sta long:staticMarkWord+1
              sta long:rayMarkWord+1
              sta long:emptyMarkWord+1
              sta long:openDoorWord+1
              sta long:saveOpenWord+1
              rtl
              .section tailio, text, root
lightRec:     .space 192
lightCell:    .space 192
bitOne:       .word 0x0001, 0x0002, 0x0004, 0x0008, 0x0010, 0x0020, 0x0040, 0x0080
              .word 0x0100, 0x0200, 0x0400, 0x0800, 0x1000, 0x2000, 0x4000, 0x8000
;;; Ceiling lights only (chandelier, ceiling light). Built when the level's
;;; statics change, from setView, so a timed frame does not walk the map.
;;; A light whose own tile was traced is already drawn; this pass only
;;; recovers one a reduced view stepped over, and snaps a short one.
              .section tailhole, text, root
;;; A = the new view index. A size key in play never runs during a timedemo.
;;; Full width disarms after the width is stored. A reduced width leaves the
;;; latch for viewCutHook, which clears it before the next frame.
              .public sizeArm
sizeArm:      cmp ##3
              bcs sizeFull
              pha
              inc a
              sep #0x20
              sta long:VIEW_LATCH
              rep #0x20
              pla
              jsr abs:.word0 (setViewInPlay)
              rts
sizeFull:     jsr abs:.word0 (setViewInPlay)
              jsl long:lightArm
              rts
              .public viewCutHook
viewCutHook:  sta abs:.word0 (viewWidth)
              cmp ##160
              bcc hookReduced
hookDone:     rts
;;; PollTicInput calls setView before it clears $03E1. A zero latch, which is
;;; the timedemo's boot view, does not reach the store. The wall cast in this
;;; setView still takes the plain branches; the sprite hook arms after it.
hookReduced:  phx
              sep #0x20
              lda long:VIEW_LATCH
              rep #0x20
              beq hookPop
              jsl long:clearLatch
              sta abs:.word0 (lightHook+1)
hookPop:      plx
              bra hookDone
armAtSprites: pha
              phx
              phy
              php
              jsl long:installLightHook
              plp
              ply
              plx
              pla
              jmp abs:.word0 (lightGate)
              .section logictail, text, root
;;; Menu boot, bank $3F. A full view drops UiLeave's latch. A reduced view
;;; keeps it for the one setView that follows. Timedemo boot does not call this.
              .public clearIfFull
clearIfFull:  php
              rep #0x30
              lda long:weaponViewIndex
              lsr a
              cmp ##3
              bcc clearIfDone
              sep #0x20
              lda #0
              sta long:VIEW_LATCH
clearIfDone:  plp
              rtl
installLightHook:
              phx
              lda abs:.word0 (viewWidth)
              cmp ##160
              bcs lightHookFull
              lda long:LOGIC_BASE+V_mapon
              cmp abs:.word0 (lightMap)
              bne lightRebuild
              lda long:LOGIC_BASE+V_laststat
              cmp abs:.word0 (lightLast)
              beq lightHookReduced
lightRebuild: lda long:LOGIC_BASE+V_mapon
              sta abs:.word0 (lightMap)
              lda long:LOGIC_BASE+V_laststat
              sta abs:.word0 (lightLast)
              jsr abs:.word0 (buildLightColumns)
lightHookReduced:
              lda ##.word0 (lightGate)
              bra lightHookStore
lightHookFull:lda ##.word0 (staticsDone)
lightHookStore:
              sta abs:.word0 (lightHook+1)
              jsl long:lightArm
              ldx ##0x8635
repairLoop:   lda long:WALL_CAST_BANK,x
              inx
              cpx ##0x87e1
              bcc repairLoop
              plx
              rtl
;;; Records only. The tile sentinels are written when the reduced view is armed,
;;; so a full-width frame never sees them.
buildLightColumns:
              rep #0x30
              stz abs:.word0 (lightCount)
              stz abs:.word0 (lightTilesOn)
              ldx ##STATICS
lightScan:    txa
              cmp long:LOGIC_BASE+V_laststat
              bcs lightScanDone
              lda long:LOGIC_BASE+0x2,x
              cmp ##SPR_STAT_14
              beq lightAdd
              cmp ##SPR_STAT_4
              bne lightScanNext
lightAdd:     lda abs:.word0 (lightCount)
              cmp ##96
              bcs lightScanDone
              asl a
              sta abs:.word0 (armPick)
              txa
              ldx abs:.word0 (armPick)
              sta long:lightRec,x
              tax
              lda long:LOGIC_BASE,x
              phx
              ldx abs:.word0 (armPick)
              sta long:lightCell,x
              plx
              inc abs:.word0 (lightCount)
lightScanNext:txa
              clc
              adc ##8
              tax
              jmp abs:.word0 (lightScan)
lightScanDone:rts
;;; Nonzero latch only. Returns A = armAtSprites and drops the latch so the
;;; frame after a menu boot does not set the view again.
clearLatch:   sep #0x20
              lda #0
              sta long:VIEW_LATCH
              rep #0x20
              lda ##.word0 (armAtSprites)
              rtl
;;; OpenFloor replaces the tile map, so the previous floor's sentinels are
;;; gone while lightTilesOn still says they were planted. The next prepare
;;; arms this floor once. A timed frame never reaches OpenFloor.
              .section logictail, text, root
              .public floorRearm
floorRearm:   jsl long:UiLoadDone
              php
              rep #0x30
              lda ##65535
              sta long:lightMap
              sta long:lightLast
              lda ##.word0 (armAtSprites)
              sta long:lightHook+1
              lda ##0
              sta long:lightTilesOn
              plp
              rtl
              .section tailhud, text, root
;;; Reduced frames only. Full width still jumps straight at staticsDone.
lightGate:    jsl long:raiseShortLights
              jmp abs:.word0 (lightPass)
lightPass:    lda abs:.word0 (noteCount)
              beq lightPassOut
              jsl long:lightFinish
lightPassOut: jmp abs:.word0 (staticsDone)
callInvalidate:
              jsr abs:.word0 (invalidateRange)
              rtl
              .byte 0
noteCount:    .word 0
noteIds:      .word 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
noteBits:     .word 0, 0, 0, 0, 0, 0
noteMask:     .word 0
noteTmp:      .word 0
noteCell:     .word 0
clearCount:   .word 0
armNeg:       .word 0
armPick:      .word 0
tileCell:     .word 0
tileSent:     .word 0
lightTilesOn: .word 0
brasOn:       .word 0
lightMap:     .word 65535
lightLast:    .word 65535
lightCount:   .word 0
lightHold:    .word 0
snapAt:       .word 0
snapUsed:     .word 0
litFrameA:    .word 0
litFrameB:    .word 0
;;; Primary slot, then a second slot or 0. Index is SP_HI (h=2,4,...,16).
lightSlots:   .byte 64,0, 65,0, 66,0, 67,0, 68,0, 70,0, 71,72, 73,74
noteClear:    .space 256
              .section logictail, text, root
;;; Reduced frames only. One compare skips h>=16. A ceiling light whose drawn
;;; samples miss the pool bulb is raised until one of those samples shows it.
raiseShortLights:
              php
              rep #0x30
              lda abs:.word0 (lightCount)
              beq raiseOut
              ldx ##SPR_STAT_14*2
              lda abs:.word0 (spriteFrame),x
              sta abs:.word0 (litFrameA)
              ldx ##SPR_STAT_4*2
              lda abs:.word0 (spriteFrame),x
              sta abs:.word0 (litFrameB)
              ldy ##0
raiseWalk:    cpy dp:SP_COUNT
              bcs raiseOut
              tya
              asl a
              asl a
              asl a
              asl a
              tax
              lda long:SPR_RECORDS+10,x
              cmp ##16
              bcs raiseNext
              lda long:SPR_RECORDS+6,x
              cmp abs:.word0 (litFrameA)
              beq raiseHit
              cmp abs:.word0 (litFrameB)
              bne raiseNext
raiseHit:     phy
              sty abs:.word0 (snapAt)
              lda long:SPR_RECORDS,x
              sta dp:SP_LEFT
              lda long:SPR_RECORDS+2,x
              sta dp:SP_RIGHT
              lda long:SPR_RECORDS+4,x
              sta dp:SP_HI
              lda long:SPR_RECORDS+6,x
              sta dp:SP_SHAPE
              lda long:SPR_RECORDS+8,x
              sta dp:SP_OBJ
              lda long:SPR_RECORDS+10,x
              sta dp:SP_H
              lda dp:SP_OBJ
              lsr a
              lsr a
              lsr a
              tax
              lda long:REMEMBERED,x
              sta dp:SP_N
              lda long:REMEMBERED+0x2,x
              sta dp:SP_LIMIT
              jsr abs:.word0 (snapBody)
              ply
raiseNext:    iny
              bra raiseWalk
raiseOut:     plp
              rtl
;;; A = source column. Carry when the pool run's slot byte is not a flat gray.
columnLitFar: jsr abs:.word0 (columnLit)
              rtl
columnLit:    phy
              sta dp:SP_EXTRA
              ldx dp:SP_HI
              lda abs:.word0 (lightSlots),x
              sta dp:SP_BOT
              lda dp:SP_EXTRA
              asl a
              clc
              adc dp:SP_SHAPE
              tax
              lda long:SPRITE_CMDS,x
              sta dp:SP_PTR
              ldx dp:SP_SHAPE
              lda long:SPRITE_CMDS+SPR_COMMAND_BANK,x
              sta dp:SP_PTR+2
              ldy ##0
              lda [SP_PTR],y
              beq colMiss
              and ##255
              cmp ##200
              bcc colMiss
              iny
              iny
              lda [SP_PTR],y
              sta dp:SP_TMP
              ldx dp:SP_SHAPE
              lda long:SPRITE_CMDS+SPR_LIGHT_BANKS,x
              sep #0x20
              sta dp:SP_EXTRA
              rep #0x20
              lda dp:SP_TMP
              sta dp:SP_PTR
              sep #0x20
              lda dp:SP_EXTRA
              sta dp:SP_PTR+2
              rep #0x20
              lda dp:SP_BOT
              and ##255
              asl a
              tay
              jsr abs:.word0 (poolByteLit)
              bcs colHit
              lda dp:SP_BOT
              xba
              and ##255
              beq colMiss
              asl a
              tay
              jsr abs:.word0 (poolByteLit)
              bcc colMiss
colHit:       ply
              sec
              rts
colMiss:      ply
              clc
              rts
poolByteLit:  sep #0x20
              lda [SP_PTR],y
              sta dp:SP_TMP
              and #0x0f
              sta dp:SP_EXTRA
              lda dp:SP_TMP
              lsr a
              lsr a
              lsr a
              lsr a
              cmp dp:SP_EXTRA
              rep #0x20
              beq poolGray
              sec
              rts
poolGray:     clc
              rts
;;; Miss path. Keep the lit horizontal sample; do not replace it with column 32.
fitLight:     php
              rep #0x30
              phy
              lda dp:SP_H
              lsr a
              sta dp:SP_TOP
              lda ##0xffff
              sta dp:SP_NEW
              ldx dp:SP_HI
fitHeight:    cpx ##16
              bcs fitNone
              lda abs:.word0 (scaleHeight),x
              sta dp:SP_H
              stx dp:SP_HI
              lda abs:.word0 (horizontalBase),x
              sta dp:SP_SCAN
              ldy ##0
fitIndex:     cpy dp:SP_TOP
              bcs fitOutside
              tya
              clc
              adc dp:SP_SCAN
              tax
              lda long:HORIZONTAL,x
              and ##255
              phy
              jsr abs:.word0 (columnLit)
              ply
              bcs fitShared
              iny
              bra fitIndex
fitOutside:   lda dp:SP_NEW
              cmp ##0xffff
              bne fitStep
              lda dp:SP_H
              lsr a
              sta dp:SP_RIGHT
              ldy dp:SP_TOP
fitOutIndex:  cpy dp:SP_RIGHT
              bcs fitStep
              tya
              clc
              adc dp:SP_SCAN
              tax
              lda long:HORIZONTAL,x
              and ##255
              sta dp:SP_SRC
              phy
              jsr abs:.word0 (columnLit)
              ply
              bcs fitRemember
              iny
              bra fitOutIndex
fitRemember:  sty dp:SP_NEW
              lda dp:SP_HI
              sta dp:SP_OLD
fitStep:      ldx dp:SP_HI
              inx
              inx
              bra fitHeight
fitShared:    ldx dp:SP_HI
              lda abs:.word0 (horizontalBase),x
              sec
              sbc dp:SP_LEFT
              jsr abs:.word0 (fitRecord)
              jsr abs:.word0 (fitSpan)
              bra fitDone
fitNone:      lda dp:SP_NEW
              cmp ##0xffff
              beq fitDone
              lda abs:.word0 (snapAt)
              cmp ##16
              bcs fitDone
              ldx dp:SP_OLD
              stx dp:SP_HI
              lda abs:.word0 (scaleHeight),x
              sta dp:SP_H
              lda abs:.word0 (horizontalBase),x
              clc
              adc ##0x9000
              sta dp:SP_PTR
              sep #0x20
              lda #8
              sta dp:SP_PTR+2
              rep #0x20
              lda abs:.word0 (snapAt)
              asl a
              asl a
              asl a
              tax
              ldy ##0
              lda dp:SP_H
              lsr a
              sta dp:SP_SCAN
fitCopy:      sep #0x20
              lda [SP_PTR],y
              sta long:SHORT_LIGHT_MAPS,x
              rep #0x20
              inx
              iny
              cpy dp:SP_SCAN
              bcc fitCopy
              lda dp:SP_TOP
              inc a
              lsr a
              cmp dp:SP_TOP
              bcc fitCenter
              lda dp:SP_TOP
              dec a
fitCenter:    sta dp:SP_TMP
              lda abs:.word0 (snapAt)
              asl a
              asl a
              asl a
              clc
              adc dp:SP_TMP
              tax
              sep #0x20
              lda dp:SP_SRC
              sta long:SHORT_LIGHT_MAPS,x
              rep #0x20
              ldy dp:SP_TMP
              lda abs:.word0 (snapAt)
              asl a
              asl a
              asl a
              clc
              adc ##0x6f00
              sec
              sbc dp:SP_LEFT
              jsr abs:.word0 (fitRecord)
              jsr abs:.word0 (fitSpan)
fitDone:      ply
              plp
              rtl
fitRecord:    pha
              lda abs:.word0 (snapAt)
              asl a
              asl a
              asl a
              asl a
              tax
              pla
              sta long:SPR_RECORDS+14,x
              lda dp:SP_HI
              sta long:SPR_RECORDS+4,x
              lda dp:SP_H
              sta long:SPR_RECORDS+10,x
              rts
fitSpan:      lda dp:SP_N
              cmp dp:SP_LIMIT
              bcc fitSpanOut
              tya
              clc
              adc dp:SP_LEFT
              bmi fitSpanOut
              cmp abs:.word0 (viewWidth)
              bcs fitSpanOut
              sta dp:SP_N
              inc a
              sta dp:SP_LIMIT
fitSpanOut:   rts
#endif

;;; With Vsync off the hook is SEP/RTL. Setting changes patch the hook.
              .section tailhud, text, root, noreorder
              .public vsyncB, vsyncWait, vsyncReady
;;; No stack use: S already points into the prepared paint list. IRQs stay on.
;;; Keep this entry and return in place; the wait lives in the resident tail.
vsyncB:
vsyncWait:    jmp long:vsyncViewWait
              .byte 0,0,0,0,0,0,0,0,0,0
vsyncReady:   rtl

#include "draw_buffer.inc"

#include "wall_paint.inc"
