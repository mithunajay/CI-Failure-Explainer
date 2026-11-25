"""Deterministic rule-based classifier.

It serves three jobs: a free baseline to compare the LLM against, a fallback
when the model output fails validation, and a sanity check in tests.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

CATEGORIES = [
    "dependency_install", "test_failure", "lint_format", "compile_error",
    "timeout", "out_of_memory", "network", "permission_auth", "config_syntax",
    "docker_build", "missing_file", "unknown",
]


@dataclass(frozen=True)
class Rule:
    category: str
    pattern: re.Pattern[str]
    summary: str
    fix: str


def _r(category: str, pattern: str, summary: str, fix: str) -> Rule:
    return Rule(category, re.compile(pattern, re.I), summary, fix)


# Order matters: more specific causes come before generic wrappers.
RULES: list[Rule] = [
    _r("out_of_memory",
       r"(OOMKilled|out of memory|heap limit|exit code 137|Killed\s*$)",
       "The job ran out of memory and was killed.",
       "Reduce memory use, raise the runner's memory limit, or split the job into smaller steps."),
    _r("config_syntax",
       r"(invalid workflow file|workflow is not valid|mapping values are not allowed|"
       r"yaml: |\.gitlab-ci\.yml.*(invalid|error)|unexpected value)",
       "The pipeline configuration file is invalid.",
       "Fix the YAML syntax or key named in the error and validate the file with a linter."),
    _r("permission_auth",
       r"(permission denied|403 forbidden|401 unauthorized|authentication failed|"
       r"denied: requested access|insufficient_scope|bad credentials)",
       "A permission or authentication check failed.",
       "Check the token or credentials used by the job and the permissions they were granted."),
    _r("dependency_install",
       r"(could not find a version that satisfies|no matching distribution|"
       r"modulenotfounderror|cannot find module|ERESOLVE|npm ERR! (code )?E404|"
       r"resolutionimpossible|could not resolve dependencies)",
       "A dependency could not be found, resolved, or installed.",
       "Check the package name and version in the dependency file and that the package is published."),
    _r("network",
       r"(could not resolve host|connection (refused|reset)|econnreset|"
       r"temporary failure in name resolution|tls handshake timeout|connection timed out)",
       "A network request failed during the job.",
       "Retry the job, then check the remote service status and runner network access."),
    _r("timeout",
       r"(exceeded the (maximum|max) execution time|timeouterror|deadline exceeded|"
       r"timed out after|job timed out)",
       "A step or the whole job exceeded its time limit.",
       "Find the slow or hanging step, then speed it up or raise the timeout."),
    _r("docker_build",
       r"(failed to solve|executor failed running|returned a non-zero code)",
       "A Docker image build step failed.",
       "Read the failing Dockerfile step above this message and fix that command."),
    _r("compile_error",
       r"(syntaxerror|error TS\d+|error\[E\d+\]|cannot find symbol|"
       r"undefined reference|compilation failed|could not compile)",
       "The code failed to compile or has a syntax error.",
       "Fix the code at the file and line named in the error message."),
    _r("test_failure",
       r"(=+ FAILURES =+|FAILED \S+::|AssertionError|\b\d+ failed\b|Tests:\s+\d+ failed)",
       "One or more automated tests failed.",
       "Run the failing test locally, read the assertion message, and fix the code or the test."),
    _r("lint_format",
       r"(✖ \d+ problems?|eslint|flake8|\bruff\b|would reformat|code style issues|no-unused-vars)",
       "A lint or formatting check failed.",
       "Run the linter or formatter locally and fix or auto-format the reported lines."),
    _r("missing_file",
       r"(no such file or directory|enoent|filenotfounderror|can't open file)",
       "A file or directory the job needs was not found.",
       "Check the path, the working directory, and that earlier steps created the file."),
]


@dataclass(frozen=True)
class RuleMatch:
    category: str
    summary: str
    fix: str
    evidence: str


def classify(log_text: str) -> RuleMatch | None:
    lines = log_text.splitlines()
    for rule in RULES:
        for line in lines:
            if rule.pattern.search(line):
                return RuleMatch(rule.category, rule.summary, rule.fix, line.strip())
    return None
