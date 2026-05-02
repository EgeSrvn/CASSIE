#!/usr/bin/env python3
"""
Create an admin user with user_id = 0 for demo file uploads.

Demo users access files under user_id = 0, so uploading files to this account
makes them available to all demo sessions.

Usage:
    python3 create_demo_admin_user.py
"""

import sys
import os
from pathlib import Path
from datetime import datetime, timezone

# Add project root to path
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
    project_root = Path.cwd()
    if not (project_root / "backend" / "api").exists():
        project_root = Path(__file__).parent.parent.parent

sys.path.insert(0, str(project_root))

from backend.api.database.db_init import get_db_connection
from backend.api.services.user_service import hash_password
from backend.api.utils.logger import get_logger

logger = get_logger(__name__)


def create_demo_admin_user(username: str = "demo_admin", password: str = "DemoAdmin123!"):
    """
    Create an admin user with user_id = 0 for demo file uploads.
    
    Args:
        username: Username for the demo admin
        password: Password for the demo admin
    
    Returns:
        bool: True if successful
    """
    
    with get_db_connection() as conn:
        cur = conn.cursor()
        
        try:
            # Check if user with id 0 already exists
            cur.execute("SELECT id FROM users WHERE id = 0")
            existing = cur.fetchone()
            
            if existing:
                logger.info(f"User with id=0 already exists")
                return True
            
            # Hash password
            password_hash = hash_password(password)
            
            # Create bucket name for user 0
            bucket_name = "users/demo_admin"
            
            # Insert user with id = 0
            cur.execute("""
                INSERT INTO users 
                (id, username, email, password_hash, bucket_name, is_admin, is_active, email_verified, created_at, updated_at)
                VALUES (0, %s, %s, %s, %s, TRUE, TRUE, TRUE, NOW(), NOW())
                RETURNING id, username, email
            """, (
                username,
                f"{username}@demo.local",
                password_hash,
                bucket_name
            ))
            
            row = cur.fetchone()
            if row:
                user_id, created_username, email = row
                conn.commit()
                logger.info(f"✓ Created demo admin user:")
                logger.info(f"    User ID: {user_id}")
                logger.info(f"    Username: {created_username}")
                logger.info(f"    Email: {email}")
                logger.info(f"    Password: {password}")
                logger.info(f"\nYou can now login with these credentials and upload files.")
                logger.info(f"Files uploaded by this user (id=0) will be visible to all demo users.")
                return True
            else:
                logger.error("Failed to create user")
                return False
                
        except Exception as e:
            conn.rollback()
            logger.error(f"Error creating demo admin user: {e}", exc_info=True)
            return False
        finally:
            cur.close()


if __name__ == "__main__":
    try:
        # Allow custom username and password via CLI args
        username = sys.argv[1] if len(sys.argv) > 1 else "demo_admin"
        password = sys.argv[2] if len(sys.argv) > 2 else "DemoAdmin123!"
        
        success = create_demo_admin_user(username, password)
        if success:
            print("\n✓ Demo admin user created successfully!")
            sys.exit(0)
        else:
            print("\n✗ Failed to create demo admin user")
            sys.exit(1)
    except Exception as e:
        print(f"\n✗ Unexpected error: {e}")
        logger.error(f"Unexpected error: {e}", exc_info=True)
        sys.exit(1)

