"""Fix placeholder job entries in the database.

This small utility will look for jobs that match likely placeholder names
(e.g., 'A. naeslundii' or 'Hybrid Assembly') and ensure that they:
 - have a pipeline string that includes FastQC (or set to a sensible default)
 - have a results object pointing at the sample-results folder added in the repo
 - are set to completed and have completed_at set

Usage: python backend/scripts/fix_placeholder_job.py

NOTE: the script uses DATABASE_URL from env (same as backend)."""

from datetime import datetime
import sys

from backend.api.database.db_init import SessionLocal, engine, init_db
from backend.api.models.job_model import Job

# ensure tables exist
init_db()

def main():
    session = SessionLocal()
    try:
        # Try to find placeholder by name fragments
        candidates = session.query(Job).filter(Job.name.ilike('%hybrid assembly%') | Job.name.ilike('%naeslundii%')).all()
        if not candidates:
            print('No matching placeholder jobs found by name. Searching for jobs that mention fastqc in pipeline...')
            candidates = session.query(Job).filter(Job.pipeline.ilike('%fastqc%')).all()

        if not candidates:
            print('No candidate jobs found. Nothing to do.')
            return 0

        for job in candidates:
            print(f'Updating job id={job.id} name="{job.name}"')
            # Normalize pipeline to a comma-separated string if it's JSON-like
            p = job.pipeline or ''
            if 'fastqc' not in p.lower():
                p = 'fastqc,genomescope2,spades,quast'
                job.pipeline = p
            # Ensure results object exists and points to sample path if not already set
            if not job.results:
                job.results = {
                    'folder': '/sample-results/hybrid-assembly/',
                    'report': '/sample-results/hybrid-assembly/fastqc_report.html',
                    'files': ['/sample-results/hybrid-assembly/result.txt'],
                }
            else:
                # add missing keys
                if 'report' not in job.results and 'folder' in job.results:
                    job.results['report'] = job.results['folder'].rstrip('/') + '/fastqc_report.html'
                if 'files' not in job.results:
                    job.results['files'] = job.results.get('files', []) + ['/sample-results/hybrid-assembly/result.txt']

            job.status = 'completed'
            if not job.completed_at:
                job.completed_at = datetime.utcnow()

            session.add(job)
        session.commit()
        print('Updated', len(candidates), 'job(s).')
        return 0
    except Exception as e:
        session.rollback()
        print('Error:', e, file=sys.stderr)
        return 1
    finally:
        session.close()

if __name__ == '__main__':
    raise SystemExit(main())