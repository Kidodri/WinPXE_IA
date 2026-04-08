import socket
import struct
import os
import select
import time
import logging
import math
from pypxe import helpers

class ParentSocket(socket.socket):
    '''Subclassed socket.socket to enable a link-back to the client object.'''
    parent = None

class Client:
    '''Client instance for TFTPD.'''
    def __init__(self, mainsock, parent):
        self.default_retries = parent.default_retries
        self.timeout = parent.timeout
        self.ip = parent.ip
        self.message, self.address = mainsock.recvfrom(1024)
        self.logger = helpers.get_child_logger(parent.logger, 'Client.{0}'.format(self.address))
        self.netboot_directory = parent.netboot_directory
        self.logger.debug('Receiving request...')
        self.retries = self.default_retries
        self.block = 1
        self.blksize = 512
        self.sent_time = float('inf')
        self.dead = False
        self.fh = None
        self.filename = ''
        self.wrap = 0
        self.arm_wrap = False
        self.handle() # message from the main socket

    def ready(self):
        '''Called when there is something to be read on our socket.'''
        self.message = self.sock.recv(1024)
        self.handle()

    def send_block(self):
        data = None
        try:
            self.fh.seek(self.blksize * (self.block - 1))
            data = self.fh.read(self.blksize)
        except:
            self.logger.error('Error while reading block {0}'.format(self.block))
            self.dead = True
            return
        response = struct.pack('!HH', 3, self.block % 65536)
        response += data
        self.sock.sendto(response, self.address)
        self.logger.debug('Sending block {0}/{1}'.format(self.block, self.lastblock))
        self.retries -= 1
        self.sent_time = time.time()

    def no_ack(self):
        if self.sent_time + self.timeout < time.time():
            return True
        return False

    def no_retries(self):
        if not self.retries:
            return True
        return False

    def valid_mode(self):
        mode = self.message.split(b'\x00')[1]
        if mode == b'octet': return True
        self.send_error(5, 'Mode {0} not supported'.format(mode))
        return False

    def check_file(self):
        filename = self.message.split(b'\x00')[0].decode('ascii').lstrip('/')
        try:
            filename = helpers.normalize_path(self.netboot_directory, filename)
        except helpers.PathTraversalException:
            self.send_error(2, 'Path traversal error', filename = filename)
            return False
        if os.path.lexists(filename) and os.path.isfile(filename):
            self.filename = filename
            return True
        self.send_error(1, 'File Not Found', filename = filename)
        return False

    def parse_options(self):
        options = self.message.split(b'\x00')[2: -1]
        options = dict(zip((i.decode('ascii') for i in options[0::2]), map(int, options[1::2])))
        self.changed_blksize = 'blksize' in options
        if self.changed_blksize:
            self.blksize = options['blksize']
        self.lastblock = math.ceil(self.filesize / float(self.blksize))
        self.tsize = True if 'tsize' in options else False
        if len(options):
            self.block = 0
            return True
        else:
            return False

    def reply_options(self):
        response = struct.pack("!H", 6)
        if self.changed_blksize:
            response += b'blksize' + b'\x00'
            response += str(self.blksize).encode('ascii') + b'\x00'
        if self.tsize:
            response += b'tsize' + b'\x00'
            response += str(self.filesize).encode('ascii') + b'\x00'
        self.sock.sendto(response, self.address)

    def new_request(self):
        self.sock = ParentSocket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((self.ip, 0))
        self.sock.parent = self
        if not self.valid_mode() or not self.check_file():
            self.complete()
            return
        self.fh = open(self.filename, 'rb')
        self.filesize = os.path.getsize(self.filename)
        self.logger.info('File {0} ({1} bytes) requested'.format(self.filename, self.filesize))
        if not self.parse_options():
            if self.block == 1:
                self.send_block()
            return
        self.reply_options()

    def send_error(self, code = 1, message = 'File Not Found', filename = ''):
        response =  struct.pack('!H', 5)
        response += struct.pack('!H', code)
        response += message.encode('ascii')
        response += b'\x00'
        self.sock.sendto(response, self.address)
        self.logger.info('Sending {0}: {1} {2}'.format(code, message, filename))

    def complete(self):
        try:
            self.fh.close()
        except AttributeError:
            pass
        self.sock.close()
        self.dead = True

    def handle(self):
        [opcode] = struct.unpack('!H', self.message[:2])
        if opcode == 1:
            self.message = self.message[2:]
            self.new_request()
        elif opcode == 4:
            [block] = struct.unpack('!H', self.message[2:4])
            if block == 0 and self.arm_wrap:
                self.wrap += 1
                self.arm_wrap = False
            if block == 32768:
                self.arm_wrap = True
            if block < self.block % 65536:
                self.logger.warning('Ignoring duplicated ACK received for block {0}'.format(self.block))
            elif block > self.block % 65536:
                self.logger.warning('Ignoring out of sequence ACK received for block {0}'.format(self.block))
            elif block + self.wrap * 65536 == self.lastblock:
                if self.filesize % self.blksize == 0:
                    self.block = block + 1
                    self.send_block()
                self.logger.info('Completed sending {0}'.format(self.filename))
                self.complete()
            else:
                self.block = block + 1
                self.retries = self.default_retries
                self.send_block()
        elif opcode == 2:
            self.sock = ParentSocket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.sock.bind((self.ip, 0))
            self.sock.parent = self
            self.send_error(4, 'Write support not implemented')
            self.dead = True

class TFTPD:
    def __init__(self, **server_settings):
        self.ip = server_settings.get('ip', '0.0.0.0')
        self.port = int(server_settings.get('port', 69))
        self.netboot_directory = server_settings.get('netboot_directory', '.')
        self.mode_verbose = server_settings.get('mode_verbose', False)
        self.mode_debug = server_settings.get('mode_debug', False)
        self.logger = server_settings.get('logger', None)
        self.default_retries = server_settings.get('default_retries', 3)
        self.timeout = server_settings.get('timeout', 5)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((self.ip, self.port))

        if self.logger == None:
            self.logger = logging.getLogger('TFTP')
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

        self.ongoing = []

    def listen(self):
        while True:
            for client in self.ongoing:
                if client.dead:
                    self.ongoing.remove(client)
            rlist, _, _ = select.select([self.sock] + [client.sock for client in self.ongoing if not client.dead], [], [], 1)
            for sock in rlist:
                if sock == self.sock:
                    self.ongoing.append(Client(sock, self))
                else:
                    sock.parent.ready()
            [client.send_block() for client in self.ongoing if client.no_ack()]
            for client in self.ongoing:
                if client.no_retries():
                    client.logger.info('Timeout while sending {0}'.format(client.filename))
                    client.complete()
