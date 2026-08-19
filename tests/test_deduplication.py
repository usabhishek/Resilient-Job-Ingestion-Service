import pytest
from app.services.repository import JobRepository
from app.schemas.job import JobNormalized

@pytest.mark.asyncio
async def test_job_deduplication_lifecycle(test_db_session):
    # Retrieve greenhouse source ID
    source = await JobRepository.get_source_by_name(test_db_session, "greenhouse")
    assert source is not None

    batch1 = [
        JobNormalized(
            external_id="gh-101",
            source="greenhouse",
            title="Backend Lead",
            company="Cloudflare",
            job_url="https://boards.greenhouse.io/cloudflare/101"
        ),
        JobNormalized(
            external_id="gh-102",
            source="greenhouse",
            title="Frontend Lead",
            company="Cloudflare",
            job_url="https://boards.greenhouse.io/cloudflare/102"
        )
    ]

    # First Insert
    new_count, dupe_count, failed_count = await JobRepository.insert_jobs_batch(
        test_db_session,
        source_id=source.id,
        normalized_jobs=batch1
    )
    await test_db_session.commit()

    assert new_count == 2
    assert dupe_count == 0
    assert failed_count == 0

    # Second Insert with same external_ids
    new_count_2, dupe_count_2, failed_count_2 = await JobRepository.insert_jobs_batch(
        test_db_session,
        source_id=source.id,
        normalized_jobs=batch1
    )
    await test_db_session.commit()

    assert new_count_2 == 0
    assert dupe_count_2 == 2
    assert failed_count_2 == 0

    # Third Insert with 1 existing and 1 new
    batch3 = [
        JobNormalized(
            external_id="gh-102", # Duplicate
            source="greenhouse",
            title="Frontend Lead",
            company="Cloudflare",
            job_url="https://boards.greenhouse.io/cloudflare/102"
        ),
        JobNormalized(
            external_id="gh-103", # New
            source="greenhouse",
            title="Security Engineer",
            company="Cloudflare",
            job_url="https://boards.greenhouse.io/cloudflare/103"
        )
    ]

    new_count_3, dupe_count_3, failed_count_3 = await JobRepository.insert_jobs_batch(
        test_db_session,
        source_id=source.id,
        normalized_jobs=batch3
    )
    await test_db_session.commit()

    assert new_count_3 == 1
    assert dupe_count_3 == 1
    assert failed_count_3 == 0

    # Verify total stored
    jobs, total = await JobRepository.list_jobs(test_db_session, source_id=source.id)
    assert total == 3
