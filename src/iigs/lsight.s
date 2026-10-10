;;; Gameplay sight checks and object visibility. One current-frame wall
;;; cast supplies word stamps to both gameplay and rendering; visibility
;;; controls which actors are transformed and tested for pickup reach.
#include "memmap.inc"
#include "logic.inc"
#include "logic_dp.inc"
#include "line_regions.inc"
              .section logiccode, text, root, noreorder
              .public InitLineRegions, LineCellChange, RecountLineRegions
              .public CheckLine, LogicRefresh, MarkRayCellL, MarkStaticCellL
              .public staticMarkWord, rayMarkWord
              .public lineRegionFallback, lineOriginal
              .public ClearStaticIndex, AddStaticIndex, RemoveStaticIndex
              .public ClearSightActors, IndexSightActor, ForgetSightActor
              .extern Mul16, MulHigh16, GetBonus, FracSmall, wallDirty
              .extern CastLogicView

PLAYER        .equ OBJLIST
MINDIST       .equ 0x5800
FL_BONUS      .equ 2
FL_VISABLE    .equ 8
;;; The transform's work area is ray scratch that is dead by then. The four row
;;; pointers are a zero byte and the page of a fraction byte's row of products.
TR_PC0        .equ L_XSTEP            ; cos low byte row
TR_PC1        .equ L_XSTEP+3          ; cos high byte row
TR_PS0        .equ L_XSTEP+6          ; sin low byte row
TR_PS1        .equ L_XSTEP+9          ; sin high byte row
TR_NC         .equ L_XTS              ; |g| * cos fraction: bytes 0..5, the result is bytes 1..3
TR_NS         .equ L_XPDN             ; |g| * sin fraction
TR_SG         .equ L_SPOT             ; sign of g
TR_SC         .equ L_YINT            ; sign of the view cosine
TR_SS         .equ L_YINT+2          ; sign of the view sine

;;; ------------------------------------------------------------- CheckLine
;;; X = object. Carry set when the line to the player is open.
CheckLine:    jmp abs:.word0 (lineOriginal)
lineOriginal: lda abs:O_X+1,x
              sta dp:L_X1
              lda abs:O_Y+1,x
              sta dp:L_Y1
              lda abs:O_X+2,x
              sta dp:L_XT1
              lda abs:O_Y+2,x
              sta dp:L_YT1
              lda abs:V_plux
              sta dp:L_X2
              lda abs:V_pluy
              sta dp:L_Y2
              lda abs:PLAYER+O_TILEX
              sta dp:L_XT2
              lda abs:PLAYER+O_TILEY
              sta dp:L_YT2
              lda dp:L_XT1
              xba
              lsr a
              lsr a
              ora dp:L_YT1
              tax
              sep #0x20
              lda long:LINEIDS,x
              beq lineRegionEmpty
              rep #0x20
              and ##255
              sta dp:L_T
              lda dp:L_XT2
              xba
              lsr a
              lsr a
              ora dp:L_YT2
              tax
              sep #0x20
              lda long:LINEIDS,x
              cmp dp:L_T
              rep #0x20
              bne lineRegionFallback
              and ##255
              asl a
              tax
              lda long:LINECOUNTS,x
              bne lineRegionFallback
lineRegionClear:
              sec
              rts
lineRegionEmpty:
              rep #0x20
lineRegionFallback:
              lda dp:L_XT2
              cmp dp:L_XT1
              bne lsight_far35
              jmp abs:.word0 (lineNoX)
lsight_far35:
              bcc lineWest
              lda dp:L_X1
              and ##255
              eor ##0xffff
              inc a
              clc
              adc ##256
              sta dp:L_PARTIAL
              lda ##1
              bra lineXStep
lineWest:     lda dp:L_X1
              and ##255
              sta dp:L_PARTIAL
              lda ##0xffff
lineXStep:    sta dp:L_TILESTEP
              lda dp:L_X2
              sec
              sbc dp:L_X1
              jsr abs:.word0 (absWord)
              sta dp:L_DIVD               ; deltafrac
              lda dp:L_Y2
              sec
              sbc dp:L_Y1                 ; delta
              jsr abs:.word0 (stepRatio)
              sta dp:L_STEP               ; ystep
              lda dp:L_Y1
              jsr abs:.word0 (stepStart)
              sta dp:L_FRACT              ; yfrac
              lda dp:L_XT1
              clc
              adc dp:L_TILESTEP
              xba
              lsr a
              lsr a
              sta dp:L_X                  ; x*64, kept across cell crossings
              lda dp:L_XT2
              clc
              adc dp:L_TILESTEP
              asl a
              asl a
              asl a
              asl a
              asl a
              asl a
              sta dp:L_XT2
              lda dp:L_TILESTEP
              asl a
              asl a
              asl a
              asl a
              asl a
              asl a
              sta dp:L_TILESTEP           ; signed map-column stride
lineXLoop:    lda dp:L_FRACT
              bmi lineXOutside
              xba
              and ##255
lineXCoordinate:
              ora dp:L_X
              cmp ##4096
              bcc lineXInside
lineXOutside: brk                         ; CheckLine left the map
lineXInside:  tax
              lda dp:L_FRACT
              clc
              adc dp:L_STEP
              sta dp:L_FRACT
              lda abs:TILEMAP,x
              and ##255
              beq lineXNext
              cmp ##128
              bcc lineXBlocked
              jsr abs:.word0 (lineDoorOnly)
              bcs lineXNext
              rts
lineXBlocked:clc
              rts
lineXNext:    lda dp:L_X
              clc
              adc dp:L_TILESTEP
              sta dp:L_X
              cmp dp:L_XT2
              bne lineXLoop
lineNoX:      lda dp:L_YT2
              cmp dp:L_YT1
              bne lineY
              sec
              rts
lineY:        bcc lineNorth
              lda dp:L_Y1
              and ##255
              eor ##0xffff
              inc a
              clc
              adc ##256
              sta dp:L_PARTIAL
              lda ##1
              bra lineYStep
lineNorth:    lda dp:L_Y1
              and ##255
              sta dp:L_PARTIAL
              lda ##0xffff
lineYStep:    sta dp:L_TILESTEP
              lda dp:L_Y2
              sec
              sbc dp:L_Y1
              jsr abs:.word0 (absWord)
              sta dp:L_DIVD
              lda dp:L_X2
              sec
              sbc dp:L_X1
              jsr abs:.word0 (stepRatio)
              sta dp:L_STEP               ; xstep
              lda dp:L_X1
              jsr abs:.word0 (stepStart)
              sta dp:L_FRACT              ; xfrac
              lda dp:L_YT1
              clc
              adc dp:L_TILESTEP
              sta dp:L_Y
              lda dp:L_YT2
              clc
              adc dp:L_TILESTEP
              sta dp:L_YT2
lineYLoop:    lda dp:L_FRACT
              bmi lineYOutside
              and ##0xff00
lineYCoordinate:
              lsr a
              lsr a
              ora dp:L_Y
              cmp ##4096
              bcc lineYInside
lineYOutside: brk                         ; CheckLine left the map
lineYInside:  tax
              lda dp:L_FRACT
              clc
              adc dp:L_STEP
              sta dp:L_FRACT
              lda abs:TILEMAP,x
              and ##255
              beq lineYNext
              cmp ##128
              bcc lineYBlocked
              jsr abs:.word0 (lineDoorOnly)
              bcs lineYNext
              rts
lineYBlocked:clc
              rts
lineYNext:    lda dp:L_Y
              clc
              adc dp:L_TILESTEP
              sta dp:L_Y
              cmp dp:L_YT2
              bne lineYLoop
              sec
              rts

;;; A = a nonzero tile. Carry set when the line passes the door.
lineDoor:     cmp ##128
              bcc lineBlocked
lineDoorOnly: and ##0x7f
              cmp ##64
              bcc lineIsDoor
              brk                         ; doorposition[] read for a moving wall
lineIsDoor:   asl a
              tax
              lda dp:L_STEP               ; intercept = frac - step/2
              bpl halfPositive
              eor ##0xffff
              inc a
              lsr a
              eor ##0xffff
              inc a
              bra halfReady
halfPositive: lsr a
halfReady:    eor ##0xffff
              sec
              adc dp:L_FRACT
              cmp abs:DOORPOS,x
              beq lineOpen
              bcs lineBlocked
lineOpen:     sec
              rts
lineBlocked:  clc
              rts

absWord:      bpl absDone
              eor ##0xffff
              inc a
absDone:      rts

;;; A = delta, L_DIVD = deltafrac: A = clamp((delta<<8)/deltafrac, +-0x7fff).
stepRatio:    sta dp:L_SIGN
              jsr abs:.word0 (absWord)
              sta dp:L_DIVN+2
              ldy ##0
              cmp dp:L_DIVD
              bcc ratioFraction
              sbc dp:L_DIVD
              iny
              cmp dp:L_DIVD
              bcc ratioFraction
              sbc dp:L_DIVD
              iny
              cmp dp:L_DIVD
              bcc ratioFraction
              sbc dp:L_DIVD
              iny
              cmp dp:L_DIVD
              bcc ratioFraction
              lda dp:L_DIVN+2
              xba
              pha
              and ##0xff00
              sta dp:L_DIVN               ; |delta|<<8, low word
              pla
              and ##0x00ff
              sta dp:L_DIVN+2
              lda dp:L_DIVN               ; quotient >= 32768 when n>>15 >= d
              asl a
              lda dp:L_DIVN+2
              rol a
              cmp dp:L_DIVD
              bcc ratioDivide
              lda ##0x7fff
              bra ratioSign
ratioDivide:  jsr abs:.word0 (Div32by16)
              lda dp:L_DIVN
              bra ratioSign
;;; For integer parts 0-3, only the eight fractional quotient bits remain.
ratioFraction:stz dp:L_DIVN
              jsr abs:.word0 (divideFraction)
              tya
              xba
              ora dp:L_DIVN
ratioSign:    ldx dp:L_SIGN
              bpl ratioDone
              eor ##0xffff
              inc a
ratioDone:    rts

;;; The fractional numerator starts at zero. Shift the quotient after the
;;; comparison, using its carry directly instead of incrementing a word.
;;; Map deltas fit below $8000, so these shifts cannot overflow. Keep the
;;; full-word divider for wider denominators and arithmetic boundary checks.
divideFraction:
              ldx dp:L_DIVD
              bpl narrowFraction
              jmp abs:.word0 (divBit8)
narrowFraction:
              asl a
              cmp dp:L_DIVD
              bcc fractionNext0
fractionSubtract0:
              sbc dp:L_DIVD
fractionNext0:
              rol dp:L_DIVN
              asl a
              cmp dp:L_DIVD
              bcc fractionNext1
fractionSubtract1:
              sbc dp:L_DIVD
fractionNext1:
              rol dp:L_DIVN
              asl a
              cmp dp:L_DIVD
              bcc fractionNext2
fractionSubtract2:
              sbc dp:L_DIVD
fractionNext2:
              rol dp:L_DIVN
              asl a
              cmp dp:L_DIVD
              bcc fractionNext3
fractionSubtract3:
              sbc dp:L_DIVD
fractionNext3:
              rol dp:L_DIVN
              asl a
              cmp dp:L_DIVD
              bcc fractionNext4
fractionSubtract4:
              sbc dp:L_DIVD
fractionNext4:
              rol dp:L_DIVN
              asl a
              cmp dp:L_DIVD
              bcc fractionNext5
fractionSubtract5:
              sbc dp:L_DIVD
fractionNext5:
              rol dp:L_DIVN
              asl a
              cmp dp:L_DIVD
              bcc fractionNext6
fractionSubtract6:
              sbc dp:L_DIVD
fractionNext6:
              rol dp:L_DIVN
              asl a
              cmp dp:L_DIVD
              bcc fractionNext7
fractionSubtract7:
              sbc dp:L_DIVD
fractionNext7:
              rol dp:L_DIVN
              rts

;;; A = A + ((L_STEP * L_PARTIAL) >> 8), the long product shifted arithmetically.
stepStart:    sta dp:L_LS
              lda dp:L_PARTIAL
              cmp ##256
              bne startFraction
              lda dp:L_STEP
              bra startAdd
startFraction:
              asl a
              tax
              stz dp:L_PROD
              lda long:RAY_PRODUCTS_DIRECTORY,x
              sta dp:L_PROD+1
              lda dp:L_STEP
              jsr abs:.word0 (absWord)
              sta dp:L_T
              and ##255
              asl a
              tay
              lda [L_PROD],y
              sta dp:L_U
              lda dp:L_T+1
              and ##255
              asl a
              tay
              lda dp:L_U+1
              and ##255
              clc
              adc [L_PROD],y
              ldx dp:L_STEP
              bpl startAdd
              sta dp:L_T
              lda dp:L_U
              and ##255
              cmp ##1                     ; round magnitude up for negative floor
              lda dp:L_T
              adc ##0
              eor ##0xffff
              inc a
startAdd:     clc
              adc dp:L_LS
              rts

;;; L_DIVN (low word) = L_DIVN / L_DIVD; requires L_DIVN+2 < L_DIVD.
Div32by16:    lda dp:L_DIVN+2
              ldx ##8                     ; the first eight quotient bits are rare: a loop
divLoop:      asl dp:L_DIVN
              rol a
              bcs divSubtractL
              cmp dp:L_DIVD
              bcc divNextL
divSubtractL: sbc dp:L_DIVD
              inc dp:L_DIVN
divNextL:     dex
              bne divLoop
divBit8:      asl dp:L_DIVN
              rol a
              bcs divSubtract8
              cmp dp:L_DIVD
              bcc divNext8
divSubtract8: sbc dp:L_DIVD
              inc dp:L_DIVN
divNext8:
divBit9:      asl dp:L_DIVN
              rol a
              bcs divSubtract9
              cmp dp:L_DIVD
              bcc divNext9
divSubtract9: sbc dp:L_DIVD
              inc dp:L_DIVN
divNext9:
divBit10:     asl dp:L_DIVN
              rol a
              bcs divSubtract10
              cmp dp:L_DIVD
              bcc divNext10
divSubtract10:sbc dp:L_DIVD
              inc dp:L_DIVN
divNext10:
divBit11:     asl dp:L_DIVN
              rol a
              bcs divSubtract11
              cmp dp:L_DIVD
              bcc divNext11
divSubtract11:sbc dp:L_DIVD
              inc dp:L_DIVN
divNext11:
divBit12:     asl dp:L_DIVN
              rol a
              bcs divSubtract12
              cmp dp:L_DIVD
              bcc divNext12
divSubtract12:sbc dp:L_DIVD
              inc dp:L_DIVN
divNext12:
divBit13:     asl dp:L_DIVN
              rol a
              bcs divSubtract13
              cmp dp:L_DIVD
              bcc divNext13
divSubtract13:sbc dp:L_DIVD
              inc dp:L_DIVN
divNext13:
divBit14:     asl dp:L_DIVN
              rol a
              bcs divSubtract14
              cmp dp:L_DIVD
              bcc divNext14
divSubtract14:sbc dp:L_DIVD
              inc dp:L_DIVN
divNext14:
divBit15:     asl dp:L_DIVN
              rol a
              bcs divSubtract15
              cmp dp:L_DIVD
              bcc divNext15
divSubtract15:sbc dp:L_DIVD
              inc dp:L_DIVN
divNext15:
              sta dp:L_DIVR
              rts

;;; ------------------------------------------------------------- refresh
LogicRefresh: lda dp:L_VISDIRTY
              bne refreshView
              lda abs:PLAYER+O_ANGLE
              cmp abs:V_viewangle
              bne refreshView
              lda abs:PLAYER+O_X
              cmp dp:L_LASTPX
              bne refreshView
              lda abs:PLAYER+O_X+2
              cmp dp:L_LASTPX+2
              bne refreshView
              lda abs:PLAYER+O_Y
              cmp dp:L_LASTPY
              bne refreshView
              lda abs:PLAYER+O_Y+2
              cmp dp:L_LASTPY+2
              bne refreshView
              jmp abs:.word0 (refreshObjects)
refreshView:  stz dp:L_VISDIRTY
              lda abs:PLAYER+O_X
              sta dp:L_LASTPX
              lda abs:PLAYER+O_X+2
              sta dp:L_LASTPX+2
              lda abs:PLAYER+O_Y
              sta dp:L_LASTPY
              lda abs:PLAYER+O_Y+2
              sta dp:L_LASTPY+2
              lda abs:PLAYER+O_ANGLE
              sta abs:V_viewangle
              asl a
              asl a
              tax
              lda abs:SINTAB,x
              sta abs:V_viewsin
              lda abs:SINTAB+2,x
              sta abs:V_viewsin_hi
              lda abs:SINTAB+360,x        ; costable = sintable+90 longs
              sta abs:V_viewcos
              lda abs:SINTAB+362,x
              sta abs:V_viewcos_hi
              lda abs:PLAYER+O_X
              sec
              sbc abs:FOCALCOS,x
              sta abs:V_viewx
              lda abs:PLAYER+O_X+2
              sbc abs:FOCALCOS+2,x
              sta abs:V_viewx_hi
              sta abs:V_focaltx
              lda abs:PLAYER+O_Y
              clc
              adc abs:FOCALSIN,x
              sta abs:V_viewy
              lda abs:PLAYER+O_Y+2
              adc abs:FOCALSIN+2,x
              sta abs:V_viewy_hi
              sta abs:V_focalty
;;; The renderer casts the current pose once. Its word stamps also supply
;;; actor/pickup visibility; there is no second thirty-ray traversal.
refreshObjects:
              jsl long:CastLogicView
              sta dp:L_STAMP             ; A=word stamp, X/Y=cast row bounds
              txa
              sec
              sbc ##64
              bpl sharedMinReady
              lda ##0
sharedMinReady:
              sta dp:L_SEENMIN
              tya
              clc
              adc ##128
              sta dp:L_SEENEND
              lda ##.word0 (prepareFirstTransform)
              sta long:transformRowsReady+1
              jsr abs:.word0 (refreshStatics)
              jmp abs:.word0 (refreshActors)

;;; ------------------------------------------------------------- DrawScaleds
;;; Statics: a visible bonus within grabbing distance is taken.
;;; A static is grabbed only if it lies within 1.25 tiles of the view point
;;; (the rotation keeps |g|; nx < 1 + 1/8 and |ny| < 1/2), so only the view
;;; point's tile and its eight neighbors can qualify.
refreshStatics:
;;; Bit 1 of a cell's object marker (bytes at $2B:F000) says a pickup was placed
;;; there, so a view point whose nine cells have it clear has nothing to grab.
;;; Two cells a load; the loads reach one cell past each row of three, which only
;;; costs a scan.
              lda abs:V_focaltx
              xba
              lsr a
              lsr a
              clc
              adc abs:V_focalty
              tax                         ; the view point's cell
              lda long:OBJECT_MARKERS-65,x
              ora long:OBJECT_MARKERS-63,x
              ora long:OBJECT_MARKERS-1,x
              ora long:OBJECT_MARKERS+1,x
              ora long:OBJECT_MARKERS+63,x
              ora long:OBJECT_MARKERS+65,x
              and ##0x0202
              bne staticsNear
              rts
staticsNear:  lda abs:V_focaltx
              and ##0xfffe              ; three two-tile bins cover the five-tile query
              tax                         ; mask word of this group's column
              ldy ##STATICS               ; first record of this group
staticGroup:  lda long:STATIC_INDEX,x
              eor long:STATIC_INDEX+0x6,x
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
              cpy abs:V_laststat
              bcc staticGroup
              rts
;;; X walks the group's records, one bit of L_PICKMASK each. LSR leaves Z set
;;; when no bit remains. Records without the bonus flag end the test first.
staticMasked: sta dp:L_PICKMASK
              stx dp:L_PICKWORD
              sty dp:L_PICKBASE
              tyx
staticBit:    lsr dp:L_PICKMASK
              bcs staticTest
              beq staticGroupDone
staticStep:   txa
              clc
              adc ##8
              tax
              bra staticBit
staticTest:   lda abs:4,x
              bit ##FL_BONUS
              beq staticNext
              lda abs:2,x
              cmp ##0xffff
              beq staticNext
              lda abs:0,x
              tay
              and ##63
              sec
              sbc abs:V_focalty
              clc
              adc ##1
              cmp ##3
              bcs staticNext
              phx
              tya
              asl a
              tax
              lda long:VIS_STAMPS,x
              plx
              cmp dp:L_STAMP
              bne staticNext
              stx dp:L_LIST
              tya
              jsr abs:.word0 (TransformTile)
              ldx dp:L_LIST
              bcc staticNext
              jsr abs:.word0 (GetBonus)
              ldx dp:L_LIST
staticNext:   lda dp:L_PICKMASK
              bne staticStep
staticGroupDone:
              ldx dp:L_PICKWORD
              ldy dp:L_PICKBASE
              bra staticAdvance

;;; TransformTile: A = cell. Carry set when the tile is within grabbing reach.
TransformTile:
              sta dp:L_T
              lsr a
              lsr a
              lsr a
              lsr a
              lsr a
              lsr a
              sta dp:L_GX+2
              lda ##0x8000
              sec
              sbc abs:V_viewx
              sta dp:L_GX
              lda dp:L_GX+2
              sbc abs:V_viewx_hi
              sta dp:L_GX+2
              lda dp:L_T
              and ##63
              sta dp:L_GY+2
              lda ##0x8000
              sec
              sbc abs:V_viewy
              sta dp:L_GY
              lda dp:L_GY+2
              sbc abs:V_viewy_hi
              sta dp:L_GY+2
              lda ##0x2000
              jsr abs:.word0 (transformViewGXGY)
              lda dp:L_NX+2               ; nx < mindist: not grabbed
              bmi tileFar
              bne tileAhead
              lda dp:L_NX
              cmp ##MINDIST
              bcc tileFar
tileAhead:    lda dp:L_NX+2               ; nx < TILEGLOBAL
              bne tileFar
              lda dp:L_NY+2               ; -0x8000 < ny < 0x8000
              beq tileNyPositive
              cmp ##0xffff
              bne tileFar
              lda dp:L_NY
              cmp ##0x8001
              bcc tileFar
              sec
              rts
tileNyPositive:
              lda dp:L_NY
              cmp ##0x8000
              bcs tileFar
              sec
              rts
tileFar:      clc
              rts

;;; In: L_GX, L_GY (32-bit signed, magnitudes below 2^24), A = the offset.
;;; Out: L_NX = gx*cos - gy*sin - A, L_NY = gy*cos + gx*sin, each product as the
;;; source's FixedByFrac: |g| * fraction >> 16 with the sign applied after. The
;;; fraction bytes of the view cosine and sine select four rows of packed word
;;; products once; each |g| then gives both fractions' products with shared
;;; indexes, accumulated in unaligned direct-page words with a carry branch.
;;; Generic entry retained for independent arithmetic checks. Game callers use
;;; transformViewGXGY after refreshObjects resets its lazy preparation entry.
transformGXGY:
              sta dp:L_TEMP32
              jsr abs:.word0 (prepareTransformProducts)
              bra transformReady
transformViewGXGY:
              sta dp:L_TEMP32
transformRowsReady:
              jmp abs:.word0 (prepareFirstTransform)
transformReady:
              lda ##0
              sec
              sbc dp:L_TEMP32
              sta dp:L_NX
              lda ##0xffff
              sta dp:L_NX+2             ; -A
              ldx ##L_GX
              jsr abs:.word0 (trProducts)
              lda dp:TR_SG              ; nx += gx*cos
              eor dp:TR_SC
              bmi gxcNegative
              lda dp:L_NX
              clc
              adc dp:TR_NC+1
              sta dp:L_NX
              lda dp:L_NX+2
              adc dp:TR_NC+3
              sta dp:L_NX+2
              bra gxcDone
gxcNegative:  lda dp:L_NX
              sec
              sbc dp:TR_NC+1
              sta dp:L_NX
              lda dp:L_NX+2
              sbc dp:TR_NC+3
              sta dp:L_NX+2
gxcDone:      lda dp:TR_SG              ; ny = gx*sin
              eor dp:TR_SS
              bmi gxsNegative
              lda dp:TR_NS+1
              sta dp:L_NY
              lda dp:TR_NS+3
              sta dp:L_NY+2
              bra gxsDone
gxsNegative:  lda ##0
              sec
              sbc dp:TR_NS+1
              sta dp:L_NY
              lda ##0
              sbc dp:TR_NS+3
              sta dp:L_NY+2
gxsDone:      ldx ##L_GY
              jsr abs:.word0 (trProducts)
              lda dp:TR_SG              ; nx -= gy*sin
              eor dp:TR_SS
              bmi gysNegative
              lda dp:L_NX
              sec
              sbc dp:TR_NS+1
              sta dp:L_NX
              lda dp:L_NX+2
              sbc dp:TR_NS+3
              sta dp:L_NX+2
              bra gysDone
gysNegative:  lda dp:L_NX
              clc
              adc dp:TR_NS+1
              sta dp:L_NX
              lda dp:L_NX+2
              adc dp:TR_NS+3
              sta dp:L_NX+2
gysDone:      lda dp:TR_SG              ; ny += gy*cos
              eor dp:TR_SC
              bmi gycNegative
              lda dp:L_NY
              clc
              adc dp:TR_NC+1
              sta dp:L_NY
              lda dp:L_NY+2
              adc dp:TR_NC+3
              sta dp:L_NY+2
              rts
gycNegative:  lda dp:L_NY
              sec
              sbc dp:TR_NC+1
              sta dp:L_NY
              lda dp:L_NY+2
              sbc dp:TR_NC+3
              sta dp:L_NY+2
              rts

;;; X = the DP address of a 32-bit g. TR_SG = its sign; TR_NC and TR_NS hold
;;; |g| * the cosine and sine fractions as 40-bit sums; the products are bytes 1..3.
trProducts:   lda dp:2,x
              bpl trPositive
              lda ##0
              sec
              sbc dp:0,x
              sta dp:L_PD
              lda ##0
              sbc dp:2,x
              sta dp:L_PD+2
              lda ##0x8000
              sta dp:TR_SG
              ldx ##L_PD
              bra trMagnitude
trPositive:   stz dp:TR_SG
trMagnitude:  lda dp:0,x
              and ##255
              asl a
              tay                       ; twice byte 0 of |g|
              lda [TR_PC0],y            ; its product with the fraction low byte: only the high byte counts
              xba
              and ##255
              sta dp:TR_NC
              stz dp:TR_NC+2
              stz dp:TR_NC+4
              lda [TR_PS0],y
              xba
              and ##255
              sta dp:TR_NS
              stz dp:TR_NS+2
              stz dp:TR_NS+4
              lda [TR_PC1],y            ; with the fraction high byte
              clc
              adc dp:TR_NC
              sta dp:TR_NC
              bcc trC01
              inc dp:TR_NC+2
trC01:          lda [TR_PS1],y
              clc
              adc dp:TR_NS
              sta dp:TR_NS
              bcc trS01
              inc dp:TR_NS+2
trS01:          lda dp:1,x
              and ##255
              asl a
              tay                       ; twice byte 1
              lda [TR_PC0],y
              clc
              adc dp:TR_NC
              sta dp:TR_NC
              bcc trC10
              inc dp:TR_NC+2
trC10:          lda [TR_PS0],y
              clc
              adc dp:TR_NS
              sta dp:TR_NS
              bcc trS10
              inc dp:TR_NS+2
trS10:          lda [TR_PC1],y            ; one byte up
              clc
              adc dp:TR_NC+1
              sta dp:TR_NC+1
              bcc trC11
              inc dp:TR_NC+3
trC11:          lda [TR_PS1],y
              clc
              adc dp:TR_NS+1
              sta dp:TR_NS+1
              bcc trS11
              inc dp:TR_NS+3
trS11:          lda dp:2,x
              asl a
              tay                       ; twice byte 2 (the high word is below 256)
              lda [TR_PC0],y            ; one byte up
              clc
              adc dp:TR_NC+1
              sta dp:TR_NC+1
              bcc trC20
              inc dp:TR_NC+3
trC20:          lda [TR_PS0],y
              clc
              adc dp:TR_NS+1
              sta dp:TR_NS+1
              bcc trS20
              inc dp:TR_NS+3
trS20:          lda [TR_PC1],y            ; two bytes up
              clc
              adc dp:TR_NC+2
              sta dp:TR_NC+2
              lda [TR_PS1],y
              clc
              adc dp:TR_NS+2
              sta dp:TR_NS+2
              rts

;;; Once per refresh, on its first needed transform. These rows/signs occupy ray
;;; scratch preserved by refreshStatics, GetBonus, refreshActors and the
;;; transform helpers. Unlike L_T/L_U, L_YINT survives intervening actor work.
prepareFirstTransform:
              jsr abs:.word0 (prepareTransformProducts)
              jmp abs:.word0 (transformReady)
prepareTransformProducts:
              lda abs:V_viewcos
              and ##255
              asl a
              tax
              lda long:RAY_PRODUCTS_DIRECTORY,x
              stz dp:TR_PC0
              sta dp:TR_PC0+1
              lda abs:V_viewcos
              xba
              and ##255
              asl a
              tax
              lda long:RAY_PRODUCTS_DIRECTORY,x
              stz dp:TR_PC1
              sta dp:TR_PC1+1
              lda abs:V_viewsin
              and ##255
              asl a
              tax
              lda long:RAY_PRODUCTS_DIRECTORY,x
              stz dp:TR_PS0
              sta dp:TR_PS0+1
              lda abs:V_viewsin
              xba
              and ##255
              asl a
              tax
              lda long:RAY_PRODUCTS_DIRECTORY,x
              stz dp:TR_PS1
              sta dp:TR_PS1+1
              lda abs:V_viewcos_hi
              and ##0x8000
              sta dp:TR_SC
              lda abs:V_viewsin_hi
              and ##0x8000
              sta dp:TR_SS
              lda ##.word0 (transformReady)
              sta long:transformRowsReady+1
              rts

;;; Row membership changes only with tile X. The short visible list lets
;;; off-view flags be cleared without scanning every distant actor.
ClearSightActors:
              lda ##0
              ldx ##128
clearSightHead:
              sta long:SIGHT_ROWS,x
              dex
              dex
              bpl clearSightHead
              lda ##0xffff
              ldx ##128
clearDoorList:sta long:ACTIVE_DOORS,x
              dex
              dex
              bpl clearDoorList
              rts

IndexSightActor:
              cpx ##PLAYER
              bne indexMovingActor
              lda abs:O_TILEX,x
              sta abs:O_SX,x
              rts
indexMovingActor:
              jsr abs:.word0 (UnlinkSightRow)
              lda abs:O_TILEX,x
              sta abs:O_SX,x
              txa
              tay
              lda abs:O_SX,x
              asl a
              tax
              lda long:SIGHT_ROWS,x
              sta abs:O_SNEXT,y
              tya
              sta long:SIGHT_ROWS,x
              tyx
              stz abs:O_SPREV,x
              ldy abs:O_SNEXT,x
              beq sightIndexDone
              txa
              sta abs:O_SPREV,y
sightIndexDone:
              rts

UnlinkSightRow:
              lda abs:O_SX,x
              cmp ##64
              bcs sightRowRemoved
              ldy abs:O_SPREV,x
              beq sightRowHead
              lda abs:O_SNEXT,x
              sta abs:O_SNEXT,y
              bra sightRowNext
sightRowHead: txa
              tay
              lda abs:O_SX,x
              asl a
              tax
              lda abs:O_SNEXT,y
              sta long:SIGHT_ROWS,x
              tyx
sightRowNext: ldy abs:O_SNEXT,x
              beq sightRowRemoved
              lda abs:O_SPREV,x
              sta abs:O_SPREV,y
sightRowRemoved:
              lda ##0xffff
              sta abs:O_SX,x
              rts

ForgetSightActor:
              jsr abs:.word0 (UnlinkSightRow)
              jmp abs:.word0 (ClearActorVisible)

;;; Preserve source list order for equal-depth projection ties.
SetActorVisible:
              lda abs:O_FLAGS,x
              bit ##FL_VISABLE
              bne visibleListDone
              ora ##FL_VISABLE
              sta abs:O_FLAGS,x
              ldy abs:O_PREV,x
findVisiblePrevious:
              beq insertVisibleHead
              lda abs:O_FLAGS,y
              bit ##FL_VISABLE
              bne insertVisibleAfter
              lda abs:O_PREV,y
              tay
              bra findVisiblePrevious
insertVisibleAfter:
              tya
              sta abs:O_VPREV,x
              lda abs:O_VNEXT,y
              sta abs:O_VNEXT,x
              txa
              sta abs:O_VNEXT,y
              bra linkVisibleNext
insertVisibleHead:
              stz abs:O_VPREV,x
              lda long:SIGHT_VISIBLE
              sta abs:O_VNEXT,x
              txa
              sta long:SIGHT_VISIBLE
linkVisibleNext:
              ldy abs:O_VNEXT,x
              beq visibleListDone
              txa
              sta abs:O_VPREV,y
visibleListDone:
              rts

ClearActorVisible:
              lda abs:O_FLAGS,x
              bit ##FL_VISABLE
              beq visibleListDone
              and ##0xffff-FL_VISABLE
              sta abs:O_FLAGS,x
              ldy abs:O_VPREV,x
              beq clearVisibleHead
              lda abs:O_VNEXT,x
              sta abs:O_VNEXT,y
              bra clearVisibleNext
clearVisibleHead:
              lda abs:O_VNEXT,x
              sta long:SIGHT_VISIBLE
clearVisibleNext:
              ldy abs:O_VNEXT,x
              beq visibleListDone
              lda abs:O_VPREV,x
              sta abs:O_VPREV,y
              rts

;;; Actors: any of nine tiles seen (neighbors only when open).
refreshActors:
              lda long:SIGHT_VISIBLE
              tax
              beq actorRowsBegin
oldVisible:   lda abs:O_VNEXT,x
              sta dp:L_SAVE
              ldy abs:O_STATE,x
              lda abs:ST_SHAPE,y
              beq oldVisibleNext
              lda abs:O_CELL,x
              cmp dp:L_SEENMIN
              bcc clearOutsideActor
              cmp dp:L_SEENEND
              bcc oldVisibleNext
clearOutsideActor:
              jsr abs:.word0 (ClearActorVisible)
oldVisibleNext:
              ldx dp:L_SAVE
              bne oldVisible
actorRowsBegin:
              lda dp:L_SEENMIN
              lsr a
              lsr a
              lsr a
              lsr a
              lsr a
              sta dp:L_SROW
              lda dp:L_SEENEND
              lsr a
              lsr a
              lsr a
              lsr a
              lsr a
              cmp ##128
              bcc actorRowEndReady
              lda ##128
actorRowEndReady:
              sta dp:L_SEND
actorRow:     ldx dp:L_SROW
              lda long:SIGHT_ROWS,x
              tax
              bne actorRefresh
              jmp abs:.word0 (actorRowNext)
actorRefresh: stx dp:L_CHECK
              ldy abs:O_STATE,x
              lda abs:ST_SHAPE,y
              bne actorHasShape
              jmp abs:.word0 (actorRefreshNext)
actorHasShape:
              lda abs:O_CELL,x
              asl a
              tax
              lda long:VIS_STAMPS,x
              cmp dp:L_STAMP
              bne sharedDirectMiss
              jmp abs:.word0 (actorSeen)
sharedDirectMiss:
              lda long:VIS_STAMPS+126,x
              cmp dp:L_STAMP
              bne sharedNeighbor1
              lda long:TILE_MIRROR+126,x
              bmi actorSeen
              beq actorSeen
sharedNeighbor1:
              lda long:VIS_STAMPS+128,x
              cmp dp:L_STAMP
              bne sharedNeighbor2
              lda long:TILE_MIRROR+128,x
              bmi actorSeen
              beq actorSeen
sharedNeighbor2:
              lda long:VIS_STAMPS+130,x
              cmp dp:L_STAMP
              bne sharedNeighbor3
              lda long:TILE_MIRROR+130,x
              bmi actorSeen
              beq actorSeen
sharedNeighbor3:
              lda long:VIS_STAMPS-126,x
              cmp dp:L_STAMP
              bne sharedNeighbor4
              lda long:TILE_MIRROR-126,x
              bmi actorSeen
              beq actorSeen
sharedNeighbor4:
              lda long:VIS_STAMPS-128,x
              cmp dp:L_STAMP
              bne sharedNeighbor5
              lda long:TILE_MIRROR-128,x
              bmi actorSeen
              beq actorSeen
sharedNeighbor5:
              lda long:VIS_STAMPS-130,x
              cmp dp:L_STAMP
              bne sharedNeighbor6
              lda long:TILE_MIRROR-130,x
              bmi actorSeen
              beq actorSeen
sharedNeighbor6:
              lda long:VIS_STAMPS+2,x
              cmp dp:L_STAMP
              bne sharedNeighbor7
              lda long:TILE_MIRROR+2,x
              bmi actorSeen
              beq actorSeen
sharedNeighbor7:
              lda long:VIS_STAMPS-2,x
              cmp dp:L_STAMP
              bne sharedNeighbor8
              lda long:TILE_MIRROR-2,x
              bmi actorSeen
              beq actorSeen
sharedNeighbor8:
actorNotSeen:  ldx dp:L_CHECK
              jsr abs:.word0 (ClearActorVisible)
              bra actorRefreshNext
actorSeen:
              ldx dp:L_CHECK
              lda ##1
              sta abs:O_ACTIVE,x
              jsr abs:.word0 (TransformActor)
              bcc actorRefreshNext        ; too close: the flag is kept
              ldx dp:L_CHECK
              jsr abs:.word0 (SetActorVisible)
actorRefreshNext:
              ldx dp:L_CHECK
              lda abs:O_SNEXT,x
              tax
              beq actorRowNext
              jmp abs:.word0 (actorRefresh)
actorRowNext: inc dp:L_SROW
              inc dp:L_SROW
              lda dp:L_SROW
              cmp dp:L_SEND
              bcs actorsDone
              jmp abs:.word0 (actorRow)
actorsDone:   rts
neighborSteps:.word 0xffff,1,0xffbf,0xffc0,0xffc1,65,64,63,0

;;; TransformActor: X = actor. transx always; carry set when nx >= mindist,
;;; with O_VIEWX = 1 when abs(viewx-centerx) < shootdelta for shootable actors.
;;; Non-shootable actors keep the exact visibility decision; aim/depth have no readers.
TransformActor:
              lda abs:O_X,x
              sec
              sbc abs:V_viewx
              sta dp:L_GX
              lda abs:O_X+2,x
              sbc abs:V_viewx_hi
              sta dp:L_GX+2
              lda abs:O_Y,x
              sec
              sbc abs:V_viewy
              sta dp:L_GY
              lda abs:O_Y+2,x
              sbc abs:V_viewy_hi
              sta dp:L_GY+2
              lda abs:O_FLAGS,x
              bit ##1                    ; only shootable actors need the aim coordinate
              beq actorDepthOnly
              lda ##0x4000
              jsr abs:.word0 (transformViewGXGY)
              bra actorDepthStored
actorDepthOnly:
              jmp abs:.word0 (guardedCorpseDepth)
actorDepthStored:
              ldx dp:L_CHECK
              lda dp:L_NX
              sta abs:O_TRANSX,x
              lda dp:L_NX+2
              sta abs:O_TRANSX+2,x
              bmi actorTooClose
              bne actorAhead
              lda dp:L_NX
              cmp ##MINDIST
              bcs actorAhead
actorTooClose:clc
              rts
actorAhead:   lda abs:O_FLAGS,x
              bit ##1
              bne actorAim
              sec                        ; corpse near-plane visibility remains exact; aim has no reader
              rts
actorAim:     lda dp:L_NY+2               ; |ny|*scale < shootdelta*nx
              bpl nyPositive
              lda ##0
              sec
              sbc dp:L_NY
              sta dp:L_NY
              lda ##0
              sbc dp:L_NY+2
              sta dp:L_NY+2
;;; Map-relative magnitudes fit 24 bits; both factors have packed word rows.
;;; Divide both aim factors by four. Dropping each 16-bit fraction changes
;;; the comparison by less than -6..41; only that boundary needs full products.
;;; O_TRANSX and the visibility/near-plane decision retain exact precision.
nyPositive:
              lda dp:L_NY+2
              asl a
              tax
              lda long:WORD_PRODUCTS+(LOGIC_SCALE/4)*512,x
              sta dp:L_T
              lda dp:L_NX+2
              asl a
              tax
              lda long:WORD_PRODUCTS+(LOGIC_SHOOTDELTA/4)*512,x
              sta dp:L_U
              lda dp:L_T
              sec
              sbc dp:L_U
              bmi aimCoarseNegative
              cmp ##LOGIC_SHOOTDELTA/4
              bcc aimPrecise
              lda ##0
              bra aimCoarseDone
aimCoarseNegative:
              cmp ##65537-LOGIC_SCALE/4
              bcs aimPrecise
              lda ##1
aimCoarseDone:
              ldx dp:L_CHECK
              sta abs:O_VIEWX,x
              sec
              rts
aimPrecise:
              lda dp:L_NY
              and ##255
              asl a
              tax
              lda long:WORD_PRODUCTS+LOGIC_SCALE*512,x
              sta dp:L_PA
              xba
              and ##255
              sta dp:L_T
              lda dp:L_NY+1
              and ##255
              asl a
              tax
              lda long:WORD_PRODUCTS+LOGIC_SCALE*512,x
              clc
              adc dp:L_T
              sep #0x20
              sta dp:L_PA+1
              rep #0x20
              xba
              and ##255
              sta dp:L_PA+2
              lda dp:L_NY+2
              asl a
              tax
              lda long:WORD_PRODUCTS+LOGIC_SCALE*512,x
              clc
              adc dp:L_PA+2
              sta dp:L_PA+2
              lda dp:L_NX
              and ##255
              asl a
              tax
              lda long:WORD_PRODUCTS+LOGIC_SHOOTDELTA*512,x
              sta dp:L_PB
              xba
              and ##255
              sta dp:L_T
              lda dp:L_NX+1
              and ##255
              asl a
              tax
              lda long:WORD_PRODUCTS+LOGIC_SHOOTDELTA*512,x
              clc
              adc dp:L_T
              sep #0x20
              sta dp:L_PB+1
              rep #0x20
              xba
              and ##255
              sta dp:L_PB+2
              lda dp:L_NX+2
              asl a
              tax
              lda long:WORD_PRODUCTS+LOGIC_SHOOTDELTA*512,x
              clc
              adc dp:L_PB+2
              sta dp:L_PB+2
              ldx dp:L_CHECK
              lda dp:L_PA
              cmp dp:L_PB
              lda dp:L_PA+2
              sbc dp:L_PB+2
              lda ##0
              rol a
              eor ##1                     ; 1 when |ny|*scale < shootdelta*nx
              sta abs:O_VIEWX,x
              sec
              rts
ClearStaticIndex:
              lda ##0
              ldx ##3498
clearStaticWord:
              sta long:STATIC_INDEX,x
              dex
              dex
              bpl clearStaticWord
              rts

;;; Each group keeps X and Y prefixes in the same 140 bytes. Coordinates
;;; use two-tile bins; prefix positions -1..33 pad both map edges. The
;;; renderer intersects both axes before projecting candidates. Exact
;;; projection and wall depths decide which candidates can draw.
AddStaticIndex:
              .extern staticRevision
              lda long:staticRevision
              inc a
              sta long:staticRevision
              phx
              jsr abs:.word0 (staticIndexStart)
addStaticPrefix:
              lda long:STATIC_INDEX,x
              ora dp:L_W
              sta long:STATIC_INDEX,x
              inx
              inx
              cpx dp:L_PC+2
              bcc addStaticPrefix
              plx
              phx
              jsr abs:.word0 (staticIndexY)
addStaticY:   lda long:STATIC_INDEX,x
              ora dp:L_W
              sta long:STATIC_INDEX,x
              inx
              inx
              cpx dp:L_PC+2
              bcc addStaticY
              plx
              rts
RemoveStaticIndex:
              lda long:staticRevision
              inc a
              sta long:staticRevision
              phx
              jsr abs:.word0 (staticIndexStart)
              lda dp:L_W
              eor ##0xffff
              sta dp:L_W
removeStaticPrefix:
              lda long:STATIC_INDEX,x
              and dp:L_W
              sta long:STATIC_INDEX,x
              inx
              inx
              cpx dp:L_PC+2
              bcc removeStaticPrefix
              plx
              phx
              jsr abs:.word0 (staticIndexY)
removeStaticY:
              lda long:STATIC_INDEX,x
              and dp:L_W
              sta long:STATIC_INDEX,x
              inx
              inx
              cpx dp:L_PC+2
              bcc removeStaticY
              plx
              rts
staticIndexStart:
              lda abs:0,x
              and ##0x0fc0
              lsr a
              lsr a
              lsr a
              lsr a
              lsr a
              lsr a
              and ##0xfffe
              sta dp:L_PC
              txa
              sec
              sbc ##STATICS
              sta dp:L_V
              and ##127
              lsr a
              lsr a
              tax
              lda long:staticBits,x
              sta dp:L_W
              lda dp:L_V
              and ##0xff80
              lsr a
              lsr a
              lsr a
              lsr a
              lsr a
              lsr a
              tax
              lda long:staticGroups,x
              clc
              adc ##70
              sta dp:L_PC+2
              sec
              sbc ##66
              clc
              adc dp:L_PC
              tax
              rts
staticIndexY: lda abs:0,x
              and ##62
              clc
              adc dp:L_PC+2             ; end of X prefixes is the Y base
              adc ##4
              sta dp:L_PC
              lda dp:L_PC+2
              clc
              adc ##70
              sta dp:L_PC+2
              ldx dp:L_PC
              rts
staticBits:   .word 1,2,4,8,16,32,64,128,256,512,1024,2048,4096,8192,16384,32768
staticGroups: .word 0,140,280,420,560,700,840,980,1120,1260,1400,1540,1680,1820,1960,2100,2240,2380,2520,2660,2800,2940,3080,3220,3360

MarkStaticCellL:
              phx
              pha
              lda abs:4,x                 ; a pickup also sets bit 1 of the marker
              and ##FL_BONUS
              ora ##64
              sta dp:L_MC
              plx                         ; the cell
              sep #0x20
              lda long:OBJECT_MARKERS,x         ; another static may share the cell
              ora dp:L_MC
              sta long:OBJECT_MARKERS,x
              rep #0x20
              txa
              asl a
              tax
              lda long:TILE_MIRROR,x
              bne staticCellMarked
staticMarkWord:lda ##0x8000
              sta long:TILE_MIRROR,x
              lda ##1                    ; a new marker needs a cached-view stamp
              sta long:wallDirty
staticCellMarked:
              plx
              rts

;;; MarkRayCellL: A = cell. The renderer's object marker and the empty
;;; neighbors it needs for sprite visibility stamps. X and Y are kept.
MarkRayCellL: phx
              phy
              sta dp:L_MC
              tax
              sep #0x20
              lda #64
              sta long:OBJECT_MARKERS,x
              rep #0x20
              lda ##16
              sta dp:L_MI
markLoop:     ldx dp:L_MI
              lda dp:L_MC
              clc
              adc long:neighborSteps,x
              cmp ##4096
              bcs markNext
              asl a
              tax
              lda long:TILE_MIRROR,x
              bne markNext
rayMarkWord:  lda ##0x8000
              sta long:TILE_MIRROR,x
markNext:     dec dp:L_MI
              dec dp:L_MI
              bpl markLoop
              ply
              plx
              rts

;;; Cold setup reuses dead movement scratch for the rectangle cursor.
InitLineRegions:
              jsr abs:.word0 (InitLineRegionProbe)
              lda ##0
              ldx ##4094
clearLineIds: sta long:LINEIDS,x
              dex
              dex
              bpl clearLineIds
              jsr abs:.word0 (clearLineCounts)
              lda ##1
              sta dp:L_Y
              lda abs:ROOMRECTS
              sta dp:L_X
              beq lineRegionsDone
              ldy ##2
lineRectNext: lda abs:ROOMRECTS,y
              and ##255
              xba
              lsr a
              lsr a
              sta dp:L_XL
              lda abs:ROOMRECTS+1,y
              and ##255
              xba
              lsr a
              lsr a
              sta dp:L_XH
              lda abs:ROOMRECTS+2,y
              and ##255
              sta dp:L_YL
              lda abs:ROOMRECTS+3,y
              and ##255
              sec
              sbc dp:L_YL
              inc a
              sta dp:L_YH
lineRectRow:  lda dp:L_XL
              clc
              adc dp:L_YL
              tax
              phy
              ldy dp:L_YH
              sep #0x20
              lda dp:L_Y
lineRectCell: sta long:LINEIDS,x
              inx
              dey
              bne lineRectCell
              rep #0x20
              ply
              lda dp:L_XL
              cmp dp:L_XH
              beq lineRectFilled
              clc
              adc ##64
              sta dp:L_XL
              bra lineRectRow
lineRectFilled:
              iny
              iny
              iny
              iny
              inc dp:L_Y
              dec dp:L_X
              bne lineRectNext
lineRegionsDone:
              rts

;;; Preserve the wall writer's inputs while counting empty/nonempty changes.
LineCellChange:
              phx
              phy
              pha
              sep #0x20
              lda abs:TILEMAP,x
              bne lineHadWall
              lda 1,s
              beq lineCountKept
              ldy ##1
              bra lineCountChange
lineHadWall:  lda 1,s
              bne lineCountKept
              ldy ##0xffff
lineCountChange:
              lda long:LINEIDS,x
              beq lineCountKept
              rep #0x20
              and ##255
              asl a
              tax
              tya
              clc
              adc long:LINECOUNTS,x
              sta long:LINECOUNTS,x
lineCountKept:
              rep #0x20
              pla
              ply
              plx
              rts

;;; JSL after restoring a saved TILEMAP, before any CheckLine. The floor's
;;; IDs must already be expanded. P, DBR, D and Y are kept; A/X are scratch.
RecountLineRegions:
              php
              rep #0x30
              phb
              pea #LOGICBANK*257
              plb
              plb
              jsr abs:.word0 (recountLineTiles)
              plb
              plp
              rtl
recountLineTiles:
              jsr abs:.word0 (clearLineCounts)
              ldx ##4095
recountLineCell:
              sep #0x20
              lda abs:TILEMAP,x
              beq recountLineNext
              lda long:LINEIDS,x
              beq recountLineNext
              rep #0x20
              and ##255
              phx
              asl a
              tax
              lda long:LINECOUNTS,x
              inc a
              sta long:LINECOUNTS,x
              plx
recountLineNext:
              dex
              bpl recountLineCell
              rep #0x20
              rts
clearLineCounts:
              lda ##0
              ldx ##510
clearLineInvalid:
              sta long:LINECOUNTS,x
              dex
              dex
              bpl clearLineInvalid
              rts

;;; Only shootable actors have a consumer for O_TRANSX/O_VIEWX (closestTarget).
;;; A corpse needs just the exact near-plane decision. Truncating |g| to8.8
;;; and the source fraction to0.8 bounds each product error by |g|'s integer
;;; part plus3 coarse units. A full transform handles the uncertain interval.
;;; No displayed geometry uses this approximation: sprites.s projects afresh.
guardedCorpseDepth:
              lda long:transformRowsReady+1
              cmp ##.word0 (transformReady)
              beq corpseRowsReady
              jsr abs:.word0 (prepareTransformProducts)
corpseRowsReady:
              lda ##6
              sta dp:L_TEMP32            ; sum of the two per-product error bounds
              ldx ##L_GX
              jsr abs:.word0 (coarseProductC)
              sta dp:TR_NC
              lda dp:TR_SG
              eor dp:TR_SC
              bmi corpseGXNegative
              lda dp:TR_NC
              sec
              sbc ##64
              bra corpseGXReady
corpseGXNegative:
              lda ##0xffc0
              sec
              sbc dp:TR_NC
corpseGXReady:
              sta dp:L_NX                ; coarse signed8.8 depth, including actor offset
              ldx ##L_GY
              jsr abs:.word0 (coarseProductS)
              sta dp:TR_NC
              lda dp:TR_SG
              eor dp:TR_SS
              bmi corpseGYNegative
              lda dp:L_NX
              sec
              sbc dp:TR_NC
              bra corpseGYReady
corpseGYNegative:
              lda dp:L_NX
              clc
              adc dp:TR_NC
corpseGYReady:
              sta dp:L_NX
              sec
              sbc dp:L_TEMP32
              bmi corpseUpperBound
              cmp ##MINDIST/256
              bcc corpseUpperBound
              sec
              rts
corpseUpperBound:
              lda dp:L_NX
              clc
              adc dp:L_TEMP32
              bmi corpseBehind
              cmp ##MINDIST/256
              bcs corpseUncertain
corpseBehind: clc
              rts
corpseUncertain:
              lda ##0x4000
              jsr abs:.word0 (transformViewGXGY)
              jmp abs:.word0 (actorDepthStored)

coarseProductC:
              jsr abs:.word0 (corpseMagnitude)
              lda dp:2,x
              clc
              adc dp:L_TEMP32
              sta dp:L_TEMP32
              lda dp:2,x
              asl a
              tay
              lda [TR_PC1],y
              sta dp:TR_NC
              lda dp:1,x
              and ##255
              asl a
              tay
              lda [TR_PC1],y
              xba
              and ##255
              clc
              adc dp:TR_NC
              rts

coarseProductS:
              jsr abs:.word0 (corpseMagnitude)
              lda dp:2,x
              clc
              adc dp:L_TEMP32
              sta dp:L_TEMP32
              lda dp:2,x
              asl a
              tay
              lda [TR_PS1],y
              sta dp:TR_NC
              lda dp:1,x
              and ##255
              asl a
              tay
              lda [TR_PS1],y
              xba
              and ##255
              clc
              adc dp:TR_NC
              rts

corpseMagnitude:
              lda dp:2,x
              bpl corpsePositive
              lda ##0
              sec
              sbc dp:0,x
              sta dp:L_PD
              lda ##0
              sbc dp:2,x
              sta dp:L_PD+2
              lda ##0x8000
              sta dp:TR_SG
              ldx ##L_PD
              rts
corpsePositive:
              stz dp:TR_SG
              rts

#include "line_proofs.inc"
