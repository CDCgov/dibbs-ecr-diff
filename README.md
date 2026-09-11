# DIBBs Difference in Docs

**General disclaimer** This repository was created for use by CDC programs to collaborate on public health related projects in support of the [CDC mission](https://www.cdc.gov/about/cdc/#cdc_about_cio_mission-our-mission).  GitHub is not hosted by the CDC, but is a third party website used by CDC and its partners to share information and collaborate on software. CDC use of GitHub does not imply an endorsement of any one particular service, product, or enterprise. 

## Related documents

* [Open Practices](open_practices.md)
* [Rules of Behavior](rules_of_behavior.md)
* [Thanks and Acknowledgements](thanks.md)
* [Disclaimer](DISCLAIMER.md)
* [Contribution Notice](CONTRIBUTING.md)
* [Code of Conduct](code-of-conduct.md)
* [Technical Overview](docs/01-Technical-Overview.md)
* [Configuration Spec](docs/02-Configuration-Spec.md)
* [Diff Output Spec](docs/03-Diff-Output-Spec.md)
* [Entry Augmentation Spec](docs/04-Entry-Augmentation-Spec.md)
* [Telemetry Semantics](docs/Telemetry-Semantics.md)

## Overview

DIBBs Difference in Docs (DiD) is a project aimed at helping Public Health Authorities (PHAs) better leverage eCR by reducing the frequency of updates to electronic Initial Case Reports (eICRs). This will allow them to identify updates that are meaningful to their public health activities.

Difference in Docs achives this by performing full structural diffs between versions of an eICR, and using a configuration file (in JSON) utilizing [XPath](https://www.w3.org/TR/xpath/) strings to determine what changes are "actionable".

Difference in Docs is deployed as an AWS Lambda Function on APHL's AIMS Platform.

```mermaid
graph TB
  linkStyle default fill:#ffffff

  subgraph diagram ["System Context View: Difference in Docs, Iteration 1 DRAFT"]
    style diagram fill:#ffffff,stroke:#ffffff

    1("<div style='font-weight: bold'>AIMS Platform</div><div style='font-size: 70%; margin-top: 0px'>[Software System]</div><div style='font-size: 80%; margin-top:10px'>Handles incoming eCRs and<br />decides whether to send to<br />PHAs. Includes eCR Refiner.</div>")
    style 1 fill:#ffffff,stroke:#009ca7,color:#009ca7
    2("<div style='font-weight: bold'>Difference in Docs</div><div style='font-size: 70%; margin-top: 0px'>[Software System]</div><div style='font-size: 80%; margin-top:10px'>Determines differences<br />between eCRs based on<br />configuration</div>")
    style 2 fill:#ffffff,stroke:#6499af,color:#6499af

    2-. "<div>Sends diff output to</div><div style='font-size: 70%'></div>" .->1
    1-. "<div>Sends eCR input to</div><div style='font-size: 70%'></div>" .->2

  end
```

m: [diff-output]: [reading this I'm now understanding that APHL sends a doc and DiD digs up the prior doc to do the compare. I assumed maybe DiD took in two files since the CLI tool has 2 file arguments] -- might be worth clarifying that the CLI exists only for devs to quickly iterate and test the core diffing logic/configuration engine

m: [wait so does this diff get passed to an augmentation step before going to APHL?] -- yes it does; the diff output gets passed to the augmentation step so that `augment.py` can then perform the augmentation with the information from the diff. CLARIFY

m: [I just realized I don't know what exactly is getting passed in to DiD and what gets passed out. 
output = this diff output plus an augmented eICR?] -- yes that's right. CLARIFY

 moe entry augmentation under diff output spec.md ordering

## Getting Started

### Prerequisites

**To start developing locally, or to run any commands in this document, you'll need the following tools installed:**

* [just](https://just.systems/man/en/) `>=1.46.x` for running project commands
* [uv](https://docs.astral.sh/uv/getting-started/installation/) `>=0.11.31` for Python version, package, and project management
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

### Command-Line Interface (CLI)

The Difference in Docs repository includes a command-line interface. **The purpose of this command-line interface is solely for development and manually testing the Difference in Docs core logic.**

To access the CLI, run:

```bash
just diff
```

This will print help text with instructions on running the CLI against a pair of eICR files.

On successfully running the CLI tool, it will produce a diff output JSON file following the [Diff Output Spec](./docs/03-Diff-Output-Spec.md), and an augmented eICR XML file.

See below for more examples:
```bash
# run CLI tool against two eICR versions; will output to `output/` directory by default
just diff tmp/eICR.xml tmp/eICR_after.xml

# specify output directory
just diff tmp/eICR.xml tmp/eICR_after.xml -o some_other_output_dir/

# specify configuration file other than the default
just diff tmp/eICR.xml tmp/eICR_after.xml -c test_configuration.json
```

### Local AWS pipeline

m: [how does this tool (DiD) work? CLI or via dev input tool? do they do the same thing? dev input tool seems more configurable] -- we can answer this here by saying that CLI is solely for testing the diff logic; the dev input tool is for testing the DiD Lambda. DiD *IS* the Lambda. The CLI is ONLY for testing core logic for developers

m: [what's expected output from dev input tool?] -- we should mention that the output from the dev input tool is only what is in the S3 Buckets

m: [what's an RR?] -- may be good to briefly define some terms, and then link to refiner's better docs here
m: [update okay I looked up what an RR is after reading through the rest of the doc and I'm not sure how it gets used by DiD] -- we might have to explicitly mention here how DiD uses the RR

The Difference in Docs repository includes a Docker Compose stack to simulate the AIMS Platform's AWS environment. This is used for local development, as well as for end-to-end testing.

Start the local S3, SQS, EventBridge, DynamoDB, Lambda, and uploader services:

```bash
docker compose --env-file .env.local up --build --watch
```

View local AWS resources at `http://localhost:8080`.

Open `http://localhost:8081` and upload an eICR and RR. The uploader:

1. Stores the documents in local S3, and generates a manifest which is also stored in local S3.
2. Triggers an S3 notification to EventBridge -> SQS.
3. `sqs-poller.py` checks SQS, and invokes the lambda on new messages.

Stop the services with `docker compose down`.

## Development

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

### Running e2e (End-to-End) tests

E2E tests can be run using the included script:

```bash
just e2e
```

The E2E tests use a pytest plugin, [syrupy](https://github.com/syrupy-project/syrupy), for snapshot assertions. To update snapshots located in `e2e/__snapshots`, pass the `--snapshot-update` flag. Updating snapshots will also delete any stale/unused snapshot files.

```bash
just e2e --snapshot-update
```

E2E tests use the same local Docker Compose stack located in `compose.yml`, with specific environment variables defined in `e2e/.e2e.env`. The Compose stack is configured as a fixture in `e2e/conftest.py`. To see additional log information while running E2E scripts, including Docker output, pass the `-s` flag to pytest:

```bash
just e2e -s
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
uv add --package did_lambda aws-lambda-powertools
```

## Architecture

### Structurizr

Difference in Docs uses [Structurizr](https://docs.structurizr.com/) to visualize the software architecture using the [C4 Model](https://c4model.com/).

To run Structurizr locally, you'll first need to have the project [prerequisites](#prerequisites) installed and then run:

```bash
just arch view
```

View it in your browser at http://localhost:7268.

## Repository Structure

The Difference in Docs repository is a [uv workspace](https://docs.astral.sh/uv/concepts/projects/workspaces/) consisting of multiple Python packages.

```
├── docker                    # Docker-related scripts, files, and containerized services
├── e2e                       # End-to-End tests, assets, and snapshots
├── packages
│   ├── cli                   # Command-line interface package
│   │   ├── pyproject.toml
│   │   └── src/
│   ├── core                  # Core Difference in Docs logic and shared modules
│   │   ├── pyproject.toml
│   │   └── src/
│   └── did_lambda            # AWS Lambda Function package
│       ├── pyproject.toml
│       └── src/
├── compose.yml               # Docker Compose stack used for local development and testing
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
