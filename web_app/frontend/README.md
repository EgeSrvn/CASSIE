# Cassie Frontend

Next.js frontend application for the Cassie Genomics Platform.

## Quick Start

### Install Dependencies
```bash
npm install
```

### Run Development Server
```bash
npm run dev
```

Open [http://localhost:3000](http://localhost:3000) in your browser.

## Running Without Backend

The frontend can run independently for UI development. See [FRONTEND_ONLY.md](../FRONTEND_ONLY.md) for details.

## Environment Variables

Create a `.env.local` file (optional):
```
NEXT_PUBLIC_API_URL=http://localhost:3001
```

If not set, defaults to `http://localhost:3001`.

## Available Scripts

- `npm run dev` - Start development server
- `npm run build` - Build for production
- `npm run start` - Start production server
- `npm run lint` - Run ESLint

## Project Structure

```
frontend/
├── app/              # Next.js app directory (pages)
├── components/       # React components
├── lib/             # Utility functions
└── public/          # Static assets
```

## Tech Stack

- Next.js 14 (App Router)
- React 18
- TypeScript
- Tailwind CSS
- React Flow (for pipeline builder)

