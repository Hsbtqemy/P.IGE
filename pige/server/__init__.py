"""HTTP server exposing the P.IGE service to the web interface and the Thunderbird extension.

The server is the only process that writes to the data directory. Interfaces
(web app, Thunderbird extension) talk to it over HTTPS and never touch storage.
"""
