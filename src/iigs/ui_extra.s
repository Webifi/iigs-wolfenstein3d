#include "frontend.inc"
#include "campaign.inc"
              .section uiextra, text, root, noreorder

              .public ListLetterMatch
              .extern adbPlain
ListLetterMatch: cmp ##0x73
              beq jumpHome
              cmp ##0x77
              beq jumpEnd
              cmp ##0x74
              beq jumpPageUp
              cmp ##0x79
              beq jumpPageDown
              tax
              lda abs:.word0 (adbPlain),x
              and ##0x00df
              cmp ##'A'
              bcc letterMiss
              cmp ##'Z'+1
              bcs letterMiss
              sta dp:U_MORE
              lda dp:UL_CUR
              sta dp:U_T0
              lda dp:UL_COUNT
              sta dp:U_T1
letterNext:   inc dp:U_T0
              lda dp:U_T0
              cmp dp:UL_COUNT
              bcc letterIndex
              stz dp:U_T0
letterIndex:  ldy dp:U_T0
              lda (UL_ACT),y
              and ##255
              beq letterAgain
              tya
              asl a
              tay
              lda (UL_ITEMS),y
              sta dp:U_STR
              lda (U_STR)
              and ##0x00df
              cmp dp:U_MORE
              beq letterHit
letterAgain:  dec dp:U_T1
              bne letterNext
letterMiss:   clc
              rtl
letterHit:    lda dp:U_T0
              sec
              rtl

jumpHome:     lda ##0
              bra jumpForward
jumpEnd:      lda dp:UL_COUNT
              dec a
              bra jumpBackward
jumpPageUp:   lda dp:UL_CUR
              sec
              sbc dp:UL_VISIBLE
              bpl jumpBackward
              lda ##0
jumpBackward: sta dp:U_T0
              lda ##0xffff
              bra jumpScan
jumpPageDown: lda dp:UL_CUR
              clc
              adc dp:UL_VISIBLE
              cmp dp:UL_COUNT
              bcc jumpForward
              lda dp:UL_COUNT
              dec a
              bra jumpBackward
jumpForward:  sta dp:U_T0
              lda ##1
jumpScan:     sta dp:U_MORE
              lda dp:UL_COUNT
              sta dp:U_T1
jumpCheck:    ldy dp:U_T0
              lda (UL_ACT),y
              and ##255
              bne letterHit
              lda dp:U_T0
              clc
              adc dp:U_MORE
              bpl jumpNotLow
              lda dp:UL_COUNT
              dec a
jumpNotLow:   cmp dp:UL_COUNT
              bcc jumpInRange
              lda ##0
jumpInRange:  sta dp:U_T0
              dec dp:U_T1
              bne jumpCheck
              clc
              rtl
              .public ListFloorColumn
ListFloorColumn: ldx dp:UL_CUR
              cmp ##1
              bne floorColumnLeft
              lda long:floorRight,x
              bra floorColumnFound
floorColumnLeft: lda long:floorLeft,x
floorColumnFound: and ##255
              rtl
floorRight: .byte 4,5,6,6,7,8,9,0,1,2
floorLeft:  .byte 7,8,9,9,0,1,2,4,5,6

              .public MenuFunctionKey
MenuFunctionKey: cmp ##0x60
              bcc functionNone
              cmp ##0x79
              bcs functionNone
              sec
              sbc ##0x60
              tax
              lda long:functionKeys,x
              and ##255
              rtl
functionNone: lda ##0
              rtl
functionKeys: .byte 4,5,6,2,7,8,0,0,0,0,0,0,0,9,0,0,0,0,0,0,0,0,3,0,1

#include "steel-extra.inc"

;;; The Vsync setting changes only while painting is idle.
              .section uiextra, text, root, noreorder
              .public VsyncSet, vsyncOn
              .extern preparedAll, vsyncB
              .extern BufferVsyncSet, BufferLoad, BufferStore
VsyncSet:     jmp long:BufferVsyncSet
vsyncOn:      .word 0

              .public VsyncLoad, VsyncStore, VsyncToggle
              .extern J13SettingsLoad, J13SettingsStore
VsyncLoad:    jmp long:BufferLoad
VsyncStore:   jmp long:BufferStore
VsyncToggle:  lda long:vsyncOn
              eor ##1
              jmp abs:.word0 (VsyncSet)

#include "ui_preview_gray.inc"
