;;; Tally-page composition: portrait animation, large glyphs, and row palettes.
;;; tools/art_lumps.py packs the tally lump in the menu file. The decoded
;;; pieces occupy PAGE_STAGE; tally.s calls these entry points after a floor.
#include "memmap.inc"
#include "menu.inc"
#include "pages.inc"
#include "logic.inc"
              .section logiccode, text, root, noreorder
              .public TallyPage, TallyReveal, TallyChar, TallyBreathe
              .extern lumpTable, CopyMenuBlocks, WaitBlank, InitFlash, flowX, flowY, PublishTallyPals
              .extern PageEnter, PageLeave
              .extern LoadTallyAssets

;;; JSL, DBR = 2. The tint of a flash goes (it would write the colors of the view), the colors of the view go black,
;;; the pieces come into the staging area, rows 0-159 take the palette of each row and the color of the page, and BJ
;;; is drawn. TallyReveal puts the colors on when the letters are in.
TallyPage:    php
              rep #0x30
              phb
              jsl long:InitFlash
              phk
              plb
              lda ##0
              sta long:tallyCacheValid
              jsl long:TallyStage
              jsl long:WaitBlank
              lda ##0
              ldx ##30
tallyBlack0:  sta long:SHR_PAL,x
              dex
              dex
              bpl tallyBlack0
              ldx ##62
tallyBlack13: sta long:SHR_PAL+0x1a0,x           ; palettes 13 and 14
              dex
              dex
              bpl tallyBlack13
              ldx ##PAGE_STAGE + TALLY_SCB
              ldy ##0x9d00
              lda ##159
              phb
              .byte 0x54, 0xe1, PAGE_STAGE_BANK        ; MVN: bank $41 to bank $E1
              plb
              lda ##TALLY_FILL * 257
              ldx ##0
tallyFill:    sta long:SHR,x
              inx
              inx
              cpx ##25600
              bcc tallyFill
              ldx ##PAGE_STAGE + TALLY_BJ1
              ldy ##0x2000 + 16 * 160
              lda ##88
              sta long:tallyRows
tallyBJ:      lda ##51
              phb
              .byte 0x54, 0xe1, PAGE_STAGE_BANK
              plb
              tya
              clc
              adc ##160 - 52
              tay
              lda long:tallyRows
              dec a
              sta long:tallyRows
              bne tallyBJ
              plb
              plp
              rtl

;;; JSL. The colors of the page, at the blank: palette 0, then 13 and 14.
TallyReveal:  php
              rep #0x30
              jsl long:PublishTallyPals
              plp
              rtl

;;; JSL with A = character, flowX even, flowY = screen row. Glyphs advance
;;; flowX by 16 pixels, or 8 for ! and :. Supported glyphs are 0-9, A-Z, :,
;;; % and !; unsupported characters advance without drawing.
TallyChar:    jsl long:TallyStage
              php
              rep #0x30
              phb
              phk
              plb
              and ##255
              sta long:tallyChar
              lda ##16
              sta long:tallyAdvance
              lda long:tallyChar
              cmp ##'%'
              bne charNotPercent
              lda ##37
              bra charGlyph
charNotPercent:
              cmp ##'!'
              bne charNotBang
              lda ##8
              sta long:tallyAdvance
              lda ##38
              bra charGlyph
charNotBang:  cmp ##':'
              bne charNotColon
              lda ##8
              sta long:tallyAdvance
              lda ##36
              bra charGlyph
charNotColon: cmp ##'0'
              bcc charAway
              cmp ##'9' + 1
              bcc charDigit
              cmp ##'A'
              bcc charAway
              cmp ##'Z' + 1
              bcs charAway
              sec
              sbc ##'A' - 10
              bra charGlyph
charAway:     jmp abs:.word0 (charSkip)
charDigit:    sec
              sbc ##'0'
charGlyph:    asl a
              tax
              lda long:SNAP_PIX + PAGE_STAGE + TALLY_GLYPHS,x
              clc
              adc ##PAGE_STAGE
              sta long:tallySource
              lda long:flowY
              asl a
              asl a
              asl a
              asl a
              asl a
              sta long:tallyRows              ; 32 a row
              asl a
              asl a
              clc
              adc long:tallyRows              ; 160 a row
              sta long:tallyRows
              lda long:flowX
              lsr a
              clc
              adc long:tallyRows
              clc
              adc ##0x2000
              sta long:tallyDest
              lda ##16
              sta long:tallyRows
charRow:      lda long:tallySource
              tax
              lda long:tallyDest
              tay
              lda long:tallyAdvance
              lsr a
              dec a                           ; the bytes of a row, less 1
              phb
              .byte 0x54, 0xe1, PAGE_STAGE_BANK
              plb
              txa
              sta long:tallySource
              lda long:tallyDest
              clc
              adc ##160
              sta long:tallyDest
              lda long:tallyRows
              dec a
              sta long:tallyRows
              bne charRow
charSkip:     lda long:flowX
              clc
              adc long:tallyAdvance
              sta long:flowX
              plb
              plp
              rtl

;;; JSL. A = 1: the part of BJ's second picture that differs from the first, 0: the first picture again.
TallyBreathe: jsl long:TallyStage
              php
              rep #0x30
              phb
              phk
              plb
              cmp ##0
              bne breatheSecond
              ldx ##PAGE_STAGE + TALLY_BJ1 + TALLY_BJ2_Y * 52 + TALLY_BJ2_X
              lda ##52 - TALLY_BJ2_W        ; the rest of a row of the first picture
              bra breatheGo
breatheSecond:
              ldx ##PAGE_STAGE + TALLY_BJ2
              lda ##0
breatheGo:    sta long:tallySkip
              ldy ##0x2000 + (16 + TALLY_BJ2_Y) * 160 + TALLY_BJ2_X
              lda ##TALLY_BJ2_H
              sta long:tallyRows
breatheRow:   lda ##TALLY_BJ2_W - 1
              phb
              .byte 0x54, 0xe1, PAGE_STAGE_BANK
              plb
              txa
              clc
              adc long:tallySkip
              tax
              tya
              clc
              adc ##160 - TALLY_BJ2_W
              tay
              lda long:tallyRows
              dec a
              sta long:tallyRows
              bne breatheRow
              plb
              plp
              rtl

              .section gamedata, data, root
tallyChar:    .word 0
tallyAdvance: .word 0
tallySource:  .word 0
tallyDest:    .word 0
tallyRows:    .word 0
tallySkip:    .word 0

;;; Menu capture invalidates the disposable intermission staging. Restore it
;;; only when the tally next needs a glyph or breathing pose.
              .section logiccode, text, root, noreorder
              .public tallyCacheValid
TallyStage:   php
              rep #0x30
              pha
              phx
              phy
              phb
              lda long:tallyCacheValid
              bne tallyStageReady
              jsl long:LoadTallyAssets      ; the lump's own group: no UI group (disk 1) after a floor
              lda ##1
              sta long:tallyCacheValid
tallyStageReady: plb
              ply
              plx
              pla
              plp
              rtl
tallyCacheValid: .word 0
