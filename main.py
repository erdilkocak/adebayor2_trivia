from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import json
import random
import unicodedata
from typing import Dict, Optional

app = FastAPI()

# Web sitenin (JavaScript) bu API'ye erişebilmesi için CORS izni veriyoruz
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_PATH = "all_time_database.json"
MAX_MATCH_ATTEMPTS = 500  # sonsuz döngüye karşı güvenlik siniri


# ---------------------------------------------------------------------------
# Yardımcı fonksiyonlar
# ---------------------------------------------------------------------------
import re

def sanitize(text: str) -> str:
    """Aksanları kaldırır, Türkçe i/ı harflerini normalize eder ve sadece harf/rakam bırakır."""
    if not text:
        return ""
    # Parantez içlerini temizle: örn. Trezeguet (Mahmoud Hassan) -> Trezeguet
    text = re.sub(r'\(.*?\)', '', text)
    text = text.replace("İ", "i").replace("I", "ı").lower()
    nfkd = unicodedata.normalize("NFKD", text)
    only_ascii = "".join(c for c in nfkd if not unicodedata.combining(c))
    # Noktalama işaretlerini boşluğa çevir
    clean = re.sub(r'[^a-z0-9\s]', ' ', only_ascii)
    return " ".join(clean.split()).strip()


def is_answer_match(guess: str, full_player_name: str) -> bool:
    """
    Kullanıcının tahminini oyuncunun tam adı ve parçalarıyla esnek eşleştirir.
    Örn:
      - 'fabregas' -> 'Cesc Fabregas' (EŞLEŞİR)
      - 'cesc fabregas' -> 'Cesc Fabregas' (EŞLEŞİR)
      - 'van persie' -> 'Robin van Persie' (EŞLEŞİR)
      - 'icardi' -> 'Mauro Icardi' (EŞLEŞİR)
    """
    s_guess = sanitize(guess)
    s_full = sanitize(full_player_name)

    if not s_guess or not s_full:
        return False

    # 1. Tam birebir eşleşme
    if s_guess == s_full:
        return True

    # Oyuncunun isim parçaları (örn: ['cesc', 'fabregas'])
    tokens = s_full.split()

    # 2. Soyadı veya adı tek başına girildiyse (örn: 'fabregas' veya 'icardi')
    # Tek harflik kısaltmaları veya çok kısa bağlaçları (de, da, van hariç) eleyebilirsin
    if s_guess in tokens:
        return True

    # 3. Bileşik soyadlar için (örn: 'van persie' -> 'robin van persie')
    if len(s_guess) >= 3 and s_guess in s_full:
        # Kelime sınırında mı kontrolü (başka bir ismin içine yanlış kaynamasın)
        pattern = r'\b' + re.escape(s_guess) + r'\b'
        if re.search(pattern, s_full):
            return True

    return False


_db_cache = None


def load_db():
    """JSON veritabanını yükler ve önbelleğe alır.

    Beklenen format: [{"club_id": str, "club_name": str, "players": [str, ...]}, ...]
    Bozuk/eksik elemanlar sessizce atlanır, tüm dosya bozuksa boş liste döner.
    """
    global _db_cache
    if _db_cache is not None:
        return _db_cache

    try:
        with open(DB_PATH, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"⚠️ Veritabanı okunamadı: {e}")
        _db_cache = []
        return _db_cache

    clean = []
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            club_id = item.get("club_id")
            club_name = item.get("club_name")
            players = item.get("players")
            if not club_id or not club_name or not isinstance(players, list):
                continue
            players = [p for p in players if isinstance(p, str) and p.strip()]
            if not players:
                continue
            clean.append({"club_id": club_id, "club_name": club_name, "players": players})

    _db_cache = clean
    return _db_cache


def find_common_players(clubA: dict, clubB: dict):
    """İki kulüp arasındaki ortak oyuncuları bulur."""
    playersA = clubA.get("players", [])
    playersB = clubB.get("players", [])
    sanitizedB = {sanitize(p) for p in playersB}

    common = []
    for pA in playersA:
        if sanitize(pA) in sanitizedB:
            common.append(pA)
    return common


def pick_valid_match() -> Optional[dict]:
    """Ortak oyuncusu olan iki farklı kulüp seçer.

    Veritabanı boşsa / yetersizse ya da MAX_MATCH_ATTEMPTS denemede
    uygun eşleşme bulunamazsa None döner (sonsuz döngü riski yok).
    """
    db = load_db()
    if len(db) < 2:
        return None

    for _ in range(MAX_MATCH_ATTEMPTS):
        clubA, clubB = random.sample(db, 2)
        common = find_common_players(clubA, clubB)
        if common:
            return {
                "clubA": {
                    "id": clubA["club_id"],
                    "name": clubA["club_name"],
                    "league": "All-Time",
                    "color": "#123526",
                },
                "clubB": {
                    "id": clubB["club_id"],
                    "name": clubB["club_name"],
                    "league": "All-Time",
                    "color": "#1B4E36",
                },
                "common_players": list(dict.fromkeys(common)),
            }

    # Son çare: tüm ikilileri tara, ilk uygun olanı döndür
    for i in range(len(db)):
        for j in range(len(db)):
            if i == j:
                continue
            common = find_common_players(db[i], db[j])
            if common:
                return {
                    "clubA": {
                        "id": db[i]["club_id"],
                        "name": db[i]["club_name"],
                        "league": "All-Time",
                        "color": "#123526",
                    },
                    "clubB": {
                        "id": db[j]["club_id"],
                        "name": db[j]["club_name"],
                        "league": "All-Time",
                        "color": "#1B4E36",
                    },
                    "common_players": list(dict.fromkeys(common)),
                }

    return None


# ---------------------------------------------------------------------------
# REST endpoint (tekli / test amaçlı)
# ---------------------------------------------------------------------------
@app.get("/api/get-match")
def get_match():
    match = pick_valid_match()
    if match is None:
        return {"error": "Uygun eşleşme bulunamadı. Veritabanını kontrol edin."}

    return {
        "clubA": match["clubA"],
        "clubB": match["clubB"],
        "answers": match["common_players"],
    }


# ---------------------------------------------------------------------------
# WebSocket - 2 kişilik online oda sistemi
# ---------------------------------------------------------------------------
# Aktif odaları RAM'de tutan yapı
rooms: Dict[str, dict] = {}


def new_room(target_score: int = 5, turn_seconds: int = 12) -> dict:
    return {
        "players": {},       # player_name -> websocket
        "scores": {},        # player_name -> score
        "current_match": None,
        "target_score": target_score,
        "turn_seconds": turn_seconds,
    }


async def broadcast(room: dict, payload: dict):
    """Odadaki tüm oyunculara mesaj gönderir; kopuk soketleri sessizce yok sayar."""
    dead = []
    for name, ws in room["players"].items():
        try:
            await ws.send_json(payload)
        except Exception:
            dead.append(name)
    for name in dead:
        room["players"].pop(name, None)


async def start_new_round(room_id: str, room: dict):
    match = pick_valid_match()
    if match is None:
        await broadcast(room, {
            "type": "ERROR",
            "msg": "Uygun eşleşme bulunamadı, lütfen veritabanını kontrol edin.",
        })
        return
    room["current_match"] = match
    await broadcast(room, {
        "type": "ROUND_START",
        "clubA": match["clubA"],
        "clubB": match["clubB"],
        "scores": room["scores"],
    })


@app.websocket("/ws/{room_id}/{player_name}")
async def game_socket(websocket: WebSocket, room_id: str, player_name: str):
    await websocket.accept()

    player_name = (player_name or "").strip()
    if not player_name:
        await websocket.send_json({"type": "ERROR", "msg": "Geçersiz oyuncu ismi."})
        await websocket.close()
        return

    # Opsiyonel sorgu parametreleri (?target=5&timer=12)
    try:
        target_score = int(websocket.query_params.get("target", 5))
    except (TypeError, ValueError):
        target_score = 5
    try:
        turn_seconds = int(websocket.query_params.get("timer", 12))
    except (TypeError, ValueError):
        turn_seconds = 12

    if room_id not in rooms:
        rooms[room_id] = new_room(target_score, turn_seconds)

    room = rooms[room_id]

    # Oda dolu mu? (bu isimle daha önce girilmemişse reddet)
    if len(room["players"]) >= 2 and player_name not in room["players"]:
        await websocket.send_json({"type": "ERROR", "msg": "Oda dolu!"})
        await websocket.close()
        return

    room["players"][player_name] = websocket
    room["scores"].setdefault(player_name, 0)

    # Odaya katılım bildirimi
    await broadcast(room, {
        "type": "ROOM_STATUS",
        "players": list(room["players"].keys()),
    })

    # 2 kişi tamamlandığında ilk soruyu üret ve oyunu başlat
    if len(room["players"]) == 2 and room["current_match"] is None:
        await start_new_round(room_id, room)

    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")

            if msg_type == "SUBMIT_ANSWER":
                match = room.get("current_match")
                if match is None:
                    await websocket.send_json({
                        "type": "ERROR",
                        "msg": "Henüz aktif bir soru yok, rakip bekleniyor.",
                    })
                    continue

                guess = sanitize(data.get("guess", ""))
                if not guess:
                    continue
# Tahmin herhangi bir ortak oyuncuyla eşleşiyor mu?
                is_correct = any(is_answer_match(guess, p) for p in match["common_players"])

                if is_correct:
                    room["scores"][player_name] = room["scores"].get(player_name, 0) + 1
                    winner = player_name

                    await broadcast(room, {
                        "type": "ROUND_WIN",
                        "winner": winner,
                        "scores": room["scores"],
                        "common_players": match["common_players"],
                    })

                    if room["scores"][player_name] >= room["target_score"]:
                        await broadcast(room, {"type": "GAME_OVER", "winner": winner})
                        rooms.pop(room_id, None)
                        break
                    else:
                        await start_new_round(room_id, room)
                else:
                    # Sadece yanlış cevabı gönderen kişiye bildirim gider
                    await websocket.send_json({"type": "WRONG_ANSWER"})

            elif msg_type == "PING":
                await websocket.send_json({"type": "PONG"})

    except WebSocketDisconnect:
        pass
    except Exception as e:
        # Beklenmeyen bir hata odayı/uvicorn'u çökertmesin
        print(f"⚠️ WebSocket hatası (room={room_id}, player={player_name}): {e}")
    finally:
        if room_id in rooms:
            rooms[room_id]["players"].pop(player_name, None)
            if len(rooms[room_id]["players"]) == 0:
                rooms.pop(room_id, None)
            else:
                await broadcast(rooms[room_id], {"type": "PLAYER_LEFT", "player": player_name})
