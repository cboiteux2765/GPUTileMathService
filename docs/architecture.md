# Architecture (target)

Client -> API -> Queue -> GPU Worker -> Result Store -> Client

For now, Feature 1 is API-only with an in-memory store.
