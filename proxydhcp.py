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
            elif opt == 'end':
                break

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
            self.pxe_clients.add(client_mac)

        is_ipxe = False
        if 77 in dhcp_options and b'iPXE' in dhcp_options[77]:
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
            print(f"Detected {'iPXE' if is_ipxe else 'PXE'} Request from {client_mac} (Port 4011: {is_port_4011}, Server ID: {server_id})")
            print(f"   Client IP: {pkt[IP].src}, Next Server IP: {pkt[BOOTP].siaddr}, Flags: {hex(pkt[BOOTP].flags)}")
            self.send_reply(pkt, boot_file, "ack")

    def send_reply(self, request_pkt, boot_file, msg_type_str):
        # Destination logic
        dst_ip = "255.255.255.255"
        # Match client's broadcast flag in BOOTP
        flags = request_pkt[BOOTP].flags

        # If the request is from port 4011, it's a unicast request, we MUST unicast back.
        if request_pkt[UDP].dport == 4011:
            dst_ip = request_pkt[IP].src
            flags = 0x0000 # Unicast
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
            (67, boot_file.encode() + b"\x00"),
            (43, b"\x06\x01\x08\xff"), # PXE Discovery Control: 8 (Unicast/Broadcast only)
            ("end")
        ]

        reply = (
            Ether(src=get_if_hwaddr(self.interface), dst=request_pkt[Ether].src) /
            IP(src=self.server_ip, dst=dst_ip) /
            UDP(sport=67, dport=68) /
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
