# Releasing the Lambda Image

This describes how to release a new version of the Lambda image. Publishing a GitHub Release triggers a workflow that builds the image and pushes it to AIMS dev ECR, where APHL then deploy it themselves to one or more of their environments (e.g. dev, test, prod).

_TODO: can add additional context about release process or decisions made here_

## Steps

1. **Make sure `main` is ready.** Ensure the code you want to release is merged into `main` and all checks have passed.

2. **Find the last released version.** Go to the [Releases page](../../../releases) and note the most recent version so you can decide the next one.

3. **Decide the next version.** Use semver (`vMAJOR.MINOR.PATCH`):
    - `MAJOR` — breaking change
    - `MINOR` — new feature, backwards compatible
    - `PATCH` — bug fix, backwards compatible

4. **Draft a new release.** Go to Releases → **Draft a new release**.
    - **Choose a tag:** enter the new version (e.g. `v1.4.0`) and create it.
    - **Target:** `main`, or, if you don't want to release the current state of main, the specific commit you want to release.
    - **Release notes:** write them, or use **Generate release notes**.

5. **Publish the release.** Click **Publish release**. This creates the tag and automatically triggers the release workflow.

6. **Confirm the push succeeded.** Go to the **Actions** tab and open the running workflow.
    - On success, the run's **Summary** shows the version pushed to ECR.
    - On failure, an alert is posted to the team Slack channel.

## If the push fails

Open the failed run in the **Actions** tab and click **Re-run failed jobs**. Re-running is safe — it rebuilds and re-pushes the same version.