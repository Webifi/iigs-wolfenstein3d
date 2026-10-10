#include "memmap.inc"
#include "progress.inc"
;;; One exact reciprocal-height table for the selected view. The compact
;;; build-time runs expand on view changes and after paused menus.
              .section gamecode, text, root, noreorder
              .public PrepareRayPages, HeightOfDepth, EnsureRayHeights
              .extern heightStreams, heightView, weaponViewIndex

PrepareRayPages:
              lda abs:.word0 (heightStreams),x
              sta dp:RP_PTR
              lda ##0x0b
              sta dp:RP_PTR+2
              ldx ##0
              ldy ##0
rpRun:        lda [RP_PTR],y
              sta dp:RP_END
              iny
              iny
              lda [RP_PTR],y
rpFill:       sta long:HEIGHT_TABLE,x
              inx
              inx
              cpx dp:RP_END
              bcc rpFill
              iny
              iny
              cpx ##32768
              bcc rpRun
              jsl long:Progress26
              rts

;;; Sprite projection already supplies perpendicular depth in range.
HeightOfDepth:
              asl a
              tax
              lda long:HEIGHT_TABLE,x
              rts

;;; Called only on transitions into rendering, never from the game frame loop.
;;; Paused menus borrow these 32 KiB for their clean gray background.
EnsureRayHeights:
              phx
              ldx abs:.word0 (weaponViewIndex)
              cpx abs:.word0 (heightView)
              beq rpReady
              phx
              jsr abs:.word0 (PrepareRayPages)
              plx
              stx abs:.word0 (heightView)
rpReady:      plx
              rts
