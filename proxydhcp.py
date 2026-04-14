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

        msg_type = pkt[DHCP].options[0][1]

        # Check for PXEClient or iPXE
        is_pxe = False
        is_ipxe = False
        for opt in pkt[DHCP].options:
            if opt[0] == 'vendor_class_id' and b'PXEClient' in opt[1]:
                is_pxe = True
            if opt[0] == 77 and b'iPXE' in opt[1]:
                is_ipxe = True

        if not is_pxe:
            return

        boot_file = self.boot_file
        if is_ipxe:
            boot_file = f"http://{self.server_ip}/netboot/boot.ipxe"

        if msg_type == 1: # DHCP Discover
            print(f"Detected {'iPXE' if is_ipxe else 'PXE'} Discover from {pkt[Ether].src}")
            self.send_reply(pkt, boot_file, "offer")
        elif msg_type == 3: # DHCP Request
            # Check if this request is for us
            server_id = None
            for opt in pkt[DHCP].options:
                if opt[0] == 'server_id':
                    server_id = opt[1]
                    break

            if server_id == self.server_ip:
                print(f"Detected {'iPXE' if is_ipxe else 'PXE'} Request from {pkt[Ether].src}")
                self.send_reply(pkt, boot_file, "ack")

    def send_reply(self, request_pkt, boot_file, msg_type_str):
        # Build ProxyDHCP Reply (Offer or ACK)
        reply = (
            Ether(src=get_if_hwaddr(self.interface), dst=request_pkt[Ether].src) /
            IP(src=self.server_ip, dst="255.255.255.255") /
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
                (43, b"\x06\x01\x03\xff"),
                ("end")
            ])
        )
        sendp(reply, iface=self.interface, verbose=False)
        print(f"Sent ProxyDHCP {msg_type_str.upper()} with bootfile: {boot_file}")

    def start(self):
        self.running = True
        print(f"Starting ProxyDHCP on {self.interface}...")
        sniff(iface=self.interface, filter="udp and (port 67 or port 68)", prn=self.handle_dhcp, stop_filter=lambda x: not self.running)

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
