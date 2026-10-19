import pytest
from pydantic import ValidationError
from app.schemas.job import JobNormalized

def test_job_normalized_valid():
    job = JobNormalized(
        external_id="ext-99",
        source="greenhouse",
        title="  Backend Engineer  ",
        company="Stripe",
        location="Remote",
        job_url="https://stripe.com/jobs/99"
    )
    assert job.title == "Backend Engineer" # Trimmed
    assert job.external_id == "ext-99"
    assert job.location == "Remote"
    assert job.description is None

def test_job_normalized_empty_title_fails():
    with pytest.raises(ValidationError):
        JobNormalized(
            external_id="ext-1",
            source="greenhouse",
            title="   ",
            company="Stripe",
            job_url="https://stripe.com/jobs/1"
        )

def test_job_normalized_missing_external_id_fails():
    with pytest.raises(ValidationError):
        JobNormalized(
            external_id="",
            source="greenhouse",
            title="Engineer",
            company="Stripe",
            job_url="https://stripe.com/jobs/1"
        )

def test_job_normalized_missing_url_fails():
    with pytest.raises(ValidationError):
        JobNormalized(
            external_id="ext-1",
            source="greenhouse",
            title="Engineer",
            company="Stripe",
            job_url=""
        )
