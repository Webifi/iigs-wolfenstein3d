;;; A zero menu-cache entry is an ending page range in WOLF.MENU: one LZSA1
;;; stream per range that PageShow and PageGray read (coldParts, written by
;;; tools/build_menu_cache.py). The stream loads into the STAGE snapshot
;;; after its first block and decodes to the caller's destination.
;;; Keep the caller's UI page: firmware prompts use its scratch words.
;;; WOLF.MENU is on the home disk; the completed episode leaves it mounted for
;;; its following pages/menu.

              .section registeredmenu, text, root, noreorder
              .public ReadColdMenuBlocks
ReadColdMenuBlocks:
              phb
              phk
              plb
              lda dp:U_BLK
              sta abs:.word0 (coldFirst)
              lda dp:U_CNT
              sta abs:.word0 (coldCount)
              lda dp:U_DOFF
              sta abs:.word0 (coldOffset)
              lda dp:U_DBNK
              sta abs:.word0 (coldBank)
              ldx ##UI_DP
              ldy ##.word0 (coldPage)
              lda ##255
              .byte 0x54, 0x3f, 0x00
              phk
              plb
              jsr abs:.word0 (NeedHomeDisk)
              bcs coldFailed
              lda long:HDR_MENU
              beq coldFailed
              ldx ##0
coldFind:     lda abs:.word0 (coldParts),x
              cmp ##0xffff
              beq coldFailed
              cmp abs:.word0 (coldFirst)
              bne coldNext
              lda abs:.word0 (coldParts+2),x
              cmp abs:.word0 (coldCount)
              beq coldFound
coldNext:     txa
              clc
              adc ##10
              tax
              bra coldFind
coldFound:    lda abs:.word0 (coldParts+6),x
              clc
              adc ##COLD_BUFFER
              sta abs:.word0 (coldSource)
              lda abs:.word0 (coldParts+4),x
              clc
              adc abs:.word0 (coldParts+8),x
              cmp long:HDR_MENUN
              bcc coldBounds
              beq coldBounds
              bra coldFailed
coldBounds:   lda abs:.word0 (coldParts+4),x
              clc
              adc long:HDR_MENU
              bcs coldFailed
              sta dp:U_BLK
              lda abs:.word0 (coldParts+8),x
              sta dp:U_CNT
              lda ##COLD_BUFFER
              sta dp:U_DOFF
              lda ##COLD_BANK
              sta dp:U_DBNK
;;; Pixels can replace the saved loading-box area during this transfer.
;;; Disk-change prompts finish first; do not restore an old box over new art.
              lda ##1
              sta dp:U_NOSIGN
              jsr abs:.word0 (ReadBlocks)
              bcs coldFailed
              stz abs:.word0 (diskHeld)
              jsr abs:.word0 (coldDecode)
              lda dp:U_T0
              sta abs:.word0 (coldOffset)
              lda ##0
              sta abs:.word0 (coldError)
              bra coldRestore
coldFailed:   jsr abs:.word0 (ReleaseDisk)
              lda ##1
              sta abs:.word0 (coldError)
coldRestore:  ldx ##.word0 (coldPage)
              ldy ##UI_DP
              lda ##255
              .byte 0x54, 0x00, 0x3f
              phk
              plb
              lda abs:.word0 (coldError)
              bne coldReturnBad
              lda abs:.word0 (coldFirst)
              clc
              adc abs:.word0 (coldCount)
              sta dp:U_BLK
              stz dp:U_CNT
              lda abs:.word0 (coldOffset)
              sta dp:U_DOFF
              plb
              clc
              rtl
coldReturnBad:plb
              sec
              rtl

;;; The LZSA1 stream at COLD_BANK:coldSource -> coldBank:coldOffset, coldCount
;;; blocks (the loader's decoder in load_fast.inc). U_T0 = the output end.
coldDecode:   sep #0x20
              lda abs:.word0 (coldBank)
              sta abs:.word0 (cdLiteral+1)
              sta abs:.word0 (cdMatch+1)
              sta abs:.word0 (cdMatch+2)
              rep #0x20
              lda abs:.word0 (coldCount)
              xba
              asl a
              clc
              adc abs:.word0 (coldOffset)
              sta dp:U_T0
              ldx abs:.word0 (coldSource)
              ldy abs:.word0 (coldOffset)
cdToken:      lda long:COLD_BANK*0x10000,x
              inx
              and ##255
              sta dp:U_T1
              lsr a
              lsr a
              lsr a
              lsr a
              and ##7
              cmp ##7
              bne cdLiterals
              jsr abs:.word0 (cdLength)
cdLiterals:   cmp ##0
              beq cdAfter
              dec a
cdLiteral:    .byte 0x54, 0x00, COLD_BANK
cdAfter:      cpy dp:U_T0
              beq cdDone
              lda dp:U_T1
              bit ##128
              beq cdShort
              lda long:COLD_BANK*0x10000,x
              inx
              inx
              bra cdOffset
cdShort:      lda long:COLD_BANK*0x10000,x
              inx
              ora ##0xff00
cdOffset:     sta dp:U_T2
              lda dp:U_T1
              and ##15
              clc
              adc ##3
              cmp ##18
              bne cdMatchLength
              jsr abs:.word0 (cdLength)
cdMatchLength:dec a
              stx dp:U_T3
              pha
              tya
              clc
              adc dp:U_T2
              tax
              pla
cdMatch:      .byte 0x54, 0x00, 0x00
              ldx dp:U_T3
              bra cdToken
cdDone:       phk
              plb
              rts

;;; Base is 7 for literals or 18 for matches. Their extension markers
;;; differ by 11, so addition makes both short/word escapes 257 and 256.
cdLength:     sta dp:U_T4
              lda long:COLD_BANK*0x10000,x
              inx
              and ##255
              clc
              adc dp:U_T4
              cmp ##256
              bcc cdLengthDone
              beq cdWordLength
              lda long:COLD_BANK*0x10000,x
              inx
              and ##255
              ora ##256
              rts
cdWordLength: lda long:COLD_BANK*0x10000,x
              inx
              inx
cdLengthDone: rts

              .section registeredmenudata, data, root
coldFirst:    .word 0
coldCount:    .word 0
coldOffset:   .word 0
coldBank:     .word 0
coldSource:   .word 0
coldError:    .word 0
coldPage:     .space 256
#include "memmap.inc"
#include "menu-parts.inc"
