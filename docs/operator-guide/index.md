# Operator Guide

Operators manage deployment, configuration, Runner readiness, live acceptance,
fleet reporting, and recovery. A configured or enabled family is not necessarily
READY: admission rejects NEW work for families without current Doctor, image,
and live-test evidence, with an actionable reason. Existing tasks are not killed
when readiness later becomes stale.
