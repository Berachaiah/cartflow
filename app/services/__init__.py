"""
Business logic layer (PRD Ch.12 sec 5 "Service layer"). Services:
  - Enforce business rules and state transitions.
  - Coordinate repositories + integrations.
  - Own transaction boundaries for multi-step operations.
  - Raise app.core.exceptions.AppException subclasses on failure.

Routers call services; services call repositories. Routers should never
talk to the database directly.
"""
