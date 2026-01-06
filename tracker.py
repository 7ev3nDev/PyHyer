import socket, ssl, threading, json, time, os, sys
from datetime import datetime

"""Variabili globali"""
FILES_INDEX = {}       # Database in RAM
ACTIVE_PEERS = set()   # Insieme dei peer attualmente online (ip, porta)
DOWNLOAD_HISTORY = []  # Registro degli ultimi download completati
current_input = ""     # Buffer per mantenere il testo scritto nel prompt durante i log

"""Ritorna l'orario attuale formattato"""
def get_time():
    return datetime.now().strftime("%H:%M:%S")

"""Calcolo dimensione in byte di un oggetto Python"""
def get_size(obj, seen=None):
    size = sys.getsizeof(obj)
    if seen is None: seen = set()
    obj_id = id(obj)
    if obj_id in seen: return 0
    seen.add(obj_id)
    if isinstance(obj, dict):
        size += sum([get_size(v, seen) for v in obj.values()])
        size += sum([get_size(k, seen) for k in obj.keys()])
    elif hasattr(obj, '__iter__') and not isinstance(obj, (str, bytes, bytearray)):
        size += sum([get_size(i, seen) for i in obj])
    return size

"""Gestione log colorati :D"""
def log(action, message):
    colors = {
        "CONNECT": "\033[92m", "DISCONNECT": "\033[91m",
        "START": "\033[93m",   "SUCCESS": "\033[92m",
        "SEARCH": "\033[94m",  "INDEX": "\033[96m",
        "RESET": "\033[0m"
    }
    col = colors.get(action, colors["RESET"])
    
    # Trucco ANSI: torna all'inizio riga e cancella la riga corrente
    sys.stdout.write("\r\033[K") 
    print(f"[{get_time()}] {col}{action:<10}\033[0m | {message}")
    
    # Ristampa prompt
    sys.stdout.write(f"Tracker > {current_input}")
    sys.stdout.flush()

"""Gestione richieste in entrata da ogni singolo Peer"""
def handle_client(conn, addr):
    try:
        data = conn.recv(4096).decode()
        if not data: return
        req = json.loads(data)
        peer_id = (addr[0], req.get('port', 6000))
        peer_label = f"{peer_id[0]}:{peer_id[1]}"
        
        # Registrazione o Heartbeat
        if req['action'] in ['REGISTER', 'HEARTBEAT']:
            peer_ip = addr[0]
            peer_port = req.get('port', 6000)
            peer_id = (peer_ip, peer_port)
            peer_label = f"{peer_ip}:{peer_port}"
            
            is_new = peer_id not in ACTIVE_PEERS
            new_files = req.get('files', [])
            new_count = len(new_files)

            # Calcoliamo quanti file avevamo PRIMA di aggiornare
            old_count = sum(1 for ps in FILES_INDEX.values() if peer_id in ps)

            if is_new:
                ACTIVE_PEERS.add(peer_id)
                log("CONNECT", f"Nuovo peer: {peer_label}")
                log("INDEX", f"{peer_label} ha indicizzato {new_count} file.")
            elif old_count != new_count:
                log("INDEX", f"Variazione risorse per {peer_label}: {old_count} -> {new_count} file.")

            # Aggiornamento fisico indice
            for f in list(FILES_INDEX.keys()):
                if peer_id in FILES_INDEX[f]:
                    del FILES_INDEX[f][peer_id]
                if not FILES_INDEX[f]:
                    del FILES_INDEX[f]

            # Inserimento nuovi dati
            for f in new_files:
                if f not in FILES_INDEX: FILES_INDEX[f] = {}
                FILES_INDEX[f][peer_id] = time.time()
            
            conn.send(json.dumps({"status": "OK"}).encode())

        # Ricerca file o richiesta catalogo completo    
        elif req['action'] in ['SEARCH', 'LIST_ALL']:
            is_list_all = req['action'] == 'LIST_ALL'
            query = "" if is_list_all else req.get('query', '').lower()
            
            if is_list_all:
                log("INDEX", f"Peer {peer_label} ha richiesto il catalogo completo (LIST_ALL)")
            else:
                log("SEARCH", f"Peer {peer_label} sta cercando: '{query}'")

            now = time.time()
            results = {}
            for f, ps in FILES_INDEX.items():
                if is_list_all or query in f.lower():
                    active_ps = [p for p, ts in ps.items() if now - ts < 30]
                    if active_ps:
                        results[f] = active_ps
            
            conn.send(json.dumps({"status": "OK", "results": results}).encode())

        # Monitoraggio download    
        elif req['action'] == 'DOWNLOAD_START':
            log("START", f"{peer_label} sta scaricando '{req['file']}'")
        elif req['action'] == 'DOWNLOAD_COMPLETE':
            DOWNLOAD_HISTORY.append(f"{get_time()} | {peer_label} -> {req['file']}")
            log("SUCCESS", f"{peer_label} ha finito '{req['file']}'")

        # Chiusura pulita sessione
        elif req['action'] == 'LOGOUT':
            log("DISCONNECT", f"Peer {peer_label} uscito.")
            if peer_id in ACTIVE_PEERS: ACTIVE_PEERS.remove(peer_id)
            for f in list(FILES_INDEX.keys()):
                if peer_id in FILES_INDEX[f]: del FILES_INDEX[f][peer_id]

    except: pass
    finally: conn.close()

"""Loop accettazione nuove connessioni SSL"""
def server_loop(ss):
    while True:
        try:
            c, a = ss.accept()
            threading.Thread(target=handle_client, args=(c, a), daemon=True).start()
        except ssl.SSLError:
            # Pulizia della riga del prompt, stampa errore e ripristino prompt
            sys.stdout.write(f"\r\033[K[!] Errore SSL: Tentativo di connessione con certificato non valido.\nTracker > ")
            sys.stdout.flush()
        except Exception as e:
            sys.stdout.write(f"\r\033[K[!] Errore connessione: {e}\nTracker > ")
            sys.stdout.flush()

"""Thread per rimuove peer non rispondenti"""
def cleanup_worker():
    while True:
        time.sleep(10); now = time.time()
        to_remove = set()
        for f in list(FILES_INDEX.keys()):
            for p, ts in list(FILES_INDEX[f].items()):
                if now - ts > 30:
                    to_remove.add(p); del FILES_INDEX[f][p]
            if not FILES_INDEX[f]: del FILES_INDEX[f]
        for p in to_remove:
            if p in ACTIVE_PEERS:
                log("EXPIRE", f"Peer {p[0]}:{p[1]} rimosso (timeout).")
                ACTIVE_PEERS.remove(p)

"""Main programma"""
if __name__ == "__main__":
    # Configurazione SSL con certificati locali
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain('cert.pem', 'key.pem')

    # Setup socket TCP
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(('0.0.0.0', 5000)); s.listen(15)
    ss = ctx.wrap_socket(s, server_side=True)

    print(f"\033[95m[*] Tracker P2P avviato sulla porta 5000\033[0m")
    
    # Avvio thread ascolto e pulizia
    threading.Thread(target=server_loop, args=(ss,), daemon=True).start()
    threading.Thread(target=cleanup_worker, daemon=True).start()

    # Console interattiva
    while True:
        cmd = input("Tracker > ").strip().lower()
        
        if cmd == "map":
            num_peers = len(ACTIVE_PEERS)
            num_files = len(FILES_INDEX)

            # Calcolo peso indice
            index_bytes = get_size(FILES_INDEX)
            index_kb = index_bytes / 1024
            
            print(f"\n\033[95m[ MAPPA DELLA RETE ]\033[0m")
            print(f"      [TRACKER (Porta 5000)]")
            
            if not ACTIVE_PEERS:
                print(f"         └── (Nessun peer connesso)")
            else:
                peer_list = list(ACTIVE_PEERS)
                for i, p in enumerate(peer_list):
                    connector = "└──" if i == len(peer_list) - 1 else "├──"
                    p_id = (p[0], p[1])
                    files_count = sum(1 for ps in FILES_INDEX.values() if p_id in ps)
                    print(f"         {connector} (Online) Peer: {p[0]}:{p[1]} [{files_count} file]")
            
            print(f"\n--- STATISTICHE RISORSE ---")
            print(f"File unici indicizzati: {num_files}")
            print(f"Peso dell'indice in RAM: {index_kb:.2f} KB ({index_bytes} bytes)")
            print(f"\033[95m" + "─" * 40 + "\033[0m")
        elif cmd == "history":
            print(f"\n--- STORICO DOWNLOAD ---")
            if not DOWNLOAD_HISTORY: print("Nessun download completato finora.")
            for entry in DOWNLOAD_HISTORY[-10:]: # Mostra gli ultimi 10
                print(f" > {entry}")
            print(f"------------------------")    
        elif cmd == "exit":
            print("[!] Spegnimento Tracker...")
            os._exit(0)
        elif cmd == "clear":
            os.system('clear' if os.name == 'posix' else 'cls')
        elif cmd == "help":
            print("Comandi disponibili: map, history, clear, exit, help")    
        elif cmd == "":
            continue
        else:
            print(f"Comando '{cmd}' non riconosciuto. (status, exit, clear)")
