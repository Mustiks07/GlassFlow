import os
import sys

# Windowed PyInstaller processes have no Python stdout/stderr; uvicorn still needs file-like streams.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf8")

if __name__ == "__main__":
    try:
        from glassflow.launcher import main

        main()
    except Exception as exc:
        message = f"GlassFlow не удалось запустить ({type(exc).__name__}). Откройте GlassFlowDiagnostics.exe и README для проверки комплекта."
        print(message, file=sys.stderr)
        if os.name == "nt" and len(sys.argv) == 1:
            import ctypes

            ctypes.windll.user32.MessageBoxW(None, message, "GlassFlow", 0x10)
        raise SystemExit(1) from None
