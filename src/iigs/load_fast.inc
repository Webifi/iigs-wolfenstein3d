;;; EP06+ retain EP05 block addresses. Bit 14 selects a fast codec; bits
;;; 9..13 count decoded 2 KiB units (zero means 64 KiB). A packed block
;;; starts with its exact output length, then an LZSA1 stream or a marker:
;;; 0 = LZ16, 1 = shared-art plan, 2 = sparse LZ16. These markers cannot
;;; start a valid LZSA1 stream. Plan records use destination bank $FF and
;;; put their exact progress credit in the address word; no write uses $FF.
;;; Decoding uses existing bank-$1D staging and the boot direct page.
#include "memmap.inc"
              .public loadMixed, ReadFloorFormat, DecodeFloorUnit, DecodeWorkSize
loadMixed:    .word 0
ReadFloorFormat:
              stz abs:loadMixed
              lda abs:EPDIR+6
              cmp ##0x3830
              beq packedNewFormat
              cmp ##0x3730
              beq packedNewFormat
              cmp ##0x3630
              bne packedOldFormat
packedNewFormat:
              inc abs:loadMixed
packedOldFormat:
              cmp ##0x3830
              beq packedWideFormat
              cmp ##0x3730
              beq packedWideFormat
              cmp ##0x3530
              beq packedWideFormat
              cmp ##0x3630
              bne packedFormatDone
packedWideFormat:
              inc abs:loadWide
packedFormatDone:
              rts

DecodeWorkSize:
              lda abs:2,y
              and ##255
              cmp ##255
              bne packedOrdinaryWork
              lda abs:0,y
              rts
packedOrdinaryWork:
              lda abs:2,y
              bit ##0x100
              beq packedNoWork
              xba
              ldy abs:loadMixed           ; caller saves its directory cursor
              beq packedOldWork
              and ##0x003e
              asl a
              bra packedWorkNonzero
packedOldWork:
              and ##0x007e
packedWorkNonzero:
              bne packedWorkDone
              lda ##128
packedWorkDone:
              rts
packedNoWork: lda ##0
              rts

DecodeFloorUnit:
              rep #0x20
              lda abs:loadMixed
              beq packedB1
              ldx dp:LV_RECORD
              lda abs:2,x
              bit ##0x4000
              bne lzsaStart
packedB1:     jsr abs:StreamB1
              sep #0x20
              jmp abs:BOOT_b1Seg

;;; Input: native A16/X16, DBR=0, D=0. Output: A8/X16, DBR=0.
;;; STAGE+stageStart holds length16 followed by one LZSA1 stream-format block.
;;; MVN performs forward overlap copies, including distance-one runs.
lzsaStart:    stz abs:sharedDecode
              ldx abs:stageStart
stageP0:      lda long:BOOT_STAGE+2,x
              and ##255
              cmp ##1
              bne lzsaDestination
              inc abs:sharedDecode
              lda ##0x4000
              sta dp:BOOT_SEGADDR
              lda ##0x1d
              sta dp:BOOT_SEGADDR+2
lzsaDestination:
              sep #0x20
              lda dp:BOOT_SEGADDR+2
              sta abs:lzsaLiteralCopy+1
              sta abs:lzsaMatchCopy+1
              sta abs:lzsaMatchCopy+2
              sta abs:lz16LiteralCopy+1
              sta abs:lz16MatchCopy+1
              sta abs:lz16MatchCopy+2
              rep #0x30
              ldx abs:stageStart
stageP1:      lda long:BOOT_STAGE,x
              clc
              adc dp:BOOT_SEGADDR
              sta dp:B1_END                 ; boot B1_END
              ldy dp:BOOT_SEGADDR
              tya
              clc
              adc ##2048
              bcc lzsaFirstLimit
              lda ##65535
lzsaFirstLimit:
              sta dp:B1_NEXT                 ; boot B1_NEXT
              stz dp:LOADER_TMP                 ; boot progress credit
              lda abs:stageStart
              inc a
              inc a
              tax
stageP2:      lda long:BOOT_STAGE,x
              and ##255
              cmp ##3
              bcs lzsaToken
              inx
              jmp abs:lz16Token
stageP3:
lzsaToken:    lda long:BOOT_STAGE,x
              inx
              and ##255
              sta dp:LZ_TOKEN
              lsr a
              lsr a
              lsr a
              lsr a
              and ##7
              cmp ##7
              bne lzsaLiteralLength
              lda ##7
              jsr abs:lzsaLength
lzsaLiteralLength:
              cmp ##0
              beq lzsaAfterLiteral
              dec a
lzsaLiteralCopy:
              .byte 0x54, 0x00, 0x1d
lzsaAfterLiteral:
              cpy dp:B1_END
              beq lzsaDone
              inx
              lda dp:LZ_TOKEN
              bit ##128
              beq lzsaShortOffset
stageM0:      lda long:BOOT_STAGE-1,x
              inx
              bra lzsaOffset
lzsaShortOffset:
stageM1:      lda long:BOOT_STAGE-1,x
              ora ##0xff00
lzsaOffset:   sta dp:B1_OFF
              lda dp:LZ_TOKEN
              and ##15
              clc
              adc ##3
              cmp ##18
              bne lzsaMatchLength
              lda ##18
              jsr abs:lzsaLength
lzsaMatchLength:
              dec a
              sta dp:B1_CNT
              stx dp:B1_INP
              tya
              clc
              adc dp:B1_OFF
              tax
              lda dp:B1_CNT
lzsaMatchCopy:
              .byte 0x54, 0x00, 0x00
              ldx dp:B1_INP
              cpy dp:B1_NEXT
              bcc lzsaToken
              jsr abs:BOOT_b1Progress
              bra lzsaToken
lzsaDone:     jsr abs:BOOT_b1Progress
              phk
              plb
              lda abs:sharedDecode
              beq lzsaReturn
              jsr abs:ExpandSharedArt
lzsaReturn:   sep #0x20
              rts

;;; Base is 7 for literals or 18 for matches. Their extension markers
;;; differ by 11, so addition makes both short/word escapes 257 and 256.
lzsaLength:   sta dp:B1_CNT
stageP4:      lda long:BOOT_STAGE,x
              inx
              and ##255
              clc
              adc dp:B1_CNT
              cmp ##256
              bcc lzsaLengthDone
              beq lzsaWordLength
stageP5:      lda long:BOOT_STAGE,x
              inx
              and ##255
              ora ##256
              rts
lzsaWordLength:
stageP6:      lda long:BOOT_STAGE,x
              inx
              inx
lzsaLengthDone:
              rts

;;; Byte counts avoid per-bit lengths and offsets. The build chooses this
;;; representation only as part of a bounded read-plus-decode load budget.
;;; Bit 7 selects literals. A zero low count has a word extension. Matches
;;; have a signed word displacement. Both use forward-overlap MVN copies.
lz16Token:    inx
stageM2:      lda long:BOOT_STAGE-1,x
              and ##255
              beq lz16LongMatch
              cmp ##128
              bcs lz16Literal
lz16Match:    dec a
              sta dp:B1_CNT
stageP7:      lda long:BOOT_STAGE,x
              inx
              inx
              cmp ##0
              beq lz16Skip
              stx dp:B1_INP
              sty dp:B1_OFF
              clc
              adc dp:B1_OFF
              tax
              lda dp:B1_CNT
lz16MatchCopy:
              .byte 0x54, 0x00, 0x00
              ldx dp:B1_INP
lz16After:    cpy dp:B1_END
              beq lz16Done
              cpy dp:B1_NEXT
              bcc lz16Token
              jsr abs:BOOT_b1Progress
              bra lz16Token
lz16LongMatch:
stageP8:      lda long:BOOT_STAGE,x
              inx
              inx
              bra lz16Match
lz16Literal:  and ##127
              bne lz16LiteralReady
stageP9:      lda long:BOOT_STAGE,x
              inx
              inx
lz16LiteralReady:
              dec a
lz16LiteralCopy:
              .byte 0x54, 0x00, 0x1d
              bra lz16After
lz16Skip:     tya
              sec
              adc dp:B1_CNT
              tay
              bra lz16After
lz16Done:     jmp abs:lzsaDone
sharedDecode: .word 0

;;; Floor loads stage packed units in FLOOR_STAGE, in sound-effect RAM:
;;; bank $1D holds generated art. Auxiliary, music and probe reads use BOOT_STAGE.
;;; For a two-run load (leveldirectory.s planRuns), the episode-disk run uses
;;; FLOOR_STAGE until GenHook finishes, then EFFECT_STAGE: the final effects
;;; overwrite FLOOR_STAGE. The floor-disk run uses FLOOR_PART_STAGE so it can
;;; precede or follow the episode-disk run without losing unread input.
;;; Patches the stage bank of the decoders above. Native A16/X16, DBR=0.
              .public SelectStage, SetStageBank, GenHook, stageBank, stageStart
              .section floppystream, text, root
stageBank:    .word BOOT_STAGE >> 16
;;; The stage offset of the packed unit: 0, or for a unit that starts its own
;;; stage bank, the bank end minus its blocks (decoded in place; the build
;;; proves that no write reaches unread input).
stageStart:   .word 0
genActive:    .word 0
              .section leveldirectory, text, root, noreorder
SelectStage:  stz abs:streamBlocks
              stz abs:genActive
              stz abs:runSwitch            ; one run until planRuns sets two
              stz abs:runFill
              lda ##.byte2 BOOT_STAGE
              ldx abs:loadAux
              bne stageChosen
              ldx abs:loadMusic
              bne stageChosen
              ldx abs:loadProbe
              bne stageChosen
              lda ##.byte2 FLOOR_STAGE
;;; A = the stage bank.
SetStageBank:
stageChosen:  sta abs:stageBank
              sep #0x20
              ldx ##0
stagePatch:   ldy abs:stageSites,x
              sta abs:0,y
              inx
              inx
              cpx ##24
              bcc stagePatch
              dec a
stageMinus:   ldy abs:stageSites,x
              sta abs:0,y
              inx
              inx
              cpx ##30
              bcc stageMinus
              rep #0x20
              rts
stageSites:   .word stageP0+3, stageP1+3, stageP2+3, stageP3+3, stageP4+3, stageP5+3
              .word stageP6+3, stageP7+3, stageP8+3, stageP9+3
              .word lzsaLiteralCopy+2, lz16LiteralCopy+2
              .word stageM0+3, stageM1+3, stageM2+3

;;; After each unit: a unit at FIXED_GEN (floor art generator), WEAPON_COMP
;;; (weapon compiler) or SIGHT_GEN (sight unit) is load-time code;
;;; call it after that unit and every later one until it returns carry clear.
;;; Native A16/X16, DBR=0, D=0.
GenHook:      lda abs:genActive
              bne genCall
              lda dp:BOOT_SEGADDR+2
              and ##255
              cmp ##.byte2 FIXED_GEN
              bne genWeapon
              lda dp:BOOT_SEGADDR
              cmp ##.word0 FIXED_GEN
              bne genIdle
              bra genStart
genWeapon:    cmp ##.byte2 WEAPON_COMP
              bne genSight
              lda dp:BOOT_SEGADDR
              cmp ##.word0 WEAPON_COMP
              bne genIdle
              bra genStart
genSight:     cmp ##.byte2 SIGHT_GEN
              bne genIdle
              lda dp:BOOT_SEGADDR
              cmp ##.word0 SIGHT_GEN
              bne genIdle
genStart:     sta abs:genCall+1
              sep #0x20
              lda dp:BOOT_SEGADDR+2
              sta abs:genCall+3
              rep #0x20
              inc abs:genActive
genCall:      jsl long:FIXED_GEN
              rep #0x30
              bcs genIdle
              stz abs:genActive
              lda abs:genCall+3           ; the art generator is done: the units after it
              and ##255                   ; (the effects) cover FLOOR_STAGE, so they stage
              cmp ##.byte2 FIXED_GEN      ; in EFFECT_STAGE
              bne genIdle
              lda abs:genCall+1
              cmp ##.word0 FIXED_GEN
              bne genIdle
              lda ##.byte2 EFFECT_STAGE
              jsr abs:SetStageBank
genIdle:      rts
