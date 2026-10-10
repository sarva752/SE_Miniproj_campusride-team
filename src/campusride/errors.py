"""Domain errors shared by all CampusRide modules."""


class CampusRideError(Exception):
    """Base class for all domain errors."""


class ValidationError(CampusRideError):
    """Input data is invalid (maps to HTTP 400/422)."""


class AuthenticationError(CampusRideError):
    """Credentials are invalid or the account is locked (HTTP 401/423)."""


class PermissionDenied(CampusRideError):
    """The actor is not allowed to perform the action (HTTP 403)."""


class NotFound(CampusRideError):
    """Entity does not exist (HTTP 404)."""


class ConflictError(CampusRideError):
    """The action conflicts with current state, e.g. no seats left (HTTP 409)."""
