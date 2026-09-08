# Operator Guide

Operators manage deployment, configuration, Runner readiness, live acceptance,
fleet reporting, and recovery. A configured or enabled family is not necessarily
READY: the family has current Doctor, image, and live-test evidence. `enabled !=
READY`; `runner-status` is the operator view of the same shared readiness
contract used by production submission admission. New submissions to a
technically non-READY family fail closed before durable task, upload, queue, or
Slurm side effects. Access entitlement and transient scheduler capacity remain
separate decisions. Readiness changes do not cancel tasks that are already
running.
