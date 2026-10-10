(load "build/gen/memmap.scm")
(define memories
  `((memory Loader (address (,SEG_LOADER . ,SEG_LOADER_LAST))
            (section loader))
    ))
