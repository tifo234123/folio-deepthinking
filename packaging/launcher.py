"""Entry point for packaged builds: the desktop app, or the isolated PDF worker."""
import os
import sys


def _attach_stdout():
    # A windowed Windows build may start without sys.stdout even when given a pipe.
    if sys.stdout is None and os.name == "nt":
        import ctypes, msvcrt
        handle = ctypes.windll.kernel32.GetStdHandle(-11)
        if handle not in (0, -1):
            fd = msvcrt.open_osfhandle(handle, os.O_WRONLY)
            sys.stdout = open(fd, "w", encoding="utf-8", buffering=1)


if __name__ == "__main__":
    from folio.pdf_worker import WORKER_FLAG
    if len(sys.argv) > 2 and sys.argv[1] == WORKER_FLAG:
        _attach_stdout()
        from folio.pdf_worker import main
        main(sys.argv[2])
    else:
        from folio.desktop import main
        main()
