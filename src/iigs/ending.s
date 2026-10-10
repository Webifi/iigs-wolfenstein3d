;;; Victory-page field positions and packed victory/ending pictures.
;;; tools/build_menu_cache.py supplies menu-pages.inc; the menu cache reads
;;; these chunks using the same layout as the corresponding menu-file pages.
              .section logiccode, text, root, noreorder
              .public endCount, layTimeX, layTimeY, laySecX, layRatioR
              .public layKillY, laySecretY, layTreasY
layTimeX:     .word 112
layTimeY:     .word 64
laySecX:      .word 152
layRatioR:    .word 240
layKillY:     .word 112
laySecretY:   .word 128
layTreasY:    .word 144
endCount:     .word 2
#include "menu-pages.inc"
