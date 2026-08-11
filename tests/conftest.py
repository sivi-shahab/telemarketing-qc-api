import os

# Must be set before any import that triggers Settings instantiation.
# Uses setdefault so a real .env in the environment is not clobbered when
# running against live infra, but tests always have a deterministic key.
TEST_API_KEY = "test-api-key-integration-12345"
os.environ.setdefault("API_KEY", TEST_API_KEY)
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("REDIS_URL", "redis://localhost:6378/0")
os.environ.setdefault("MINIO_ENDPOINT", "localhost:9000")
