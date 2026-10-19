from app.schemas.job import JobNormalized
from app.services.repository import JobRepository
from app.services import analytics


def make_jobs(n, company="Acme", prefix="j"):
    return [JobNormalized(external_id=f"{prefix}{i}", source="greenhouse", title=f"Engineer {i}",
                          company=company, location="Remote" if i % 2 else "Pune",
                          job_url=f"https://x.com/{prefix}{i}") for i in range(n)]


def test_repository_crud(db):
    # CREATE
    assert JobRepository.insert_jobs_batch(db, "u1", "greenhouse", make_jobs(3)) == (3, 0, 0)
    # READ + search
    jobs, total = JobRepository.list_jobs(db, "u1", search="engineer 1")
    assert total == 1 and jobs[0].title == "Engineer 1"
    # UPDATE
    job_id = jobs[0].id
    updated = JobRepository.update_job(db, "u1", job_id, {"title": "Principal Engineer", "is_active": False})
    assert updated.title == "Principal Engineer" and updated.is_active is False
    # DELETE
    assert JobRepository.delete_job(db, "u1", job_id) is True
    assert JobRepository.delete_job(db, "u1", job_id) is False
    assert JobRepository.list_jobs(db, "u1")[1] == 2


def test_in_batch_and_cross_batch_duplicates(db):
    batch = make_jobs(2) + make_jobs(2)          # same ids twice in one batch
    assert JobRepository.insert_jobs_batch(db, "u1", "greenhouse", batch) == (2, 2, 0)
    assert JobRepository.insert_jobs_batch(db, "u1", "greenhouse", make_jobs(3)) == (1, 2, 0)


def test_same_job_can_be_saved_by_two_users(db):
    assert JobRepository.insert_jobs_batch(db, "u1", "greenhouse", make_jobs(3)) == (3, 0, 0)
    assert JobRepository.insert_jobs_batch(db, "u2", "greenhouse", make_jobs(3)) == (3, 0, 0)


def test_users_only_see_and_change_their_own_jobs(db):
    JobRepository.insert_jobs_batch(db, "u1", "greenhouse", make_jobs(2))
    JobRepository.insert_jobs_batch(db, "u2", "greenhouse", make_jobs(5, prefix="k"))
    assert JobRepository.list_jobs(db, "u1")[1] == 2
    assert JobRepository.list_jobs(db, "u2")[1] == 5
    u2_job = JobRepository.list_jobs(db, "u2")[0][0]
    assert JobRepository.get_job(db, "u1", u2_job.id) is None
    assert JobRepository.update_job(db, "u1", u2_job.id, {"title": "Hacked"}) is None
    assert JobRepository.delete_job(db, "u1", u2_job.id) is False
    assert JobRepository.get_job(db, "u2", u2_job.id).title != "Hacked"


def test_pagination_reaches_every_record(db):
    JobRepository.insert_jobs_batch(db, "u1", "greenhouse", make_jobs(57))
    seen = set()
    for page in range(1, 7):
        jobs, total = JobRepository.list_jobs(db, "u1", page=page, limit=10)
        assert total == 57
        seen |= {j.id for j in jobs}
    assert len(seen) == 57                                      # nothing skipped, nothing repeated
    assert len(JobRepository.list_jobs(db, "u1")[0]) == 57      # limit=None still returns all


def test_aggregations(db):
    JobRepository.insert_jobs_batch(db, "u1", "greenhouse", make_jobs(5, "Acme") + make_jobs(2, "Beta", "b"))
    JobRepository.insert_jobs_batch(db, "u2", "greenhouse", make_jobs(1, "Other", "o"))
    run = JobRepository.create_ingestion_run(db, "u1", "greenhouse", "API")
    JobRepository.complete_ingestion_run(db, run.id, "SUCCESS", 7, 7, 0, 7, 0, 0)
    assert analytics.jobs_per_company(db, "u1")[0] == {"company": "Acme", "total_jobs": 5}
    assert analytics.jobs_per_source(db, "u1") == [{"source": "greenhouse", "total_jobs": 7, "company_count": 2}]
    assert analytics.jobs_per_source(db) == [{"source": "greenhouse", "total_jobs": 8, "company_count": 3}]
    assert analytics.top_locations(db, "u1")[0]["total_jobs"] >= 3
    stats = analytics.run_statistics_by_status(db, "u1")
    assert stats[0]["status"] == "SUCCESS" and stats[0]["total_new_jobs"] == 7
    assert analytics.runs_per_user(db)[0]["_id"] == "u1"
