"""Spike E toolkit — shared code copied into both fixture images.

Each image gets its own framework-specific bits (torch vs tensorflow)
via the deployment class's ``__init__``, but the I/O, introspection,
and VRAM helpers are common.
"""
