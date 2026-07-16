# CI/CD Learning Guide

This guide explains the first cloud-engineering automation layer in TinyProvisioner. The goal is not only to have a green badge. The goal is to understand why an automated delivery system exists, what evidence it produces, and where its trust boundaries are.

## The Core Idea

Continuous integration (CI) means every proposed code change is automatically combined with the rest of the repository and checked in a clean environment.

Continuous delivery (CD) means a change that passed those checks can be packaged and moved toward an environment in a repeatable way. Continuous deployment is the more automated version in which a passing change can reach production without a manual release step.

This phase implements CI. It intentionally does not deploy yet. A deployment pipeline without trustworthy tests is simply a fast way to ship a failure.

## What Happens After a Push

```text
Developer pushes a commit or opens a pull request
                    |
                    v
GitHub creates a new temporary Ubuntu runner
                    |
                    v
The runner checks out the exact commit being evaluated
                    |
                    v
Python 3.12 and project dependencies are installed
                    |
          +---------+---------+
          |                   |
          v                   v
     Ruff linting       Pytest + coverage
          |                   |
          +---------+---------+
                    |
                    v
Test evidence is stored as a workflow artifact
                    |
                    v
Docker Compose files are validated
                    |
                    v
The production-style API image is built and started
                    |
                    v
An HTTP request proves that the container responds
```

If any required step exits with a non-zero status, the job fails and later dependent work does not run.

## Why There Are Two Jobs

The `quality` job answers: **Is the source code internally consistent and does its behavior pass the automated tests?**

The `container` job answers: **Can the artifact we intend to run actually be assembled and started?**

The container job declares `needs: quality`. That creates a dependency between the jobs. GitHub will only spend time building a container after the faster source checks pass.

This separation will matter later. A future image-publishing job can depend on both jobs without copying their implementation.

## Important Workflow Decisions

### Triggers

The workflow runs for pull requests, pushes to `main`, and manual runs. Pull-request checks protect code before it is merged. The `main` run proves the merged result still works. The manual trigger is useful while learning and troubleshooting.

### Clean runners

A hosted runner starts without the uncommitted files, cached application state, or local configuration on a developer laptop. Passing in that environment is stronger evidence that the repository contains everything required to build the project.

### Least-privilege permissions

The workflow grants the automatically-created `GITHUB_TOKEN` only `contents: read`. Linting, testing, and building do not need permission to modify repository contents or publish packages.

A later deployment job will receive its own narrowly-scoped permissions. Permissions should be added to the smallest job that needs them, not granted to the entire workflow.

### Action pinning

An action is executable code downloaded into the runner. A reference such as `@v6` is convenient, but its target can change. This workflow pins each action to a full 40-character commit SHA and leaves the human-readable release in a comment.

Dependabot watches those references and proposes upgrades. This combines immutable builds with a reviewable update path.

### Dependency caching

`setup-python` caches pip downloads using `pyproject.toml` as part of the cache key. A cache makes later runs faster; it does not skip dependency installation or become part of the application artifact.

### Concurrency control

When another commit is pushed to the same branch, the older in-progress run is cancelled. The older result no longer represents the newest code, so continuing to spend runner time on it provides little value.

### Timeouts and cleanup

Each job has a timeout so a hung command cannot consume a runner forever. The temporary smoke-test container is removed with `if: always()`, which means cleanup still runs after a failed test.

## Linting, Tests, Coverage, and Smoke Tests

These checks solve different problems:

| Check | Question it answers |
| --- | --- |
| Ruff | Does the code violate agreed static-quality rules? |
| Pytest | Does the behavior match the assertions written by the project? |
| Coverage | Which application lines were exercised while tests ran? |
| Compose validation | Can Docker interpret the local and production configuration? |
| Image build | Can the deployable container artifact be created? |
| HTTP smoke test | Does that artifact start and answer a basic request? |

Coverage is a map, not a guarantee of correctness. A line can run without its behavior being meaningfully tested. The current suite measures 84% application coverage, and CI enforces a baseline of 80% to catch a meaningful regression. The target is deliberately not 100%; useful behavioral tests matter more than executing lines simply to increase a score.

## Reproduce the Quality Job Locally

Activate a Python 3.12 virtual environment and install the development dependencies:

```powershell
python -m pip install --editable ".[dev]"
```

Run the same quality commands as CI:

```powershell
python -m ruff check .
python -m pytest --cov=app --cov-fail-under=80 --cov-report=term-missing
```

If Docker is installed, reproduce the artifact check:

```powershell
docker build --tag tiny-provisioner:ci .
docker run --rm --publish 8000:8000 tiny-provisioner:ci
```

In another terminal, request the control panel:

```powershell
curl.exe --fail http://127.0.0.1:8000/
```

## Reading a Failed Run

Start with the first failed step, not the last skipped job.

1. Open the workflow run and select the failed job.
2. Expand the first red step.
3. Find the command, error type, file, and line number.
4. Reproduce that exact command locally.
5. Fix the cause and push a new commit.
6. Confirm the new run replaces the old result.

For test failures, download the `python-quality-reports` artifact. `pytest.xml` is structured test output and `coverage.xml` records measured coverage. Later, external quality systems can consume these same files.

## Hands-On Labs

### Lab 1: Prove linting is a gate

Create an unused import in a temporary branch, run Ruff locally, and observe its exit code. Push the branch and inspect the failed `quality` job. Remove the import and confirm that the next run passes.

### Lab 2: Prove job dependencies work

Temporarily make one assertion fail. Notice that the container job is skipped because its `needs: quality` dependency failed. Restore the assertion afterward.

### Lab 3: Diagnose a container failure

Temporarily change the Dockerfile command to an invalid module. The image will still build, but the HTTP smoke test will fail and print the stopped container's logs. This demonstrates why building an image is not the same as proving it runs.

Do these experiments only on a temporary branch and discard the intentional breakage after observing it.

## What Comes Next

CI proves that a commit is a plausible release candidate. The next phases will add stronger worker concurrency, observability, Infrastructure as Code, image publishing, and deployment. Each one will reuse this workflow's core rule: produce evidence before promoting a change.
