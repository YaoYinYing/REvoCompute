# Runner Readiness

Readiness is derived from Doctor checks, active SIF provenance, live receipts, and required smoke coverage. It is not a mutable flag.

After a prepared deployment, the controller publishes `runner-readiness.json`
under the server configuration directory. Production API admission can enforce
this snapshot with `RUNNER_ADMISSION_ENFORCED=true`; a family that is enabled
but not `READY` rejects only new submissions with its readiness reason. Existing
and running tasks are not cancelled when a later snapshot becomes stale.
