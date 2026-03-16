from core import diff_xml


def main() -> None:
    """CLI entrypoint."""
    xml = diff_xml()
    print(xml)


if __name__ == "__main__":
    main()
