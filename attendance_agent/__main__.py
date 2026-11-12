"""Run with: python -m attendance_agent C:\\path\\to\\agent.ini [--once [--serial S]]"""
import argparse
import sys

from .collector import configure_logging, load_config, run_forever, run_once


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog='attendance_agent')
    parser.add_argument('settings', help='path to agent.ini')
    parser.add_argument('--once', action='store_true', help='one pass, then exit')
    parser.add_argument(
        '--serial', help='with --once: read only this machine, for the first-contact test',
    )
    args = parser.parse_args(argv)
    if args.serial and not args.once:
        parser.error('--serial needs --once')
    try:
        config = load_config(args.settings)
        configure_logging(config, console=args.once)
    except (ValueError, OSError) as exc:
        message = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
        print(f'attendance_agent: {message}', file=sys.stderr)
        return 2
    if args.once:
        run_once(config, serial=args.serial)
    else:
        run_forever(config)
    return 0


if __name__ == '__main__':
    sys.exit(main())
