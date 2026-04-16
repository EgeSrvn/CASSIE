# CASSIE: Cloud-based Assembly Streamlined Service Integration Engine

Automated genome assembly and annotation: Build a website that has many options for different assemblers and other tools depending on different data types: Illumina/Pacbio/ONT combinations, additional HiC, StrandSeq, BioNano combinations, RNAseq, etc. Use docker, k8s, nextflow/cwl. Automated runs will require creating EC instances as necessary and removing them when they are done. Uploading data to S3 would be nice, but the EC instances should be able to mount the S3. (GCP/Azure counterparts should replace EC/S3 terms). Check the T2T paper.

## Read QC  (fastqc could be reimplemented, should be easy)
## Genome size, heterozygosity, and repeat content estimation (https://www.nature.com/articles/s41467-020-14998-3)
## Assembler(s)+scaffolders+error correction. 
## Post-assembly work like gene annotation, RepeatMasker, segmental duplications (sedef/biser) 
## Assembly QC, using e.g., QUAST
## Assembly QC - sedef/biser vs mrcanavar
## The website should then spawn all these processes on e.g., AWS/GCP/Azure. Multi-cloud support would be very good to have (as an option in the interface)
## CAMP for more tools and inspiration

## Admin Panel

Temporary secret admin panel endpoint: `http://localhost:8000/_cassie_admin_console_7f3a9b`

Current default credentials:
- Username: `admin`
- Password: `admin`

The admin password can be changed from inside the panel after login.
This endpoint is intentionally exposed only on the backend host, not through the frontend app.
