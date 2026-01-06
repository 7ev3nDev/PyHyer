# 🐝 PyHyer

**PyHyer** (**Py**thon **Hy**brid Peer-to-Pe**er**) è una soluzione avanzata per lo scambio di file decentralizzato. Sfrutta una **Topologia Ibrida** per combinare la rapidità di ricerca di un server centrale con la potenza di trasferimento della rete Peer-to-Peer, il tutto protetto da uno strato crittografico **TLS/SSL** di livello industriale.

![Python](https://img.shields.io/badge/Python-3.8%2B-blue?logo=python&logoColor=white)
![Security](https://img.shields.io/badge/Security-TLS%2FSSL-success?logo=letsencrypt&logoColor=white)
![Architecture](https://img.shields.io/badge/Architecture-Hybrid%20P2P-orange)
![License](https://img.shields.io/badge/License-MIT-lightgrey)

---

## 🚀 Caratteristiche Principali

### 📡 Architettura Ibrida
* **Tracker (Centralizzato):** Gestisce l'indicizzazione in tempo reale e lo stato della rete mediante un Heartbeat System ogni 15 secondi, eliminando automaticamente le risorse non più disponibili. Grazie alla filosofia Zero-Storage, il Tracker non ospita mai i file, ottimizzando banda e risorse del server.
* **Peer (Decentralizzati):** Ogni nodo è un'entità "Servent" che integra un Upload Server multithread per servire file simultaneamente e un Download Client con logica di ricerca multi-fonte.

### 🔒 Sicurezza "Zero-Trust"
* **End-to-End Encryption:** Tutte le comunicazioni sono cifrate via TLS.
* **Identity Verification:** Sistema di *Kill-Switch* attivo. Se un nodo rileva un certificato non valido o manomesso sul Tracker, termina immediatamente il processo per prevenire attacchi Man-in-the-Middle.
* **SSL Handshake:** Autenticazione mutua basata su certificati X.509, evitando lo scambio di dati in mancanza di chiavi corrette.

### ⚡ Performance & Affidabilità
* **Smart Resume:** Supporto al resume dei download interrotti tramite gestione degli `offset` dei file.
* **Integrità SHA-256:** Verifica bit-a-bit del file scaricato con sistema di caching degli hash per evitare il ricalcolo di essi ottimizzando il carico sulla CPU.
* **Buffer Ottimizzato:** Trasferimento dati a blocchi (chunk da 128KB) per gestire file di grandi dimensioni senza saturare la RAM.

---

## ⚙️ Installazione e Configurazione

### Generazione Certificati SSL
Il sistema richiede una coppia di chiavi per la cifratura. Generala con OpenSSL:
```bash
openssl req -x509 -newkey rsa:4096 -keyout key.pem -out cert.pem -days 365 -nodes -subj "/CN=PyHyerTracker"
# Questo comando esempio genererà un file cert.pem (certificato pubblico) e un file key.pem (chiave privata), necessari per la cifratura del canale.
```

### Configurazione del Peer
Modifica il file `node.py` impostando l'indirizzo IP del Tracker:
```python
TRACKER_IP = '192.168.1.X' # L'IP della macchina che ospita tracker.py
MY_PORT = 6000             # La porta locale per ricevere file
```

---

## 💻 Guida all'Uso

Una volta configurati gli indirizzi IP e generati i certificati, il sistema è pronto per lo scambio file.

### 1. Avvio del Tracker (Server)
Il Tracker deve essere sempre il primo componente ad essere avviato per poter accogliere le registrazioni dei nodi.
```bash
python tracker.py
```
Comandi console disponibili: `map`, `history`, `clear`, `exit`.

### 2. Avvio Nodi (Peer)
Assicurati di avere dei file nella cartella ./files se vuoi condividere qualcosa, quindi avvia:
```bash
python node.py
```
Operazioni disponibili:
* Invio (vuoto): Scarica la lista di tutti i file disponibili nella rete.
* Ricerca: Inserisci una parola chiave per filtrare i file.
* Download: Seleziona l'ID del file per avviare il download sicuro.

---

## 📂 Struttura della Repository
```
PyHyer/
├── tracker.py       # Il "Cervello": Gestisce l'indice dei file e la topologia di rete.
├── node.py          # Il "Muscolo": Gestisce upload, download e interfaccia utente.
└── test_pem/
    └── cert.pem     # Certificato Pubblico: Necessario per l'autenticazione SSL/TLS.
    └── key.pem      # Chiave Privata: Necessaria per la cifratura dei canali di comunicazione.
```
