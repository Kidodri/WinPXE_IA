from scapy.all import *
import threading

class ProxyDHCP:
    def __init__(self, interface_name, server_ip, boot_file="ipxe.efi"):
        self.interface = interface_name
        self.server_ip = server_ip
        self.boot_file = boot_file
        self.running = False
        self.pxe_clients = set() # Track MACs that have identified as PXE

    def handle_dhcp(self, pkt):
        if DHCP not in pkt:
            return

        # Robustly extract DHCP options into a dictionary
        dhcp_options = {}
        for opt in pkt[DHCP].options:
            if isinstance(opt, tuple):
                dhcp_options[opt[0]] = opt[1]
            elif isinstance(opt, str):
                dhcp_options[opt] = True
            if opt == 'end':
                break

        # print(f"DEBUG: DHCP Options from {pkt[Ether].src}: {dhcp_options}")

        msg_type = dhcp_options.get('message-type')
        if msg_type is None:
            return

        # Check for PXEClient or iPXE
        client_mac = pkt[Ether].src
        is_pxe = False
        vendor_class = dhcp_options.get('vendor_class_id')
        if vendor_class:
            if isinstance(vendor_class, bytes) and b'PXEClient' in vendor_class:
                is_pxe = True
            elif isinstance(vendor_class, str) and 'PXEClient' in vendor_class:
                is_pxe = True

        if is_pxe:
            if client_mac not in self.pxe_clients:
                print(f"Adding {client_mac} to PXE client tracking")
            self.pxe_clients.add(client_mac)

        is_ipxe = False
        # Scapy might use 'user_class' or 77. Also iPXE might send it as a string or bytes, or a list.
        # iPXE also sometimes identifies itself in Option 175.
        user_class = dhcp_options.get(77) or dhcp_options.get('user_class')

        def check_ipxe(val):
            if isinstance(val, (bytes, str)):
                return (b'iPXE' if isinstance(val, bytes) else 'iPXE') in val
            if isinstance(val, list):
                return any(check_ipxe(item) for item in val)
            return False

        if check_ipxe(user_class) or dhcp_options.get(175) or dhcp_options.get('ipxe'):
            is_ipxe = True

        # In ProxyDHCP mode, we ONLY respond to PXEClient requests
        # We also check our pxe_clients set in case the REQUEST omits Option 60
        if not is_pxe and client_mac not in self.pxe_clients:
            return

        boot_file = self.boot_file
        if is_ipxe:
            boot_file = f"http://{self.server_ip}/netboot/boot.ipxe"

        # Determine if this packet was sent to the standard ProxyDHCP port (4011)
        is_port_4011 = pkt.haslayer(UDP) and pkt[UDP].dport == 4011

        # Scapy can return integers or strings for message-type
        if msg_type == 1 or msg_type == 'discover':
            print(f"Detected {'iPXE' if is_ipxe else 'PXE'} Discover from {client_mac}")
            self.send_reply(pkt, boot_file, "offer")
        elif msg_type == 3 or msg_type == 'request':
            server_id = dhcp_options.get('server_id')
            # ProxyDHCP logic:
            # 1. If it's on port 4011, it's definitely for us.
            # 2. If it's on port 67, it MUST be targeting our Server ID to get an ACK from us.
            # If the client is requesting from the main DHCP server (like 192.168.100.1),
            # we must stay silent on port 67.
            if not is_port_4011 and server_id and server_id != self.server_ip:
                print(f"Ignoring Request from {client_mac} (Targeting Server ID: {server_id}, not ours)")
                return

            print(f"Detected {'iPXE' if is_ipxe else 'PXE'} Request from {client_mac} (Port 4011: {is_port_4011}, Server ID: {server_id})")
            print(f"   Client IP: {pkt[IP].src}, Next Server IP: {pkt[BOOTP].siaddr}, Flags: {hex(int(pkt[BOOTP].flags))}")
            self.send_reply(pkt, boot_file, "ack")

    def send_reply(self, request_pkt, boot_file, msg_type_str):
        # Destination logic
        dst_ip = "255.255.255.255"
        # Match client's broadcast flag in BOOTP - Cast to int to avoid Scapy FlagValue issues
        flags = int(request_pkt[BOOTP].flags)

        # Determine ports
        sport = 67
        dport = 68

        # If the request is from port 4011, it's a unicast request, we MUST unicast back.
        if request_pkt[UDP].dport == 4011:
            dst_ip = request_pkt[IP].src
            flags = 0x0000 # Unicast
            sport = 4011
            dport = 4011
        elif not (flags & 0x8000) and request_pkt[IP].src != "0.0.0.0":
            # Client requested unicast and has an IP
            dst_ip = request_pkt[IP].src

        # Build ProxyDHCP Reply (Offer or ACK)
        # We include Option 66 (TFTP Server) and 67 (Bootfile) in DHCP options for UEFI compatibility.
        # We also tune Option 43 (Vendor Specific Info) to satisfy strict PXE implementations.

        options = [
            ("message-type", msg_type_str),
            ("server_id", self.server_ip),
            ("vendor_class_id", b"PXEClient"),
            (66, self.server_ip.encode()),
            (67, boot_file.encode()), # No null terminator here, DHCP strings are usually length-prefixed or null-terminated by the protocol
            (43, b"\x06\x01\x08\xff"), # PXE Discovery Control: 8 (Unicast/Broadcast only)
            ("end")
        ]

        reply = (
            Ether(src=get_if_hwaddr(self.interface), dst=request_pkt[Ether].src) /
            IP(src=self.server_ip, dst=dst_ip) /
            UDP(sport=sport, dport=dport) /
            BOOTP(
                op=2,
                flags=flags,
                yiaddr="0.0.0.0",
                siaddr=self.server_ip,
                giaddr=request_pkt[BOOTP].giaddr,
                xid=request_pkt[BOOTP].xid,
                chaddr=request_pkt[BOOTP].chaddr,
                sname=b"\x00" * 64, # Clear sname
                file=boot_file.encode().ljust(128, b'\x00')
            ) /
            DHCP(options=options)
        )
        sendp(reply, iface=self.interface, verbose=False)
        print(f"Sent ProxyDHCP {msg_type_str.upper()} to {dst_ip} with bootfile: {boot_file}")

    def start(self):
        self.running = True
        print(f"Starting ProxyDHCP on {self.interface}...")
        # Sniff on standard DHCP ports (67/68) and the ProxyDHCP port (4011)
        sniff(iface=self.interface, filter="udp and (port 67 or port 68 or port 4011)", prn=self.handle_dhcp, stop_filter=lambda x: not self.running)

    def stop(self):
        self.running = False

if __name__ == "__main__":
    # Test stub
    import sys
    if len(sys.argv) < 3:
        print("Usage: python proxydhcp.py <interface_name> <server_ip>")
    else:
        pdhcp = ProxyDHCP(sys.argv[1], sys.argv[2])
        pdhcp.start()
