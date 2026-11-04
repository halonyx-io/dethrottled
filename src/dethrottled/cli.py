"""Keep the standalone server CLI; load stack tooling without importing the API."""
import sys


def main():
    if sys.argv[1:2] == ['stack']:
        from .stack import main as stack_main
        raise SystemExit(stack_main(sys.argv[2:]))
    from .server import main as serve
    return serve()
