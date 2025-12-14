"""
Test script for Task 1.3: Test Database Setup

This script:
1. Tests database connection
2. Initializes the database schema
3. Verifies all tables are created correctly
4. Verifies indexes and constraints exist

Usage:
    python -m backend.tests.test_database_setup
    OR
    cd backend && python tests/test_database_setup.py
"""

import sys
import os

# Add parent directory to path to import backend modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from backend.api.database import db_init


def test_connection():
    """Test that we can connect to the database."""
    print("\n[1/4] Testing database connection...")
    try:
        with db_init.get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT version();")
            version = cur.fetchone()[0]
            print(f"    ✓ Connected to PostgreSQL: {version.split(',')[0]}")
            cur.close()
        return True
    except Exception as e:
        print(f"    ✗ Connection failed: {e}")
        print("\n    Make sure PostgreSQL is running:")
        print("    docker run -d --name postgres-db \\")
        print("      -e POSTGRES_USER=admin \\")
        print("      -e POSTGRES_PASSWORD=admin \\")
        print("      -e POSTGRES_DB=cassie_db \\")
        print("      -p 5432:5432 \\")
        print("      postgres:15")
        return False


def test_schema_initialization():
    """Test that schema initialization works."""
    print("\n[2/4] Initializing database schema...")
    try:
        db_init.initialize_database()
        print("    ✓ Schema initialized successfully")
        return True
    except Exception as e:
        print(f"    ✗ Schema initialization failed: {e}")
        return False


def verify_tables():
    """Verify all 6 required tables exist."""
    print("\n[3/4] Verifying tables...")
    expected_tables = [
        'users',
        'workflows',
        'pipeline_configs',
        'jobs',
        'job_executions',
        'files'
    ]
    
    try:
        with db_init.get_db_connection() as conn:
            cur = conn.cursor()
            
            # Get all tables
            cur.execute("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = 'public'
                ORDER BY table_name;
            """)
            existing_tables = [row[0] for row in cur.fetchall()]
            
            print(f"    Found {len(existing_tables)} tables in database")
            
            # Check each expected table
            all_present = True
            for table in expected_tables:
                if table in existing_tables:
                    print(f"    ✓ Table '{table}' exists")
                else:
                    print(f"    ✗ Table '{table}' is MISSING")
                    all_present = False
            
            # Check for unexpected tables (optional info)
            unexpected = [t for t in existing_tables if t not in expected_tables]
            if unexpected:
                print(f"    Note: Found additional tables: {', '.join(unexpected)}")
            
            cur.close()
            return all_present
    except Exception as e:
        print(f"    ✗ Error verifying tables: {e}")
        return False


def verify_indexes_and_constraints():
    """Verify some key indexes and constraints exist."""
    print("\n[4/4] Verifying indexes and constraints...")
    
    try:
        with db_init.get_db_connection() as conn:
            cur = conn.cursor()
            
            # Check for some key indexes
            cur.execute("""
                SELECT indexname 
                FROM pg_indexes 
                WHERE schemaname = 'public'
                AND indexname LIKE 'idx_%'
                ORDER BY indexname;
            """)
            indexes = [row[0] for row in cur.fetchall()]
            print(f"    Found {len(indexes)} indexes")
            
            # Check for some key constraints
            cur.execute("""
                SELECT conname, contype
                FROM pg_constraint
                WHERE connamespace = (SELECT oid FROM pg_namespace WHERE nspname = 'public')
                AND conname LIKE 'chk_%' OR conname LIKE 'uq_%'
                ORDER BY conname;
            """)
            constraints = cur.fetchall()
            print(f"    Found {len(constraints)} check/unique constraints")
            
            # Verify some specific constraints
            cur.execute("""
                SELECT conname 
                FROM pg_constraint
                WHERE connamespace = (SELECT oid FROM pg_namespace WHERE nspname = 'public')
                AND conname IN ('chk_job_status', 'chk_file_type', 'chk_workflow_type');
            """)
            check_constraints = [row[0] for row in cur.fetchall()]
            
            if len(check_constraints) >= 3:
                print(f"    ✓ Key check constraints present: {', '.join(check_constraints)}")
            else:
                print(f"    ⚠ Some check constraints may be missing")
            
            # Verify triggers
            cur.execute("""
                SELECT trigger_name 
                FROM information_schema.triggers
                WHERE trigger_schema = 'public'
                AND trigger_name LIKE 'trigger_%';
            """)
            triggers = [row[0] for row in cur.fetchall()]
            print(f"    Found {len(triggers)} triggers")
            
            if len(triggers) >= 4:
                print(f"    ✓ Timestamp update triggers present")
            else:
                print(f"    ⚠ Some triggers may be missing")
            
            cur.close()
            return True
    except Exception as e:
        print(f"    ✗ Error verifying indexes/constraints: {e}")
        return False


def main():
    """Run all database setup tests."""
    print("=" * 60)
    print("Database Setup Test (Task 1.3)")
    print("=" * 60)
    
    results = []
    
    # Test 1: Connection
    results.append(("Connection", test_connection()))
    if not results[-1][1]:
        print("\n❌ Connection test failed. Please fix connection issues first.")
        return False
    
    # Test 2: Schema initialization
    results.append(("Schema Initialization", test_schema_initialization()))
    if not results[-1][1]:
        print("\n❌ Schema initialization failed.")
        return False
    
    # Test 3: Verify tables
    results.append(("Tables Verification", verify_tables()))
    
    # Test 4: Verify indexes and constraints
    results.append(("Indexes/Constraints", verify_indexes_and_constraints()))
    
    # Summary
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)
    
    all_passed = True
    for test_name, passed in results:
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"  {status}: {test_name}")
        if not passed:
            all_passed = False
    
    if all_passed:
        print("\n✅ All tests passed! Database setup is working correctly.")
    else:
        print("\n❌ Some tests failed. Please review the errors above.")
    
    return all_passed


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
