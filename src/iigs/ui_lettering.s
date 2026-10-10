#include "memmap.inc"
#include "frontend.inc"
;;; Lettering stays in the menu bank. The game banks have no room for it.
              .section menucode, text, root, noreorder
              .public DrawTitleCore, DrawCursorCore, DrawTitleBanked
              .extern fadeBase, screenBlack, DrawWordBlock, TitleGray, nativeRecord, nativeBank, BindAddr

;;; U_SRC is a resident lettering record; U_Y is the first row.
              .extern updatePalette
DrawTitleCore:
              lda ##1
              sta long:updatePalette
              lda ##0xffff
              sta dp:U_X
DrawCursorCore:
              phb
              lda ##0x3f
              sta dp:W_PTR+2
              lda dp:U_SRC
              cmp ##.word0 (UI_STAGE+0x1800)
              bne htResident
              lda long:nativeBank
              beq htResident
              sta dp:W_PTR+2
              lda long:nativeRecord
              sta dp:U_SRC
              bra htResident
;;; U_SRC and W_PTR+2 select a temporary record; U_X/U_Y give its position.
DrawTitleBanked:
              phb
htResident:   sep #0x20
              lda dp:W_PTR+2
              pha
              plb
              rep #0x20
              lda dp:U_Y
              sta dp:HT_Y
              ldy dp:U_SRC
              lda abs:0,y
              sta dp:U_W
              lda ##320
              sec
              sbc dp:U_W
              lsr a
              sta dp:HT_X
              lda dp:U_X
              bmi htCenter
              sta dp:HT_X
htCenter:     lda abs:2,y
              sta dp:HT_ROWS
              lda abs:4,y
              sta dp:HT_BANDS
              tya
              clc
              adc ##6
              tay
              lda dp:HT_BANDS
              bne htBand
              jmp abs:.word0 (htRow)
htBand:       sty dp:HT_PTR
              lda abs:0,y
              and ##255
              clc
              adc dp:HT_Y
              tax
              lda abs:1,y
              and ##255
              clc
              adc dp:HT_Y
              sta dp:HT_ROW
              lda abs:2,y
              and ##255
              sta dp:HT_INK
              sep #0x20
htScb:
titleTargetSCB: sta long:SHR_SCB,x
              inx
              cpx dp:HT_ROW
              bcc htScb
              rep #0x20
              lda dp:HT_INK
              asl a
              asl a
              asl a
              asl a
              asl a
              tax
              iny
              iny
              iny
              iny
              lda ##16
              sta dp:HT_COLS
htColors:     lda abs:0,y
              sta long:fadeBase,x
              pha
              lda long:screenBlack
              bne htHidden
              pla
              sta long:SHR_PAL,x
              bra htColorNext
htHidden:     pla
htColorNext:
              iny
              iny
              inx
              inx
              dec dp:HT_COLS
              bne htColors
              jsl long:TitleGray
              phy
              lda abs:12,y
              pha
              sep #0x20
              lda abs:14,y
              rep #0x20
              and ##255
              tay
              lda dp:HT_INK
              and ##15
              tax
              pla
              jsl long:BindAddr
              ply
              tya
              clc
              adc ##16
              tay
              dec dp:HT_BANDS
              beq htRow
              jmp abs:.word0 (htBand)
htRow:        tya
              sta dp:HT_PTR
              lda dp:HT_X
              and ##1
              asl a
              clc
              adc dp:HT_PTR
              tay
              lda abs:0,y
              clc
              adc dp:HT_PTR
              tax
              lda dp:HT_Y
              sta dp:HT_ROW
              asl a
              asl a
              clc
              adc dp:HT_ROW
              asl a
              asl a
              asl a
              asl a
              asl a
              sta dp:W_BASE
              lda dp:HT_X
              lsr a
              clc
              adc dp:W_BASE
              sta dp:W_BASE
              lda dp:U_C
              pha
              stz dp:U_C
              jsl long:DrawWordBlock
              pla
              sta dp:U_C
htDone:       plb
              rtl

              .public titleTargetSCB
