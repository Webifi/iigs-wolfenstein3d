;;; A menu pauses the slideshow in its existing call stack. Preserve the
;;; slideshow's working page and unfaded colors outside the menu frame.
              .section attractdata, data, root
              .public attractPage, attractPalette
attractPage:   .space 256
attractPalette: .space 512
