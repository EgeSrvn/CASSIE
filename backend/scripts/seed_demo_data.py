#!/usr/bin/env python3
"""
Seed demo data files into MinIO and database.

This script reads the manifest.json from mock/data/ and uploads all referenced files
to MinIO under the demo user (user_id=0) bucket, then creates database records for them.

Usage:
    python3 seed_demo_data.py
"""

import sys
import json
import hashlib
import os
from pathlib import Path

# Add project root to path - handle both backend/scripts and scripts/ locations
script_dir = Path(__file__).parent
possible_roots = [
    script_dir.parent.parent,  # For /path/to/backend/scripts/
    script_dir.parent,  # For /path/to/scripts/
]

project_root = None
for root in possible_roots:
    if (root / "backend" / "api").exists():
        project_root = root
        break

if not project_root:
    # Fallback: assume we're in the repo root or adjust from cwd
    project_root = Path.cwd()
    if not (project_root / "backend" / "api").exists():
        project_root = Path(__file__).parent.parent.parent

sys.path.insert(0, str(project_root))

from backend.api.database.db_init import get_db_connection
from backend.api.services.minio_client import get_minio_client
from backend.api.models.pipeline_model import FileType
from backend.api.utils.logger import get_logger
from backend.api.utils.config_loader import get_config

logger = get_logger(__name__)

DEMO_USER_ID = 0
DEMO_USERNAME = "demo"


def get_file_checksum(file_path: str) -> str:
    """Calculate MD5 checksum of a file."""
    hash_md5 = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()


def seed_demo_data():
    """
    Read manifest.json and upload all referenced demo files to MinIO.
    Create database records for each file under user_id=0.
    """
    # Paths
    mock_data_dir = project_root / "mock" / "data"
    
    if not mock_data_dir.exists():
        logger.error(f"Mock data directory not found: {mock_data_dir}")
        logger.error(f"Current project root: {project_root}")
        return False
    
    manifest_path = mock_data_dir / "manifest.json"
    
    if not manifest_path.exists():
        logger.error(f"Manifest not found: {manifest_path}")
        return False
    
    # Read manifest
    try:
        with manifest_path.open("r", encoding="utf-8") as f:
            manifest = json.load(f)
    except Exception as e:
        logger.error(f"Failed to read manifest: {e}")
        return False
    
    datasets = manifest.get("datasets", [])
    if not datasets:
        logger.warning("No datasets in manifest")
        return True
    
    # Initialize MinIO client
    minio_client = get_minio_client()
    
    # Ensure demo user bucket exists
    try:
        logger.info(f"Ensuring bucket exists for demo user (id={DEMO_USER_ID})...")
        minio_client.ensure_user_bucket(DEMO_USER_ID, DEMO_USERNAME)
    except Exception as e:
        logger.error(f"Failed to ensure demo bucket: {e}")
        return False
    
    # Database connection
    with get_db_connection() as conn:
        cur = conn.cursor()
        
        try:
            uploaded_count = 0
            
            for dataset in datasets:
                dataset_id = dataset.get("dataset_id")
                files = dataset.get("files", [])
                
                logger.info(f"\nProcessing dataset: {dataset_id}")
                
                for filename in files:
                    file_path = mock_data_dir / filename
                    
                    if not file_path.exists():
                        logger.warning(f"  File not found: {filename}")
                        continue
                    
                    try:
                        # Get file info
                        file_size = file_path.stat().st_size
                        file_checksum = get_file_checksum(str(file_path))
                        
                        # Check if file already exists in database
                        cur.execute("""
                            SELECT id FROM files
                            WHERE user_id = %s AND filename = %s
                            LIMIT 1
                        """, (DEMO_USER_ID, filename))
                        
                        existing = cur.fetchone()
                        if existing:
                            logger.info(f"  File already in database: {filename} (id={existing[0]})")
                            continue
                        
                        # Upload to MinIO
                        logger.info(f"  Uploading {filename}...")
                        s3_key = f"data/{DEMO_USER_ID}/{filename}"
                        
                        upload_result = minio_client.upload_file(
                            user_id=DEMO_USER_ID,
                            local_path=str(file_path),
                            s3_key=s3_key,
                            username=DEMO_USERNAME
                        )
                        
                        # Infer file format from extension
                        _, ext = os.path.splitext(filename)
                        file_format = ext.lstrip('.').lower() if ext else None
                        
                        # Create database record
                        cur.execute("""
                            INSERT INTO files 
                            (user_id, filename, s3_key, file_type, file_format, size_bytes, checksum, uploaded_at)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
                            RETURNING id
                        """, (
                            DEMO_USER_ID,
                            filename,
                            s3_key,
                            FileType.INPUT.value,
                            file_format,
                            file_size,
                            file_checksum
                        ))
                        
                        file_id = cur.fetchone()[0]
                        logger.info(f"    ✓ Uploaded and registered (id={file_id}, size={file_size} bytes)")
                        uploaded_count += 1
                        
                    except Exception as e:
                        logger.error(f"  Failed to process {filename}: {e}")
                        continue
            
            conn.commit()
            logger.info(f"\n✓ Successfully uploaded {uploaded_count} demo data files")
            return True
            
        except Exception as e:
            conn.rollback()
            logger.error(f"Database error: {e}", exc_info=True)
            return False
        finally:
            cur.close()


if __name__ == "__main__":
    try:
        success = seed_demo_data()
        if success:
            print("\n✓ Demo data seeding completed successfully!")
            sys.exit(0)
        else:
            print("\n✗ Demo data seeding failed")
            sys.exit(1)
    except Exception as e:
        print(f"\n✗ Unexpected error: {e}")
        logger.error(f"Unexpected error during demo data seeding: {e}", exc_info=True)
        sys.exit(1)
