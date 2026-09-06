# Operator Guide

Operators manage deployment, configuration, Runner readiness, live acceptance,
fleet reporting, and recovery. A configured or enabled family is not necessarily
READY: the family has current Doctor, image, and live-test evidence. Readiness is
an operational diagnostic; task admission remains governed by enabled state,
access policy, and scheduler/runtime behavior.
