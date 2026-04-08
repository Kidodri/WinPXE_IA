# WinPXE Server (Python / Scapy / UEFI)

Ce projet implémente un serveur PXE fonctionnel sur **Windows**, configuré en mode **ProxyDHCP**. Il permet de distribuer des fichiers de boot (comme iPXE) à des clients sur le réseau sans interférer avec le serveur DHCP principal (votre box internet par exemple).

## Points Clés

- **ProxyDHCP** : Fonctionne en complément de votre DHCP existant.
- **Scapy Integration** : Utilise Scapy pour envoyer les paquets DHCP au niveau Ethernet (Layer 2), contournant les limitations des sockets Windows sur les ports 67/68.
- **Support UEFI & BIOS** : Détecte l'architecture du client (Option 93) pour servir le bon fichier (`ipxe.efi` pour UEFI x64, `undionly.kpxe` pour BIOS Legacy).
- **Option 43 Enrichie** : Inclut les sous-options nécessaires pour que les BIOS UEFI acceptent l'offre ProxyDHCP.

## Prérequis

1.  **Python 3.x**
2.  **Npcap** : Indispensable pour Scapy sous Windows. [Télécharger Npcap](https://nmap.org/npcap/).
    - *Note : Lors de l'installation, assurez-vous de cocher "Install Npcap in WinPcap API-compatible Mode".*
3.  **Dépendances Python** :
    ```bash
    pip install scapy
    ```

## Structure du Projet

- `server.py` : Script principal pour lancer les services (DHCP, TFTP, HTTP).
- `winpxe_dhcp.py` : Implémentation du ProxyDHCP utilisant Scapy.
- `pypxe/` : Package contenant la logique de base des services (adapté de PyPXE).
- `netboot/` : Dossier où placer vos fichiers de boot (créé automatiquement au premier lancement).

## Utilisation

### 1. Préparation des fichiers de boot
Placez vos chargeurs d'amorçage dans le dossier `netboot/` :
- `ipxe.efi` (pour les machines UEFI)
- `undionly.kpxe` (pour les machines BIOS Legacy)

### 2. Configuration
Ouvrez `server.py` et adaptez la variable `SERVER_IP` avec l'adresse IP de votre machine Windows :
```python
SERVER_IP = '192.168.1.100'  # Remplacer par votre IP réelle
```

### 3. Démarrage du serveur
Lancez le serveur avec les privilèges Administrateur (nécessaire pour Scapy et les ports réseau bas niveau) :
```bash
python server.py
```
Ou en passant l'IP en argument :
```bash
python server.py 192.168.1.100
```

## Fonctionnement technique

Le serveur ProxyDHCP écoute les requêtes `DHCP DISCOVER` des clients PXE. Lorsqu'il en détecte une, il répond avec un `DHCP OFFER` contenant les informations suivantes :
- L'adresse IP du serveur de fichiers (Option 66)
- Le nom du fichier de boot (Option 67)
- Les informations spécifiques PXE (Option 43)

Grâce à Scapy, le paquet est forgé manuellement pour s'assurer qu'il respecte strictement les attentes des clients UEFI, souvent très exigeants sur la structure des paquets DHCP.

## Licence
Inspiré par le projet [PyPXE](https://github.com/pypxe/PyPXE).
