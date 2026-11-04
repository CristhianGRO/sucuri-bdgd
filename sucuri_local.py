"""Desktop companion entry point, also used by the portable Windows build."""
import multiprocessing

if __name__ == '__main__':
    multiprocessing.freeze_support()
    import sys
    if '--serve' in sys.argv:
        sys.argv.remove('--serve')
        from web_backend.server import main
    else:
        from web_backend.launcher import main
    main()
