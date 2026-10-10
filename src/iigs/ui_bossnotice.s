#include "logic.inc"
;;; JSL with gameplay paused, initialized UI fonts, and no active disk prompt.
;;; Display STR_SEEAGAIN for 300 game tics or a fresh menu key, then restore
;;; the covered pixels. D, DB, P, A, X, Y and the UI direct page are preserved.
;;; Uses the existing aligned loading-box ink; no palette or HUD writes.
#include "frontend.inc"
              .section registeredmenu, text, root, noreorder
              .public RegisteredDeathNotice
              .extern UiEnterCore, UiLeaveCore, UiTime, PollKey, DrawStrCenter
              .extern SaveBox, RestoreBox, BusyHoldPal, BusyReleasePal
              .extern BusySaveRows, BusyRestoreRows, BusyBegin, BusyPanel, BusyEndDraw
              .extern EndUpdate, WaitBlank, busyKind, busyDark, busyShown

RegisteredDeathNotice:
              php
              rep #0x30
              pha
              phx
              phy
              phb
              phd
              phk
              plb
              jsr abs:.word0 (UiEnterCore)
              jsl long:BusyHoldPal
              stz abs:.word0 (busyDark)
              lda ##1
              sta abs:.word0 (busyKind)
              jsr abs:.word0 (noticeBounds)
              jsr abs:.word0 (SaveBox)
              jsl long:BusySaveRows
              jsr abs:.word0 (noticeBounds)
              jsl long:BusyBegin
              jsl long:BusyPanel
              lda ##.word0 (noticeText)
              sta dp:U_STR
              lda ##160
              sta dp:U_X
              lda ##94
              sta dp:U_Y
              stz dp:U_FONT
              lda ##C_GRAY
              sta dp:U_C
              jsr abs:.word0 (DrawStrCenter)
              jsl long:BusyEndDraw
              jsl long:EndUpdate
              lda ##1
              sta abs:.word0 (busyShown)
              jsr abs:.word0 (UiTime)
              sta abs:.word0 (noticeStart)
noticeWait:   jsr abs:.word0 (PollKey)
              cmp ##65535
              bne noticeDone
              jsr abs:.word0 (UiTime)
              sec
              sbc abs:.word0 (noticeStart)
              cmp ##300
              bcc noticeWait
noticeDone:   jsl long:WaitBlank
              jsr abs:.word0 (noticeBounds)
              jsr abs:.word0 (RestoreBox)
              jsl long:BusyRestoreRows
              jsl long:BusyReleasePal
              stz abs:.word0 (busyShown)
              jsr abs:.word0 (UiLeaveCore)
              pld
              plb
              ply
              plx
              pla
              plp
              rtl

noticeBounds: lda ##BOX_X
              sta dp:U_X
              lda ##BOX_Y
              sta dp:U_Y
              lda ##BOX_W
              sta dp:U_W
              lsr a
              sta dp:U_WB
              lda ##BOX_H
              sta dp:U_H
              rts


noticeStart:  .word 0
noticeText:   .asciz "Let's see that again!"

