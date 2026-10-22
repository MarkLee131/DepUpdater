"""Checked execution for external analyzers; failures are never analysis results."""
import subprocess


class AnalysisError(RuntimeError):
    """An analyzer failed to produce a trustworthy result."""


class AnalysisTimeout(AnalysisError):
    """An analyzer exceeded its time budget."""


def run_checked(command, *, timeout=300, input=None, reject_stderr=False):
    try:
        result = subprocess.run(
            command, input=input, text=True, capture_output=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise AnalysisTimeout(f"{command[0]} timed out after {timeout}s") from exc
    except OSError as exc:
        raise AnalysisError(f"Cannot start {command[0]}: {exc}") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()[-4000:]
        raise AnalysisError(f"{command[0]} exited with {result.returncode}: {detail}")
    if reject_stderr and result.stderr.strip():
        # The bundled BCEL tools catch parsing exceptions and still exit zero.
        raise AnalysisError(f"{command[0]} reported diagnostics: {result.stderr.strip()[-4000:]}")
    return result.stdout
