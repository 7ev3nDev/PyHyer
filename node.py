import socket, ssl, threading, json, os, hashlib, time, sys, signal, shutil

# Configurazione
TRACKER_IP = '192.168.1.156' # Indirizzo IP del Server (da cambiare)
TRACKER_PORT = 5000          # Porta del Server
MY_PORT = 6000               # Porta su cui questo Peer accetta connessioni dagli altri
SHARE_DIR = './files'        # Cartella locale contenente i file da condividere
BUFFER_SIZE = 128 * 1024     # Dimensione del buffer (128KB) per ottimizzare letture/invii

os.makedirs(SHARE_DIR, exist_ok=True) # Creazione cartella condivisione se non esiste
HASH_CACHE = {} # Cache per memorizzazione hash file evitando ricalcoli se file non cambia

# Configurazione SSL sicura per connessioni in uscita
ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)
try:
    ctx.load_verify_locations('cert.pem')
    ctx.verify_mode = ssl.CERT_REQUIRED  # Obblighiamo il server a mostrare un certificato valido
    ctx.check_hostname = False           # Necessario se usiamo indirizzi IP e non nomi di domini
except Exception as e:
    print(f"Errore caricamento certificato: {e}")
    sys.exit(1)

"""Calcolo hash SHA256 con cache per ottimizzazione CPU"""
def get_hash(p):
    mtime = os.path.getmtime(p)

    # Restituisce hash salvato se già esiste
    if p in HASH_CACHE and HASH_CACHE[p]['mtime'] == mtime:
        return HASH_CACHE[p]['hash']
    
    h = hashlib.sha256()
    with open(p, "rb") as f:
        # Lettura a blocchi per evitare saturazione
        while chunk := f.read(BUFFER_SIZE):
            h.update(chunk)
    
    res = h.hexdigest()

    # Salvataggio hash appena calcolato
    HASH_CACHE[p] = {'hash': res, 'mtime': mtime}
    return res

"""Gestione uscita notificando logout al server"""
def signal_handler(sig, frame):
    try:
        with socket.create_connection((TRACKER_IP, TRACKER_PORT), timeout=2) as s:
            with ctx.wrap_socket(s) as ss:
                ss.sendall(json.dumps({"action": "LOGOUT", "port": MY_PORT}).encode())
    except: pass
    os._exit(0)

"""Invio aggiornamenti di stato al server"""
def notify_tracker(action, filename=None):
    try:
        data = {"action": action, "port": MY_PORT}
        if filename: data["file"] = filename

        # Se l'azione è REGISTER, invia anche la lista dei file locali aggiornata
        if action == "REGISTER":
            data["files"] = [f for f in os.listdir(SHARE_DIR) if os.path.isfile(os.path.join(SHARE_DIR, f))]
            
        with socket.create_connection((TRACKER_IP, TRACKER_PORT), timeout=3) as s:
            with ctx.wrap_socket(s) as ss:
                ss.sendall(json.dumps(data).encode())
    except ssl.SSLError:
        print("\033[91m[!] Impossibile stabilire una connessione sicura con il server. Controlla i certificati o l'IP.\033[0m")
        os._exit(1)
    except (socket.timeout, ConnectionRefusedError):
        if action == "REGISTER":
            print(f"\033[93m[!] Impossibile raggiungere il server {TRACKER_IP}. Controlla il server o l'IP.\033[0m")
            os._exit(1)
        return False    
    except Exception as e:
        print(f"\n[!] Errore di comunicazione: {e}")
        return False

"""Invio segnale keep-alive ogni 15 secondi su thread secondario"""
def heartbeat():
    while True:
        notify_tracker("REGISTER")
        time.sleep(15)

"""Invio file ad altri Peer su thread secondario"""
def p2p_server():
    s_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    s_ctx.load_cert_chain('cert.pem', 'key.pem')     # Carica certificato per cifrare la connessione
    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1) # Riutilizzo immediato porta
    server_sock.bind(('0.0.0.0', MY_PORT))
    server_sock.listen(10)
    
    with s_ctx.wrap_socket(server_sock, server_side=True) as ss:
        while True:
            try:
                # Accetta connessione e invia file con un nuovo thread
                c, _ = ss.accept()
                threading.Thread(target=handle_upload, args=(c,), daemon=True).start()
            except: pass

"""Gestione logica invio file a peer richiedente"""
def handle_upload(conn):
    with conn: # Chiusura automatica connessione a fine blocco
        try:
            # Riceve richiesta formato: "nome_file|offset"
            m = conn.recv(1024).decode().split('|')
            p = os.path.join(SHARE_DIR, m[0])
            offset = int(m[1]) # Punto da cui riprendere in caso di resume
            if os.path.exists(p):
                # Invio dimensione totale e hash per verifica integrità
                file_hash = get_hash(p)
                conn.send(f"{os.path.getsize(p)}|{file_hash}".encode())
                time.sleep(0.1)  # Pausa tecnica per sincronizzazione stream
                with open(p, 'rb') as f:
                    f.seek(offset) # Skippiamo parti già inviate in precedenza
                    while chunk := f.read(BUFFER_SIZE):
                        conn.sendall(chunk)
        except: pass

"""Gestione download di un file da un altro Peer con supporto resume"""
def download_sync(name, ip, port):
    try:
        notify_tracker("DOWNLOAD_START", name)
        path = os.path.join(SHARE_DIR, name)
        # Se il file esiste già parzialmente, calcola l'offset per riprendere da dove interrotto
        offset = os.path.getsize(path) if os.path.exists(path) else 0
        
        with socket.create_connection((ip, port), timeout=5) as s:
            with ctx.wrap_socket(s) as ss:
                # Invio richiesta download
                ss.sendall(f"{name}|{offset}".encode())
                info = ss.recv(1024).decode().split('|')
                total, r_hash = int(info[0]), info[1]

                # Se offset locale è uguale al totale del peer, il file è già completo
                if offset >= total: 
                    print(f"\n[*] {name} già completo."); return True

                # Controllo spazio sufficiente su disco
                if (total - offset) > shutil.disk_usage(SHARE_DIR).free:
                    print("\n[!] Spazio insufficiente!"); return False

                start_t = time.time()
                # Scrittura append per supporto resume
                with open(path, 'ab' if offset > 0 else 'wb') as f:
                    curr = offset
                    while curr < total:
                        chunk = ss.recv(BUFFER_SIZE)
                        if not chunk: break
                        f.write(chunk)
                        curr += len(chunk)
                        
                        # Barra progresso e velocità
                        speed = (curr - offset) / (time.time() - start_t + 0.001) / 1024
                        percent = 100 * curr / total
                        sys.stdout.write(f"\r[{'#'*int(percent/3.3):-<30}] {percent:.1f}% | {speed:.1f} KB/s")
                        sys.stdout.flush()
                
                print(f"\n[*] Verifica Hash...")
                # Confronto hash locale con quello mittente
                if get_hash(path) == r_hash:
                    print("[OK] File integro.")
                    notify_tracker("DOWNLOAD_COMPLETE", name)
                    return True
                else:
                    print("[!] Hash fallito! Riprovo..."); os.remove(path); return False
    except Exception as e:
        print(f"\n[!] Errore connessione fonte: {e}"); return False

"""Main programma"""
if __name__ == "__main__":
    # Gestione segnali di interruzione
    signal.signal(signal.SIGINT, signal_handler)

    # Avvio thread server
    threading.Thread(target=p2p_server, daemon=True).start()

    # Tentativo di collegamento al server
    print(f"[*] Tentativo di connessione al server ({TRACKER_IP})...")
    notify_tracker("REGISTER")

    # Avvio thread heartbeat
    threading.Thread(target=heartbeat, daemon=True).start()
    
    print(f"[*] Nodo attivo sulla porta {MY_PORT}")

    # Menu interattivo
    while True:
        try:
            q = input("\nCerca (Invio per tutti): ").strip()
            action = "LIST_ALL" if not q else "SEARCH"
            
            # Richiesta lista file al server
            with socket.create_connection((TRACKER_IP, TRACKER_PORT)) as s:
                with ctx.wrap_socket(s) as ss:
                    ss.sendall(json.dumps({"action": action, "query": q, "port": MY_PORT}).encode())
                    res = json.loads(ss.recv(8192).decode())
            res_dict = res.get('results', {})
            if not res_dict: print("Nessun file trovato."); continue 
            
            # Visualizzazione risultati
            f_list = list(res_dict.keys())
            for i, f in enumerate(f_list): 
                print(f"{i}: {f} ({len(res_dict[f])} fonti)")
            
            sel = int(input("Seleziona numero: "))
            fname, sources = f_list[sel], res_dict[f_list[sel]]

            # Logica scaricamento da più fonti
            success = False
            for i, (t_ip, t_port) in enumerate(sources):
                print(f"[*] Tentativo da fonte {i+1}: {t_ip}:{t_port}")
                if download_sync(fname, t_ip, t_port):
                    success = True; break
            
            if not success: print(f"[ERROR] Download fallito da tutte le fonti.")
        except KeyboardInterrupt: signal_handler(None, None)
        except Exception as e: print(f"Errore input: {e}")