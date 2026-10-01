"""Dependency injection providers for SentinelOps Project Knowledge Base."""

from app.knowledge.service import ProjectKnowledgeService

_shared_knowledge_service: ProjectKnowledgeService | None = None


def get_project_knowledge_service() -> ProjectKnowledgeService:
    """Provides the shared ProjectKnowledgeService instance."""
    global _shared_knowledge_service
    if _shared_knowledge_service is None:
        from app.projects.dependencies import get_project_store

        store = get_project_store()
        _shared_knowledge_service = ProjectKnowledgeService(project_store=store)
    return _shared_knowledge_service


def reset_knowledge_state() -> None:
    """Reset in-memory knowledge indices for test isolation."""
    global _shared_knowledge_service
    if _shared_knowledge_service is not None:
        _shared_knowledge_service.clear()
        _shared_knowledge_service = None
