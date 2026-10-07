# LedgerGuard worker

The worker is a separate Celery process built from the backend image so it shares validated configuration, SQLAlchemy models, and domain code without creating a premature microservice. Docker Compose starts it with `celery -A ledgerguard.worker.celery_app worker` and verifies it with Celery's inspect ping.

Domain tasks begin on Day 9. Day 3 provides only the side-effect-free diagnostic task `ledgerguard.worker.ping`.
