# DIBBs Difference in Docs

**General disclaimer** This repository was created for use by CDC programs to collaborate on public health related projects in support of the [CDC mission](https://www.cdc.gov/about/cdc/#cdc_about_cio_mission-our-mission).  GitHub is not hosted by the CDC, but is a third party website used by CDC and its partners to share information and collaborate on software. CDC use of GitHub does not imply an endorsement of any one particular service, product, or enterprise. 

## Related documents

* [Open Practices](open_practices.md)
* [Rules of Behavior](rules_of_behavior.md)
* [Thanks and Acknowledgements](thanks.md)
* [Disclaimer](DISCLAIMER.md)
* [Contribution Notice](CONTRIBUTING.md)
* [Code of Conduct](code-of-conduct.md)

## Overview

DIBBs Difference in Docs (DiD) is a project aimed at helping Public Health Authorities (PHAs) better leverage eCR by reducing the frequency of updates to electronic Initial Case Reports (eICRs). This will allow them to identify updates that are meaningful to their public health activities. 

## Getting Started

### Prerequisites

To start developing locally, you need the following tools installed:

* [just](https://just.systems/man/en/) `>=1.46.x` for running project commands
* [uv](https://docs.astral.sh/uv/getting-started/installation/) `>=0.10.x` for Python version, package, and project management
* [Docker](https://www.docker.com/) `>=28.3.x` for running containers

### Setup

View all available commands

```bash
just
```

Download Python dependencies and sync all packages:

```bash
just sync
```

To start the FastAPI server, run:

```bash
just server dev
```

To access the CLI, run:

```bash
just diff
```

### Type checking / Linting / Formatting

Check types:

```bash
just ty
```

Run linter:

```bash
just check
```

Apply formatting:
```bash
just format
```

### Running tests

All unit tests can be run with pytest:

```bash
just test
```

Unit tests for a specific package can be ran by passing a path to pytest:

```bash
just test packages/cli
```

### Adding dependencies

Additional dependencies can be added to the root workspace with `uv`:

```bash
uv add httpx

# adding a dev dependency
uv add --dev pytest
```

Dependencies can be added to workspace packages by specifying the package using `--package <name>`:

```bash
uv add --package lambda aws-lambda-powertools
```

## Architecture

### Structurizr

The Difference in Docs project uses [Structurizr](https://docs.structurizr.com/) to visualize the software architecture using the [C4 Model](https://c4model.com/).

To run Structurizr locally, you'll first need to have [Docker](https://www.docker.com/) installed and then run:

```bash
just arch view
```

View it in your browser at http://localhost:7268.

## Repository Structure

This project is a [uv workspace](https://docs.astral.sh/uv/concepts/projects/workspaces/) consisting of multiple Python packages.

```
├── packages
│   ├── cli                   # Command-line interface package
│   │   ├── pyproject.toml
│   │   └── src/
│   ├── core                  # Core Difference in Docs logic and shared modules
│   │   ├── pyproject.toml
│   │   └── src/
│   ├── lambda                # AWS Lambda package
│   │   ├── pyproject.toml
│   │   └── src/
│   └── server                # Long-running FastAPI server
│       ├── pyproject.toml
│       └── src/
├── pyproject.toml            # Workspace config (dependencies, linter rules, metadata)
└── uv.lock                   # Lockfile for all workspace dependencies
```

## Public Domain Standard Notice

This repository constitutes a work of the United States Government and is not
subject to domestic copyright protection under 17 USC § 105. This repository is in
the public domain within the United States, and copyright and related rights in
the work worldwide are waived through the [CC0 1.0 Universal public domain dedication](https://creativecommons.org/publicdomain/zero/1.0/).
All contributions to this repository will be released under the CC0 dedication. By
submitting a pull request you are agreeing to comply with this waiver of
copyright interest.

## License Standard Notice

The repository utilizes code licensed under the terms of the Apache Software
License and therefore is licensed under ASL v2 or later.

This source code in this repository is free: you can redistribute it and/or modify it under
the terms of the Apache Software License version 2, or (at your option) any
later version.

This source code in this repository is distributed in the hope that it will be useful, but WITHOUT ANY
WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A
PARTICULAR PURPOSE. See the Apache Software License for more details.

You should have received a copy of the Apache Software License along with this
program. If not, see http://www.apache.org/licenses/LICENSE-2.0.html

The source code forked from other open source projects will inherit its license.

## Privacy Standard Notice

This repository contains only non-sensitive, publicly available data and
information. All material and community participation is covered by the
[Disclaimer](DISCLAIMER.md)
and [Code of Conduct](code-of-conduct.md).
For more information about CDC's privacy policy, please visit [http://www.cdc.gov/other/privacy.html](https://www.cdc.gov/other/privacy.html).

## Contributing Standard Notice

Anyone is encouraged to contribute to the repository by [forking](https://help.github.com/articles/fork-a-repo)
and submitting a pull request. (If you are new to GitHub, you might start with a
[basic tutorial](https://help.github.com/articles/set-up-git).) By contributing
to this project, you grant a world-wide, royalty-free, perpetual, irrevocable,
non-exclusive, transferable license to all users under the terms of the
[Apache Software License v2](http://www.apache.org/licenses/LICENSE-2.0.html) or
later.

All comments, messages, pull requests, and other submissions received through
CDC including this GitHub page may be subject to applicable federal law, including but not limited to the Federal Records Act, and may be archived. Learn more at [http://www.cdc.gov/other/privacy.html](http://www.cdc.gov/other/privacy.html).

## Records Management Standard Notice

This repository is not a source of government records, but is a copy to increase
collaboration and collaborative potential. All government records will be
published through the [CDC web site](http://www.cdc.gov).

## Additional Standard Notices

Please refer to [CDC's Template Repository](https://github.com/CDCgov/template) for more information about [contributing to this repository](https://github.com/CDCgov/template/blob/main/CONTRIBUTING.md), [public domain notices and disclaimers](https://github.com/CDCgov/template/blob/main/DISCLAIMER.md), and [code of conduct](https://github.com/CDCgov/template/blob/main/code-of-conduct.md).
