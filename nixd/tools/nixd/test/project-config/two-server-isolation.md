# RUN: python3 %S/two-server-isolation.py

Two concurrently live server processes share one launch directory but receive
different usable roots. Interleaved hover and formatting requests must return
only each process's project-relative evaluator and formatter markers.
