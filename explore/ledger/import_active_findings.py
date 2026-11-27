"""Import retained active-check evidence into finalized reports in the configured ledger."""

from jobs import get_ledger


def main() -> None:
    ledger = get_ledger()
    imported = 0
    for job in ledger.list_jobs():
        if ledger.import_active_findings(job.job_id):
            imported += 1
            print(f"Updated report {job.job_id}")
    print(f"Reports updated: {imported}")


if __name__ == "__main__":
    main()
