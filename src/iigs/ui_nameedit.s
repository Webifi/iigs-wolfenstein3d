#include "frontend.inc"
              .public AskSlotName
              .extern SlotName, slotNameBuf, slotCur, editorName, nameLine, nameLen
              .extern nameShift, nameCaps, nameCursor, listInk, adbPlain, adbShift
              .extern NamePollKey, NameOutStr, NameDrawStr, NameStrWidth
              .extern BeginUpdate, EndUpdate
NOKEY         .equ 0xffff
LS_X          .equ 40
LS_Y          .equ 48
              .section uiextra, text, root, noreorder
;;; The name of slotCur. Carry clear when Return accepts it, set when Esc cancels.
AskSlotName:  stz abs:.word0 (nameShift)
              stz abs:.word0 (nameCaps)
              lda abs:.word0 (slotCur)
              jsl long:SlotName
              ldy ##0
askCopy:      sep #0x20
              lda abs:.word0 (slotNameBuf),y
              sta abs:.word0 (editorName),y
              beq askCopied
              rep #0x20
              iny
              cpy ##31
              bcc askCopy
              sep #0x20
              lda #0
              sta abs:.word0 (editorName),y
askCopied:    rep #0x20
              sty abs:.word0 (nameLen)
              jsr abs:.word0 (nameDraw)
askLoop:      jsl long:NamePollKey
              cmp ##NOKEY
              beq askLoop
              sta dp:U_KEY
              and ##0x7f
              sta dp:U_T0
              cmp ##0x38
              beq askShift
              cmp ##0x7b
              beq askShift
              cmp ##0x39
              beq askCaps
              lda dp:U_KEY
              bit ##0x80
              bne askLoop
              lda dp:U_T0
              cmp ##K_RETURN
              beq askAccept
              cmp ##K_ENTER
              beq askAccept
              cmp ##K_ESC
              beq askCancel
              cmp ##K_DELETE
              beq askBack
              jsr abs:.word0 (askChar)
              bra askLoop
askShift:     lda dp:U_KEY
              and ##0x80
              eor ##0x80
              sta abs:.word0 (nameShift)
              bra askLoop
askCaps:      lda dp:U_KEY
              and ##0x80
              eor ##0x80
              sta abs:.word0 (nameCaps)
              bra askLoop
askBack:      lda abs:.word0 (nameLen)
              beq askLoop
              dec a
              sta abs:.word0 (nameLen)
              tay
              sep #0x20
              lda #0
              sta abs:.word0 (editorName),y
              rep #0x20
              jsr abs:.word0 (nameDraw)
              bra askLoop
askCancel:    sec
              rtl
askAccept:    clc
              rtl

;;; U_T0 is a raw key. It joins the name when the row still fits in 272 pixels.
askChar:      ldx dp:U_T0
              sep #0x20
              lda abs:.word0 (adbPlain),x
              rep #0x20
              and ##255
              beq askNone
              sta dp:U_T1
              cmp ##'a'
              bcc askNotLetter
              cmp ##'z' + 1
              bcs askNotLetter
              lda abs:.word0 (nameShift)
              eor abs:.word0 (nameCaps)
              bra askPick
askNotLetter: lda abs:.word0 (nameShift)
askPick:      beq askAdd
              ldx dp:U_T0
              sep #0x20
              lda abs:.word0 (adbShift),x
              rep #0x20
              and ##255
              sta dp:U_T1
askAdd:       lda abs:.word0 (nameLen)
              cmp ##31
              bcs askNone
              tay
              sep #0x20
              lda dp:U_T1
              sta abs:.word0 (editorName),y
              lda #0
              sta abs:.word0 (editorName + 1),y
              rep #0x20
              jsr abs:.word0 (nameMeasure)
              cmp ##272
              bcc askFits
              ldy abs:.word0 (nameLen)
              sep #0x20
              lda #0
              sta abs:.word0 (editorName),y
              rep #0x20
              rts
askFits:      inc abs:.word0 (nameLen)
              jsr abs:.word0 (nameDraw)
askNone:      rts

;;; The cursor is included in the editor width limit.
nameMeasure:  lda ##.word0 (nameLine)
              sta dp:U_OUT
              lda ##.word0 (editorName)
              sta dp:U_STR
              jsl long:NameOutStr
              lda ##.word0 (nameCursor)
              sta dp:U_STR
              jsl long:NameOutStr
              lda ##.word0 (nameLine)
              sta dp:U_STR
              stz dp:U_FONT
              jsl long:NameStrWidth
              rts

;;; The selected row, the name and a cursor.
nameDraw:     jsr abs:.word0 (nameMeasure)
              lda abs:.word0 (slotCur)
              asl a
              asl a
              asl a
              asl a
              sec
              sbc abs:.word0 (slotCur)
              clc
              adc ##LS_Y
              pha
              dec a
              sta dp:U_Y
              lda ##LS_X - 1
              and ##0xfffc
              sta dp:U_X
              lda ##272 + 7
              and ##0xfffc
              sta dp:U_W
              lda ##10
              sta dp:U_H
              jsl long:BeginUpdate
              pla
              sta dp:U_Y
              lda ##LS_X
              sta dp:U_X
              lda ##.word0 (nameLine)
              sta dp:U_STR
              stz dp:U_FONT
              stz abs:.word0 (listInk)
              lda ##C_WHITE
              sta dp:U_C
              jsl long:NameDrawStr
              jsl long:EndUpdate
              rts
