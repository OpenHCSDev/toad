"""Opt-in observer entry point for an explicitly configured Toad CLI command."""

if __name__ == "__main__":
    from sidebar_validation_driver import install_observer

    install_observer()

    from toad.cli import main  # noqa: E402

    main()
