#!/usr/bin/env python3
import sys
import json
import struct
import socket
import threading
import os

LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bridge_log.txt")
def log(msg):
    with open(LOG_FILE, "a") as f:
        f.write(f"{msg}\n")

cli_socket = None

def get_message():
    """Reads a message from Firefox with the 4-byte header."""
    raw_length = sys.stdin.buffer.read(4)
    if len(raw_length) < 4:
        return None
    msg_length = struct.unpack('@I', raw_length)[0]
    
    # Robust read loop for large data
    message = b''
    while len(message) < msg_length:
        chunk = sys.stdin.buffer.read(msg_length - len(message))
        if not chunk:
            break
        message += chunk
    return message.decode('utf-8')

def read_from_firefox():
    global cli_socket
    log("Bridge: Started reading from Firefox")
    while True:
        message_chars = get_message()
        if message_chars is None:
            log("Bridge: Firefox closed the pipe.")
            os._exit(0)
        
        if cli_socket:
            try:
                # Send the whole JSON object as one line.
                clean_msg = message_chars.replace('\n', '').replace('\r', '')
                cli_socket.sendall((clean_msg + '\n').encode('utf-8'))
            except Exception as e:
                log(f"Bridge: Failed to forward to CLI: {e}")

def send_to_firefox(msg_dict):
    """Sends a message to Firefox with the 4-byte header."""
    try:
        content = json.dumps(msg_dict).encode('utf-8')
        length = struct.pack('@I', len(content))
        sys.stdout.buffer.write(length)
        sys.stdout.buffer.write(content)
        sys.stdout.buffer.flush()
    except Exception as e:
        log(f"Bridge: Failed to send to Firefox: {e}")

def main():
    global cli_socket
    threading.Thread(target=read_from_firefox, daemon=True).start()

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(('127.0.0.1', 8766))
    server.listen(1)

    while True:
        conn, addr = server.accept()
        log("Bridge: CLI connected")
        cli_socket = conn
        try:
            f = conn.makefile('r', encoding='utf-8')
            for line in f:
                if not line: break
                send_to_firefox(json.loads(line.strip()))
        except Exception as e:
            log(f"Bridge: CLI connection error: {e}")
        finally:
            conn.close()
            cli_socket = None
            log("Bridge: CLI disconnected")

if __name__ == '__main__':
    main()
