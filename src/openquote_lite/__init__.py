"""OpenQuote Lite - a small, self-hosted endpoint that lets AI agents send
bounded, machine-readable quote requests to a service provider.

Every request lands in a local inbox and is reviewed by a person. The endpoint
never quotes prices, never books appointments and never confirms orders.
"""

__version__ = "0.1.1a1"
PROTOCOL_VERSION = "0.1"

__all__ = ["__version__", "PROTOCOL_VERSION"]
