;;; Project visible sprites and paint their opaque runs with the wall scaler.
;;; Each run retains the corrected source pointer needed by the scaler's
;;; texture-coordinate calculation.
#include "memmap.inc"
#include "game.inc"
#include "sprite_ids.inc"
#include "asset_constants.inc"
#include "picture_config.inc"
#include "weapon_empty.inc"
#include "logic.inc"
#include "sprite_layout.inc"
#include "sight.inc"
              .section gamecode, text, root, noreorder
SORT_KEYS_AT  .equ SPR_SORT_KEYS        ; sort key per order entry, after the saved projection IDs
SORT_KEYS     .equ 472                  ; entries before SPR_HISTORY
              .public SPR_RECORDS, SPR_ORDER, SPR_SAVED_IDS, SPR_HISTORY
              .public PrepareSprites, UseLogicActorVisibility, UseRayActorVisibility, logicActorVisibility
              .public lightHook, trackHook, staticsDone, trackProjection, projectObject, invalidateRange
              .extern castMinX, castMaxX, castMinY, castMaxY
              .extern wallDirty
              .public weaponMaskTable, oldWeaponMaskTable, weaponScaleIndex
              .public maskBitOnlyUsed
              .public projectionStamp
              .public spriteSideLimit
              .public staticRevision
              .extern castMinHeight
#if !WOLF_PREPARED
              .public ComposeAndPaint
              .public spanBuffer
              .public texturedSpan
#endif
              .extern viewWidth, viewFactor, viewTop, viewBottom, viewLeft, viewBytes
              .extern frameCount, heightIndex, sourceAddr, sourceBank
              .extern scaleIndex, scaleHeight, scaleBank, scaleWidthRecip
              .extern rowCodeBase, rowTexBase, texEndpointBase, spriteFrame
              .extern horizontalBase
              .extern HeightOfDepth
              .extern groupBase
              .extern oldHeight, oldSource, oldBank
              .extern stateRotate, flatNonempty, viewScaleTop, viewScaleBottom
              .extern viewScaleTex
              .extern levelState
              .extern objectBytes, weapon, weaponFrame, weaponReady
              .extern weaponViewIndex

              .public projectionCold
              .extern ResetSharedProjections
PrepareSprites:
              lda abs:.word0 (projectionCold)
              beq projectionWarm
              jsl long:ResetSharedProjections
projectionWarm:
#if WOLF_PREPARED
              lda dp:FIRST
              beq masksKept
              ldx ##318
              lda ##0
clearMasks:   sta long:COLUMN_MASKS,x   ; the paint clears each mask it reads
              dex
              dex
              bpl clearMasks
masksKept:
#endif
              lda abs:.word0 (weaponMaskTable)
#if WOLF_PREPARED
              ldx dp:FIRST
              beq oldWeaponReady
              lda ##EMPTY_WEAPON_MASK   ; a new view has no weapon pixels yet
oldWeaponReady:
#endif
              sta abs:.word0 (oldWeaponMaskTable)
              lda abs:.word0 (projectionStamp)
              inc a
              and ##255
              bne newProjectionStamp
              ldx ##550
clearProjectionStamp:
              lda ##0
              sta long:OBJECT_STAMPS,x
              dex
              dex
              bpl clearProjectionStamp
              lda ##1
newProjectionStamp:
              sta abs:.word0 (projectionStamp)
              lda dp:SP_COUNT
              asl a
              sta dp:SP_PREV
              lda ##.word0 (SPR_RECORDS+8)
              sta dp:SP_PTR
              lda ##.byte2 (SPR_RECORDS)
              sta dp:SP_PTR+2
              ldx ##0
              ldy ##0
;;; X indexes saved words; Y advances through the 16-byte visible records.
saveProjectionIDs:
              cpx dp:SP_PREV
              bcs projectionIDsReady
              lda [SP_PTR],y
              sta long:SPR_SAVED_IDS,x
              tya
              adc ##16                  ; CPX left carry clear; the record span fits one bank
              tay
              inx
              inx
              bra saveProjectionIDs
projectionIDsReady:
              stz dp:SP_COUNT
#if WOLF_PREPARED
;;; Only the columns that sprites marked or invalidated last frame need
;;; their marks cleared (all of them after a view change).
              lda dp:FIRST
              beq touchedOnly
              stz abs:.word0 (touchedLow)
              lda ##WOLF_COLUMN_BYTES
              sta abs:.word0 (touchedHigh)
touchedOnly:  lda abs:.word0 (touchedHigh)
              cmp abs:.word0 (touchedLow)
              beq candidatesClear
              bcc candidatesClear
              dec a
              ora ##1
              tax                       ; last word to clear
              lda abs:.word0 (touchedLow)
              and ##0xfffe
              sta dp:SP_TMP
              cpx dp:SP_TMP
              bcc candidatesClear
              lda ##0
clearCandidates:
              sta long:MARKS-1,x     ; bit 4 (a moved sprite) clears with the mark
              dex
              dex
              bmi candidatesClear
              cpx dp:SP_TMP
              bcs clearCandidates
candidatesClear:
              lda ##255
              sta abs:.word0 (touchedLow)
              stz abs:.word0 (touchedHigh)
#else
              ldx ##WOLF_COLUMN_BYTES-2
clearCandidates:
              lda ##0
              sta long:MARKS,x
              sta long:EXTRA_MASKS,x
              dex
              dex
              bpl clearCandidates
#endif
;;; The exact logic owns the objects in bank $28: statics (render IDs 0..399)
;;; and the actor list (render IDs 400..549). Sparse wall rays bound a
;;; conservative static rectangle; live actors use the gameplay visibility flag.
              lda dp:ANGLE
              asl a
              tax
              lda long:COS_TABLE,x
              sta dp:SP_C
              lda long:SIN_TABLE,x
              sta dp:SP_S
              jsr abs:.word0 (prepareFactors)
              stz dp:ENTRY
              lda ##0x33
              sta dp:ENTRY+2
              jsr abs:.word0 (reuseStaticRecords)
              bcc freshStatics
              jmp abs:.word0 (actorsFromStatics)
freshStatics:
              jsr abs:.word0 (prepareStaticFactors)
              stz dp:SP_OBJ
              stz dp:AI_FAMILY            ; statics: no actor depth offset
              stz dp:AI_TURN              ; and no rotation
              lda abs:.word0 (castMinX)
              lsr a
              lsr a
              lsr a
              lsr a
              lsr a
              lsr a
              and ##0xfffe
              clc
              adc ##0xe000
              sta abs:.word0 (staticLowLoad+1)
              lda abs:.word0 (castMaxX)
              lsr a
              lsr a
              lsr a
              lsr a
              lsr a
              lsr a
              and ##0xfffe
              clc
              adc ##0xe006
              sta abs:.word0 (staticHighLoad+1)
              lda abs:.word0 (castMinY)
              and ##0xfffe
              clc
              adc ##0xe046
              sta abs:.word0 (staticYLowLoad+1)
              lda abs:.word0 (castMaxY)
              and ##0xfffe
              clc
              adc ##0xe04c
              sta abs:.word0 (staticYHighLoad+1)
              lda long:LOGIC_BASE+V_laststat
              sta abs:.word0 (staticMaskEnd)
              ldx ##0                     ; mask word of the first group
              ldy ##STATICS               ; and its first record
staticGroup:
staticYLowLoad:
              lda long:STATIC_INDEX+0x46,x
staticYHighLoad:
              eor long:STATIC_INDEX+0x4c,x
              sta dp:SP_TMP
staticLowLoad:
              lda long:STATIC_INDEX,x
staticHighLoad:
              eor long:STATIC_INDEX+0x6,x
              and dp:SP_TMP
              bne staticMasked
staticAdvance:
              txa
              clc
              adc ##140
              tax
              tya
              clc
              adc ##128
              tay
              cpy abs:.word0 (staticMaskEnd)
              bcc staticGroup
;;; setView patches this jump to lightPass for views below full width,
;;; or to staticsDone for full width.
lightHook:    jmp abs:.word0 (staticsDone)
staticMasked: sta abs:.word0 (staticMaskBits)
              stx abs:.word0 (staticMaskOffset)
              sty abs:.word0 (staticGroupBase)
              sty abs:.word0 (staticBitBase)
staticSelect: and ##255
              bne staticLowBit
              lda abs:.word0 (staticMaskBits)
              xba
              sta abs:.word0 (staticMaskBits)
              lda abs:.word0 (staticBitBase)
              clc
              adc ##64
              sta abs:.word0 (staticBitBase)
              lda abs:.word0 (staticMaskBits)
staticLowBit: tay
              lda abs:.word0 (staticBitOffset),y
              and ##255
              clc
              adc abs:.word0 (staticBitBase)
              tax
              lda abs:.word0 (staticMaskBits)
              dec a
              and abs:.word0 (staticMaskBits)
              sta abs:.word0 (staticMaskBits)
staticTest:   lda long:LOGIC_BASE,x         ; cell
              sta dp:AI_CELL
              lda long:LOGIC_BASE+0x2,x
              cmp ##0xffff
              beq staticNext              ; taken or never placed
              sta dp:SP_SHAPE
;;; Ceiling fixtures already stamp their expanded footprint through lightNote.
;;; Their sample recovery must not admit distant lights through an unseen room.
              cmp ##SPR_STAT_14
              beq staticLight
              cmp ##SPR_STAT_4
              bne staticProject
staticLight:  lda dp:AI_CELL
              asl a
              tay
              lda [ENTRY],y
              cmp dp:VISSTAMP
              bne staticNext
staticProject:
              stx dp:AI_OBJ
              txa
              sec
              sbc ##STATICS
              asl a
              asl a
              sta dp:SP_OBJ               ; render ID: eight bytes of record, 32 per static
              jsr abs:.word0 (projectStatic)
              ldx dp:AI_OBJ
staticNext:   lda abs:.word0 (staticMaskBits)
              bne staticSelect
staticGroupDone:
              ldx abs:.word0 (staticMaskOffset)
              ldy abs:.word0 (staticGroupBase)
              jmp abs:.word0 (staticAdvance)
staticsDone:  jsr abs:.word0 (saveStaticRecords)
actorsFromStatics:
              lda ##1
              sta dp:AI_FAMILY
actorStartLoad:
              lda long:SIGHT_VISIBLE
actorScan:    bne actorRecord
              jmp abs:.word0 (actorsDone)
actorRecord:  tax
              stx dp:AI_OBJ
actorHasFlags:
              lda long:LOGIC_BASE+O_STATE,x
              tax
              lda long:LOGIC_BASE+ST_SHAPE,x
              bne actorShaped
              jmp abs:.word0 (actorNext)
actorShaped:  sta dp:SP_SHAPE
              lda long:LOGIC_BASE+ST_ROTATE,x
              sta dp:AI_TURN
              lda dp:AI_OBJ
              sec
              sbc ##OBJLIST
              lsr a
              clc
              adc ##400*32
              sta dp:SP_OBJ
              ldx dp:AI_OBJ
actorCellsGate:
              bra actorVisible
actorCellsTest:
              lda long:LOGIC_BASE+O_MARKED,x
              asl a
              sta dp:AI_CELL
              tay
;;; Word stamps match the ray front end; negative mirror words are floors.
              lda [ENTRY],y
              cmp dp:VISSTAMP
              beq actorVisible
              ldx ##14
actorNeighbor:lda dp:AI_CELL
              clc
              adc long:actorSteps,x
              tay
              lda [ENTRY],y
              cmp dp:VISSTAMP
              bne actorNotHere
              tya
              clc
              adc ##0x2000
              tay
              lda [ENTRY],y               ; the tile mirror
              bmi actorVisible
              beq actorVisible
actorNotHere: dex
              dex
              bpl actorNeighbor
              bra actorNext
actorVisible: ldx dp:AI_OBJ
              lda long:LOGIC_BASE+O_X+1,x
              sec
              sbc dp:VX
              sta dp:SP_DX
              lda long:LOGIC_BASE+O_Y+1,x
              sec
              sbc dp:VY
              sta dp:SP_DY
              lda long:LOGIC_BASE+O_DIR,x
              sta dp:AI_DIR
              jsr abs:.word0 (projectObject)
actorNext:    ldx dp:AI_OBJ
actorNextLoad:
              lda long:LOGIC_BASE+O_VNEXT,x
              jmp abs:.word0 (actorScan)
actorsDone:   lda ##550*32
              sta dp:SP_OBJ               ; the weapon's ID follows the objects
              jmp abs:.word0 (objectsDone)
actorSteps:   .word 0xfffe, 2, 0xff7e, 0xff80, 0xff82, 130, 128, 126

;;; SP_DX, SP_DY (8.8 from the view point), SP_SHAPE, AI_FAMILY (1: actor),
;;; AI_TURN (state rotate), AI_DIR: project and add a visible record.
projectObject:
              lda dp:SP_DX
              jsr abs:.word0 (productsCS)
              sta dp:SP_DEPTH
              sty dp:SP_SIDE
              lda dp:SP_DY
              jsr abs:.word0 (productsCS)
              sec
              sbc dp:SP_SIDE
              sta dp:SP_SIDE
              tya
              clc
              adc dp:SP_DEPTH
              sec
              sbc ##32
              sta dp:SP_DEPTH
              lda dp:AI_FAMILY
              beq depthReady
              lda dp:SP_DEPTH
              sec
              sbc ##32
              sta dp:SP_DEPTH
depthReady:   lda dp:SP_DEPTH
              cmp ##88
              bcc depthRejected
              cmp ##16384
              bcc depthVisible
depthRejected:rts
depthVisible:
#if WOLF_TRUE_PIXELS
              asl a
              tax
              lda long:NP_TRUE_HEIGHTS,x
#else
              jsr abs:.word0 (HeightOfDepth)
#endif
              sta dp:SP_HI
#if WOLF_PREPARED
;;; Interpolated heights stay between their traced endpoints. A shorter
;;; sprite cannot clear any wall. Short-light sample recovery remains exempt.
              cmp abs:.word0 (castMinHeight)
              bcs spriteHasDepth
              lda dp:SP_SHAPE
              cmp ##SPR_STAT_14
              beq spriteHasDepth
              cmp ##SPR_STAT_4
              bne depthRejected
spriteHasDepth:
              lda dp:SP_HI
;;; Each height page has build-time side limits for all four view sizes.
;;; Reject only beyond the whole billboard, before scaling its side offset.
              cmp ##256
              xba
              ror a
              tax
              lda dp:SP_SIDE
              bpl sideMagnitude
              eor ##65535
              inc a
sideMagnitude:
spriteSideLimit:
              cmp long:ENDPOINTS+0xd8,x
              bcs depthRejected
              lda dp:SP_HI
#endif
              tax
              lda abs:.word0 (scaleHeight),x
              sta dp:SP_H
scaleSide:
              lda dp:SP_H
              lsr a
              tay
              jsr abs:.word0 (scaleSetup)
              lda dp:SP_SIDE
              bpl sidePositive
              eor ##65535
              inc a
              jsr abs:.word0 (scaleValue)
              eor ##65535
              inc a
              bra sideScaled
sidePositive: jsr abs:.word0 (scaleValue)
sideScaled:
#if WOLF_TRUE_PIXELS
              asl a
#endif
              sta dp:SP_SIDE
              lda dp:SP_H
#if !WOLF_TRUE_PIXELS
              lsr a
#endif
              sta dp:SP_TMP
              lda abs:.word0 (viewWidth)
              sec
              sbc dp:SP_TMP
              cmp ##0x8000
              ror a
              clc
              adc dp:SP_SIDE
              sta dp:SP_LEFT
              clc
              adc dp:SP_TMP
              sta dp:SP_RIGHT
              bmi behindCamera
              cmp ##0
              beq behindCamera
              lda dp:SP_LEFT
              bmi onScreen
              cmp abs:.word0 (viewWidth)
              bcc onScreen
behindCamera: rts
onScreen:     lda dp:AI_TURN
              beq noRotation
              ldx dp:AI_OBJ
              lda long:LOGIC_BASE+O_CLASS,x
              cmp ##20                   ; a rocket has an angle, not a facing direction
              bne directionRotation
              lda long:LOGIC_BASE+O_ANGLE,x
              asl a
              tax
              lda long:LOGIC_BASE+DEG1024,x
              bra facingReady
directionRotation:
              lda dp:AI_DIR
              asl a
              asl a
              asl a
              asl a
              asl a
              asl a
              asl a
facingReady:
              sta dp:SP_TMP
              lda dp:ANGLE
              sec
              sbc dp:SP_TMP
              clc
              adc ##576
              and ##1023
              lsr a
              lsr a
              lsr a
              lsr a
              lsr a
              lsr a
              lsr a
              ldx dp:AI_TURN
              cpx ##2
              bne fullRotation
              and ##4
fullRotation: clc
              adc dp:SP_SHAPE
              sta dp:SP_SHAPE
noRotation:   lda dp:SP_SHAPE
              asl a
              tax
              lda abs:.word0 (spriteFrame),x
              sta dp:SP_SHAPE
              lda ##0
              sta dp:SP_PRI
              jmp abs:.word0 (addVisible)
objectsDone:  jsr abs:.word0 (retireProjection)
              lda abs:.word0 (levelState)
              beq weaponVisible
              lda ##EMPTY_WEAPON_MASK
              sta abs:.word0 (weaponMaskTable)
              jmp abs:.word0 (spritesReady)
weaponVisible: ; SimpleScaleShape(viewheight+1) rounds to an even height.
              lda abs:.word0 (viewBytes)
              inc a
              and ##0xfffe
              asl a
              tax
              lda abs:.word0 (scaleIndex),x
              sta dp:SP_HI
              sta abs:.word0 (weaponScaleIndex)
              tax
              lda abs:.word0 (scaleHeight),x
              sta dp:SP_H
 #if !WOLF_TRUE_PIXELS
              lsr a
 #endif
              sta dp:SP_TMP
              lda abs:.word0 (viewWidth)
              sec
              sbc dp:SP_TMP
              lsr a
              sta dp:SP_LEFT
              clc
              adc dp:SP_TMP
              sta dp:SP_RIGHT
              lda abs:.word0 (weapon)
              asl a
              tax
              lda abs:.word0 (weaponReady),x
              clc
              adc abs:.word0 (weaponFrame)
              pha
              sec
              sbc ##SPR_KNIFEREADY
              asl a
              asl a
              asl a
              clc
              adc abs:.word0 (weaponViewIndex)
              tax
              lda long:WEAPON_RUNS,x
              sta abs:.word0 (weaponMaskTable)
#if WOLF_PREPARED
;;; Literal weapon drawers use exact ScalePost sampling. Their prepared
;;; bounds also own cleanup; world-sprite reciprocal rounding can omit an
;;; opaque edge column when the pose changes.
              lda long:weaponBounds,x
              and ##255
              sta dp:SP_N
              lda long:weaponBounds,x
              xba
              and ##255
              sta dp:SP_LIMIT
#endif
              pla
              asl a
              tax
              lda abs:.word0 (spriteFrame),x
              sta dp:SP_SHAPE
              lda ##65535
              sta dp:SP_PRI
#if WOLF_PREPARED
              jsr abs:.word0 (spriteDepthKept)
#else
              lda dp:SP_H
              lsr a
              tay
              jsr abs:.word0 (scaleSetup)
              jsr abs:.word0 (addVisible)
#endif
spritesReady: jsr abs:.word0 (sortVisible)
#if WOLF_PREPARED
              jsr abs:.word0 (buildColumnMasks)
#endif
              rts

addVisible:
              ldx dp:SP_HI
              lda abs:.word0 (viewScaleTex),x
              asl a
              clc
              adc dp:SP_SHAPE
              tax
              lda long:SPRITE_CMDS+SPR_CLIP,x
              sta dp:SP_BASE
#if WOLF_PREPARED
              ldx dp:SP_SHAPE
              lda long:SPRITE_CMDS+SPR_GAP,x
              bmi paddedSilhouette      ; synthetic floor pools extend normal art
              jsr abs:.word0 (inverseSilhouette)
              jmp abs:.word0 (rightClipped)
paddedSilhouette:
              lda dp:SP_BASE
#endif
              and ##255                   ; the scale of SP_H is set up: projectObject did it,
                                          ; and weaponVisible does it for the weapon
              asl a
              asl a
              jsr abs:.word0 (scaleEdge)
#if WOLF_TRUE_PIXELS
              asl a
#endif
              sec
              sbc ##1
              clc
              adc dp:SP_LEFT
              bpl leftClipped
              lda ##0
leftClipped:  sta dp:SP_N
              lda dp:SP_BASE
              xba
              and ##255
              inc a
              asl a
              asl a
              jsr abs:.word0 (scaleEdge)
#if WOLF_TRUE_PIXELS
              asl a
#endif
              clc
              adc ##2
              adc dp:SP_LEFT
              bpl rightEdgeKept
              jmp abs:.word0 (markedEmpty)
rightEdgeKept:cmp abs:.word0 (viewWidth)
              bcc rightClipped
              lda abs:.word0 (viewWidth)
rightClipped: sta dp:SP_LIMIT
#if WOLF_PREPARED
;;; Sparse wall rays can miss an otherwise visible static's cell. Reject
;;; only when every silhouette column is behind the wall at that column.
;;; Short ceiling lights retain their later sample-placement correction.
              lda dp:SP_PRI
              inc a
              beq spriteDepthKept
              lda dp:SP_H
              cmp ##16
              bcs testSpriteDepth
              lda dp:SP_SHAPE
              cmp abs:.word0 (spriteFrame+SPR_STAT_14*2)
              beq spriteDepthKept
              cmp abs:.word0 (spriteFrame+SPR_STAT_4*2)
              beq spriteDepthKept
testSpriteDepth:
              lda dp:SP_N
              cmp dp:SP_LIMIT
              bcs spriteBehindWalls
              asl a
              tax
              lda dp:SP_LIMIT
              asl a
              sta dp:SP_TMP
spriteDepthColumn:
              lda abs:.word0 (heightIndex),x
              cmp dp:SP_HI
              bcc spriteDepthKept
              beq spriteDepthKept
              inx
              inx
              cpx dp:SP_TMP
              bcc spriteDepthColumn
spriteBehindWalls:
              rts
spriteDepthKept:
#endif
              lda dp:SP_COUNT
              asl a
              asl a
              asl a
              asl a
              tax
              lda dp:SP_LEFT
              sta long:SPR_RECORDS,x
              lda dp:SP_RIGHT
              sta long:SPR_RECORDS+2,x
              lda dp:SP_HI
              sta long:SPR_RECORDS+4,x
              lda dp:SP_SHAPE
              sta long:SPR_RECORDS+6,x
              lda dp:SP_OBJ
              sta long:SPR_RECORDS+8,x
              lda dp:SP_H
              sta long:SPR_RECORDS+10,x
              lda dp:SP_PRI
              sta long:SPR_RECORDS+12,x
#if WOLF_PREPARED
              ldy dp:SP_HI
              lda abs:.word0 (horizontalBase),y
              sec
              sbc dp:SP_LEFT
              sta long:SPR_RECORDS+14,x       ; source column = horizontal(this + screen column)
#endif
              inc dp:SP_COUNT
#if WOLF_PREPARED
              lda dp:SP_LIMIT
              cmp abs:.word0 (touchedHigh)
              bcc touchHighKept
              sta abs:.word0 (touchedHigh)
touchHighKept:lda dp:SP_N
              cmp abs:.word0 (touchedLow)
              bcs touchLowKept
              sta abs:.word0 (touchedLow)
touchLowKept: lda dp:SP_LIMIT
              xba
              ora dp:SP_N
              pha
              lda dp:SP_COUNT
              dec a
              asl a
              tax
              pla
              sta long:SILHOUETTES,x       ; silhouette columns, for the per-column masks
#endif
#if WOLF_PREPARED
              lda dp:SP_PRI
              inc a
              beq weaponUntracked       ; its own column runs show a change
#endif
trackHook:    jsr abs:.word0 (trackProjection)
weaponUntracked:
              ldx dp:SP_N
              lda dp:SP_PRI
              cmp ##65535
              bne markedEmpty           ; buildColumnMasks marks a world sprite's columns
;;; The weapon ORs 5 into every column of its span. Two columns share one
;;; word. The pair count is taken once. A start already past the end marks
;;; nothing, and a leftover column is an 8-bit store so its neighbor stays
;;; as it was.
weaponColumns:
              txa
              eor ##65535
              sec
              adc dp:SP_LIMIT
              bcs weaponSpan
              jmp abs:.word0 (marked)
weaponSpan:   lsr a
              tay
              beq weaponTail
weaponPair:   inx
              lda long:MARKS-1,x
              ora ##0x0505
              sta long:MARKS-1,x
              inx
              dey
              bne weaponPair
weaponTail:   bcc marked
              inx
              sep #0x20
              lda #5
              ora long:MARKS-1,x
              sta long:MARKS-1,x
              bra marked
;;; An occluded sprite needs no owner sweep. Match the depth test used by
;;; the compositor, including equal-height ties; old visible owners retire.
marked:       rep #0x20
markedEmpty:
              rts

;;; Exact projection records invalidate only their old and new rectangles.
;;; A stationary weapon therefore leaves unchanged composed columns alone.
trackProjection:
              lda dp:SP_OBJ
              lsr a
              lsr a
              sta dp:SP_OLD
              tax
              lda long:SPR_HISTORY+4,x
              cmp dp:SP_HI
              bne changedProjection
              lda long:SPR_HISTORY+6,x
              cmp dp:SP_SHAPE
              bne changedProjection
              lda long:SPR_HISTORY,x
              cmp dp:SP_LEFT
              bne changedProjection
              lda long:SPR_HISTORY+2,x
              cmp dp:SP_RIGHT
              bne changedProjection
              jmp abs:.word0 (keepProjection)
changedProjection:
#if WOLF_PREPARED
              jsr abs:.word0 (padChangedSilhouette)
#endif
              lda long:SPR_HISTORY+4,x
              cmp ##65535
              beq newRectangle
              txa
              lsr a
              tax
              lda long:REMEMBERED,x
              sta dp:SP_TOP
              lda long:REMEMBERED+0x2,x
              sta dp:SP_BOT
;;; The marks are idempotent, so nonempty old and new rectangles that overlap
;;; or touch invalidate their union once.
              cmp dp:SP_TOP
              bcc separateRects
              beq separateRects
              lda dp:SP_LIMIT
              cmp dp:SP_N
              bcc separateRects
              beq separateRects
              lda dp:SP_BOT
              cmp dp:SP_N
              bcc separateRects
              lda dp:SP_LIMIT
              cmp dp:SP_TOP
              bcc separateRects
              lda dp:SP_N
              cmp dp:SP_TOP
              bcs unionLeft
              sta dp:SP_TOP
unionLeft:    lda dp:SP_LIMIT
              cmp dp:SP_BOT
              bcc unionRight
              sta dp:SP_BOT
unionRight:   jsr abs:.word0 (invalidateRange)
              bra rememberProjection
separateRects:jsr abs:.word0 (invalidateRange)
newRectangle: lda dp:SP_N
              sta dp:SP_TOP
              lda dp:SP_LIMIT
              sta dp:SP_BOT
              jsr abs:.word0 (invalidateRange)
rememberProjection:
              ldx dp:SP_OLD
              lda dp:SP_LEFT
              sta long:SPR_HISTORY,x
              lda dp:SP_RIGHT
              sta long:SPR_HISTORY+2,x
              lda dp:SP_HI
              sta long:SPR_HISTORY+4,x
              lda dp:SP_SHAPE
              sta long:SPR_HISTORY+6,x
              txa
              lsr a
              tax
              lda dp:SP_N
              sta long:REMEMBERED,x
              lda dp:SP_LIMIT
              sta long:REMEMBERED+0x2,x
keepProjection:
              lda dp:SP_OBJ
              lsr a
              lsr a
              lsr a
              lsr a
              lsr a
              tax
              sep #0x20
              lda abs:.word0 (projectionStamp)
              sta long:OBJECT_STAMPS,x
              rep #0x20
              rts

retireProjection:
              stz dp:SP_SCAN
retireObject: ldx dp:SP_SCAN
              cpx dp:SP_PREV
              bcs retirementDone
              lda long:SPR_SAVED_IDS,x
              sta dp:SP_N
              lsr a
              lsr a
              lsr a
              lsr a
              lsr a
              tax
              lda long:OBJECT_STAMPS,x
              and ##255
              cmp abs:.word0 (projectionStamp)
              beq retired
              lda dp:SP_N
              lsr a
              lsr a
              tax
              stx dp:SP_OLD
              lda long:SPR_HISTORY+4,x
              cmp ##65535
              beq retired
              txa
              lsr a
              tax
              lda long:REMEMBERED,x
              sta dp:SP_TOP
              lda long:REMEMBERED+0x2,x
              sta dp:SP_BOT
              jsr abs:.word0 (invalidateRange)
              ldx dp:SP_OLD
              lda ##65535
              sta long:SPR_HISTORY+4,x
retired:      inc dp:SP_SCAN
              inc dp:SP_SCAN
              bra retireObject
retirementDone:
              rts

invalidateRange:
              lda dp:SP_BOT
              bmi invalidated
              cmp abs:.word0 (viewWidth)
              bcc invalidRight
              lda abs:.word0 (viewWidth)
invalidRight: sta dp:SP_BOT
              lda dp:SP_TOP
              bpl invalidLeft
              lda ##0
invalidLeft:  tax
#if WOLF_PREPARED
              cmp abs:.word0 (touchedLow)
              bcs invalidLowKept
              sta abs:.word0 (touchedLow)
invalidLowKept:
              lda dp:SP_BOT
              cmp abs:.word0 (touchedHigh)
              bcc invalidHighKept
              sta abs:.word0 (touchedHigh)
invalidHighKept:
;;; Bit 4 (value 16) of $01B200: a sprite rectangle changed on this column.
;;; Value 4 is the weapon and values 1 and 8 are the world-sprite marks.
;;; Retirement runs before weapon marking; no owner bits exist here yet.
;;; Store 16 directly, including overlaps with earlier invalidations.
;;; The paint tests this bit and never reads a row hull. Two columns share
;;; one word. The pair count is taken once. A start already past the end
;;; marks nothing, and a leftover column is an 8-bit store so its neighbor
;;; stays as it was.
invalidateColumn:
              txa
              eor ##65535
              sec
              adc dp:SP_BOT
              bcc invalidDone
              lsr a
              tay
              beq invalidTail
              lda ##0x1010
invalidPair:  inx
              sta long:MARKS-1,x
              inx
              dey
              bne invalidPair
invalidTail:  bcc invalidDone
              inx
              sep #0x20
              lda #16
              sta long:MARKS-1,x
#else
              sep #0x20
              lda #1
invalidateColumn:
              cpx dp:SP_BOT
              bcs invalidDone
              sta long:EXTRA_MASKS,x
              inx
              bra invalidateColumn
#endif
invalidDone:  rep #0x20
invalidated:  rts
#if WOLF_PREPARED
;;; Per column, a bit for each world sprite in front of the wall there, in
;;; near-first order (bit 0 nearest), so the paint visits only its owners.
;;; Owners 16..63 have three extra masks; farther owners retain the sorted scan.
;;; The same walk sets MARKS over the sprite's silhouette, so a
;;; column meets the wall once. A wall at least as high as the sprite hides it
;;; (SP_HI is one past the sprite's height). The marks span the silhouette,
;;; and the bit only the columns inside the sprite's edges; the columns
;;; before and after the bit's span take their marks alone.
buildColumnMasks:
              stz abs:.word0 (maskBitOnlyUsed)
              lda ##9
              sta dp:SP_TOP             ; ordinary world marks; bit 5 means an unmasked owner
              stz abs:.word0 (maskFallback)
              stz dp:SP_SCAN
              stz dp:SP_EXTRA           ; bit index * 2
              lda ##1
              sta dp:SP_BASE
              lda ##.word0 (MARKS)
              sta dp:SP_PTR             ; long pointer to the marks
              lda ##MARKS>>16
              sta dp:SP_PTR+2
maskSprite:   lda dp:SP_SCAN
              lsr a
              cmp dp:SP_COUNT
              bcc maskMore
              rts
maskMore:     ldx dp:SP_SCAN
              inc dp:SP_SCAN
              inc dp:SP_SCAN
              lda long:SPR_ORDER,x
              tax
              lda long:SPR_RECORDS+12,x
              inc a
              bne maskWorld
              jmp abs:.word0 (maskSprite) ; the weapon has its own runs
maskWorld:    stx dp:SP_TMP             ; the record
              lda dp:SP_BASE
              bne maskRoom
              lda ##41
              sta dp:SP_TOP
              jsl long:prepareExtraOwner
              bra maskRange
maskRoom:     ldy dp:SP_EXTRA
              txa
              sta abs:.word0 (maskOwners),y
maskRange:    lda long:SPR_RECORDS+4,x
              inc a
              sta dp:SP_HI
              lda long:SPR_RECORDS+8,x       ; the first column addVisible remembered for the object:
              lsr a                     ; from 256 on it spills into the silhouette's end, which
              lsr a                     ; then marks nothing (the end is below the first column)
              lsr a
              tax
              lda long:REMEMBERED,x
              sta dp:SP_PRI
              lda dp:SP_TMP
              lsr a
              lsr a
              lsr a
              tax
              lda long:SILHOUETTES,x       ; the silhouette: end << 8 | first column
              sta dp:SP_N
              and ##255
              sta dp:SP_SIGN            ; first column
              lda dp:SP_N
              xba
              and ##255
              sta dp:SP_LIMIT           ; end column
              cmp dp:SP_SIGN
              beq maskNext
              bcc maskNext              ; no columns
              lda dp:SP_BASE
              bne maskBounded
              jsl long:buildExtraMask
              bra maskAll
maskBounded:  ldx dp:SP_TMP
              lda dp:SP_LIMIT           ; never past the sprite's own right edge
              cmp long:SPR_RECORDS+2,x
              bcc maskRight
              lda long:SPR_RECORDS+2,x
maskRight:    sta dp:SP_END
              lda long:SPR_RECORDS,x       ; nor left of its left edge (signed)
              bpl maskLeftEdge
              lda ##0
maskLeftEdge: cmp dp:SP_SIGN
              bcs maskLeft
              lda dp:SP_SIGN
maskLeft:     sta dp:SP_N               ; the bit's first column
              cmp dp:SP_END
              bcs maskAll               ; empty span
              lda dp:SP_PRI
              cmp ##256
              bcs maskBitOnly
              lda dp:SP_N
              cmp dp:SP_SIGN
              beq maskBody
              ldx dp:SP_SIGN
              jsr abs:.word0 (markSpan) ; A = the end: the columns before the bit
              bra maskBody
maskAll:      lda dp:SP_PRI
              cmp ##256
              bcs maskNext
              ldx dp:SP_SIGN
              lda dp:SP_LIMIT
              jsr abs:.word0 (markSpan)
maskNext:     asl dp:SP_BASE
              inc dp:SP_EXTRA
              inc dp:SP_EXTRA
              jmp abs:.word0 (maskSprite)
;;; The bit alone, over the span the silhouette word gives.
maskBitOnly:  lda ##1
              sta abs:.word0 (maskBitOnlyUsed)
              lda dp:SP_N
              asl a
              tax
              lda dp:SP_END
              asl a
              sta dp:SP_TMP
maskBitColumn:
              lda abs:.word0 (heightIndex),x
              cmp dp:SP_HI
              bcs maskBitBehind
              lda dp:SP_BASE
              ora long:COLUMN_MASKS,x
              sta long:COLUMN_MASKS,x
maskBitBehind:
              inx
              inx
              cpx dp:SP_TMP
              bcc maskBitColumn
              bra maskNext
maskBody:     lda dp:SP_N
              tay                       ; Y = column, X = column * 2
              asl a
              tax
              lda dp:SP_END
              sec
              sbc dp:SP_N               ; columns in the span, at least one
              lsr a                     ; pairs, and the carry is one more
              php
              bne maskPairs
              jmp abs:.word0 (maskOdd)
maskPairs:    sta dp:SP_N               ; the pairs
              asl a
              asl a
              sta dp:SP_TMP
              txa
              clc
              adc dp:SP_TMP
              adc ##4
              sta dp:SP_TMP             ; X after the last pair, plus 4
              lda dp:SP_N
              lsr a
              bcs maskPairB             ; an odd number of pairs starts with one pair, the second of the loop
              inx
              inx
              inx
              inx                       ; X is the second pair of the loop, the first is 4 below it
;;; Two columns share one word of marks: 9 each, and a zero half writes that
;;; column's byte back unchanged. A round of the loop does two pairs.
maskPairA:    lda abs:.word0 (heightIndex-4),x
              cmp dp:SP_HI
              bcs maskBehindA
              lda dp:SP_BASE
              ora long:COLUMN_MASKS-4,x
              sta long:COLUMN_MASKS-4,x
              lda abs:.word0 (heightIndex-2),x
              cmp dp:SP_HI
              bcs maskFrontA
              lda dp:SP_BASE
              ora long:COLUMN_MASKS-2,x
              sta long:COLUMN_MASKS-2,x
              lda [SP_PTR],y
              ora ##0x0909
              sta [SP_PTR],y
maskStepAB:   iny
              iny
maskPairB:    lda abs:.word0 (heightIndex),x
              cmp dp:SP_HI
              bcs maskBehindB
              lda dp:SP_BASE
              ora long:COLUMN_MASKS,x
              sta long:COLUMN_MASKS,x
              lda abs:.word0 (heightIndex+2),x
              cmp dp:SP_HI
              bcs maskFrontB
              lda dp:SP_BASE
              ora long:COLUMN_MASKS+2,x
              sta long:COLUMN_MASKS+2,x
              lda [SP_PTR],y
              ora ##0x0909
              sta [SP_PTR],y
maskPairNext: txa
              clc
              adc ##8
              tax
              iny
              iny
              cpx dp:SP_TMP
              bcc maskPairA
              txa
              sec
              sbc ##4
              tax                       ; X after the last pair
              bra maskOdd
maskFrontA:   lda [SP_PTR],y
              ora ##0x0009
              sta [SP_PTR],y
              bra maskStepAB
maskBehindA:  lda abs:.word0 (heightIndex-2),x
              cmp dp:SP_HI
              bcs maskStepAB
              lda dp:SP_BASE
              ora long:COLUMN_MASKS-2,x
              sta long:COLUMN_MASKS-2,x
              lda [SP_PTR],y
              ora ##0x0900
              sta [SP_PTR],y
              bra maskStepAB
maskFrontB:   lda [SP_PTR],y
              ora ##0x0009
              sta [SP_PTR],y
              bra maskPairNext
maskBehindB:  lda abs:.word0 (heightIndex+2),x
              cmp dp:SP_HI
              bcs maskPairNext
              lda dp:SP_BASE
              ora long:COLUMN_MASKS+2,x
              sta long:COLUMN_MASKS+2,x
              lda [SP_PTR],y
              ora ##0x0900
              sta [SP_PTR],y
              bra maskPairNext
maskOdd:      plp
              bcc maskTail
              lda abs:.word0 (heightIndex),x
              cmp dp:SP_HI
              bcs maskTail
              lda dp:SP_BASE
              ora long:COLUMN_MASKS,x
              sta long:COLUMN_MASKS,x
              sep #0x20
              lda [SP_PTR],y
              ora #9
              sta [SP_PTR],y
              rep #0x20
maskTail:     lda dp:SP_LIMIT
              cmp dp:SP_END
              beq maskDone
              bcc maskDone
              ldx dp:SP_END
              jsr abs:.word0 (markSpan) ; A = the end: the columns after the bit
maskDone:     jmp abs:.word0 (maskNext)
;;; Marks only. X = first column, A = end column.
markSpan:     sta dp:SP_TMP
              txa
              asl a
              tay
markSpanColumn:
              lda abs:.word0 (heightIndex),y
              cmp dp:SP_HI
              bcs markSpanBehind
              sep #0x20
              lda dp:SP_TOP
              ora long:MARKS,x
              sta long:MARKS,x
              rep #0x20
markSpanBehind:
              iny
              iny
              inx
              cpx dp:SP_TMP
              bcc markSpanColumn
              rts
              .section gamecode, text, root, noreorder
#endif

;;; Near-first stream order stops the sweep at its first opaque owner.
;;; Later source objects retain the original equal-height tie order.
sortVisible:  lda dp:SP_COUNT
              cmp ##2
              bcs sortLimit
              lda ##0
              sta long:SPR_ORDER
              rts
sortLimit:    cmp ##SORT_KEYS+1
              bcc sortGuarded
              brk                         ; more visible sprites than key words
sortGuarded:  stz dp:SP_SCAN
              stz dp:SP_BASE
              dec a
              asl a
              asl a
              asl a
              asl a
              tax
              lda long:SPR_RECORDS+12,x
              inc a
              bne sortObject
;;; The weapon is submitted last and always sorts first. Place it directly
;;; so it never shifts every world record after their insertion sort.
              txa
              sta long:SPR_ORDER
              lda ##65535
              sta long:SORT_KEYS_AT
              lda ##2
              sta dp:SP_SCAN
              cpx ##0
              bne sortObject
              rts
sortObject:   ldx dp:SP_BASE
              lda long:SPR_RECORDS+4,x
sortKey:      sta dp:SP_EXTRA
              ldx dp:SP_SCAN
              beq orderPosition
;;; The key of each sorted entry is kept beside the order list, so a step
;;; compares one word and moves two.
insertOrder:  lda long:SORT_KEYS_AT-2,x
              cmp dp:SP_EXTRA
              bcc shiftOrder
              beq shiftOrder
              bra orderPosition
shiftOrder:   sta long:SORT_KEYS_AT,x
              lda long:SPR_ORDER-2,x
              sta long:SPR_ORDER,x
              dex
              dex
              bne insertOrder
orderPosition:
              lda dp:SP_BASE
              sta long:SPR_ORDER,x
              clc
              adc ##16
              sta dp:SP_BASE
              lda dp:SP_EXTRA
              sta long:SORT_KEYS_AT,x
              lda dp:SP_SCAN
              clc
              adc ##2
              sta dp:SP_SCAN
              lsr a
              cmp dp:SP_COUNT
              bcc sortObject
              rts

;;; Projection products, 8.8 by 8.8 truncated toward zero as the source does.
;;; The high-byte lookup plus the low product's high byte gives each result.
;;; The view factors are at most 256 in magnitude. prepareFactors selects
;;; the identity case, product rows and signed return form once per frame.
prepareFactors:
              lda dp:SP_C
              jsr abs:.word0 (factorParts)
              sta abs:.word0 (productCLow+2)
              sta abs:.word0 (productCHigh+2)
              lda dp:SP_SIGN
              sta abs:.word0 (productsPositive+1)
              lda ##.word0 (productsSign)
              ldx dp:SP_EXTRA
              beq productCoreSelected
              lda ##.word0 (productIdentityC)
productCoreSelected:
              sta abs:.word0 (productsExtra+1)
              lda dp:SP_S
              jsr abs:.word0 (factorParts)
              sta abs:.word0 (productSLow+2)
              sta abs:.word0 (productSHigh+2)
              lda dp:SP_SIGN
              asl a
              ora abs:.word0 (productsPositive+1)
              asl a
              sta abs:.word0 (productsPositive+1)
              eor ##6
              sta abs:.word0 (productsNegative+1)
              ldx dp:SP_EXTRA
              beq productFactorsReady
              lda ##.word0 (productIdentityS)
              sta abs:.word0 (productsExtra+1)
productFactorsReady:
              rts
;;; A = signed factor. SP_SIGN = 1 when negative, SP_EXTRA = 1 when its
;;; magnitude is 256 (the fraction is then zero and the value is added),
;;; A = the product row of the fraction.
factorParts:  stz dp:SP_SIGN
              stz dp:SP_EXTRA
              cmp ##0x8000
              bcc factorMagnitude
              eor ##65535
              inc a
              inc dp:SP_SIGN
factorMagnitude:
              cmp ##256
              bcc factorFraction
              inc dp:SP_EXTRA
              lda ##0
factorFraction:
              asl a
              tax
              lda long:RAY_PRODUCTS_DIRECTORY,x
              rts

;;; Rotate each coordinate with both view factors. Sharing the magnitude
;;; and byte indexes avoids decomposing it again for the side projection.
;;; In: signed A. Out: signed cosine product in A, sine product in Y.
;;; Each product retains truncation toward zero, including factors +/-256.
productsCS:   bpl productsPositive
              eor ##65535
              inc a
productsNegative:
              ldy ##0
              bra productsCore
productsPositive: ldy ##0
productsCore: sta dp:SP_TMP
              and ##255
              asl a
              tax
productCLow:  lda long:INPUT_CODE,x
              xba
              and ##255
              sta dp:MULR
productSLow:  lda long:INPUT_CODE,x
              xba
              and ##255
              sta dp:MULV
              lda dp:SP_TMP
              xba
              and ##255
              asl a
              tax
productCHigh: lda long:INPUT_CODE,x
              clc
              adc dp:MULR
              sta dp:MULR
productSHigh: lda long:INPUT_CODE,x
              clc
              adc dp:MULV
              sta dp:MULV
productsExtra: jmp abs:.word0 (productsSign)
productsSign: tyx
              jmp (abs:.word0 (productResults),x)
productPositive:
              ldy dp:MULV
              lda dp:MULR
              rts
productNegativeC:
              lda ##0
              sec
              sbc dp:MULR
              ldy dp:MULV
              rts
productNegativeS:
              lda ##0
              sec
              sbc dp:MULV
              tay
              lda dp:MULR
              rts
productNegativeCS:
              lda ##0
              sec
              sbc dp:MULV
              tay
              lda ##0
              sec
              sbc dp:MULR
              rts
;;; A factor of +/-256 used the zero row; replace that result with the
;;; coordinate magnitude. View factors never both have magnitude 256.
productIdentityC:
              lda dp:SP_TMP
              sta dp:MULR
              bra productsSign
productIdentityS:
              lda dp:SP_TMP
              sta dp:MULV
              bra productsSign
productResults:
              .word .word0 (productPositive), .word0 (productNegativeC)
              .word .word0 (productNegativeS), .word0 (productNegativeCS)

;;; Y = the object's half height, A (scaleValue) = a nonnegative value. A
;;; half height of 256 or more adds the value to the product of the rest.
scaleSetup:   stz dp:MULW
              stz dp:MULP
              cpy ##256
              bcc scaleFraction
              inc dp:MULW
              tya
              sec
              sbc ##256
              tay
scaleFraction:tya
              asl a
              tax
              lda long:RAY_PRODUCTS_DIRECTORY,x
              sta dp:MULP+1
              rts
scaleValue:   sta dp:SP_TMP
              and ##255
              asl a
              tay
              lda [MULP],y
              xba
              and ##255
              sta dp:MULV
              lda dp:SP_TMP
              xba
              and ##255
              asl a
              tay
              lda [MULP],y
              clc
              adc dp:MULV
              ldy dp:MULW
              beq scaleValueDone
              clc
              adc dp:SP_TMP
scaleValueDone:
              rts

;;; A is four times a source-column endpoint, in 0..256. The low-byte
;;; product covers every interior edge; endpoint 64 is the exact half height.
scaleEdge:    sta dp:SP_TMP
              cmp ##256
              beq scaleLastEdge
              asl a
              tay
              lda [MULP],y
              xba
              and ##255
              ldy dp:MULW
              beq scaleValueDone
              clc
              adc dp:SP_TMP
              rts
scaleLastEdge:
              lda dp:SP_H
              lsr a
              rts

#if !WOLF_PREPARED
ComposeAndPaint:
#if WOLF_TRUE_PIXELS
              jmp abs:.word0 (generalColumn)
#endif
              ldx dp:COL
              lda long:OLD_MARKS,x
              ora long:MARKS,x
              and ##1
              bne composeNeeded
              clc
              rts
composeNeeded:
              lda dp:FIRST
              bne changedColumn
              lda long:EXTRA_MASKS,x
              and ##255
              bne changedColumn
              ldx dp:SCAN
              lda dp:HEIGHT
              cmp abs:.word0 (oldHeight),x
              bne changedColumn
              lda abs:.word0 (sourceAddr),x
              cmp abs:.word0 (oldSource),x
              bne changedColumn
              ldx dp:COL
              sep #0x20
              lda abs:.word0 (sourceBank),x
              cmp abs:.word0 (oldBank),x
              rep #0x20
              bne changedColumn
              sec
              rts
changedColumn:
              lda dp:FIRST
              bne generalColumn
              ldx dp:COL
              lda long:MARKS,x
              ora long:OLD_MARKS,x
              bit ##8
              bne changedSceneColumn
              ldx dp:SCAN
              lda dp:HEIGHT
              cmp abs:.word0 (oldHeight),x
              bne changedSceneColumn
              lda abs:.word0 (sourceAddr),x
              cmp abs:.word0 (oldSource),x
              bne changedSceneColumn
              ldx dp:COL
              lda abs:.word0 (sourceBank),x
              eor abs:.word0 (oldBank),x
              and ##255
              bne changedSceneColumn
              jsr abs:.word0 (paintChangedWeapon)
              sec
              rts
changedSceneColumn:
              ldx dp:COL
              lda long:EXTRA_MASKS,x
              and ##255
              bne generalColumn
              lda long:MARKS,x
              and ##255
              cmp ##5
              bne generalColumn
              lda long:OLD_MARKS,x
              and ##12
              cmp ##4
              bne generalColumn
              jsr abs:.word0 (paintBehindWeapon)
              sec
              rts
generalColumn:
              ldx dp:COL
              lda long:MARKS,x
              and ##255
              cmp ##5
              bne worldColumn
              jmp abs:.word0 (weaponColumn)
worldColumn:
              stz dp:SP_RUNS
              stz dp:SP_NEW
              lda ##1
              sta dp:SP_WEAPON
              stz dp:SP_VPOS
              lda dp:SP_COUNT
              asl a
              sta dp:SP_LIMIT
columnObject: ldx dp:SP_VPOS
              lda long:SPR_ORDER,x
              tax
              lda long:SPR_RECORDS,x
              bmi objectLeft
              cmp dp:COL
              bcc objectLeft
              beq objectLeft
              jmp abs:.word0 (nextColumnObject)
objectLeft:   lda long:SPR_RECORDS+2,x
              cmp dp:COL
              bne objectRight
              jmp abs:.word0 (nextColumnObject)
objectRight:  bcs objectCovers
              jmp abs:.word0 (nextColumnObject)
objectCovers: lda long:SPR_RECORDS+4,x
              sta dp:SP_HI
              lda long:SPR_RECORDS+12,x
              cmp ##65535
              bne worldDepthCheck
              jmp abs:.word0 (projectedWeaponStream)
worldDepthCheck:
              lda dp:SP_HI
              cmp dp:HEIGHT
              bcs inFront
              jmp abs:.word0 (nextColumnObject)
inFront:      lda long:SPR_RECORDS+6,x
              sta dp:SP_SHAPE
              lda dp:COL
              sec
              sbc long:SPR_RECORDS,x
              ldx dp:SP_HI
              clc
              adc abs:.word0 (horizontalBase),x
              tax
#if WOLF_TRUE_PIXELS
              lda long:NP_TRUE_HORIZONTAL,x
#else
              lda long:NP_HORIZONTAL,x
#endif
              and ##255
              sta dp:SP_TMP
              asl a
              clc
              adc dp:SP_SHAPE
              tax
              lda long:NP_SPRITE_CMDS,x
              sta dp:SP_PTR
              lda dp:SP_TMP
              clc
              adc dp:SP_SHAPE
              adc ##128
              tax
              lda long:NP_SPRITE_CMDS,x
              and ##255
              sta dp:SP_PTR+2
              ldy ##0
              lda [SP_PTR],y
              beq nextColumnObject
              stz dp:SP_WEAPON
              lda ##0
              bra streamCursor
;;; The weapon has fixed projection for each view. Mixed guard columns use
;;; its offline commands too, without repeating horizontal/endpoint lookups.
projectedWeaponStream:
              jsr abs:.word0 (loadWeaponColumn)
              ldy ##0
              lda [SP_PTR],y
              beq nextColumnObject
              lda ##2
streamCursor: sta dp:SP_BASE
              ldx dp:SP_RUNS
              lda dp:SP_HI
              sta abs:.word0 (streamBuffer+0),x
              lda dp:SP_PTR
              sta abs:.word0 (streamBuffer+2),x
              lda dp:SP_PTR+2
              sta abs:.word0 (streamBuffer+4),x
              lda dp:SP_BASE
              sta abs:.word0 (streamBuffer+6),x
              stx dp:SP_N
              jsr abs:.word0 (advanceStream)
              lda dp:SP_RUNS
              clc
              adc ##16
              sta dp:SP_RUNS
nextColumnObject:
              lda dp:SP_VPOS
              clc
              adc ##2
              sta dp:SP_VPOS
              cmp dp:SP_LIMIT
              bcs streamsReady
              jmp abs:.word0 (columnObject)
streamsReady:
#if WOLF_TRUE_PIXELS
              jmp abs:.word0 (composeStreams)
#endif
              lda dp:FIRST
              bne composeStreams
              ldx dp:COL
              lda long:EXTRA_MASKS,x
              and ##255
              bne composeStreams
              lda long:OLD_MARKS,x
              bit ##4
              beq composeStreams
              lda dp:SP_WEAPON
              beq composeStreams
              lda dp:SP_RUNS
              beq backgroundOnly
              ldx dp:HEIGHT
              lda abs:.word0 (viewScaleBottom),x
              cmp abs:.word0 (streamBuffer+8)
              bcc previousWeaponGap
              beq previousWeaponGap
              bra composeStreams
previousWeaponGap:
              ldx dp:SCAN
              lda abs:.word0 (oldHeight),x
              tax
              lda abs:.word0 (viewScaleBottom),x
              cmp abs:.word0 (streamBuffer+8)
              bcc backgroundOnly
              beq backgroundOnly
              bra composeStreams
backgroundOnly:
              ldx dp:COL
              sep #0x20
              lda long:OLD_MARKS,x
              and #16
              sta dp:SP_EXTRA
              lda long:MARKS,x
              beq backgroundMask
              ora dp:SP_EXTRA
              ora #6                    ; only weapon, span cache now stale
backgroundMask:
              sta long:OLD_MARKS,x
              rep #0x20
              clc
              rts
composeStreams:
              stz dp:SP_FPOS
              lda abs:.word0 (viewTop)
              sta dp:SP_ROW

;;; Near-first streams bound the next change of owner. Each opaque command
;;; advances once; the wall/floor partition supplies uncovered intervals.
sweepRow:     lda abs:.word0 (viewBottom)
              sta dp:SP_END
              ldx ##0
streamOwner:  cpx dp:SP_RUNS
              bcs backgroundOwner
              lda abs:.word0 (streamBuffer+10),x
              cmp dp:SP_ROW
              bcc expiredStream
              beq expiredStream
              bra currentStream
expiredStream:
              stx dp:SP_N
              jsr abs:.word0 (advanceStream)
              ldx dp:SP_N
              bra streamOwner
currentStream:
              lda abs:.word0 (streamBuffer+8),x
              cmp dp:SP_ROW
              bcc opaqueOwner
              beq opaqueOwner
              cmp dp:SP_END
              bcs nextStream
              sta dp:SP_END
nextStream:   txa
              clc
              adc ##16
              tax
              bra streamOwner
opaqueOwner:  lda abs:.word0 (streamBuffer+0),x
              sta dp:SP_HI
              lda abs:.word0 (streamBuffer+12),x
              sta dp:SP_SRC
              lda abs:.word0 (streamBuffer+14),x
              ora ##128
              sta dp:SP_BANK
              lda abs:.word0 (streamBuffer+10),x
              bra ownerEnd
backgroundOwner:
              ldx dp:HEIGHT
              lda abs:.word0 (viewScaleTop),x
              cmp dp:SP_ROW
              bcc afterCeiling
              beq afterCeiling
              pha
              stz dp:SP_HI
              stz dp:SP_BANK
flat_ceiling_sprites_1_0:
              lda ##CEILING
              sta dp:SP_SRC
              pla
              bra ownerEnd
afterCeiling: lda abs:.word0 (viewScaleBottom),x
              cmp dp:SP_ROW
              bcc floorOwner
              beq floorOwner
              pha
              lda dp:HEIGHT
              sta dp:SP_HI
              ldx dp:SCAN
              lda abs:.word0 (sourceAddr),x
              sta dp:SP_SRC
              ldx dp:COL
              lda abs:.word0 (sourceBank),x
              and ##255
              sta dp:SP_BANK
              pla
              bra ownerEnd
floorOwner:   stz dp:SP_HI
              stz dp:SP_BANK
flat_floor_sprites_1_1:
              lda ##FLOOR
              sta dp:SP_SRC
              lda abs:.word0 (viewBottom)
ownerEnd:     cmp dp:SP_END
              bcs emitSpan
              sta dp:SP_END
emitSpan:     ldx dp:SP_FPOS
              lda dp:SP_END
              xba
              ora dp:SP_ROW
              sta abs:.word0 (spanBuffer+0),x
              lda dp:SP_HI
              sta abs:.word0 (spanBuffer+2),x
              lda dp:SP_SRC
              sta abs:.word0 (spanBuffer+4),x
              lda dp:SP_BANK
              sta abs:.word0 (spanBuffer+6),x
              txa
              clc
              adc ##8
              sta dp:SP_FPOS
              lda dp:SP_END
              sta dp:SP_ROW
              cmp abs:.word0 (viewBottom)
              bcs sweepDone
              jmp abs:.word0 (sweepRow)
sweepDone:
#if WOLF_TRUE_PIXELS
              rts
#endif
              lda dp:COL
              asl a
              tax
              lda long:NP_CACHE_PTRS,x
              sta dp:SP_CACHE
              ldx dp:COL
              lda long:NP_CACHE_PTRS+0x140,x
              and ##255
              sta dp:SP_CACHE+2
              lda long:OLD_MARKS,x
              and ##255
              sta dp:SP_EXTRA
              lda dp:FIRST
              bne forceColumn
              lda dp:SP_EXTRA
              beq forceColumn
              bit ##2
              beq oldColumnReady
              bit ##16
              bne forceColumn
              bit ##4
              beq forceColumn
              ; The wall changed around a retained weapon. Its cached weapon
              ; spans remain valid; only background comparisons need forcing.
              lda ##1
              sta dp:SP_NEW
oldColumnReady:
              lda ##2
              sta dp:SP_OLD
              bra compareColumn
forceColumn:  stz dp:SP_OLD
              lda ##1
              sta dp:SP_NEW
compareColumn:
              stz dp:SP_SCAN
paintSpan:    ldx dp:SP_SCAN
              lda abs:.word0 (spanBuffer+0),x
              sta dp:SP_BASE
              and ##255
              sta dp:SP_TOP
              lda dp:SP_BASE
              xba
              and ##255
              sta dp:SP_LIMIT
              lda abs:.word0 (spanBuffer+2),x
              sta dp:SP_HI
              lda abs:.word0 (spanBuffer+4),x
              sta dp:SP_SRC
              lda abs:.word0 (spanBuffer+6),x
              sta dp:SP_BANK
compareRegion:
              lda dp:SP_OLD
              bne validOldSpan
              lda dp:SP_LIMIT
              sta dp:SP_BOT
              jsr abs:.word0 (drawSpan)
              bra currentSpanDone
validOldSpan: tay
              lda [SP_CACHE],y
              xba
              and ##255
              sta dp:SP_BOT
              cmp dp:SP_TOP
              bcc advanceOld
              beq advanceOld
              bra oldOverlaps
advanceOld:   lda dp:SP_OLD
              clc
              adc ##8
              sta dp:SP_OLD
              bra compareRegion
oldOverlaps:  lda dp:SP_BOT
              cmp dp:SP_LIMIT
              bcc regionEnd
              lda dp:SP_LIMIT
              sta dp:SP_BOT
regionEnd:    lda dp:SP_EXTRA
              bit ##2
              beq compareOwner
              lda dp:SP_BANK
              bit ##128
              beq regionDirty
compareOwner: iny
              iny
              lda [SP_CACHE],y
              cmp dp:SP_HI
              bne regionDirty
              iny
              iny
              lda [SP_CACHE],y
              cmp dp:SP_SRC
              bne regionDirty
              iny
              iny
              lda [SP_CACHE],y
              cmp dp:SP_BANK
              beq regionClean
regionDirty:  lda ##1
              sta dp:SP_NEW
              jsr abs:.word0 (drawSpan)
regionClean:  lda dp:SP_BOT
              sta dp:SP_TOP
              cmp dp:SP_LIMIT
              bcc compareRegion
currentSpanDone:
              lda dp:SP_SCAN
              clc
              adc ##8
              sta dp:SP_SCAN
              cmp dp:SP_FPOS
              bcs columnPainted
              jmp abs:.word0 (paintSpan)
columnPainted:
              lda dp:SP_NEW
              beq retainedCache
              ldy ##0
              lda dp:SP_FPOS
              sta [SP_CACHE],y
              lda dp:SP_CACHE+2
              sep #0x20
              sta abs:.word0 (saveSpans+1)
              rep #0x20
              lda dp:SP_CACHE
              clc
              adc ##2
              tay
              ldx ##.word0 (spanBuffer)
              lda dp:SP_FPOS
              dec a
saveSpans:    .byte 0x54,0x18,0x02       ; fast RAM metadata, seven cycles/byte
              sep #0x20
              lda #2
              pha
              plb
              rep #0x20
retainedCache:
              ldx dp:COL
              sep #0x20
              lda long:MARKS,x
              beq mixedColumn           ; plain walls invalidate a vanished cache
              ldy dp:SP_WEAPON
              beq mixedColumn
              ora #4
mixedColumn:
              ldy dp:SP_WEAPON
              bne keepWeaponMask
              and #0xfb
keepWeaponMask:
              sta long:OLD_MARKS,x
              rep #0x20
              sec
              rts

;;; A stationary weapon is already on screen. Paint only the new wall and
;;; exposed flats around its offline intervals; there is no sprite sweep.
loadWeaponColumn:
              lda dp:COL
              asl a
              clc
              adc abs:.word0 (weaponMaskTable)
              tax
              lda long:NP_WEAPON_MASK,x
              sta dp:SP_PTR
#if WOLF_TRUE_PIXELS
              bmi upperWeaponCommands
              lda ##20
              bra weaponCommandsReady
upperWeaponCommands:
              lda ##31
weaponCommandsReady:
#else
              lda ##21
#endif
              sta dp:SP_PTR+2
              rts
paintBehindWeapon:
              jsr abs:.word0 (loadWeaponColumn)
              ldx dp:HEIGHT
              lda abs:.word0 (viewScaleTop),x
              sta dp:SP_TOP
              lda abs:.word0 (viewScaleBottom),x
              sta dp:SP_END
              lda dp:HEIGHT
              sta dp:SP_HI
              ldx dp:SCAN
              lda abs:.word0 (sourceAddr),x
              sta dp:SP_SRC
              ldx dp:COL
              lda abs:.word0 (sourceBank),x
              and ##255
              sta dp:SP_BANK
              jsr abs:.word0 (paintOpenIntervals)
              ldx dp:SCAN
              lda abs:.word0 (oldHeight),x
              tax
              lda abs:.word0 (viewScaleTop),x
              sta dp:SP_TOP
              ldx dp:HEIGHT
              lda abs:.word0 (viewScaleTop),x
              sta dp:SP_END
              stz dp:SP_BANK
              stz dp:SP_HI
flat_ceiling_sprites_1_2:
              lda ##CEILING
              sta dp:SP_SRC
              jsr abs:.word0 (paintOpenIntervals)
              ldx dp:HEIGHT
              lda abs:.word0 (viewScaleBottom),x
              sta dp:SP_TOP
              ldx dp:SCAN
              lda abs:.word0 (oldHeight),x
              tax
              lda abs:.word0 (viewScaleBottom),x
              sta dp:SP_END
flat_floor_sprites_1_3:
              lda ##FLOOR
              sta dp:SP_SRC
              jsr abs:.word0 (paintOpenIntervals)
              ldx dp:COL
              sep #0x20
              lda long:OLD_MARKS,x
              and #16
              ora #7                     ; background cache is now stale
              sta long:OLD_MARKS,x
              rep #0x20
              rts

paintOpenIntervals:
              lda dp:SP_TOP
              cmp dp:SP_END
              bcs openIntervalsDone
              ldy ##0
              lda [SP_PTR],y
              sta dp:SP_N
              lda ##2
              sta dp:SP_VPOS
openInterval: lda dp:SP_N
              beq finalOpenInterval
              ldy dp:SP_VPOS
              lda [SP_PTR],y
              sta dp:SP_ROW
              xba
              and ##255
              sta dp:SP_RPOS
              cmp dp:SP_TOP
              bcc nextOpenInterval
              beq nextOpenInterval
              lda dp:SP_ROW
              and ##255
              cmp dp:SP_END
              bcs finalOpenInterval
              sta dp:SP_BOT
              cmp dp:SP_TOP
              bcc occludedInterval
              beq occludedInterval
              jsr abs:.word0 (drawSpan)
occludedInterval:
              lda dp:SP_RPOS
              sta dp:SP_TOP
              cmp dp:SP_END
              bcs openIntervalsDone
nextOpenInterval:
              lda dp:SP_VPOS
              clc
              adc ##6
              sta dp:SP_VPOS
              dec dp:SP_N
              bra openInterval
finalOpenInterval:
              lda dp:SP_END
              sta dp:SP_BOT
              jmp abs:.word0 (drawSpan)
openIntervalsDone:
              rts

#endif
              .section gamedata, data, root
weaponMaskTable: .word 0
oldWeaponMaskTable: .word 0
weaponScaleIndex: .word 0
actorNeighbors: .word 65535,1,65471,65472,65473,65,64,63
staticMaskBits: .word 0
staticMaskOffset: .word 0
staticMaskEnd: .word 0
staticGroupBase: .word 0
projectionStamp: .word 0              ; actors can move while wall rays are retained
projectionCold: .word 1               ; paused composition reuses projection storage
#if WOLF_PREPARED
              .public maskFallback, maskOwners, maskColumnBytes
maskBitOnlyUsed: .word 1              ; whether a mask can exist without a world mark
maskFallback: .word 0                 ; extra groups, or 4 for the complete-list fallback
maskColumnBytes: .word 0
touchedLow:   .word 0                   ; columns [low, high) to clear next frame
touchedHigh:  .word WOLF_COLUMN_BYTES
maskOwners:   .space 32                 ; visible record of each mask bit
#endif
#if !WOLF_PREPARED
streamBuffer: .space 8816             ; short indexed reads for the owner sweep
spanBuffer:   .space 1284
#endif
              .section gamecode, text, root, noreorder
#if !WOLF_PREPARED

;;; With fixed walls and no world sprite, a weapon change needs only its
;;; new pixels and the old pixels it uncovered. Never repaint the full column.
paintChangedWeapon:
              jsr abs:.word0 (loadWeaponColumn)
              lda dp:COL
              asl a
              clc
              adc abs:.word0 (oldWeaponMaskTable)
              tax
              lda long:NP_WEAPON_MASK,x
              cmp dp:SP_PTR
              bne weaponPixelsChanged
              jmp abs:.word0 (weaponAlreadyPainted)
weaponPixelsChanged:
              sta dp:SP_CACHE
              lda ##21
              sta dp:SP_CACHE+2
              ldy ##0
              lda [SP_CACHE],y
              sta dp:SP_EXTRA
              lda ##2
              sta dp:SP_OLD
restoreWeaponRun:
              lda dp:SP_EXTRA
              bne restoreNextWeaponRun
              jmp abs:.word0 (newWeaponPixels)
restoreNextWeaponRun:
              ldy dp:SP_OLD
              lda [SP_CACHE],y
              pha
              and ##255
              sta dp:SP_LEFT
              sta dp:SP_TOP
              pla
              xba
              and ##255
              sta dp:SP_RIGHT
              ldx dp:HEIGHT
              lda abs:.word0 (viewScaleTop),x
              cmp dp:SP_RIGHT
              bcc restoreWeaponCeiling
              lda dp:SP_RIGHT
restoreWeaponCeiling:
              sta dp:SP_END
              stz dp:SP_HI
              stz dp:SP_BANK
flat_ceiling_sprites_1_4:
              lda ##CEILING
              sta dp:SP_SRC
              jsr abs:.word0 (paintOpenIntervals)
              ldx dp:HEIGHT
              lda abs:.word0 (viewScaleTop),x
              cmp dp:SP_LEFT
              bcs restoreWeaponWallTop
              lda dp:SP_LEFT
restoreWeaponWallTop:
              sta dp:SP_TOP
              lda abs:.word0 (viewScaleBottom),x
              cmp dp:SP_RIGHT
              bcc restoreWeaponWallBottom
              lda dp:SP_RIGHT
restoreWeaponWallBottom:
              sta dp:SP_END
              lda dp:HEIGHT
              sta dp:SP_HI
              ldx dp:SCAN
              lda abs:.word0 (sourceAddr),x
              sta dp:SP_SRC
              ldx dp:COL
              lda abs:.word0 (sourceBank),x
              and ##255
              sta dp:SP_BANK
              jsr abs:.word0 (paintOpenIntervals)
              ldx dp:HEIGHT
              lda abs:.word0 (viewScaleBottom),x
              cmp dp:SP_LEFT
              bcs restoreWeaponFloorTop
              lda dp:SP_LEFT
restoreWeaponFloorTop:
              sta dp:SP_TOP
              lda dp:SP_RIGHT
              sta dp:SP_END
              stz dp:SP_BANK
              stz dp:SP_HI
flat_floor_sprites_1_5:
              lda ##FLOOR
              sta dp:SP_SRC
              jsr abs:.word0 (paintOpenIntervals)
              lda dp:SP_OLD
              clc
              adc ##6
              sta dp:SP_OLD
              dec dp:SP_EXTRA
              jmp abs:.word0 (restoreWeaponRun)
newWeaponPixels:
              ldy ##0
              lda [SP_PTR],y
              sta dp:SP_EXTRA
              lda ##2
              sta dp:SP_OLD
paintWeaponRun:
              lda dp:SP_EXTRA
              beq weaponAlreadyPainted
              ldy dp:SP_OLD
              lda [SP_PTR],y
              pha
              and ##255
              sta dp:SP_TOP
              pla
              xba
              and ##255
              sta dp:SP_BOT
              iny
              iny
              lda [SP_PTR],y
              sta dp:SP_SRC
              iny
              iny
              lda [SP_PTR],y
              ora ##128
              sta dp:SP_BANK
              lda abs:.word0 (weaponScaleIndex)
              sta dp:SP_HI
              jsr abs:.word0 (drawSpan)
              lda dp:SP_OLD
              clc
              adc ##6
              sta dp:SP_OLD
              dec dp:SP_EXTRA
              bra paintWeaponRun
weaponAlreadyPainted:
              ldx dp:COL
              sep #0x20
              lda long:MARKS,x
              beq weaponColumnEmpty
              lda #23                    ; all cached owners now need rebuilding
weaponColumnEmpty:
              sta long:OLD_MARKS,x
              rep #0x20
              rts

;;; One weapon stream needs no object search or runtime projection of its
;;; opaque intervals. Keep the usual final-span comparison for changed art.
weaponColumn:
              jsr abs:.word0 (loadWeaponColumn)
              ldy ##0
              lda [SP_PTR],y
              sta dp:SP_RUNS
              lda ##2
              sta dp:SP_VPOS
              stz dp:SP_FPOS
              stz dp:SP_NEW
              lda ##1
              sta dp:SP_WEAPON
              lda abs:.word0 (viewTop)
              sta dp:SP_ROW
weaponRow:    lda abs:.word0 (viewBottom)
              sta dp:SP_END
weaponRun:    lda dp:SP_RUNS
              beq weaponBackground
              ldy dp:SP_VPOS
              lda [SP_PTR],y
              sta dp:SP_BASE
              xba
              and ##255
              cmp dp:SP_ROW
              beq weaponNextRun
              bcc weaponNextRun
              sta dp:SP_END
              lda dp:SP_BASE
              and ##255
              cmp dp:SP_ROW
              beq weaponOwner
              bcc weaponOwner
              sta dp:SP_END
              bra weaponBackground
weaponNextRun:
              dec dp:SP_RUNS
              tya
              clc
              adc ##6
              sta dp:SP_VPOS
              bra weaponRun
weaponOwner:  iny
              iny
              lda [SP_PTR],y
              sta dp:SP_SRC
              iny
              iny
              lda [SP_PTR],y
              ora ##128
              sta dp:SP_BANK
              lda abs:.word0 (weaponScaleIndex)
              sta dp:SP_HI
              bra weaponEmit
weaponBackground:
              stz dp:SP_HI
              stz dp:SP_BANK
flat_ceiling_sprites_1_6:
              lda ##CEILING
              sta dp:SP_SRC
              ldx dp:HEIGHT
              lda abs:.word0 (viewScaleTop),x
              cmp dp:SP_ROW
              beq weaponWall
              bcc weaponWall
              bra weaponBackgroundEnd
weaponWall:   lda abs:.word0 (viewScaleBottom),x
              cmp dp:SP_ROW
              beq weaponFloor
              bcc weaponFloor
              pha
              lda dp:HEIGHT
              sta dp:SP_HI
              ldx dp:SCAN
              lda abs:.word0 (sourceAddr),x
              sta dp:SP_SRC
              ldx dp:COL
              lda abs:.word0 (sourceBank),x
              and ##255
              sta dp:SP_BANK
              pla
              bra weaponBackgroundEnd
flat_floor_sprites_1_7:
weaponFloor:  lda ##FLOOR
              sta dp:SP_SRC
              lda abs:.word0 (viewBottom)
weaponBackgroundEnd:
              cmp dp:SP_END
              bcs weaponEmit
              sta dp:SP_END
weaponEmit:   ldx dp:SP_FPOS
              lda dp:SP_END
              xba
              ora dp:SP_ROW
              sta abs:.word0 (spanBuffer+0),x
              lda dp:SP_HI
              sta abs:.word0 (spanBuffer+2),x
              lda dp:SP_SRC
              sta abs:.word0 (spanBuffer+4),x
              lda dp:SP_BANK
              sta abs:.word0 (spanBuffer+6),x
              txa
              clc
              adc ##8
              sta dp:SP_FPOS
              lda dp:SP_END
              sta dp:SP_ROW
              cmp abs:.word0 (viewBottom)
              bcs weaponSwept
              jmp abs:.word0 (weaponRow)
weaponSwept:  jmp abs:.word0 (sweepDone)

advanceStream:
              ldx dp:SP_N
              lda abs:.word0 (streamBuffer+2),x
              sta dp:SP_PTR
              lda abs:.word0 (streamBuffer+4),x
              sta dp:SP_PTR+2
              lda abs:.word0 (streamBuffer+6),x
              tay
              lda dp:SP_PTR+2
#if WOLF_TRUE_PIXELS
              cmp ##0x11
              beq sourceOpaqueStream
              cmp ##0x12
              bne advanceProjectedWeapon
sourceOpaqueStream:
#else
              cmp ##21
              beq advanceProjectedWeapon
#endif
              lda [SP_PTR],y
              bne streamRun
streamEnded:
              lda ##161
              sta abs:.word0 (streamBuffer+8),x
              sta abs:.word0 (streamBuffer+10),x
              rts
advanceProjectedWeapon:
              lda [SP_PTR],y
              beq streamEnded
              sta dp:SP_BASE
              and ##255
              sta abs:.word0 (streamBuffer+8),x
              lda dp:SP_BASE
              xba
              and ##255
              sta abs:.word0 (streamBuffer+10),x
              bra streamSource
streamRun:    sta dp:SP_BASE
;;; The height index and source row form one byte-table address. Both
;;; endpoints keep id's ceiling division and clipping, without multiplying
;;; or looking up a height-dependent pointer for each endpoint.
              lda abs:.word0 (streamBuffer+0),x
              lsr a
              xba
              sta dp:SP_TMP
              lda dp:SP_BASE
              and ##255
              ora dp:SP_TMP
              tax
              lda long:NP_ENDPOINTS,x
              and ##255
              ldx dp:SP_N
              sta abs:.word0 (streamBuffer+8),x
              lda dp:SP_BASE
              xba
              and ##255
              ora dp:SP_TMP
              tax
              lda long:NP_ENDPOINTS,x
              and ##255
              ldx dp:SP_N
              sta abs:.word0 (streamBuffer+10),x
streamSource:
              iny
              iny
              lda [SP_PTR],y
              sta abs:.word0 (streamBuffer+12),x
              iny
              iny
              lda [SP_PTR],y
              sta abs:.word0 (streamBuffer+14),x
              iny
              iny
              tya
              sta abs:.word0 (streamBuffer+6),x
              rts

;;; Arbitrary spans use offline row-address/sample tables. The same scaler
;;; draws walls, statics, actors and the weapon, with no transparent-pixel loop.
drawSpan:     lda dp:COL
              clc
              adc abs:.word0 (viewLeft)
              sta dp:MULR
              lda dp:SP_BANK
              bne texturedSpan
              sep #0x20
              lda dp:SP_SRC
              sta dp:EXITBYTE
              rep #0x20
              lda dp:SP_TOP
              ldy dp:SP_BOT
              jsr abs:.word0 (flatNonempty)
              rts
texturedSpan: ldx dp:SP_HI
#if !WOLF_GROUPS && !WOLF_TRUE_PIXELS
              lda abs:.word0 (scaleBank),x
              sta dp:ENTRY+2
              sta dp:EXITP+2
#endif
              lda abs:.word0 (rowCodeBase),x
              sta dp:SP_BASE
              lda dp:SP_TOP
              asl a
              clc
              adc dp:SP_BASE
              tax
              lda long:ROWCODE,x
              sta dp:ENTRY
#if !WOLF_GROUPS && !WOLF_TRUE_PIXELS
;;; The view already installs an RTL at this scaler's clipped end.
;;; A terminal span needs neither an exit lookup nor a temporary patch.
              ldx dp:SP_HI
              lda dp:SP_BOT
              cmp abs:.word0 (viewScaleBottom),x
              bne spanNeedsCut
              stz dp:EXITP+2
              bra spanEntryReady
spanNeedsCut:
#endif
              lda dp:SP_BOT
              asl a
              clc
              adc dp:SP_BASE
              tax
              lda long:ROWCODE,x
              sta dp:EXITP
#if WOLF_GROUPS || WOLF_TRUE_PIXELS
              ldx dp:SP_HI
              lda abs:.word0 (scaleBank),x
              sta dp:ENTRY+2
              sta dp:EXITP+2
#else
spanEntryReady:
#endif
#if WOLF_GROUPS
              stz dp:MASK_COUNT
              bit ##256
              beq spanClipReady
              jsr abs:.word0 (maskGroupedSpan)
spanClipReady:
#endif
#if !WOLF_FOUR_COLORS
              ldx dp:SP_HI
              lda abs:.word0 (rowTexBase),x
              clc
              adc dp:SP_TOP
              tax
              lda long:NP_ROWTEX,x
              and ##255
              sta abs:.word0 (spanFirstTex+1)
#endif
              sep #0x20
#if !WOLF_GROUPS && !WOLF_TRUE_PIXELS
              lda dp:EXITP+2
              beq spanCutReady
#endif
              lda [EXITP]
              sta dp:EXITBYTE
              lda #0x6b
              sta [EXITP]
spanCutReady:
              lda dp:SP_BANK
              and #127
              pha
              plb
              ldy dp:SP_SRC
              ldx dp:MULR
#if !WOLF_FOUR_COLORS
spanFirstTex: lda abs:0,y
#endif
              phk
              pea #.word0 (spanReturned-1)
              .byte 0xdc
              .word 0x103a
spanReturned: lda #2
              pha
              plb
#if WOLF_GROUPS
              rep #0x20
              lda dp:MASK_COUNT
              beq groupMaskRestored
              jsr abs:.word0 (restoreGroupedSpan)
groupMaskRestored:
              sep #0x20
#endif
#if !WOLF_GROUPS && !WOLF_TRUE_PIXELS
              lda dp:EXITP+2
              beq spanExitReady
#endif
              lda dp:EXITBYTE
              sta [EXITP]
spanExitReady: rep #0x20
              rts
#if WOLF_GROUPS
;;; Only the first and last texel runs need temporary clipping. Grouping
;;; their even/odd stores saves loads; each column still finishes before
;;; the next column begins. The table names every operand and run bound.
maskGroupedSpan:
              lda dp:ENTRY+2
              sta dp:MASK_PTR+2
              ldx dp:SP_HI
              lda abs:.word0 (groupBase),x
              sta dp:GROUP_BASE
              lda dp:SP_TOP
              asl a
              asl a
              clc
              adc dp:GROUP_BASE
              tax
              lda long:NP_GROUP_META+0x2,x
              and ##255
              sta dp:MASK_ROW
              lda dp:SP_TOP
              sta dp:MASK_END
              jsr abs:.word0 (maskGroupRows)
              lda dp:SP_BOT
              dec a
              asl a
              asl a
              clc
              adc dp:GROUP_BASE
              tax
              lda long:NP_GROUP_META+0x2,x
              xba
              and ##255
              sta dp:MASK_END
              asl a
              clc
              adc dp:SP_BASE
              tax
              lda long:ROWCODE,x
              sta dp:EXITP
              lda dp:SP_BOT
              sta dp:MASK_ROW
maskGroupRows:
              lda dp:MASK_ROW
              cmp dp:MASK_END
              bcs groupRowsMasked
              asl a
              asl a
              clc
              adc dp:GROUP_BASE
              tax
              lda long:NP_GROUP_META,x
              sta dp:MASK_PTR
              ldy dp:MASK_COUNT
              sta abs:.word0 (maskedStores),y
              lda [MASK_PTR]
              sta abs:.word0 (maskedStores+2),y
              lda ##0x0090
              sta [MASK_PTR]
              lda dp:MASK_COUNT
              clc
              adc ##4
              sta dp:MASK_COUNT
              inc dp:MASK_ROW
              bra maskGroupRows
groupRowsMasked:
              rts
restoreGroupedSpan:
              ldy ##0
restoreGroupRow:
              lda abs:.word0 (maskedStores),y
              sta dp:MASK_PTR
              lda abs:.word0 (maskedStores+2),y
              sta [MASK_PTR]
              iny
              iny
              iny
              iny
              cpy dp:MASK_COUNT
              bcc restoreGroupRow
              rts
              .section gamedata, data, root
maskedStores: .space 80
#endif
#endif

              .section gamecode, text, root, noreorder
;;; Live actors already have exact gameplay visibility; death uses fresh rays.
UseLogicActorVisibility:
              lda ##1
              sta abs:.word0 (logicActorVisibility)
              lda ##.word0 (SIGHT_VISIBLE)
              sta abs:.word0 (actorStartLoad+1)
              sep #0x20
              lda #.byte2 (SIGHT_VISIBLE)
              sta abs:.word0 (actorStartLoad+3)
              lda #O_VNEXT
              sta abs:.word0 (actorNextLoad+1)
              lda #.byte0 (actorVisible-actorCellsGate-2)
              sta abs:.word0 (actorCellsGate+1)
              rep #0x20
              rts
UseRayActorVisibility:
              stz abs:.word0 (logicActorVisibility)
              lda ##OBJLIST+O_NEXT
              sta abs:.word0 (actorStartLoad+1)
              sep #0x20
              lda #0x30
              sta abs:.word0 (actorStartLoad+3)
              lda #O_NEXT
              sta abs:.word0 (actorNextLoad+1)
              lda #.byte0 (actorCellsTest-actorCellsGate-2)
              sta abs:.word0 (actorCellsGate+1)
              rep #0x20
              lda ##1
              sta abs:.word0 (wallDirty)
              rts
              .section gamedata, data, root
logicActorVisibility: .word 1

              .section gamedata, data, root
staticBitBase: .word 0
              .section flowcode, text, root, noreorder
staticBitOffset:
              .byte 0,0,8,0,16,0,8,0,24,0,8,0,16,0,8,0
              .byte 32,0,8,0,16,0,8,0,24,0,8,0,16,0,8,0
              .byte 40,0,8,0,16,0,8,0,24,0,8,0,16,0,8,0
              .byte 32,0,8,0,16,0,8,0,24,0,8,0,16,0,8,0
              .byte 48,0,8,0,16,0,8,0,24,0,8,0,16,0,8,0
              .byte 32,0,8,0,16,0,8,0,24,0,8,0,16,0,8,0
              .byte 40,0,8,0,16,0,8,0,24,0,8,0,16,0,8,0
              .byte 32,0,8,0,16,0,8,0,24,0,8,0,16,0,8,0
              .byte 56,0,8,0,16,0,8,0,24,0,8,0,16,0,8,0
              .byte 32,0,8,0,16,0,8,0,24,0,8,0,16,0,8,0
              .byte 40,0,8,0,16,0,8,0,24,0,8,0,16,0,8,0
              .byte 32,0,8,0,16,0,8,0,24,0,8,0,16,0,8,0
              .byte 48,0,8,0,16,0,8,0,24,0,8,0,16,0,8,0
              .byte 32,0,8,0,16,0,8,0,24,0,8,0,16,0,8,0
              .byte 40,0,8,0,16,0,8,0,24,0,8,0,16,0,8,0
              .byte 32,0,8,0,16,0,8,0,24,0,8,0,16,0,8,0
              .byte 0

;;; A horizontal texel's first screen column, precomputed with horizontal.bin.
;;; Endpoint 64 includes its clamped final texel. Keep the existing range and
;;; invalidation contracts; only columns that cannot contain a run disappear.
              .section flowcode, text, root, noreorder
inverseSilhouette:
              lda dp:SP_HI
              cmp ##256
              xba
              ror a                     ; height index * 128, including bit 8
              clc
              adc ##65
              sta dp:SP_PTR
              lda ##9
              sta dp:SP_PTR+2
              lda dp:SP_BASE
              and ##255
              asl a
              tay
              lda [SP_PTR],y
              clc
              adc dp:SP_LEFT
              bpl inverseLeft
              lda ##0
inverseLeft:  sta dp:SP_N
              lda dp:SP_BASE
              xba
              and ##255
              inc a
              asl a
              tay
              lda [SP_PTR],y
              clc
              adc dp:SP_LEFT
              bpl inverseRight
              lda ##0
inverseRight:
              cmp abs:.word0 (viewWidth)
              bcc inverseDone
              lda abs:.word0 (viewWidth)
inverseDone:  rts

;;; The painter may retain background under a weapon in the former padded
;;; rectangle. Keep that restoration contract while narrowing owner masks.
;;; Unchanged projections retain their saved restoration rectangle directly.
padChangedSilhouette:
              phx
              ldx dp:SP_SHAPE
              lda long:SPRITE_CMDS+SPR_GAP,x
              plx
              and ##0x8000               ; PLX changes N; test the shape flag again
              bmi paddedBoundsDone
#if !WOLF_TRUE_PIXELS
;;; Up to height 96, inverse edges differ by at most one column from the
;;; direct product; up to 320, by at most two. These margins retain the old span;
;;; ownership still uses the exact silhouette saved before this call.
              lda dp:SP_H
              cmp ##98
              bcc paddedSmallBounds
              cmp ##322
              bcs paddedExactBounds
              jmp abs:.word0 (mediumPadBounds)
paddedSmallBounds:
              jmp abs:.word0 (smallPadBounds)
paddedExactBounds:
#endif
              lda dp:SP_BASE
              and ##255
              asl a
              asl a
              jsr abs:.word0 (scaleEdge)
#if WOLF_TRUE_PIXELS
              asl a
#endif
              sec
              sbc ##1
              clc
              adc dp:SP_LEFT
              bpl paddedLeftReady
              lda ##0
paddedLeftReady:
              sta dp:SP_N
              lda dp:SP_BASE
              xba
              and ##255
              inc a
              asl a
              asl a
              jsr abs:.word0 (scaleEdge)
#if WOLF_TRUE_PIXELS
              asl a
#endif
              clc
              adc ##2
              adc dp:SP_LEFT
              bpl paddedRightReady
              lda ##0
paddedRightReady:
              cmp abs:.word0 (viewWidth)
              bcc paddedBoundsReady
              lda abs:.word0 (viewWidth)
paddedBoundsReady:
              sta dp:SP_LIMIT
paddedBoundsDone:
              rts

;;; Static centers share only 64 coordinates on each map axis. Cache their
;;; exact signed products in spare endpoint-page bytes (224..229), using
;;; pages 0..63 for X and 64..127 for Y. Endpoint clipping leaves them intact.
;;; Actors retain their arbitrary-coordinate products. No new table bank is
;;; allocated; each coordinate is evaluated once per camera pose on demand.
              .section flowcode, text, root, noreorder
prepareStaticFactors:
              lda dp:VX
              cmp abs:.word0 (staticVX)
              bne staticFactorsChanged
              lda dp:VY
              cmp abs:.word0 (staticVY)
              bne staticFactorsChanged
              lda dp:ANGLE
              cmp abs:.word0 (staticAngle)
              beq staticFactorsReady
staticFactorsChanged:
              lda dp:VX
              sta abs:.word0 (staticVX)
              lda dp:VY
              sta abs:.word0 (staticVY)
              lda dp:ANGLE
              sta abs:.word0 (staticAngle)
              inc abs:.word0 (staticEpoch)
              bne staticFactorsReady
              lda ##0
              ldx ##0x7f00
clearStaticProducts:
              sta long:ENDPOINTS+0xe4,x
              txa
              sec
              sbc ##256
              tax
              lda ##0
              bcs clearStaticProducts
              inc abs:.word0 (staticEpoch)
staticFactorsReady:
              rts

projectStatic:
              lda dp:AI_CELL
              and ##63
              xba
              tax
              lda long:ENDPOINTS+0x40e4,x
              cmp abs:.word0 (staticEpoch)
              beq staticYReady
              phx
              txa
              ora ##128
              sec
              sbc dp:VY
              jsr abs:.word0 (productsCS)
              plx
              sta long:ENDPOINTS+0x40e0,x
              tya
              sta long:ENDPOINTS+0x40e2,x
              lda abs:.word0 (staticEpoch)
              sta long:ENDPOINTS+0x40e4,x
staticYReady:
              lda long:ENDPOINTS+0x40e0,x
              sta dp:SP_SIDE
              lda long:ENDPOINTS+0x40e2,x
              sta dp:SP_DEPTH
              lda dp:AI_CELL
              and ##0x0fc0
              asl a
              asl a
              tax
              lda long:ENDPOINTS+0xe4,x
              cmp abs:.word0 (staticEpoch)
              beq staticXReady
              phx
              txa
              ora ##128
              sec
              sbc dp:VX
              jsr abs:.word0 (productsCS)
              plx
              sta long:ENDPOINTS+0xe0,x
              tya
              sta long:ENDPOINTS+0xe2,x
              lda abs:.word0 (staticEpoch)
              sta long:ENDPOINTS+0xe4,x
staticXReady:
              lda dp:SP_SIDE
              sec
              sbc long:ENDPOINTS+0xe2,x
              sta dp:SP_SIDE
              lda long:ENDPOINTS+0xe0,x
              clc
              adc dp:SP_DEPTH
              sec
              sbc ##32
              sta dp:SP_DEPTH
              jmp abs:.word0 (depthReady)

              .section gamedata, data, root
staticVX:     .word 65535
staticVY:     .word 65535
staticAngle:  .word 65535
staticEpoch:  .word 0

              .section flowcode, text, root, noreorder
;;; Static records remain at the head of the draw list. If the wall cast and
;;; static set are unchanged, reuse their projections and light sampling.
;;; Renew history stamps; actors and the weapon still prepare every frame.
reuseStaticRecords:
              lda dp:FIRST
              bne staticRecordsMiss
              lda dp:VISSTAMP
              cmp abs:.word0 (staticRecordStamp)
              bne staticRecordsMiss
              lda abs:.word0 (staticRevision)
              cmp abs:.word0 (staticRecordRevision)
              bne staticRecordsMiss
              lda abs:.word0 (staticRecordCount)
              sta dp:SP_COUNT
              asl a
              asl a
              asl a
              asl a
              sta dp:SP_TMP
              ldy ##0
reuseStaticRecord:
              cpy dp:SP_TMP
              bcs staticRecordsReady
              tyx
              lda long:SPR_RECORDS+8,x
              lsr a
              lsr a
              lsr a
              lsr a
              lsr a
              tax
              sep #0x20
              lda abs:.word0 (projectionStamp)
              sta long:OBJECT_STAMPS,x
              rep #0x20
              tya
              clc
              adc ##16
              tay
              bra reuseStaticRecord
staticRecordsReady:
              lda abs:.word0 (staticRecordLow)
              sta abs:.word0 (touchedLow)
              lda abs:.word0 (staticRecordHigh)
              sta abs:.word0 (touchedHigh)
              sec
              rts
staticRecordsMiss:
              clc
              rts
saveStaticRecords:
              lda dp:VISSTAMP
              sta abs:.word0 (staticRecordStamp)
              lda abs:.word0 (staticRevision)
              sta abs:.word0 (staticRecordRevision)
              lda dp:SP_COUNT
              sta abs:.word0 (staticRecordCount)
              lda abs:.word0 (touchedLow)
              sta abs:.word0 (staticRecordLow)
              lda abs:.word0 (touchedHigh)
              sta abs:.word0 (staticRecordHigh)
              rts

              .section gamedata, data, root
staticRevision:       .word 0
staticRecordStamp:    .word 65535
staticRecordRevision:.word 65535
staticRecordCount:    .word 0
staticRecordLow:      .word 255
staticRecordHigh:     .word 0
#if WOLF_PREPARED
              .section weaponbounds, data, root
#include "weapon_bounds.inc"
#endif

#if WOLF_PREPARED
              .section paintsetup, text, root
;;; The extra directory has a frame lifetime independent of paint shortcuts.
;;; Its first owner clears every word; without that owner the painter ignores it.
prepareExtraOwner:
              lda abs:.word0 (maskFallback)
              cmp ##4
              beq extraNoMask
              lda dp:SP_EXTRA
              cmp ##32
              beq extraFirst
              asl dp:SP_NEW
              bne extraRecord
              cmp ##128
              bcs extraFallback
              lda abs:.word0 (maskColumnBytes)
              sta dp:SP_RPOS
              bra extraGroup
extraFirst:   lda dp:SP_COUNT
              cmp ##66
              bcs extraFallback
              stz dp:SP_RPOS
extraGroup:   lda dp:SP_RPOS
              clc
              adc ##320
              sta abs:.word0 (maskColumnBytes)
              dec a
              dec a
              tax
              lda ##0
extraClear:   sta long:EXTRA_MASKS,x
              dex
              dex
              bmi extraCleared
              cpx dp:SP_RPOS
              bcs extraClear
extraCleared: lda ##1
              sta dp:SP_NEW
              inc abs:.word0 (maskFallback)
extraRecord:  ldx dp:SP_EXTRA
              lda dp:SP_TMP
              sta long:EXTRA_OWNERS-32,x
              tax
              rtl
extraFallback:
              lda ##4
              sta abs:.word0 (maskFallback)
              stz dp:SP_NEW
extraNoMask:  ldx dp:SP_TMP
              rtl

;;; The near-first bit is clipped to both the prepared silhouette and wall.
;;; Marks retain their wider silhouette for restoring last frame's pixels.
buildExtraMask:
              lda dp:SP_NEW
              beq extraMaskDone
              ldx dp:SP_TMP
              lda dp:SP_LIMIT
              cmp long:SPR_RECORDS+2,x
              bcc extraRight
              lda long:SPR_RECORDS+2,x
extraRight:   sta dp:SP_END
              lda long:SPR_RECORDS,x
              bpl extraLeftPositive
              lda ##0
extraLeftPositive:
              cmp dp:SP_SIGN
              bcs extraLeft
              lda dp:SP_SIGN
extraLeft:    cmp dp:SP_END
              bcs extraMaskDone
              asl a
              tay
              clc
              adc dp:SP_RPOS
              tax
              lda dp:SP_END
              asl a
              sta dp:SP_END
extraColumn:  lda abs:.word0 (heightIndex),y
              cmp dp:SP_HI
              bcs extraBehind
              lda dp:SP_NEW
              ora long:EXTRA_MASKS,x
              sta long:EXTRA_MASKS,x
extraBehind:  inx
              inx
              iny
              iny
              cpy dp:SP_END
              bcc extraColumn
extraMaskDone:rtl
#endif

#if !WOLF_TRUE_PIXELS
              .section tailflow, text, root, noreorder
mediumPadBounds:
              lda dp:SP_N
              sec
              sbc ##3
              bra padLeftClipped
smallPadBounds:
              lda dp:SP_N
              sec
              sbc ##2
padLeftClipped:
              bpl smallPadLeft
              lda ##0
smallPadLeft: sta dp:SP_N
              lda dp:SP_LIMIT
              clc
              adc ##2
              cmp abs:.word0 (viewWidth)
              bcc smallPadRight
              lda abs:.word0 (viewWidth)
smallPadRight:sta dp:SP_LIMIT
              rts
#endif
