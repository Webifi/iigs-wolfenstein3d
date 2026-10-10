(load "build/gen/memmap.scm")
(define memories
  `((memory Boot (address (,SEG_BOOT . ,SEG_BOOT_LAST))
            (section boot))
    ))
