import sys


if __name__ == "__main__":
    if sys.platform != "win32":
        raise SystemExit("Writing Assistant requires Windows 10 or 11.")
    from writing_assistant.app import main

    main()
