import requests, time, re, os, json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

MODE = "DEBUG"

CFG = {
    "DEBUG": dict(
        PRINT_DETAILS=False,
        PRINT_CAPTURE_SUMMARY=True,
        PRINT_CAPTURE_LIST=False,
        DUMP_ENABLED=True,
        STOP_AFTER_N=None,
        DAY_WINDOW_MODE="calendar",
    ),
    "ONLINE": dict(
        PRINT_DETAILS=False,
        PRINT_CAPTURE_SUMMARY=False,
        PRINT_CAPTURE_LIST=False,
        DUMP_ENABLED=False,
        STOP_AFTER_N=None,
        DAY_WINDOW_MODE="sports",
    ),
}

conf = CFG.get(MODE, CFG["DEBUG"])
PRINT_DETAILS = conf["PRINT_DETAILS"]
PRINT_CAPTURE_SUMMARY = conf["PRINT_CAPTURE_SUMMARY"]
PRINT_CAPTURE_LIST = conf["PRINT_CAPTURE_LIST"]
DUMP_ENABLED = conf["DUMP_ENABLED"]
STOP_AFTER_N = conf["STOP_AFTER_N"]
DAY_WINDOW_MODE = conf["DAY_WINDOW_MODE"]

API = "https://mlb25.theshow.com/apis/game_history.json"
PLATFORM = "psn"
MODE = "LEAGUE"
SINCE = datetime(2025, 11, 29)  # ← usaremos esta fecha como inicio de Postemporada
PAGES = tuple(range(1, 7))
TIMEOUT = 20
RETRIES = 2

PRINT_DETAILS = False
STOP_AFTER_N = None
DUMP_ENABLED = True
DUMP_DIR = "out"
PRINT_CAPTURE_SUMMARY = True
PRINT_CAPTURE_LIST = False

LEAGUE_ORDER_FROM_IMAGE = [
("ENOVA23", "Red Sox"),
("EFLORES1306", "Yankees"),
("alex08201996", "Blue Jays"),
("osnielito4004", "Tigers"),
("Eduardo94Cuba", "Mariners"),
("Sacapeo860", "Mets"),
("TheTsunami24", "Phillies"),
("Santinueva3", "Cubs"),
("Handy-Barreto", "Dodgers"),
("Tabla25", "Padres"),
]

# Alias para compatibilidad con otros módulos (update_cache.py, compute_rows, etc.)
LEAGUE_ORDER = LEAGUE_ORDER_FROM_IMAGE

FETCH_ALIASES = {
    "EFLORES1306": ["EFLORESS1306"],
    "Sacapeo860": ["CMALDONADO101","CALLMETYRONE860"],
}

TEAM_RECORD_ADJUSTMENTS = {
"Yankees": (0, -3),
"Blue Jays": (-1, -1),
"Cubs": (-1, -1),
"Red Sox": (-2, -2),

}

TEAM_POINT_ADJUSTMENTS = {}


LEAGUE_USERS = {u for (u, _t) in LEAGUE_ORDER_FROM_IMAGE}
for base, alts in FETCH_ALIASES.items():
    LEAGUE_USERS.add(base)
    LEAGUE_USERS.update(alts)
LEAGUE_USERS.update({"AiramReynoso_", "Yosoyreynoso_"})
LEAGUE_USERS_NORM = {u.lower() for u in LEAGUE_USERS}

BXX_RE = re.compile(r"\^(b\d+)\^", flags=re.IGNORECASE)


def _safe_name(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", s or "")


def _dump_json(filename: str, data):
    if not DUMP_ENABLED:
        return
    os.makedirs(DUMP_DIR, exist_ok=True)
    path = os.path.join(DUMP_DIR, filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path


def normalize_user_for_compare(raw: str) -> str:
    if not raw:
        return ""
    return BXX_RE.sub("", raw).strip().lower()


def is_cpu(raw: str) -> bool:
    return normalize_user_for_compare(raw) == "cpu"


def parse_date(s: str):
    for fmt in ("%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M"):
        try:
            return datetime.strptime(s, fmt)
        except:
            pass
    return None


def fetch_page(username: str, page: int):
    params = {"username": username, "platform": PLATFORM, "page": page}
    last = None
    for _ in range(RETRIES):
        try:
            r = requests.get(API, params=params, timeout=TIMEOUT)
            r.raise_for_status()
            return (r.json() or {}).get("game_history") or []
        except Exception as e:
            last = e
            time.sleep(0.4)
    print(f"[WARN] {username} p{page} sin datos ({last})")
    return []


def dedup_by_id(gs):
    seen = set()
    out = []
    for g in gs:
        gid = str(g.get("id") or "")
        if gid and gid in seen:
            continue
        if gid:
            seen.add(gid)
        out.append(g)
    return out


def norm_team(s: str) -> str:
    return (s or "").strip().lower()


def compute_team_record_for_user(username_exact: str, team_name: str):
    pages_raw = []
    usernames_to_fetch = [username_exact] + FETCH_ALIASES.get(username_exact, [])
    for uname in usernames_to_fetch:
        for p in PAGES:
            page_items = fetch_page(uname, p)
            pages_raw += page_items
            if PRINT_CAPTURE_LIST:
                for g in page_items:
                    print(
                        f"    [cap] {uname} p{p} id={g.get('id')} {g.get('away_full_name','')} @ {g.get('home_full_name','')} {g.get('display_date','')}"
                    )
    pages_dedup = dedup_by_id(pages_raw)
    considered = []
    for g in pages_dedup:
        if (g.get("game_mode") or "").strip().upper() != MODE:
            continue
        d = parse_date(g.get("display_date", ""))
        if not d or d < SINCE:
            continue
        home = (g.get("home_full_name") or "").strip()
        away = (g.get("away_full_name") or "").strip()
        if norm_team(team_name) not in (norm_team(home), norm_team(away)):
            continue
        home_name_raw = g.get("home_name", "")
        away_name_raw = g.get("away_name", "")
        h_norm = normalize_user_for_compare(home_name_raw)
        a_norm = normalize_user_for_compare(away_name_raw)
        h_mem = h_norm in LEAGUE_USERS_NORM
        a_mem = a_norm in LEAGUE_USERS_NORM
        if not ((h_mem and a_mem) or (is_cpu(home_name_raw) and a_mem) or (is_cpu(away_name_raw) and h_mem)):
            continue
        considered.append(g)

    # --- 🔍 Guardar archivos de depuración por jugador ---
    if DUMP_ENABLED:
        os.makedirs(DUMP_DIR, exist_ok=True)
        base = _safe_name(username_exact)
        _dump_json(f"{base}_raw.json", pages_raw)
        _dump_json(f"{base}_dedup.json", pages_dedup)
        _dump_json(f"{base}_considered.json", considered)

    if PRINT_CAPTURE_SUMMARY:
        print(
            f"    [capturas] {team_name} ({username_exact}): raw={len(pages_raw)}  dedup={len(pages_dedup)}  considerados={len(considered)}"
        )

    wins = losses = 0
    for g in considered:
        home = (g.get("home_full_name") or "").strip()
        away = (g.get("away_full_name") or "").strip()
        hr = (g.get("home_display_result") or "").strip().upper()
        ar = (g.get("away_display_result") or "").strip().upper()
        if hr == "W":
            win, lose = home, away
        elif ar == "W":
            win, lose = away, home
        else:
            continue
        if norm_team(win) == norm_team(team_name):
            wins += 1
        elif norm_team(lose) == norm_team(team_name):
            losses += 1

    adj_w, adj_l = TEAM_RECORD_ADJUSTMENTS.get(team_name, (0, 0))
    wins_adj, losses_adj = wins + adj_w, losses + adj_l
    scheduled = 77
    played = max(wins_adj + losses_adj, 0)
    remaining = max(scheduled - played, 0)
    points_base = 3 * wins_adj + 1 * losses_adj
    pts_extra, pts_reason = TEAM_POINT_ADJUSTMENTS.get(team_name, (0, ""))
    points_final = points_base + pts_extra
    return {
        "user": username_exact,
        "team": team_name,
        "scheduled": scheduled,
        "played": played,
        "wins": wins_adj,
        "losses": losses_adj,
        "remaining": remaining,
        "k": max(0, 15 - played),
        "points": points_final,
    }


def compute_rows():
    rows = []
    for user_exact, team_name in LEAGUE_ORDER:
        rows.append(compute_team_record_for_user(user_exact, team_name))
    rows.sort(key=lambda r: (-r.get("points", 0), -r.get("wins", 0), r.get("losses", 0)))
    return rows


def games_played_today_scl():
    tz_scl = ZoneInfo("America/Santiago")
    tz_utc = ZoneInfo("UTC")

    now_scl = datetime.now(tz_scl)
    day_start = now_scl.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start.replace(hour=23, minute=59, second=59, microsecond=999999)

    all_pages = []
    for username_exact, _team in LEAGUE_ORDER:
        for p in PAGES:
            all_pages += fetch_page(username_exact, p)

    seen_ids, seen_keys = set(), set()
    items = []
    valid_teams = {team for (_user, team) in LEAGUE_ORDER}
    user_to_team = {u.lower(): t.lower() for (u, t) in LEAGUE_ORDER}

    for g in dedup_by_id(all_pages):
        if (g.get("game_mode") or "").strip().upper() != MODE:
            continue

        d = parse_date(g.get("display_date", ""))
        if not d:
            continue
        if d.tzinfo is None:
            d = d.replace(tzinfo=tz_utc)
        d_local = d.astimezone(tz_scl)
        if not (day_start <= d_local <= day_end):
            continue

        home = (g.get("home_full_name") or "").strip()
        away = (g.get("away_full_name") or "").strip()
        if home not in valid_teams or away not in valid_teams:
            continue

        home_user_raw = g.get("home_name", "")
        away_user_raw = g.get("away_name", "")
        h_norm = normalize_user_for_compare(home_user_raw)
        a_norm = normalize_user_for_compare(away_user_raw)
        if h_norm not in LEAGUE_USERS_NORM or a_norm not in LEAGUE_USERS_NORM:
            continue

        expected_home_team = user_to_team.get(h_norm)
        expected_away_team = user_to_team.get(a_norm)
        if expected_home_team and expected_home_team != home.lower():
            continue
        if expected_away_team and expected_away_team != away.lower():
            continue

        gid = str(g.get("id") or "")
        if gid and gid in seen_ids:
            continue

        hr = str(g.get("home_runs") or "0")
        ar = str(g.get("away_runs") or "0")
        pitcher_info = (g.get("display_pitcher_info") or "").strip()
        canon_key = (home, away, hr, ar, pitcher_info)
        if canon_key in seen_keys:
            continue
        if gid:
            seen_ids.add(gid)
        seen_keys.add(canon_key)

        d_et = d_local - timedelta(hours=1)
        try:
            fecha_hora = d_et.strftime("%d-%m-%Y - %-I:%M %p").lower()
        except Exception:
            fecha_hora = d_et.strftime("%d-%m-%Y - %#I:%M %p").lower()

        items.append((d_et, f"{home} {hr} - {away} {ar}  - {fecha_hora} ET"))

    items.sort(key=lambda x: x[0])
    return [s for _, s in items]


def main():
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] Iniciando actualización del cache...")
    os.makedirs(DUMP_DIR, exist_ok=True)
    rows = compute_rows()
    _dump_json("standings.json", rows)
    games_today = games_played_today_scl()
    _dump_json(
        "games_today.json",
        {"generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "items": games_today},
    )
    print("✅ Actualización completada exitosamente.")


def debug_standings_raw():
    os.makedirs(DUMP_DIR, exist_ok=True)
    debug_data = []
    tz_scl = ZoneInfo("America/Santiago")
    tz_utc = ZoneInfo("UTC")

    for username_exact, team_name in LEAGUE_ORDER:
        pages_raw = []
        usernames_to_fetch = [username_exact] + FETCH_ALIASES.get(username_exact, [])
        for uname in usernames_to_fetch:
            for p in PAGES:
                try:
                    page_items = fetch_page(uname, p)
                    pages_raw += page_items
                except Exception as e:
                    debug_data.append(
                        {"team": team_name, "user": username_exact, "error": f"Error fetching {uname} p{p}: {e}"}
                    )

        for g in dedup_by_id(pages_raw):
            reason = ""
            include = True

            if (g.get("game_mode") or "").strip().upper() != MODE:
                include = False
                reason = "modo_no_LEAGUE"

            d = parse_date(g.get("display_date", ""))
            if not d:
                include = False
                reason = "sin_fecha_valida"
            else:
                if d.tzinfo is None:
                    d = d.replace(tzinfo=tz_utc)
                d_local = d.astimezone(tz_scl)
                since_utc = SINCE.replace(tzinfo=tz_utc)
                d_utc = d.astimezone(tz_utc)
                if d_utc < since_utc:
                    include = False
                    reason = "fecha_anterior_al_inicio"

            home = (g.get("home_full_name") or "").strip()
            away = (g.get("away_full_name") or "").strip()
            if norm_team(team_name) not in (norm_team(home), norm_team(away)):
                include = False
                reason = "equipo_no_coincide"

            home_user_raw = g.get("home_name", "")
            away_user_raw = g.get("away_name", "")
            h_norm = normalize_user_for_compare(home_user_raw)
            a_norm = normalize_user_for_compare(away_user_raw)
            h_mem = h_norm in LEAGUE_USERS_NORM
            a_mem = a_norm in LEAGUE_USERS_NORM
            if not (h_mem and a_mem):
                include = False
                reason = "jugador_externo"

            debug_data.append(
                {
                    "id": g.get("id"),
                    "team_in_focus": team_name,
                    "home_team": home,
                    "away_team": away,
                    "home_user": home_user_raw,
                    "away_user": away_user_raw,
                    "home_runs": g.get("home_runs"),
                    "away_runs": g.get("away_runs"),
                    "mode": g.get("game_mode"),
                    "display_date": g.get("display_date"),
                    "included_in_standings": include,
                    "reason_if_excluded": reason,
                }
            )

    path = os.path.join(DUMP_DIR, "standings_debug.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(debug_data, f, ensure_ascii=False, indent=2)

    print(f"✅ Archivo de depuración standings generado: {path}")
    print(f"   Total juegos evaluados: {len(debug_data)}")
    return debug_data
















def get_full_history_grouped():
    """
    Retorna un diccionario agrupado por fecha, filtrando duplicados estrictamente
    usando IDs y contenido del juego (canon keys).
    """
    tz_scl = ZoneInfo("America/Santiago")
    
    # 1. Recopilar todos los juegos raw
    all_pages = []
    for username_exact, _team in LEAGUE_ORDER:
        for p in PAGES:
            all_pages += fetch_page(username_exact, p)

    seen_ids = set()
    seen_keys = set() # <--- NUEVO: Para evitar duplicados por contenido
    
    valid_games = []
    valid_teams = {team for (_user, team) in LEAGUE_ORDER}
    user_to_team = {u.lower(): t.lower() for (u, t) in LEAGUE_ORDER}

    # 2. Filtrar y procesar
    # dedup_by_id ayuda, pero no es infalible si faltan IDs
    for g in dedup_by_id(all_pages):
        if (g.get("game_mode") or "").strip().upper() != MODE:
            continue

        d = parse_date(g.get("display_date", ""))
        if not d: continue
        
        if d.tzinfo is None:
            d = d.replace(tzinfo=ZoneInfo("UTC"))
        d_local = d.astimezone(tz_scl)
        
        # Filtro de fecha de inicio de temporada
        if d_local < SINCE.replace(tzinfo=tz_scl):
            continue

        home = (g.get("home_full_name") or "").strip()
        away = (g.get("away_full_name") or "").strip()
        
        # Validar que sean equipos de la liga
        if home not in valid_teams or away not in valid_teams:
            continue

        # Validar usuarios reales
        home_user_raw = g.get("home_name", "")
        away_user_raw = g.get("away_name", "")
        h_norm = normalize_user_for_compare(home_user_raw)
        a_norm = normalize_user_for_compare(away_user_raw)

        if h_norm not in LEAGUE_USERS_NORM or a_norm not in LEAGUE_USERS_NORM:
            continue
            
        # Validar match Usuario vs Equipo (evita gente jugando con equipos ajenos)
        expected_home = user_to_team.get(h_norm)
        expected_away = user_to_team.get(a_norm)
        if expected_home and expected_home != home.lower(): continue
        if expected_away and expected_away != away.lower(): continue

        # --- LÓGICA ANTI-DUPLICADOS ROBUSTA ---
        gid = str(g.get("id") or "")
        
        # 1. Check por ID
        if gid and gid in seen_ids: 
            continue
            
        # 2. Check por Contenido (Canon Key)
        # Creamos una firma única del juego: Equipos + Carreras + Pitcher + Fecha (hasta el minuto)
        hr = str(g.get("home_runs") or "0")
        ar = str(g.get("away_runs") or "0")
        pitcher_info = (g.get("display_pitcher_info") or "").strip()
        # Usamos fecha formateada "yyyymmddHHMM" para que diferencias de segundos no dupliquen
        date_key_simple = d_local.strftime("%Y%m%d%H%M") 
        
        canon_key = (home, away, hr, ar, pitcher_info, date_key_simple)
        
        if canon_key in seen_keys:
            continue

        # Si pasa los filtros, lo registramos como visto
        if gid:
            seen_ids.add(gid)
        seen_keys.add(canon_key)
        # ---------------------------------------

        # Formatear string para visualización
        d_et = d_local - timedelta(hours=1) 
        fecha_group = d_local.strftime("%d-%m-%Y")
        
        try:
            hora_fmt = d_et.strftime("%d-%m-%Y - %-I:%M %p").lower()
        except:
            hora_fmt = d_et.strftime("%d-%m-%Y - %#I:%M %p").lower()

        game_str = f"{home} {hr} - {away} {ar}  - {hora_fmt} ET"
        
        valid_games.append({
            "sort_ts": d_local.timestamp(),
            "date_group": fecha_group,
            "game_str": game_str
        })

    # 3. Ordenar: Más reciente arriba
    valid_games.sort(key=lambda x: x["sort_ts"], reverse=True)

    # 4. Agrupar por fecha
    grouped = {}
    for item in valid_games:
        k = item["date_group"]
        if k not in grouped:
            grouped[k] = []
        grouped[k].append(item["game_str"])
        
    return grouped













































if __name__ == "__main__":
    main()
    debug_standings_raw()
