from scapy.all import *
import threading

class ProxyDHCP:
    def __init__(self, interface_name, server_ip, boot_file="ipxe.efi"):
        self.interface = interface_name
        self.server_ip = server_ip
        self.boot_file = boot_file
        self.running = False

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
        is_pxe = False
        vendor_class = dhcp_options.get('vendor_class_id')
        if vendor_class:
            if isinstance(vendor_class, bytes) and b'PXEClient' in vendor_class:
                is_pxe = True
            elif isinstance(vendor_class, str) and 'PXEClient' in vendor_class:
                is_pxe = True

        is_ipxe = False
        if 77 in dhcp_options and b'iPXE' in dhcp_options[77]:
            is_ipxe = True

        # In ProxyDHCP mode, we ONLY respond to PXEClient requests
        if not is_pxe:
            return

        boot_file = self.boot_file
        if is_ipxe:
            boot_file = f"http://{self.server_ip}/netboot/boot.ipxe"

        # Determine if this packet was sent to the standard ProxyDHCP port (4011)
        is_port_4011 = pkt.haslayer(UDP) and pkt[UDP].dport == 4011

        # Scapy can return integers or strings for message-type
        if msg_type == 1 or msg_type == 'discover':
            print(f"Detected {'iPXE' if is_ipxe else 'PXE'} Discover from {pkt[Ether].src}")
            self.send_reply(pkt, boot_file, "offer")
        elif msg_type == 3 or msg_type == 'request':
            # In ProxyDHCP, we respond with an ACK if:
            # 1. The request is specifically for our Server ID
            # 2. OR the request came on port 4011 (ProxyDHCP unicast)
            # 3. OR the request is a broadcast and we already sent an offer (most common)
            # To stay simple and effective, we respond to any PXE Request.
            server_id = dhcp_options.get('server_id')

            # If server_id is present and it's NOT us, it means the client is accepting
            # an IP from another server. In ProxyDHCP, we SHOULD still send our boot info ACK.
            print(f"Detected {'iPXE' if is_ipxe else 'PXE'} Request from {pkt[Ether].src} (Port 4011: {is_port_4011}, Server ID: {server_id})")
            self.send_reply(pkt, boot_file, "ack")

    def send_reply(self, request_pkt, boot_file, msg_type_str):
        # Destination: Broadcast by default, but unicast if we have a client IP (port 4011 requests)
        dst_ip = "255.255.255.255"
        if request_pkt[IP].src != "0.0.0.0":
            dst_ip = request_pkt[IP].src

        # Build ProxyDHCP Reply (Offer or ACK)
        # We include Option 66 (TFTP Server) and 67 (Bootfile) in DHCP options for UEFI compatibility.
        # We also tune Option 43 (Vendor Specific Info) to satisfy strict PXE implementations.
        reply = (
            Ether(src=get_if_hwaddr(self.interface), dst=request_pkt[Ether].src) /
            IP(src=self.server_ip, dst=dst_ip) /
            UDP(sport=67, dport=68) /
            BOOTP(
                op=2,
                yiaddr="0.0.0.0",
                siaddr=self.server_ip,
                giaddr=request_pkt[BOOTP].giaddr,
                xid=request_pkt[BOOTP].xid,
                chaddr=request_pkt[BOOTP].chaddr,
                sname=self.server_ip.encode().ljust(64, b'\x00'),
                file=boot_file.encode().ljust(128, b'\x00')
            ) /
            DHCP(options=[
                ("message-type", msg_type_str),
                ("server_id", self.server_ip),
                ("vendor_class_id", b"PXEClient"),
                (66, self.server_ip.encode()),
                (67, boot_file.encode() + b"\x00"),
                # Option 43: PXE Vendor Specific Options
                # Suboption 6: 0x01, value 0x08 (PXE_DISCOVERY_CONTROL: bits 3=Disable multicast discovery, always use unicast/broadcast)
                # Suboption 10: 0x04, value 0x00 b'PXE' (PXE_MENU_PROMPT: Timeout 0, "PXE")
                (43, b"\x06\x01\x08\x0a\x04\x00\x50\x58\x45\xff"),
                ("end")
            ])
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
