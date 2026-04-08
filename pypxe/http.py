import socket
import struct
import os
import threading
import logging
from pypxe import helpers

class HTTPD:
    def __init__(self, **server_settings):
        self.ip = server_settings.get('ip', '0.0.0.0')
        self.port = int(server_settings.get('port', 80))
        self.netboot_directory = server_settings.get('netboot_directory', '.')
        self.mode_verbose = server_settings.get('mode_verbose', False)
        self.mode_debug = server_settings.get('mode_debug', False)
        self.logger =  server_settings.get('logger', None)

        if self.logger == None:
            self.logger = logging.getLogger('HTTP')
            handler = logging.StreamHandler()
            formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(name)s %(message)s')
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)

        if self.mode_debug:
            self.logger.setLevel(logging.DEBUG)
        elif self.mode_verbose:
            self.logger.setLevel(logging.INFO)
        else:
            self.logger.setLevel(logging.WARN)

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((self.ip, self.port))
        self.sock.listen(5)

    def handle_request(self, connection, addr):
        try:
            request = connection.recv(1024)
            if not request:
                connection.close()
                return
            lines = request.decode('ascii').split('\r\n')
            if not lines:
                connection.close()
                return
            parts = lines[0].split(' ')
            if len(parts) < 3:
                connection.close()
                return
            method, target, version = parts
            target = target.lstrip('/')
            try:
                target = helpers.normalize_path(self.netboot_directory, target)
                if not os.path.lexists(target) or not os.path.isfile(target):
                    status = '404 Not Found'
                elif method not in ('GET', 'HEAD'):
                    status = '501 Not Implemented'
                else:
                    status = '200 OK'
            except helpers.PathTraversalException:
                status = '403 Forbidden'

            response = 'HTTP/1.1 {0}\r\n'.format(status)
            if status[:3] != '200':
                connection.send(response.encode('ascii'))
                connection.close()
                return

            response += 'Content-Length: {0}\r\n'.format(os.path.getsize(target))
            response += '\r\n'
            connection.send(response.encode('ascii'))

            if method == 'GET':
                with open(target, 'rb') as handle:
                    while True:
                        data = handle.read(8192)
                        if not data: break
                        connection.send(data)
        except Exception as e:
            self.logger.error(f"Error handling HTTP request: {e}")
        finally:
            connection.close()

    def listen(self):
        while True:
            conn, addr = self.sock.accept()
            client = threading.Thread(target = self.handle_request, args = (conn, addr))
            client.daemon = True
            client.start()
