#!/usr/bin/env python3
"""
Seed database with FastQC workflow for demo purposes.

This script inserts a predefined FastQC workflow into the workflows table.
"""

import sys
import json
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from backend.api.database.db_init import get_db_connection
from backend.api.utils.logger import get_logger

logger = get_logger(__name__)


def read_pipeline_content() -> str:
    """Read the main.nf pipeline content."""
    pipeline_path = Path(__file__).parent.parent.parent / "pipelines" / "main.nf"
    if not pipeline_path.exists():
        logger.warning(f"Pipeline file not found: {pipeline_path}")
        return "# FastQC Pipeline\n# Placeholder workflow content"
    
    with open(pipeline_path, 'r') as f:
        return f.read()


def seed_fastqc_workflow():
    """Seed the database with FastQC workflow."""
    
    workflow_content = read_pipeline_content()
    
    with get_db_connection() as conn:
        cur = conn.cursor()
        
        try:
            # Check if workflow already exists
            cur.execute("""
                SELECT id FROM workflows 
                WHERE name = 'FastQC Quality Control' 
                AND workflow_type = 'predefined'
            """)
            existing = cur.fetchone()
            
            if existing:
                logger.info(f"FastQC workflow already exists with ID: {existing[0]}")
                return existing[0]
            
            # Insert workflow
            cur.execute("""
                INSERT INTO workflows (
                    name, description, workflow_type, workflow_content,
                    tools_used, workflow_steps, parameters_schema,
                    is_public, is_active, validation_status
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (
                "FastQC Quality Control",
                "FastQC quality control pipeline for sequencing data. Runs FastQC on input FASTQ files to generate quality reports.",
                "predefined",
                workflow_content,
                json.dumps(["fastqc"]),  # tools_used as JSONB
                json.dumps([{"step": 1, "name": "FastQC", "tool": "fastqc"}]),  # workflow_steps as JSONB
                json.dumps({  # parameters_schema as JSONB
                    "input": {
                        "type": "string",
                        "required": True,
                        "description": "Input FASTQ file path"
                    },
                    "outdir": {
                        "type": "string",
                        "required": False,
                        "default": "./results",
                        "description": "Output directory for results"
                    }
                }),
                True,  # is_public
                True,  # is_active
                "valid"  # validation_status
            ))
            
            workflow_id = cur.fetchone()[0]
            conn.commit()
            
            logger.info(f"✓ Successfully seeded FastQC workflow with ID: {workflow_id}")
            return workflow_id
            
        except Exception as e:
            conn.rollback()
            logger.error(f"Error seeding workflow: {e}", exc_info=True)
            raise
        finally:
            cur.close()


if __name__ == "__main__":
    try:
        workflow_id = seed_fastqc_workflow()
        print(f"\n[OK] FastQC workflow seeded successfully!")
        print(f"  Workflow ID: {workflow_id}")
        print(f"\nYou can now create jobs using this workflow_id: {workflow_id}")
        sys.exit(0)
    except Exception as e:
        print(f"\n[ERROR] Failed to seed workflow: {e}")
        sys.exit(1)

