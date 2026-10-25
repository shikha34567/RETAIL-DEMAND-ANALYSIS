"""
RideIntel API Dependencies.

Provides dependency injection for ArtifactService to facilitate testing.
"""

from api.services.artifact_service import ArtifactService, service as default_service


def get_artifact_service() -> ArtifactService:
    """Dependency provider for ArtifactService."""
    return default_service

