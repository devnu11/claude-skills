"""Synonyms PowerShell asks to avoid."""


def delete_job(job):  # expect: verb-synonym warn
    """Prefer remove."""
    return job


def fetch_job(job):  # expect: verb-synonym warn
    """Prefer get."""
    return job
