"""Auth tests generate isolated temporary service modules inside subprocesses.

Do not import checkout-local generated fixtures at collection: they are neither
required nor authoritative for this service's persistence and RPC scenarios.
"""
