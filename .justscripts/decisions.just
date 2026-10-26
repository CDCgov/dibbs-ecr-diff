alias help := default

[private]
@default:
    just --list decisions

# @variable type
# @type string
# @description A string representing the singular name to use when outputting
# messages from the `new` recipe below.

type := "decision record"

# @variable folder
# @type string
# @description A string representing the file path relative to the root of the
# repository which contains the .template and where the files are being
# created.

folder := "docs/decisions"

[doc('Create a new decision record from the template found in docs/decisions/.template')]
new title:
    #!/usr/bin/env python3
    import datetime
    import re
    from pathlib import Path
    from string import Template

    # NOTE: `justfile_directory()` resolves to the *root* justfile's directory
    # even when the recipe is invoked through a module, so this does not depend
    # on where `just` was run from
    root = Path("{{ justfile_directory() }}")
    folder = root / "{{ folder }}"
    title = "{{ title }}"
    file_title = "{{ kebabcase(title) }}"
    today = datetime.date.today().isoformat()

    numbered = re.compile(r"^(\d{4})_")

    print(f"📝 Creating a new {{ type }} on {today}")
    print(f"🔍 Found {{ type }} title: {title}")
    print(f"🔦 Checking for existing {{ type }}s in {folder}")

    existing = [p for p in folder.iterdir() if p.is_file() and numbered.match(p.name)]
    print(f"🔍 Found {len(existing):04d} {{ type }}(s)")

    # NOTE: the next number is max+1 rather than count+1 -- a deleted or
    # withdrawn record must never hand its number to the next one
    next_number = max((int(numbered.match(p.name)[1]) for p in existing), default=0) + 1
    print(f"🖊️ Setting your new {{ type }} to #{next_number:04d}")

    target = folder / f"{next_number:04d}_{today}_{file_title}.md"
    print(f"📊 Attempting to save {{ type }} #{next_number:04d} to {target}")

    if target.exists():
        raise SystemExit(f"❌ {target} already exists")

    # NOTE: `safe_substitute` leaves an unrecognized `$...` in the template
    # alone instead of raising -- the template is prose and may contain one
    content = Template((folder / ".template").read_text()).safe_substitute(
        title=title, today=today, nextNumber=next_number
    )
    target.write_text(content)
    print(f"✅ Successfully created {{ type }} #{next_number:04d} for {title} at {target}")
