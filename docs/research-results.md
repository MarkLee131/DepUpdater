# Supplementary research notes

[Back to research data](../README.md#data-for-rqs)

These records come from the original ICSE 2026 artifact. They describe the
published study, not new measurements from `main`. The
[original artifact](https://github.com/MarkLee131/DepUpdater/tree/163cf411da6047dbacb8340602314723d88b729b)
remains pinned for reproducibility.

## Data files

| Study | File | Contents |
| --- | --- | --- |
| RQ1 | [depupdater.csv](../research/results/rq1/depupdater.csv) | DepUpdater results. |
| RQ1 | [dependabot.csv](../research/results/rq1/dependabot.csv) | Dependabot results. |
| RQ1 | [snyk.csv](../research/results/rq1/snyk.csv) | Snyk results. |
| RQ2 | [compatibility_only.csv](../research/results/rq2/compatibility_only.csv) | Compatibility-only variant. |
| RQ2 | [pruning_only.csv](../research/results/rq2/pruning_only.csv) | Pruning-only variant. |
| RQ2 | [naive.csv](../research/results/rq2/naive.csv) | Naive variant. |
| RQ3 | [api_distribution.csv](../research/results/rq3/api_distribution.csv) | Distribution of client-impacting APIs. |
| RQ3 | [client_distribution.csv](../research/results/rq3/client_distribution.csv) | Distribution of broken clients. |

## Project-level results

The following table was provided during the paper's major revision to make
project-level outcomes available:

![Project-level comparison of dependency upgrade results from the published artifact.](../assets/images/paper/rq1-project-results.png)

Interpretation notes from the artifact:

1. Dependabot and Snyk did not consider pruning during the studied upgrades.
   Redundant dependencies could increase total technical lag; for example,
   Dependabot increased Netty's total version lag by 150 versions.
2. GoblinUpdater was omitted from this table because all its recorded data
   points were zero.
3. Dependency-tree generation failed after Dependabot upgrades for Apollo,
   Jenkins, and Druid, and after Snyk upgrades for Sentinel and Jenkins. Since
   technical lag is calculated from the dependency tree, these entries are
   **N/A**, not zero lag.

## Upstream upgrade proposals

Build/test outcomes and descriptions below are **as reported in the artifact**.
They are not a live status check. Follow each PR for the current discussion;
historical star counts have been omitted.

| Project | PR | Compilation | Regression tests | Outcome reported in the artifact |
| --- | --- | --- | --- | --- |
| easyexcel | [#4123](https://github.com/alibaba/easyexcel/pull/4123) | Passed | Passed | Submitted. |
| spring-cloud-alibaba | [#4023](https://github.com/alibaba/spring-cloud-alibaba/pull/4023) | Passed | Passed | Submitted. |
| dubbo | [#15577](https://github.com/apache/dubbo/pull/15577) | Passed | Passed | Not adopted: the project maintained unified dependency versions across modules. |
| Sentinel | [#3536](https://github.com/alibaba/Sentinel/pull/3536) | Passed | Passed | Maintainer upgraded the dependencies after reviewing the proposal; recorded as merged. |
| WxJava | [#3643](https://github.com/binarywang/WxJava/pull/3643) | Passed | No tests in this module | Maintainer upgraded the dependencies after reviewing the proposal; recorded as merged. |
