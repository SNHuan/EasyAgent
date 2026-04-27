import sys


def main() -> None:
    name = sys.argv[1] if len(sys.argv) > 1 else "EasyAgent"
    print(name.upper())


if __name__ == "__main__":
    main()
