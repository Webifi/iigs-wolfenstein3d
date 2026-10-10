;;; Menu-file pictures used by victory.s and tally_art.s.
;;; CopyMenuBlocks (ui_cache.s) expects D=UI_DP. CM_* aliases match the
;;; U_BLK..U_DBNK offsets in memmap.inc. PAGE_STAGE borrows the menu snapshot
;;; between menus; TallyStage reloads it after a menu capture.
#include "memmap.inc"
CM_BLK        .equ 0x42
CM_CNT        .equ 0x44
CM_DOFF       .equ 0x46
CM_DBNK       .equ 0x48
