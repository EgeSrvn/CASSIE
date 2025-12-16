import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.database.db_init import init_db
from backend.api.routes import auth, jobs, pipelines, community


def create_app() -> FastAPI:
  app = FastAPI(title="Cassie API", version="1.0.0")

  # CORS configuration – by default allow all origins so the Next.js frontend can talk to us
  frontend_origin = os.getenv("FRONTEND_ORIGIN")
  if frontend_origin:
    origins = [frontend_origin]
  else:
    origins = ["*"]

  app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
  )

  # Routers
  app.include_router(auth.router)
  app.include_router(jobs.router)
  app.include_router(pipelines.router)
  app.include_router(community.router)

  # Initialize database tables
  @app.on_event("startup")
  def on_startup():
    init_db()

  @app.get("/api/health")
  def health():
    return {"status": "ok"}

  return app


app = create_app()


