# Cassie Genomics Platform

A comprehensive genomic data analysis platform with multi-cloud support (AWS, GCP, Azure) for assembly, annotation, and quality control pipelines.

## Features

- **User Authentication**: Registration and login system
- **Multi-Cloud Support**: AWS (EC2/S3), GCP, and Azure integration
- **Data Upload**: Support for multiple genomic data formats (Illumina, PacBio, ONT, HiC, etc.)
- **Pipeline Configuration**: Visual pipeline builder and community workflow sharing
- **Job Management**: Monitor active and completed analysis jobs
- **Automated Infrastructure**: Auto-scaling compute instances with automatic cleanup

## Supported Analysis Types

- Read QC (FastQC-like)
- Genome size, heterozygosity, and repeat content estimation
- Assembly + Scaffolding + Error correction + Gap filling
- Post-assembly: Gene annotation, RepeatMasker, SEDEF/BISER, BUSCO
- Assembly QC: QUAST, SEDEF/BISER vs mrCaNaVaR

## Tech Stack

- **Frontend**: Next.js 14, React, TypeScript, Tailwind CSS
- **Backend**: Node.js, Express, MongoDB
- **Infrastructure**: Docker, Kubernetes, Nextflow/CWL
- **Cloud**: AWS EC2/S3, GCP Compute/Storage, Azure Compute/Blob

## Getting Started

### Prerequisites

- Node.js 18+
- MongoDB
- Docker and Docker Compose (optional)
- Kubernetes cluster (optional, for production)

### Installation

1. Clone the repository:
```bash
cd cassie_test
```

2. Install dependencies:
```bash
npm install
cd frontend && npm install
cd ../backend && npm install
```

3. Set up environment variables:
```bash
cp backend/.env.example backend/.env
# Edit backend/.env with your configuration
```

4. Start MongoDB (if not using Docker):
```bash
mongod
```

5. Start the development servers:
```bash
npm run dev
```

This will start:
- Frontend on http://localhost:3000
- Backend API on http://localhost:3001

### Using Docker

```bash
docker-compose up
```

### Kubernetes Deployment

```bash
kubectl apply -f k8s/deployment.yaml
```

## Project Structure

```
cassie_test/
├── frontend/          # Next.js frontend application
├── backend/           # Express.js backend API
├── nextflow/          # Nextflow pipeline definitions
├── k8s/              # Kubernetes deployment configs
├── Dockerfile         # Backend Docker image
├── Dockerfile.frontend # Frontend Docker image
└── docker-compose.yml # Docker Compose configuration
```

## Configuration

### Cloud Provider Setup

1. Navigate to the Configure page after logging in
2. Select your cloud provider (AWS/GCP/Azure)
3. Enter your credentials
4. Configure project details (genome size, data types, analyses)
5. Set S3/storage paths for your data

### Pipeline Creation

- Use the Visual Pipeline Builder to create custom workflows
- Browse the Community page for shared workflows
- Pipelines are automatically converted to Nextflow scripts

## API Endpoints

- `POST /api/auth/register` - User registration
- `POST /api/auth/login` - User login
- `POST /api/upload/presigned-url` - Get S3 upload URL
- `POST /api/projects/configure` - Save project configuration
- `GET /api/jobs` - List user jobs
- `POST /api/jobs` - Create new job
- `GET /api/community/workflows` - List community workflows

## Development

### Frontend Development

```bash
cd frontend
npm run dev
```

### Backend Development

```bash
cd backend
npm run dev
```

## Production Deployment

1. Build the frontend:
```bash
cd frontend && npm run build
```

2. Set production environment variables
3. Deploy using Docker or Kubernetes

## License

MIT

## References

- T2T Paper: https://www.nature.com/articles/s41586-021-03451-y
- GenomeScope2.0: https://github.com/tbenavi1/genomescope2.0
- ANViL Project: https://anvilproject.org/
- Gap Analysis: https://gap.cog.sanger.ac.uk/

