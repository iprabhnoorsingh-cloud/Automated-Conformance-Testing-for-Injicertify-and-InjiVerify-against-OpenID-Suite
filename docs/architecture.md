# Architecture

## 1. Purpose

MOSIP Conformance Center is a conformance-testing orchestration platform for
the MOSIP/Inji ecosystem. It will eventually run OpenID Foundation
conformance suites and MOSIP/Inji API test-rigs, normalize their results into
a common format, apply configurable benchmark gates, generate reports, and
expose all of this through a web dashboard and CI/CD integration.

This document describes both what exists today (Milestone 1) and what is
planned for later milestones. Anything listed under "Future" below is
**NOT IMPLEMENTED**.

## 2. Frontend responsibility

A Next.js (TypeScript, Tailwind) dashboard. Currently a navigation shell with
placeholder sections for Dashboard, Test Runs, Environments, and Reports, and
a live backend health indicator. In later milestones it will visualize test
runs, benchmark results, and reports.

## 3. Backend responsibility

A FastAPI service. Currently exposes only `/health` and `/` for service
identification and health checking, with environment-variable-based
configuration. In later milestones it will host the orchestration API.

## 4. Future: Orchestrator (NOT IMPLEMENTED)

A component that schedules and runs conformance test suites against
configured environments, tracks run state, and collects raw results.

## 5. Future: OpenID Foundation integration (NOT IMPLEMENTED)

Integration with the OpenID Foundation conformance test suite to run
standard OpenID/OAuth conformance tests against MOSIP/Inji identity
components and retrieve structured results.

## 6. Future: MOSIP API Test-Rig integration (NOT IMPLEMENTED)

Integration with MOSIP/Inji-specific API test-rigs to exercise
implementation-specific behavior not covered by generic OpenID conformance
suites.

## 7. Future: Benchmark engine (NOT IMPLEMENTED)

A configurable rules engine that evaluates normalized test results against
pass/fail benchmarks/gates (e.g. required test coverage, required passing
tests) to produce a conformance verdict.

## 8. Future: Reporting system (NOT IMPLEMENTED)

Generation of human-readable and machine-readable conformance reports from
normalized results and benchmark evaluations, surfaced in the dashboard and
as downloadable artifacts.

## 9. Future: CI/CD integration (NOT IMPLEMENTED)

Hooks to trigger conformance runs from CI/CD pipelines and to gate merges or
releases on conformance benchmark results. The current `.github/workflows/ci.yml`
only builds/tests this repository's own code — it does not run conformance
suites.
