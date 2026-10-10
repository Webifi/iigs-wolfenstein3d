;;; Stop the game and restore firmware before showing the original DOS quit page.
#include "memmap.inc"
#include "frontend.inc"
              .section menucode, text, root, noreorder
              .public DoQuit
              .extern UiFwPut, SoundStop, demoMode, timeDemo

ADBCMD        .equ DATAREG
ADBSTATUS     .equ KMSTATUS

;;; Never returns. ADB keyboard polling goes back to the micro: command 5 clears
;;; the mode bit that StartKeys set, command 1 follows it, as it does there.
DoQuit:       lda ##0
              sta long:demoMode
              sta long:timeDemo
              jsr abs:.word0 (SoundStop)
              SCREEN_ID 16
              sei
              jsl long:UiFwPut               ; the firmware's own state, for the interrupts it gets back
              ; ROM keyboard polling asks EMStatus. Its old workspace has been
              ; reused by the game; SetWAP marks the Event Manager inactive.
              pea #0                          ; system tool set
              pea #6                          ; Event Manager
              pea #0
              pea #0                          ; no work-area pointer
              ldx ##0x0d01                   ; Tool Locator SetWAP
              jsl long:BANK_E1               ; ROM tool dispatcher
              sep #0x20
              lda #0
              sta long:ADBSTATUS             ; no ADB interrupts any more
quitDrain:    lda long:ADBSTATUS
              and #0x20
              beq quitSend
              lda long:ADBCMD                ; old key data
              bra quitDrain
quitSend:     lda #5
              jsr abs:.word0 (quitCommand)
              lda #1
              jsr abs:.word0 (quitCommand)
              rep #0x30
              jmp long:UiQuitRom

quitCommand:  pha
quitWait:     lda long:ADBSTATUS
              lsr a
              bcs quitWait
              pla
              sta long:ADBCMD
              rts


              .section menucode, text, root, noreorder
              .public UiQuitRom, UiQuitTextCopy
              .extern UiQuitTextInit, UiQuitPrompt
              .extern J13Stop

UiQuitRom:    jsl long:J13Stop
              sei
              rep #0x30
              lda ##0
              tcd
              sep #0x30
              lda #0
              pha
              plb
              lda #0x08                      ; ROM visible, text-page shadowing enabled
              sta long:SHADOW
              sta long:SHADOW_00
              lda long:NEWVIDEO
              and #0x3f
              ora #0x40
              sta long:NEWVIDEO
              lda #0
              sta long:TXTSET
              sta long:TXTPAGE1
              lda #0xd1                      ; ROM text: yellow on red
              sta long:TBCOLOR
              lda long:BORDER
              and #0xf0
              ora #1
              sta long:BORDER
              jmp long:UiQuitTextInit

              .section menucode, text, root, noreorder
UiQuitTextCopy: sep #0x20
              lda #0
              sta long:SETALTCHAR
              rep #0x30
              ldx ##0
              stz abs:QUIT_ROW
quitRow:      phx
              ldx abs:QUIT_ROW
              lda long:quitRowOffset,x
              tay
              plx
              sep #0x20
              lda #40
              sta abs:QUIT_COLUMNS
quitColumn:   lda long:QUIT_TEXT,x
              phx
              tyx
              sta long:TEXT_AUX,x
              plx
              lda long:(QUIT_TEXT+40),x
              phx
              tyx
              sta long:TEXT_SCREEN,x
              plx
              inx
              iny
              dec abs:QUIT_COLUMNS
              bne quitColumn
              rep #0x21
              txa
              adc ##40
              tax
              lda abs:QUIT_ROW
              adc ##2
              sta abs:QUIT_ROW
              cmp ##42
              bcc quitRow
              jmp long:UiQuitPrompt
quitRowOffset:
              .word 0x000, 0x080, 0x100, 0x180, 0x200, 0x280, 0x300, 0x380
              .word 0x028, 0x0a8, 0x128, 0x1a8, 0x228, 0x2a8, 0x328, 0x3a8
              .word 0x050, 0x0d0, 0x150, 0x1d0, 0x250
