#!/usr/bin/env python3
"""stdin/stdout <-> TCP relay, for QEMU's guestfwd=...-cmd: (one process per
guest connection): lets the guest reach a host server at extra addresses
(the 'CDN that moves' in the exam-network VM test).
  relay.py PORT      connects to 127.0.0.1:PORT"""
import os
import socket
import sys
import threading

sock = socket.create_connection(("127.0.0.1", int(sys.argv[1])))


def up():
    while True:
        data = os.read(0, 65536)
        if not data:
            break
        sock.sendall(data)
    sock.shutdown(socket.SHUT_WR)


threading.Thread(target=up, daemon=True).start()
while True:
    data = sock.recv(65536)
    if not data:
        break
    os.write(1, data)
