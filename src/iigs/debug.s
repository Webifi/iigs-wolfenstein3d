;;; DOS cheat chords are examined only on a new key-down event. Cold code lives
;;; in slow RAM; idle input and disabled god/noclip/delay paths remain unchanged.
#include "memmap.inc"
#include "game.inc"
#include "logic.inc"
#include "logic_dp.inc"
#include "frontend.inc"
#include "campaign.inc"
              .section debugcode, text, root, noreorder
              .public DebugKey, DebugDispatch, DebugMenuEntry, DebugWait
              .public debugAction, debugGod, debugNoclip, debugSlow, debugVbls
              .public DebugSetText, DebugAppendText, DebugNumber, DebugChar, DebugDialog, DebugAck
              .public debugWarpFloor
              .extern keyHeld, keyChars, demoMode, levelState, uiGameOn
              .extern DebugLogic, DebugTryMove, debugClipCall, TryMove, debugDamageOp
              .extern debugFrameJump, DebugFrame, frameLoop, DebugClockReset
              .extern DebugOpen, DebugWarp, DebugHUD, UiResetInput, UiPublishGame
              .extern levelStart, levelIndex, I_GetTime
              .extern MenuOpen, MenuDimOpen, MenuDimClose, DebugUiCall, menuDim, benchFresh
              .extern adbPlain, DebugCounts, DebugFacing, DebugMemory, DebugShapes
#ifdef WOLF_SPEAR
              .extern debugOuchOp, PlaySound
#include "logic_sounds.inc"
#endif

;;; A8, X16 = raw ADB key. Return the original action, or $FE for a cheat.
DebugKey:     php
              rep #0x30
              phx
              phy
              lda long:demoMode
              ora long:levelState
              ora long:LOGIC_BASE+V_playstate
              ora long:LOGIC_BASE+V_victoryflag
              beq debugLiveKey
              jmp abs:.word0 (debugKeyNormal)
debugLiveKey: sep #0x20
              lda long:keyHeld+0x2e
              beq debugTestBAT
              lda long:keyHeld+0x25
              beq debugTestBAT
              lda long:keyHeld+0x22
              beq debugTestBAT
              lda #1
              bra debugKeyFound
debugTestBAT: lda long:keyHeld+0x0b
              beq debugTestEnable
              lda long:keyHeld
              beq debugTestEnable
              lda long:keyHeld+0x11
              beq debugTestEnable
              lda #2
              bra debugKeyFound
debugTestEnable:
              lda long:keyHeld+0x33
              beq debugTestTab
              lda long:keyHeld+0x38
              beq debugTestTab
              lda long:keyHeld+0x3a
              beq debugTestTab
              lda #3
              bra debugKeyFound
debugTestTab: lda long:keyHeld+0x30
              beq debugKeyNormal
#ifdef WOLF_SPEAR
              lda long:keyHeld+5
              beq debugTabScan
              lda long:keyHeld+0x6d
              beq debugTabScan
              lda #0xc7
              bra debugKeyFound
#endif
debugTabScan: ldx ##0
debugTabNext: phx
              lda long:debugRaw,x
              rep #0x20
              and ##255
              tax
              sep #0x20
              lda long:keyHeld,x
              plx
              cmp #0
              bne debugTabFound
              inx
              cpx ##18
              bcc debugTabNext
              bra debugKeyNormal
debugTabFound:
              lda long:debugAscii,x
#ifndef WOLF_SPEAR
              cmp #'N'
              beq debugKeyNormal
#endif
debugKeyFound:rep #0x20
              and ##255
              sta long:debugAction
debugKeyNormal:
              rep #0x30
              ply
              plx
              plp
              lda long:debugAction
              bne debugKeyPending
#ifdef WOLF_SPEAR
              cpx ##0x6d
              bne debugOrdinaryKey
              lda long:keyHeld+0x30
              beq debugOrdinaryKey
              lda #0                      ; keep Tab+F10 held until G completes the chord
              rtl
debugOrdinaryKey:
#endif
              lda long:keyChars,x
              rtl
debugKeyPending:
              lda #0xfe
              rtl

debugRaw:     .byte 0x0b,8,0x0e,3,5,4,0x22,0x2e,0x2d,0x23,0x0c,1,0x11,9,0x0d,7,0x7f,0x7f
debugAscii:   .ascii "BCEFGHIMNPQSTVWX"
              .byte 0,0

;;; Caller is the live input action path, DBR=2 and D=GAME_DP.
DebugDispatch:
              php
              rep #0x30
              pha
              phx
              phy
              lda long:debugAction
              cmp ##'E'
              beq debugImmediate
              cmp ##'H'
              beq debugImmediate
              cmp ##1
              beq debugInventory
              cmp ##'I'
              bne debugOpenDialog
debugInventory:
              jsl long:DebugLogic
              jsl long:UiPublishGame
              jsl long:DebugHUD
debugOpenDialog:
              jsl long:DebugOpen
              lda long:debugWarpFloor
              cmp ##65535
              beq debugDispatchDone
              jsl long:DebugWarp
              bra debugDispatchDone
debugImmediate:
              jsl long:DebugLogic
              jsl long:UiPublishGame
              jsl long:UiResetInput
debugDispatchDone:
              lda ##0
              sta long:debugAction
              lda ##65535
              sta long:debugWarpFloor
              ply
              plx
              pla
              plp
              rtl

;;; UiOpen supplies pause timing, input cleanup and the resumed game view.
DebugMenuEntry:
              lda long:debugAction
              bne debugMenu
              jmp long:MenuOpen
debugMenu:    php
              rep #0x30
              phb
              phd
              pea #0x3f3f
              plb
              plb
              lda ##0
              sta long:menuDim
              sta long:benchFresh
              ldx ##0
              jsl long:DebugUiCall
              lda ##1
              sta long:uiGameOn
              lda long:debugAction
              cmp ##'P'
              bne debugDim
              jsr abs:.word0 (debugPicture)
              ldx ##10
              jsl long:DebugUiCall
              bra debugMenuOut
debugDim:     jsl long:MenuDimOpen
              jsr abs:.word0 (debugCommand)
              lda ##0
              jsl long:MenuDimClose
              ldx ##2
              jsl long:DebugUiCall
debugMenuOut: pld
              plb
              plp
              rtl

debugCommand: lda long:debugAction
              cmp ##1
              bne debugNotMLI
              lda long:levelStart
              sec
              sbc ##42000
              sta long:levelStart
              lda long:levelStart+2
              sbc ##0
              sta long:levelStart+2
              lda ##.word0 (debugMliText)
              jmp abs:.word0 (debugNote)
debugNotMLI:  cmp ##2
              bne debugNotBAT
              lda ##.word0 (debugBatText)
              jmp abs:.word0 (debugNote)
debugNotBAT:  cmp ##3
              bne debugNotEnable
              lda ##.word0 (debugEnableText)
              jmp abs:.word0 (debugNote)
debugNotEnable:
              cmp ##'G'
              beq debugGodToggle
#ifdef WOLF_SPEAR
              cmp ##0xc7
              beq debugGodToggle
#endif
              cmp ##'I'
              bne debugNotItems
              lda ##.word0 (debugItemText)
              jmp abs:.word0 (debugNote)
debugNotItems:cmp ##'N'
              bne debugNotClip
              jmp abs:.word0 (debugClipToggle)
debugNotClip:
              cmp ##'S'
              bne debugBranchSkip0
              jmp abs:.word0 (debugSlowToggle)
debugBranchSkip0:
              cmp ##'B'
              bne debugBranchSkip1
              jmp abs:.word0 (debugBorder)
debugBranchSkip1:
              cmp ##'V'
              bne debugBranchSkip2
              jmp abs:.word0 (debugExtraVbl)
debugBranchSkip2:
              cmp ##'W'
              bne debugNotWarp
              jmp abs:.word0 (debugWarp)
debugNotWarp: cmp ##'Q'
              bne debugNotQuit
              ldx ##8
              jsl long:DebugUiCall
debugNotQuit: cmp ##'C'
              bne debugNotCounts
              jsl long:DebugCounts
              rts
debugNotCounts:
              cmp ##'F'
              bne debugNotFacing
              jsl long:DebugFacing
              rts
debugNotFacing:
              cmp ##'M'
              bne debugNotMemory
              jsl long:DebugMemory
              rts
debugNotMemory:
              cmp ##'T'
              bne debugNotShapes
              jsl long:DebugShapes
              rts
debugNotShapes:
              lda ##.word0 (debugExtraText)
              jmp abs:.word0 (debugNote)

debugGodToggle:
              lda long:debugGod
              eor ##1
              sta long:debugGod
              beq debugGodOff
              lda ##0xeaea
              sta long:debugDamageOp
#ifdef WOLF_SPEAR
              lda ##65535
              sta long:debugOuchOp+1
#endif
              lda ##.word0 (debugGodOnText)
              bra debugGodMessage
debugGodOff:  lda ##0xe5+(L_DAMAGE*256)
              sta long:debugDamageOp
#ifdef WOLF_SPEAR
              lda ##31
              sta long:debugOuchOp+1
#endif
              lda ##.word0 (debugGodOffText)
debugGodMessage:
              pha
#ifdef WOLF_SPEAR
              jsr abs:.word0 (debugGodFaceSwap)
#endif
#ifdef WOLF_SPEAR
              lda long:debugAction
              cmp ##0xc7
              bne debugGodSilent
              lda long:debugGod
              beq debugGodOffSound
              lda ##ENDBONUS2SND
              bra debugGodSound
debugGodOffSound:
              lda ##NOBONUSSND
debugGodSound:jsl long:PlaySound
debugGodSilent:
#endif
              pla
              jmp abs:.word0 (debugNote)

debugClipToggle:
              lda long:debugNoclip
              eor ##1
              sta long:debugNoclip
              beq debugClipOff
              lda ##.word0 (DebugTryMove)
              sta long:debugClipCall+1
              lda ##.word0 (debugClipOnText)
              jmp abs:.word0 (debugNote)
debugClipOff: lda ##.word0 (TryMove)
              sta long:debugClipCall+1
              lda ##.word0 (debugClipOffText)
              jmp abs:.word0 (debugNote)

debugSlowToggle:
              lda long:debugSlow
              eor ##1
              sta long:debugSlow
              jsr abs:.word0 (debugDelayPatch)
              lda long:debugSlow
              beq debugSlowOff
              lda ##.word0 (debugSlowOnText)
              jmp abs:.word0 (debugNote)
debugSlowOff: lda ##.word0 (debugSlowOffText)
              jmp abs:.word0 (debugNote)

debugBorder:  lda ##.word0 (debugBorderText)
              jsr abs:.word0 (debugNumberInput)
              bcs debugCommandDone
              cmp ##16
              bcs debugCommandDone
              sep #0x20
              sta long:debugBorderColor
              lda long:BORDER
              and #0xf0
              ora long:debugBorderColor
              sta long:BORDER
              rep #0x20
              rts
debugExtraVbl:
              lda ##.word0 (debugVblText)
              jsr abs:.word0 (debugNumberInput)
              bcs debugCommandDone
              cmp ##9
              bcs debugCommandDone
              sta long:debugVbls
              jmp abs:.word0 (debugDelayPatch)
debugWarp:    lda ##.word0 (debugWarpText)
              jsr abs:.word0 (debugNumberInput)
              bcs debugCommandDone
              cmp ##1
              bcc debugCommandDone
#ifdef WOLF_SPEAR
              cmp ##22
#else
              cmp ##11
#endif
              bcs debugCommandDone
              dec a
              pha
#ifndef WOLF_SPEAR
              lda long:levelIndex
debugEpisode: cmp ##10
              bcc debugEpisodeFound
              sbc ##10
              bra debugEpisode
debugEpisodeFound:
              sta long:debugValue
              lda long:levelIndex
              sec
              sbc long:debugValue
              sta long:debugValue
              pla
              clc
              adc long:debugValue
#else
              pla
#endif
              sta long:debugWarpFloor
debugCommandDone:
              rts

;;; Patch an existing jump instead of adding a test to every normal frame.
debugDelayPatch:
              lda long:debugSlow
              ora long:debugVbls
              beq debugNoDelay
              lda ##.word0 (DebugFrame)
              bra debugSetDelay
debugNoDelay: lda ##.word0 (frameLoop)
debugSetDelay:sta long:debugFrameJump+1
              rts

DebugWait:    lda long:demoMode
              bne debugWaitDone
              lda long:debugSlow
              beq debugWaitExtra
              jsl long:I_GetTime
              sta long:debugWaitAt
              txa
              sta long:debugWaitAt+2
              ldx ##14
              jsr abs:.word0 (debugVblank)
              jsl long:I_GetTime
              sec
              sbc long:debugWaitAt
              pha
              txa
              sbc long:debugWaitAt+2
              sta long:debugWaitAt+2
              pla
              clc
              adc long:levelStart
              sta long:levelStart
              lda long:levelStart+2
              adc long:debugWaitAt+2
              sta long:levelStart+2
              jsl long:DebugClockReset
debugWaitExtra:
              lda long:debugVbls
              beq debugWaitDone
              tax
              jsr abs:.word0 (debugVblank)
debugWaitDone:rtl
debugVblank:  sep #0x20
debugBlankOut:lda long:RDVBLBAR
              bmi debugBlankOut
debugBlankIn: lda long:RDVBLBAR
              bpl debugBlankIn
              dex
              bne debugBlankOut
              rep #0x20
              rts

;;; Pause the unaltered SHR picture. Enter arms a second-key immediate quit.
              .extern UiInitFlash
debugPicture:jsl long:UiInitFlash
              sep #0x20
              lda long:BORDER
              and #0xf0
              ora #15
              sta long:BORDER
              rep #0x20
              ldx ##6
              jsl long:DebugUiCall
              cmp ##K_RETURN
              beq debugPictureQuit
              cmp ##K_ENTER
              beq debugPictureQuit
              sep #0x20
              lda long:BORDER
              and #0xf0
              sta long:BORDER
              rep #0x20
              rts
debugPictureQuit:
              sep #0x20
              lda long:BORDER
              and #0xf0
              ora #1
              sta long:BORDER
              rep #0x20
              ldx ##6
              jsl long:DebugUiCall
              ldx ##8
              jsl long:DebugUiCall
              rts

debugNote:    jsr abs:.word0 (debugText)
              jsl long:DebugAck
              rts
debugText:    ldx ##.byte2 (debugMliText)
              jsl long:DebugSetText
              rts

;;; A=source offset, X=source bank. UI_BOXBUF is scratch while a dialog owns it.
DebugSetText: pha
              lda ##0
              sta long:debugLength
              pla
DebugAppendText:
              sta long:debugSource
              txa
              sep #0x20
              sta long:debugSource+2
              rep #0x20
              phb
              sep #0x20
              lda long:debugSource+2
              pha
              plb
              rep #0x20
              lda long:debugSource
              tay
              lda long:debugLength
              tax
              sep #0x20
debugCopyText:lda abs:0,y
              sta long:UI_BOXBUF,x
              beq debugTextDone
              iny
              inx
              bra debugCopyText
debugTextDone:rep #0x20
              txa
              sta long:debugLength
              plb
              rtl

DebugChar:    pha
              lda long:debugLength
              tax
              pla
              sep #0x20
              sta long:UI_BOXBUF,x
              lda #0
              sta long:UI_BOXBUF+1,x
              rep #0x20
              inx
              txa
              sta long:debugLength
              rtl
DebugNumber:  sta long:debugValue
              lda ##0
              sta long:debugStarted
              ldy ##0
debugNumPower:lda ##0
              sta long:debugDigit
              tya
              tax
debugNumSub:  lda long:debugValue
              cmp long:debugPowers,x
              bcc debugNumDigit
              sbc long:debugPowers,x
              sta long:debugValue
              lda long:debugDigit
              inc a
              sta long:debugDigit
              bra debugNumSub
debugNumDigit:lda long:debugDigit
              ora long:debugStarted
              bne debugNumEmit
              cpy ##8
              bne debugNumNext
debugNumEmit: lda ##1
              sta long:debugStarted
              lda long:debugDigit
              clc
              adc ##'0'
              jsl long:DebugChar
debugNumNext: iny
              iny
              cpy ##10
              bcc debugNumPower
              rtl
DebugDialog:  lda ##.word0 UI_BOXBUF
              sta dp:U_STR
              ldx ##4
              jsl long:DebugUiCall
              rtl
DebugAck:     jsl long:DebugDialog
              ldx ##6
              jsl long:DebugUiCall
              rtl

;;; Two decimal digits, with Backspace and Escape, as in the DOS debug prompts.
debugNumberInput:
              jsr abs:.word0 (debugText)
              lda ##10
              jsl long:DebugChar
              lda long:debugLength
              sta long:debugInputStart
              lda ##0
              sta long:debugInputLen
              sta long:debugInputValue
debugInputDraw:
              jsl long:DebugDialog
debugInputKey:ldx ##6
              jsl long:DebugUiCall
              cmp ##K_ESC
              bne debugBranchSkip3
              jmp abs:.word0 (debugInputCancel)
debugBranchSkip3:
              cmp ##K_RETURN
              bne debugBranchSkip4
              jmp abs:.word0 (debugInputAccept)
debugBranchSkip4:
              cmp ##K_ENTER
              bne debugInputOther
              jmp abs:.word0 (debugInputAccept)
debugInputOther:
              cmp ##K_DELETE
              beq debugInputBack
              tax
              lda long:adbPlain,x
              and ##255
              cmp ##'0'
              bcc debugInputKey
              cmp ##'9'+1
              bcs debugInputKey
              pha
              lda long:debugInputLen
              cmp ##2
              bcc debugInputAdd
              pla
              bra debugInputKey
debugInputAdd:inc a
              sta long:debugInputLen
              pla
              pha
              jsl long:DebugChar
              pla
              sec
              sbc ##'0'
              pha
              lda long:debugInputValue
              asl a
              sta long:debugValue
              asl a
              asl a
              clc
              adc long:debugValue
              sta long:debugInputValue
              pla
              clc
              adc long:debugInputValue
              sta long:debugInputValue
              jmp abs:.word0 (debugInputDraw)
debugInputBack:
              lda long:debugInputLen
              beq debugInputKey
              dec a
              sta long:debugInputLen
              clc
              adc long:debugInputStart
              sta long:debugLength
              tax
              sep #0x20
              lda #0
              sta long:UI_BOXBUF,x
              rep #0x20
              lda long:debugInputValue
              ldx ##0
debugInputDiv:cmp ##10
              bcc debugInputDivDone
              sbc ##10
              inx
              bra debugInputDiv
debugInputDivDone:
              txa
              sta long:debugInputValue
              jmp abs:.word0 (debugInputDraw)
debugInputAccept:
              lda long:debugInputValue
              clc
              rts
debugInputCancel:
              sec
              rts

debugPowers:  .word 10000,1000,100,10,1
debugAction:  .word 0
debugGod:     .word 0
debugNoclip:  .word 0
debugSlow:    .word 0
debugVbls:    .word 0
debugWarpFloor:.word 65535
debugBorderColor:.word 0
debugWaitAt:  .word 0,0
debugLength:  .word 0
debugSource:  .word 0,0
debugValue:   .word 0
debugDigit:   .word 0
debugStarted: .word 0
debugInputStart:.word 0
debugInputLen:.word 0
debugInputValue:.word 0
debugMliText: .asciz "You now have 100% Health,\n99 Ammo and both Keys!\n\nNote that you have basically\neliminated your chances of\ngetting a high score!"
debugBatText: .asciz "Commander Keen is also\navailable from Apogee, but\nthen, you already know\nthat - right, Cheatmeister?!"
debugEnableText:.asciz "Debugging keys are\nnow available!"
debugGodOnText:.asciz "God mode ON"
debugGodOffText:.asciz "God mode OFF"
debugClipOnText:.asciz "No clipping ON"
debugClipOffText:.asciz "No clipping OFF"
debugSlowOnText:.asciz "Slow motion ON"
debugSlowOffText:.asciz "Slow motion OFF"
debugItemText:.asciz "Free items!"
debugExtraText:.asciz "Extra stuff!"
debugBorderText:.asciz " Border color (0-15):"
debugVblText: .asciz "  Add how many extra VBLs(0-8):"
#ifdef WOLF_SPEAR
debugWarpText:.asciz "  Warp to which level(1-21):"
#else
debugWarpText:.asciz "  Warp to which level(1-10):"
#endif

#ifdef WOLF_SPEAR
#include "debug-faces.inc"
              .extern debugFaces, hudHealthFace, DebugGodFace, health
;;; Exchange the three normal face pictures with converted god faces. The
;;; inactive set stays in cold RAM; the HUD keeps its existing source bank.
debugGodFaceSwap:
              ldx ##DEBUG_FACE_BYTES-2
debugFaceExchange:
              lda long:UI+DEBUG_FACE_OFFSET,x
              pha
              lda long:debugFaces,x
              sta long:UI+DEBUG_FACE_OFFSET,x
              pla
              sta long:debugFaces,x
              dex
              dex
              bpl debugFaceExchange
              lda long:debugGod
              beq debugRestoreFace
              lda ##.word0 (DebugGodFace)
              sta long:hudHealthFace+1
              sep #0x20
              lda #0x4c
              bra debugFaceOpcode
debugRestoreFace:
              lda ##.word0 (health)
              sta long:hudHealthFace+1
              sep #0x20
              lda #0xad
debugFaceOpcode:
              sta long:hudHealthFace
              rep #0x20
              rts
#endif

#define BUSY_WORDS_DATA 1
#include "busy_signs.inc"
