import sys

from glassflow.launcher import main

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"GlassFlow не удалось запустить ({type(exc).__name__}). Проверьте комплект приложения и README.", file=sys.stderr)
        raise SystemExit(1) from None
