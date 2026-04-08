import socket
import struct
from scapy.all import Ether, IP, UDP, BOOTP, DHCP, sendp, get_if_hwaddr, conf
from pypxe.dhcp import DHCPD

class WinPXEDHCPD(DHCPD):
    def __init__(self, **server_settings):
        # On initialise la classe parente
        super().__init__(**server_settings)

        # On essaie de récupérer l'interface réseau associée à l'IP du serveur
        self.interface = server_settings.get('interface', conf.iface)
        self.logger.info(f"Using interface: {self.interface}")

        # On récupère l'adresse MAC de notre interface pour Scapy
        try:
            self.server_mac = get_if_hwaddr(self.interface)
        except:
            self.server_mac = "ff:ff:ff:ff:ff:ff" # Fallback (peu probable)

    def dhcp_offer(self, message):
        '''Répond au DISCOVER avec un OFFER via Scapy (Layer 2)'''
        client_mac_bin, header_response = self.craft_header(message)
        options_response = self.craft_options(2, client_mac_bin) # 2 = DHCPOFFER

        self.send_with_scapy(client_mac_bin, header_response + options_response)
        self.logger.info(f"DHCPOFFER sent via Scapy to {self.get_mac(client_mac_bin)}")

    def dhcp_ack(self, message):
        '''Répond au REQUEST avec un ACK via Scapy (Layer 2)'''
        client_mac_bin, header_response = self.craft_header(message)
        options_response = self.craft_options(5, client_mac_bin) # 5 = DHCPACK

        self.send_with_scapy(client_mac_bin, header_response + options_response)
        self.logger.info(f"DHCPACK sent via Scapy to {self.get_mac(client_mac_bin)}")

    def craft_options(self, opt53, client_mac):
        '''
            This method crafts the DHCP option fields (Improved for UEFI)
        '''
        response = self.tlv_encode(53, struct.pack('!B', opt53)) # message type
        response += self.tlv_encode(54, socket.inet_aton(self.ip)) # DHCP Server IP

        if not self.mode_proxy:
            # DHCP Complet (non utilisé ici normalement)
            subnet_mask = self.get_namespaced_static('dhcp.binding.{0}.subnet'.format(self.get_mac(client_mac)), self.subnet_mask)
            response += self.tlv_encode(1, socket.inet_aton(subnet_mask))
            router = self.get_namespaced_static('dhcp.binding.{0}.router'.format(self.get_mac(client_mac)), self.router)
            response += self.tlv_encode(3, socket.inet_aton(router))
            response += self.tlv_encode(51, struct.pack('!I', 86400)) # 24h lease

        # Option 60 : Obligatoire pour PXE
        response += self.tlv_encode(60, 'PXEClient')

        # Détection de l'architecture UEFI (Option 93)
        arch = 0
        if 93 in self.options[client_mac]:
            [arch] = struct.unpack("!H", self.options[client_mac][93][0])

        # Détection iPXE (Option 77) pour éviter la boucle infinie
        is_ipxe = False
        if 77 in self.options[client_mac]:
            if b'iPXE' in self.options[client_mac][77][0]:
                is_ipxe = True

        # Choix du fichier de boot
        if is_ipxe:
            # Si c'est déjà iPXE, on envoie le script de config
            filename = "boot.ipxe"
        elif arch in [7, 9]: # UEFI x64
            filename = "ipxe.efi"
        elif arch == 6: # UEFI x86
            filename = "ipxe_ia32.efi"
        else: # BIOS Legacy
            filename = "undionly.kpxe"

        # On peut surcharger par la config si besoin
        filename = self.get_namespaced_static('dhcp.binding.{0}.rom'.format(self.get_mac(client_mac)), filename)

        # Option 66 (Serveur TFTP/Next Server)
        response += self.tlv_encode(66, self.file_server)

        # Option 67 (Nom du fichier de boot)
        response += self.tlv_encode(67, filename.encode('ascii') + b'\x00')

        if self.mode_proxy:
            # Option 43 (Vendor Specific Information) - Version complète pour UEFI
            # On utilise le format PXE standard pour le ProxyDHCP

            # Sub-option 6: Discovery Control (8 = Disable Broadcast Discovery)
            # Sub-option 71: Boot Item (Type 0, Layer 0)

            # Format:
            # Sub-option 6: Tag(B), Len(B), Val(B) -> 3 items
            # Sub-option 71: Tag(B), Len(B), Type(H), Index(H) -> 4 items
            # End: Tag(B) -> 1 item
            # Total expected items: 8

            opt43 = struct.pack('!BBB BBH H B',
                6, 1, 8,            # Discovery Control
                71, 4, 0, 0,        # Boot Item (Type 0, Index 0)
                255)                # End

            response += self.tlv_encode(43, opt43)

        response += b'\xff'
        return response

    def send_with_scapy(self, client_mac_bin, raw_payload):
        '''Forge et envoie le paquet DHCP au niveau Ethernet'''

        # Le payload de PyPXE contient déjà le header BOOTP + Options
        # On doit juste l'encapsuler dans Ethernet/IP/UDP

        # Destination : Broadcast (pour être sûr que le client reçoive même sans IP)
        # Mais on peut aussi cibler la MAC du client.
        # PXE Spec recommande broadcast si le flag 'broadcast' est mis dans la requête client.

        pkt = (Ether(src=self.server_mac, dst="ff:ff:ff:ff:ff:ff") /
               IP(src=self.ip, dst="255.255.255.255") /
               UDP(sport=67, dport=68) /
               raw_payload)

        sendp(pkt, iface=self.interface, verbose=False)

if __name__ == "__main__":
    # Test minimal
    dhcp = WinPXEDHCPD(ip='192.168.1.10', mode_proxy=True)
    print("ProxyDHCP ready...")
