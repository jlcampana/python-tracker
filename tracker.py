#!/usr/bin/env python3
"""Tracker: explorador de modarchive.org y reproductor de música tracker para la terminal."""
import hashlib
import html
import os
import re
import signal
import sqlite3
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

from rich.markup import escape
from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import (DataTable, Footer, Input, Label, OptionList, ProgressBar, Static,
                             TabbedContent, TabPane)
from textual.widgets.option_list import Option

MUSIC_DIR = Path(os.environ.get("TRACKER_DIR", Path.home() / "Música" / "Tracker"))
DB_PATH = Path.home() / ".local/share/trackerplay/biblioteca.db"
BASE = "https://modarchive.org/index.php"
DOWNLOAD_URL = "https://api.modarchive.org/downloads.php?moduleid={}"
MODULE_URL = "https://modarchive.org/index.php?request=view_by_moduleid&query={}"
UA = "Mozilla/5.0 (X11; Linux x86_64) trackerplay/1.0"
EXTS = set("""mptm mod s3m xm it 667 669 amf ams c67 cba dbm digi dmf dsm dsym dtm etx far fc fc13
fc14 fmt fst ftm imf ims ice j2b m15 mdl med mms mt2 mtm mus nst okt plm psm pt36 ptm puma rtm sfx
sfx2 smod st26 stk stm stx stp symmod tcb gmc gtk gt2 ult unic wow xmf gdm mo3 oxm umx xpk ppm
mmcmp""".split())


# ---------------------------------------------------------------- modarchive

def fetch(url, binary=False):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = r.read()
    return data if binary else data.decode("utf-8", "replace")


def page_url(params, page=1):
    p = dict(params)
    if page > 1:
        p["page"] = page
    return BASE + "?" + urllib.parse.urlencode(p)


def to_int(s):
    return int(s.replace(",", "")) if s else None


ID_RE = re.compile(r"(?:moduleid=|view_by_moduleid&amp;query=|module\.php\?)(\d+)")


def parse_modules(doc):
    """Saca los módulos de cualquier listado de modarchive (búsquedas, charts, listas...)."""
    marks, seen = [], set()
    for m in ID_RE.finditer(doc):
        mid = int(m.group(1))
        if mid not in seen:
            seen.add(mid)
            marks.append((doc.rfind("<", 0, m.start()), mid))
    mods = []
    for n, (pos, mid) in enumerate(marks):
        seg = doc[pos:marks[n + 1][0] if n + 1 < len(marks) else len(doc)]
        fm = re.search(rf"moduleid={mid}#([^\"'\s<>]+)", seg)
        if not fm:
            continue
        filename = html.unescape(urllib.parse.unquote(fm.group(1)))
        tm = (re.search(r'<h1>(.*?)\s*<span class="module-sub-header">', doc)
              or re.search(rf'class="chart-listing-title" href="module\.php\?{mid}">([^<]*)<', seg)
              or re.search(r'<span class="module-listing">\s*([^<]+?)\s*</span>', seg)
              or re.search(rf'query={mid}" title="([^"]*)"', seg))
        title = html.unescape(tm.group(1)).strip() if tm else ""
        info, pop = "", 0
        if m := re.search(r"Downloaded ([\d,]+) times", seg):
            pop = to_int(m.group(1)); info = f"{pop:,} descargas".replace(",", ".")
        elif m := re.search(r"favourite of ([\d,]+) member", seg):
            pop = to_int(m.group(1)); info = f"{pop} favoritos"
        elif m := re.search(r"Rated</a>\s*(\d+) / 10", seg):
            pop = int(m.group(1)); info = f"{pop}/10"
        elif m := re.search(r"Downloads:\s*</b>?\s*([\d,]+)", seg):
            pop = to_int(m.group(1)); info = f"{pop:,} descargas".replace(",", ".")
        mods.append({"id": mid, "filename": filename, "title": title or filename,
                     "format": Path(filename).suffix.lstrip(".").upper(), "info": info, "pop": pop})
    return mods


def fetch_module_file(url):
    data = fetch(url, binary=True)
    if data[:200].lstrip().lower().startswith((b"<!doctype", b"<html")) or len(data) < 400:
        raise RuntimeError("modarchive devolvió una página en vez del archivo")
    return data


def parse_pages(doc):
    pages = [int(p) for p in re.findall(r"[?&](?:amp;)?page=(\d+)", doc)]
    return max(pages, default=1)


def parse_genres(doc):
    out, seen = [], set()
    for gid, name in re.findall(
            r'href="index\.php\?query=(\d+)&amp;request=search&amp;search_type=genre">([^<]+)<', doc):
        if gid not in seen:
            seen.add(gid)
            out.append({"id": gid, "name": html.unescape(name).strip()})
    return out


def parse_artists(doc):
    return [{"id": aid, "name": html.unescape(name).strip()} for aid, name in
            re.findall(r'href="member\.php\?(\d+)" class=\'search-result-link\'>([^<]+)</a>', doc)]


def module_info(mid):
    """Datos de la ficha de un módulo: artista, descargas, favoritos, género..."""
    doc = fetch(MODULE_URL.format(mid))
    text = html.unescape(re.sub(r"<[^>]+>", " ", doc))

    def g(pat):
        m = re.search(pat, text)
        return m.group(1).strip() if m else None

    artists = []
    if am := re.search(r"Registered Artist\(s\):(.*?)</ul>", doc, re.S):
        artists = [html.unescape(a).strip() for a in re.findall(r'member\.php\?\d+">([^<]+)</a>', am.group(1))]
    genre = g(r"Genre:\s*([^\n]+?)\s{2,}")
    tm = re.search(r"<h1>(.*?)\s*<span", doc)
    return {"artist": ", ".join(artists) or None,
            "title": html.unescape(tm.group(1)).strip() if tm else None,
            "ma_downloads": to_int(g(r"Downloads:\s*([\d,]+)")),
            "ma_favourites": to_int(g(r"Favourited:\s*([\d,]+)")),
            "genre": None if genre in (None, "n/a") else genre,
            "channels": to_int(g(r"Channels:\s*(\d+)")),
            "md5": g(r"MD5:\s*([0-9a-f]{32})")}


def openmpt_info(path):
    try:
        out = subprocess.run(["openmpt123", "--info", "--banner", "0", "--", str(path)],
                             capture_output=True, text=True, timeout=20).stdout
    except (subprocess.SubprocessError, OSError):
        return {}
    info = {}
    for line in out.splitlines():
        if m := re.match(r"^(\w[\w ]*?)\.*:\s?(.*)$", line):
            info[m.group(1).strip().lower()] = m.group(2).strip()
    secs = 0.0
    for part in info.get("duration", "").split(":"):
        try:
            secs = secs * 60 + float(part)
        except ValueError:
            pass
    return {"title": info.get("title") or None, "artist": info.get("artist") or None,
            "duration": secs or None, "channels": to_int(info.get("channels"))}


# ---------------------------------------------------------------- base de datos

class Library:
    def __init__(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS tracks (
                path TEXT PRIMARY KEY, ma_id INTEGER, filename TEXT, title TEXT, artist TEXT,
                format TEXT, genre TEXT, channels INTEGER, duration REAL, ma_downloads INTEGER,
                ma_favourites INTEGER, added_at TEXT, plays INTEGER DEFAULT 0, last_played TEXT,
                favorite INTEGER DEFAULT 0);
            CREATE INDEX IF NOT EXISTS tracks_ma_id ON tracks(ma_id);
        """)
        # columnas añadidas en versiones posteriores
        have = {r["name"] for r in self.db.execute("PRAGMA table_info(tracks)")}
        for col in ("download_url TEXT", "md5 TEXT", "checked_at TEXT"):
            if col.split()[0] not in have:
                self.db.execute(f"ALTER TABLE tracks ADD COLUMN {col}")
        self.db.commit()

    def _q(self, sql, args=()):
        with self.lock:
            cur = self.db.execute(sql, args)
            self.db.commit()
            return [dict(r) for r in cur.fetchall()]

    def all(self):
        return self._q("SELECT * FROM tracks")

    def by_ma_id(self, mid):
        rows = self._q("SELECT * FROM tracks WHERE ma_id = ?", (mid,))
        return next((r for r in rows if Path(r["path"]).exists()), None)

    def ma_ids(self):
        return {r["ma_id"] for r in self._q("SELECT ma_id FROM tracks WHERE ma_id IS NOT NULL")}

    def add(self, track):
        track = {"added_at": datetime.now().isoformat(timespec="seconds"), **track}
        cols = ", ".join(track)
        marks = ", ".join("?" * len(track))
        self._q(f"INSERT OR REPLACE INTO tracks ({cols}) VALUES ({marks})", tuple(track.values()))
        return self._q("SELECT * FROM tracks WHERE path = ?", (track["path"],))[0]

    def update(self, path, fields):
        if fields:
            sets = ", ".join(f"{k} = ?" for k in fields)
            self._q(f"UPDATE tracks SET {sets} WHERE path = ?", (*fields.values(), path))

    def remove(self, path):
        self._q("DELETE FROM tracks WHERE path = ?", (path,))

    def played(self, path):
        self._q("UPDATE tracks SET plays = plays + 1, last_played = ? WHERE path = ?",
                (datetime.now().isoformat(timespec="seconds"), path))

    def toggle_favorite(self, path):
        self._q("UPDATE tracks SET favorite = 1 - favorite WHERE path = ?", (path,))


# ---------------------------------------------------------------- reproductor

class Player:
    """Envuelve openmpt123: pausa con SIGSTOP/SIGCONT y reinicia con --seek para saltar o cambiar volumen."""

    def __init__(self):
        self.proc = None
        self.track = None
        self.paused = False
        self.offset = 0.0
        self.started = 0.0
        self.gain = 0

    def play(self, track, seek=0.0):
        self.stop()
        self.track = track
        self.offset, self.started, self.paused = seek, time.monotonic(), False
        self.proc = subprocess.Popen(
            ["openmpt123", "--batch", "-q", "--gain", str(self.gain), "--seek", str(int(seek)),
             "--", track["path"]],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True)

    def stop(self):
        proc, self.proc = self.proc, None
        if proc and proc.poll() is None:
            if self.paused:
                proc.send_signal(signal.SIGCONT)
            proc.terminate()
            try:
                proc.wait(2)
            except subprocess.TimeoutExpired:
                proc.kill()
        self.paused = False

    def toggle_pause(self):
        if not self.proc:
            return
        if self.paused:
            self.proc.send_signal(signal.SIGCONT)
            self.started = time.monotonic()
        else:
            self.proc.send_signal(signal.SIGSTOP)
            self.offset += time.monotonic() - self.started
        self.paused = not self.paused

    def restart_at(self, pos):
        if not self.proc:
            return
        was_paused = self.paused
        duration = self.track.get("duration") or 0
        self.play(self.track, max(0.0, min(pos, duration - 1 if duration else pos)))
        if was_paused:
            self.toggle_pause()

    @property
    def position(self):
        if not self.proc:
            return 0.0
        return self.offset if self.paused else self.offset + time.monotonic() - self.started

    def finished(self):
        return self.proc is not None and self.proc.poll() is not None


def fmt_time(secs):
    secs = int(secs or 0)
    return f"{secs // 60:02d}:{secs % 60:02d}"


# ---------------------------------------------------------------- interfaz

class ResultsTable(DataTable):
    BINDINGS = [
        Binding("right_square_bracket", "app.page(1)", "Pág. sig."),
        Binding("left_square_bracket", "app.page(-1)", "Pág. ant."),
        Binding("backspace,escape", "app.back", "Volver"),
        Binding("d", "app.download_only", "Descargar"),
        Binding("o", "app.sort_results", "Ordenar"),
    ]

    # Av Pág en la última fila pide la página siguiente; Re Pág en la primera, la anterior
    def action_page_down(self):
        if self.row_count and self.cursor_row >= self.row_count - 1:
            self.app.action_page(1)
        else:
            super().action_page_down()

    def action_page_up(self):
        if self.cursor_row <= 0:
            self.app.action_page(-1, cursor_end=True)
        else:
            super().action_page_up()


class LibraryTable(DataTable):
    BINDINGS = [
        Binding("o", "app.sort_library", "Ordenar"),
        Binding("f", "app.favorite", "Favorita"),
        Binding("r", "app.rescan", "Reescanear"),
        Binding("u", "app.check_updates", "Actualizar"),
    ]


MENU = [
    ("buscar", "Buscar canción"),
    ("artista", "Buscar artista"),
    ("tophits", "Más descargadas"),
    ("topscore", "Mejor puntuadas"),
    ("favs", "Favoritas de la gente"),
    ("featured", "Destacadas"),
    ("generos", "Géneros"),
    ("az", "A-Z"),
    ("random", "Aleatorias"),
]
VIEWS = {
    "tophits": ("Más descargadas", {"request": "view_chart", "query": "tophits"}),
    "topscore": ("Mejor puntuadas", {"request": "view_chart", "query": "topscore"}),
    "featured": ("Destacadas", {"request": "view_chart", "query": "featured"}),
    "favs": ("Favoritas de la gente", {"request": "view_top_favourites"}),
}
RESULT_SORTS = ["web", "alfabético", "popularidad"]
LIB_SORTS = [("alfa", "Alfabético"), ("artista", "Por artista"), ("popular", "Populares en modarchive"),
             ("escuchadas", "Más escuchadas"), ("recientes", "Añadidas recientemente"),
             ("favoritas", "Favoritas")]


class TrackerApp(App):
    TITLE = "Tracker"
    CSS = """
    TabbedContent { height: 1fr; }
    TabPane { height: 1fr; padding: 0; }
    #menu { width: 26; border: round $primary; }
    #explore-main, #library-main { height: 1fr; }
    #status, #libstatus { height: 1; padding: 0 1; color: $text-muted; }
    DataTable { height: 1fr; }
    #player { height: 4; border: round $accent; padding: 0 1; }
    #now-row { height: 1; }
    #now { width: 1fr; }
    #keys { width: auto; color: $text-muted; }
    #progress-row { height: 1; }
    #bar { width: 1fr; }
    #bar Bar { width: 1fr; }
    #time { width: auto; padding-left: 2; }
    """
    BINDINGS = [
        Binding("q", "quit", "Salir"),
        Binding("1", "tab('explorar')", "Explorar", show=False),
        Binding("2", "tab('biblioteca')", "Biblioteca", show=False),
        Binding("space", "pause", "Pausa"),
        Binding("s", "stop", "Parar"),
        Binding("n", "next", "Sig."),
        Binding("b", "prev", "Ant."),
        Binding("comma", "seek(-10)", "-10s", show=False),
        Binding("full_stop", "seek(10)", "+10s", show=False),
        Binding("minus", "volume(-3)", "Vol-", show=False),
        Binding("plus", "volume(3)", "Vol+", show=False),
        Binding("slash", "focus_input", "Buscar"),
    ]

    def __init__(self):
        super().__init__()
        MUSIC_DIR.mkdir(parents=True, exist_ok=True)
        self.lib = Library(DB_PATH)
        self.player = Player()
        self.view = None            # vista actual del explorador
        self.history = []           # vistas anteriores, para volver
        self.rows = []              # filas mostradas en el explorador
        self.result_sort = 0
        self.search_mode = "song"
        self.lib_sort = 0
        self.lib_rows = []          # filas mostradas en la biblioteca (None = cabecera de artista)
        self.queue = []
        self.qpos = -1
        self.play_token = 0

    def compose(self) -> ComposeResult:
        with TabbedContent(initial="explorar"):
            with TabPane("Explorar modarchive", id="explorar"):
                with Horizontal(id="explore-main"):
                    yield OptionList(*[Option(label, id=key) for key, label in MENU], id="menu")
                    with Vertical():
                        yield Input(placeholder="Buscar canción en modarchive (Enter)", id="search")
                        yield Label("", id="status")
                        yield ResultsTable(id="results", cursor_type="row", zebra_stripes=True)
            with TabPane("Biblioteca", id="biblioteca"):
                with Vertical(id="library-main"):
                    yield Input(placeholder="Filtrar por título, artista, archivo o género", id="filter")
                    yield Label("", id="libstatus")
                    yield LibraryTable(id="library", cursor_type="row", zebra_stripes=True)
        with Vertical(id="player"):
            with Horizontal(id="now-row"):
                yield Static("■ Parado", id="now")
                yield Label("1/2 pestañas · espacio pausa · , . ±10s · - + volumen", id="keys")
            with Horizontal(id="progress-row"):
                yield ProgressBar(id="bar", total=100, show_eta=False, show_percentage=False)
                yield Label("00:00 / 00:00", id="time")
        yield Footer()

    def on_mount(self):
        self.set_interval(0.5, self.tick)
        self.open_menu("tophits")
        self.query_one("#results").focus()
        self.scan_library()

    def on_unmount(self):
        self.player.stop()

    # ---------------------------------------------------------- explorador

    def on_option_list_option_selected(self, event):
        self.open_menu(event.option.id)

    def open_menu(self, key):
        search = self.query_one("#search", Input)
        if key in ("buscar", "artista"):
            self.search_mode = "song" if key == "buscar" else "artist"
            search.placeholder = ("Buscar canción en modarchive (Enter)" if key == "buscar"
                                  else "Buscar artista en modarchive (Enter)")
            search.focus()
            return
        self.history.clear()
        if key in VIEWS:
            title, params = VIEWS[key]
            self.load_view({"kind": "modules", "title": title, "params": params})
        elif key == "generos":
            self.load_view({"kind": "genres", "title": "Géneros", "params": {"request": "view_genres"}})
        elif key == "az":
            letters = [{"id": c, "name": c} for c in "0ABCDEFGHIJKLMNOPQRSTUVWXYZ"]
            self.show_view({"kind": "letters", "title": "A-Z", "page": 1, "pages": 1}, letters)
        elif key == "random":
            self.load_view({"kind": "modules", "title": "Aleatorias (vuelve a elegirlo para otras)",
                            "params": {"request": "zomg_random"}})
        self.query_one("#results").focus()

    def on_input_submitted(self, event):
        if event.input.id != "search" or not event.value.strip():
            return
        q = event.value.strip()
        self.history.clear()
        if self.search_mode == "song":
            self.load_view({"kind": "modules", "title": f"Búsqueda: {q}",
                            "params": {"request": "search", "query": q, "submit": "Find",
                                       "search_type": "filename_or_songtitle"}})
        else:
            self.load_view({"kind": "artists", "title": f"Artistas: {q}",
                            "params": {"request": "search", "query": q, "submit": "Find",
                                       "search_type": "search_artist"}})
        self.query_one("#results").focus()

    def on_input_changed(self, event):
        if event.input.id == "filter":
            self.render_library()

    @work(thread=True, exclusive=True, group="explore")
    def load_view(self, view):
        view = {"page": 1, **view}
        self.call_from_thread(self.set_status, f"Cargando {view['title']}…")
        try:
            doc = fetch(page_url(view["params"], view["page"]))
            parse = {"modules": parse_modules, "genres": parse_genres, "artists": parse_artists}
            rows = parse[view["kind"]](doc)
            view["pages"] = max(parse_pages(doc), view["page"])
        except Exception as e:  # noqa: BLE001 - cualquier fallo de red se muestra en la barra
            self.call_from_thread(self.set_status, f"Error cargando {view['title']}: {e}")
            return
        self.call_from_thread(self.show_view, view, rows)

    def set_status(self, msg):
        self.query_one("#status", Label).update(Text(msg))

    def show_view(self, view, rows):
        cursor_end = view.pop("cursor_end", False)
        self.view, self.rows, self.result_sort = view, rows, 0
        self.render_results()
        if cursor_end and rows:
            self.query_one("#results", DataTable).move_cursor(row=len(rows) - 1)

    def render_results(self):
        view, table = self.view, self.query_one("#results", DataTable)
        table.clear(columns=True)
        rows = list(self.rows)
        if view["kind"] == "modules":
            sort = RESULT_SORTS[self.result_sort]
            if sort == "alfabético":
                rows.sort(key=lambda r: r["title"].lower())
            elif sort == "popularidad":
                rows.sort(key=lambda r: -(r["pop"] or 0))
            self.shown = rows
            have = self.lib.ma_ids()
            table.add_columns(" ", "Título", "Archivo", "Formato", "Popularidad")
            for i, r in enumerate(rows):
                table.add_row("✓" if r["id"] in have else "", Text(r["title"]), Text(r["filename"]),
                              r["format"], r["info"], key=str(i))
            extra = f" · orden: {sort} (o)"
        else:
            self.shown = rows
            table.add_columns({"genres": "Género", "artists": "Artista", "letters": "Letra"}[view["kind"]])
            for i, r in enumerate(rows):
                table.add_row(Text(r["name"]), key=str(i))
            extra = ""
        pages = f" · página {view['page']}/{view['pages']} ([ ])" if view["pages"] > 1 else ""
        back = " · ← retroceso" if self.history else ""
        self.set_status(f"{view['title']} · {len(rows)} resultados{pages}{extra}{back}")

    def on_data_table_row_selected(self, event):
        if event.data_table.id == "results":
            self.select_result(event.cursor_row)
        elif event.data_table.id == "library":
            track = self.lib_rows[event.cursor_row]
            if track:
                self.queue = [t for t in self.lib_rows if t]
                self.play_index(self.queue.index(track))

    def select_result(self, idx):
        if not self.view or idx >= len(self.shown):
            return
        row, kind = self.shown[idx], self.view["kind"]
        if kind == "modules":
            self.queue = list(self.shown)
            self.play_index(idx)
            return
        self.history.append(self.view)
        if kind == "genres":
            self.load_view({"kind": "modules", "title": f"Género: {row['name']}",
                            "params": {"query": row["id"], "request": "search", "search_type": "genre"}})
        elif kind == "artists":
            self.load_view({"kind": "modules", "title": f"Artista: {row['name']}",
                            "params": {"request": "view_artist_modules", "query": row["id"]}})
        elif kind == "letters":
            self.load_view({"kind": "modules", "title": f"Letra {row['name']}",
                            "params": {"request": "view_by_list", "query": row["id"]}})

    def action_page(self, delta, cursor_end=False):
        v = self.view
        if v and "params" in v and 1 <= v["page"] + delta <= v["pages"]:
            self.load_view({**v, "page": v["page"] + delta, "cursor_end": cursor_end})

    def action_back(self):
        if self.history:
            self.load_view(self.history.pop())

    def action_sort_results(self):
        if self.view and self.view["kind"] == "modules":
            self.result_sort = (self.result_sort + 1) % len(RESULT_SORTS)
            self.render_results()

    def action_download_only(self):
        table = self.query_one("#results", DataTable)
        if self.view and self.view["kind"] == "modules" and self.shown:
            self.download_worker(self.shown[table.cursor_row], play_token=None)

    # ---------------------------------------------------------- descargas

    def download(self, mod):
        """Descarga un módulo (si no está ya) y lo registra en la biblioteca. Se llama desde hilos."""
        if track := self.lib.by_ma_id(mod["id"]):
            return track
        url = DOWNLOAD_URL.format(mod["id"])
        data = fetch_module_file(url)
        name = Path(mod["filename"]).name.replace("/", "_") or f"{mod['id']}.mod"
        dest = MUSIC_DIR / name
        if dest.exists():
            dest = MUSIC_DIR / f"{mod['id']}_{name}"
        dest.write_bytes(data)
        try:
            info = module_info(mod["id"])
        except Exception:  # noqa: BLE001 - sin ficha nos quedamos con lo que sabemos
            info = {}
        local = openmpt_info(dest)
        return self.lib.add({
            "path": str(dest), "ma_id": mod["id"], "filename": mod["filename"],
            "title": info.get("title") or local.get("title") or mod["title"],
            "artist": info.get("artist") or local.get("artist"),
            "format": mod["format"], "genre": info.get("genre"),
            "channels": info.get("channels") or local.get("channels"),
            "duration": local.get("duration"), "ma_downloads": info.get("ma_downloads"),
            "ma_favourites": info.get("ma_favourites"), "download_url": url,
            "md5": hashlib.md5(data).hexdigest(),
            "checked_at": datetime.now().isoformat(timespec="seconds")})

    @work(thread=True, exclusive=True, group="updates")
    def check_updates(self):
        """Refresca los datos de modarchive y vuelve a bajar los archivos cuyo MD5 haya cambiado."""
        tracks = [t for t in self.lib.all() if t["ma_id"]]
        updated = failed = 0
        for n, t in enumerate(tracks, 1):
            self.call_from_thread(self.set_libstatus, f"Comprobando actualizaciones {n}/{len(tracks)}…")
            try:
                info = module_info(t["ma_id"])
                fields = {k: info[k] for k in ("artist", "title", "genre", "channels",
                                               "ma_downloads", "ma_favourites") if info.get(k)}
                path = Path(t["path"])
                local_md5 = hashlib.md5(path.read_bytes()).hexdigest() if path.exists() else None
                if info.get("md5") and info["md5"] != local_md5:
                    url = t["download_url"] or DOWNLOAD_URL.format(t["ma_id"])
                    data = fetch_module_file(url)
                    if hashlib.md5(data).hexdigest() == info["md5"]:
                        path.write_bytes(data)
                        fields["duration"] = openmpt_info(path).get("duration")
                        updated += 1
                fields.update(md5=info.get("md5") or local_md5, download_url=t["download_url"]
                              or DOWNLOAD_URL.format(t["ma_id"]),
                              checked_at=datetime.now().isoformat(timespec="seconds"))
                self.lib.update(t["path"], fields)
            except Exception:  # noqa: BLE001 - seguimos con las demás
                failed += 1
            time.sleep(0.5)  # no saturar modarchive
        msg = f"Comprobadas {len(tracks)} canciones: {updated} actualizadas"
        if failed:
            msg += f", {failed} con error"
        self.call_from_thread(self.notify, msg)
        self.call_from_thread(self.render_library)

    def action_check_updates(self):
        self.check_updates()

    @work(thread=True, group="download")
    def download_worker(self, mod, play_token):
        if play_token is None:
            self.call_from_thread(self.notify, f"Descargando {escape(mod['filename'])}…")
        try:
            track = self.download(mod)
        except Exception as e:  # noqa: BLE001
            self.call_from_thread(self.notify, f"No se pudo descargar {escape(mod['filename'])}: {escape(str(e))}",
                                  severity="error")
            if play_token == self.play_token:
                self.call_from_thread(self.set_now, "■ Error de descarga")
            return
        self.call_from_thread(self.after_download, track, play_token)

    def after_download(self, track, play_token):
        if self.view and self.view["kind"] == "modules":
            table = self.query_one("#results", DataTable)
            cursor = table.cursor_row
            self.render_results()
            table.move_cursor(row=cursor)
        self.render_library()
        if play_token is None:
            self.notify(f"Guardado en {escape(str(MUSIC_DIR))}: {escape(Path(track['path']).name)}")
        elif play_token == self.play_token:
            self.start_track(track)

    # ---------------------------------------------------------- reproducción

    def play_index(self, idx):
        if not 0 <= idx < len(self.queue):
            return
        self.qpos = idx
        self.play_token += 1
        item = self.queue[idx]
        if "path" in item:
            self.start_track(item)
        elif track := self.lib.by_ma_id(item["id"]):
            self.start_track(track)
        else:
            self.player.stop()
            self.set_now(f"⇣ Descargando {item['title']}…")
            self.download_worker(item, play_token=self.play_token)

    def start_track(self, track):
        if not Path(track["path"]).exists():
            self.notify(f"No existe {escape(track['path'])}", severity="error")
            return
        self.player.play(track)
        self.lib.played(track["path"])
        self.update_now()
        self.render_library()

    def update_now(self):
        t = self.player.track
        if not t or not self.player.proc:
            self.set_now("■ Parado")
            return
        icon = "⏸" if self.player.paused else "▶"
        artist = t.get("artist") or "artista desconocido"
        fmt = t.get("format") or Path(t["path"]).suffix.lstrip(".").upper()
        self.set_now(f"{icon} {t.get('title') or t.get('filename')} — {artist} [{fmt}]")

    def set_now(self, msg):
        self.query_one("#now", Static).update(Text(msg))

    def tick(self):
        p = self.player
        if p.finished():
            p.proc = None
            if self.qpos + 1 < len(self.queue):
                self.play_index(self.qpos + 1)
            else:
                self.update_now()
        duration = (p.track or {}).get("duration") or 0
        pos = min(p.position, duration) if duration else p.position
        self.query_one("#bar", ProgressBar).update(total=duration or 100, progress=pos if duration else 0)
        gain = f"  vol {p.gain:+d} dB" if p.gain else ""
        self.query_one("#time", Label).update(f"{fmt_time(pos)} / {fmt_time(duration)}{gain}")

    def action_pause(self):
        self.player.toggle_pause()
        self.update_now()

    def action_stop(self):
        self.play_token += 1
        self.player.stop()
        self.update_now()

    def action_next(self):
        self.play_index(self.qpos + 1)

    def action_prev(self):
        if self.player.position > 5:
            self.player.restart_at(0)
        else:
            self.play_index(self.qpos - 1)

    def action_seek(self, delta):
        self.player.restart_at(self.player.position + delta)

    def action_volume(self, delta):
        self.player.gain = max(-30, min(12, self.player.gain + delta))
        self.player.restart_at(self.player.position)

    def action_tab(self, tab):
        self.query_one(TabbedContent).active = tab
        self.query_one("#results" if tab == "explorar" else "#library").focus()

    def action_focus_input(self):
        tab = self.query_one(TabbedContent).active
        self.query_one("#search" if tab == "explorar" else "#filter").focus()

    # ---------------------------------------------------------- biblioteca

    @work(thread=True, exclusive=True, group="scan")
    def scan_library(self):
        known = {t["path"] for t in self.lib.all()}
        files = {str(p) for p in MUSIC_DIR.rglob("*") if p.is_file() and p.suffix.lower().lstrip(".") in EXTS}
        for path in known - files:
            self.lib.remove(path)
        new = sorted(files - known)
        for n, path in enumerate(new, 1):
            if n % 10 == 1:
                self.call_from_thread(self.set_libstatus, f"Escaneando {n}/{len(new)}…")
            info = openmpt_info(path)
            p = Path(path)
            self.lib.add({"path": path, "filename": p.name, "title": info.get("title") or p.stem,
                          "artist": info.get("artist"), "format": p.suffix.lstrip(".").upper(),
                          "channels": info.get("channels"), "duration": info.get("duration")})
        self.call_from_thread(self.render_library)

    def action_rescan(self):
        self.scan_library()

    def render_library(self, keep_cursor=True):
        table = self.query_one("#library", DataTable)
        cursor = table.cursor_row if keep_cursor else 0
        tracks = self.lib.all()
        if q := self.query_one("#filter", Input).value.strip().lower():
            tracks = [t for t in tracks if any(q in (t.get(k) or "").lower()
                                               for k in ("title", "artist", "filename", "genre"))]
        key, label = LIB_SORTS[self.lib_sort]
        title = lambda t: (t["title"] or t["filename"] or "").lower()  # noqa: E731
        artist = lambda t: (t["artist"] or "~").lower()  # noqa: E731  ("~" deja los desconocidos al final)
        if key == "alfa":
            tracks.sort(key=title)
        elif key == "artista":
            tracks.sort(key=lambda t: (artist(t), title(t)))
        elif key == "popular":
            tracks.sort(key=lambda t: (-(t["ma_downloads"] or 0), title(t)))
        elif key == "escuchadas":
            tracks.sort(key=lambda t: (-t["plays"], title(t)))
        elif key == "recientes":
            tracks.sort(key=lambda t: t["added_at"] or "", reverse=True)
        elif key == "favoritas":
            tracks = sorted((t for t in tracks if t["favorite"]), key=title)

        table.clear(columns=True)
        table.add_columns("★", "Título", "Artista", "Formato", "Duración", "Descargas MA", "Escuchas")
        self.lib_rows = []
        playing = (self.player.track or {}).get("path") if self.player.proc else None
        last_artist = object()
        for t in tracks:
            if key == "artista" and artist(t) != last_artist:
                last_artist = artist(t)
                count = sum(1 for x in tracks if artist(x) == last_artist)
                name = t["artist"] or "Artista desconocido"
                table.add_row("", Text(f"▾ {name} ({count})", style="bold"), "", "", "", "", "",
                              key=f"h{len(self.lib_rows)}")
                self.lib_rows.append(None)
            style = "bold green" if t["path"] == playing else ""
            table.add_row("★" if t["favorite"] else "",
                          Text(("▶ " if style else "") + (t["title"] or t["filename"]), style=style),
                          Text(t["artist"] or ""), t["format"] or "", fmt_time(t["duration"]),
                          f"{t['ma_downloads']:,}".replace(",", ".") if t["ma_downloads"] else "",
                          str(t["plays"] or ""), key=f"t{len(self.lib_rows)}")
            self.lib_rows.append(t)
        if self.lib_rows:
            table.move_cursor(row=min(cursor, len(self.lib_rows) - 1))
        n = sum(1 for t in self.lib_rows if t)
        self.set_libstatus(f"{n} canciones en {MUSIC_DIR} · orden: {label} (o) · f favorita"
                           " · r reescanear · u buscar actualizaciones")

    def set_libstatus(self, msg):
        self.query_one("#libstatus", Label).update(Text(msg))

    def action_sort_library(self):
        self.lib_sort = (self.lib_sort + 1) % len(LIB_SORTS)
        self.render_library(keep_cursor=False)

    def action_favorite(self):
        table = self.query_one("#library", DataTable)
        if self.lib_rows and (t := self.lib_rows[table.cursor_row]):
            self.lib.toggle_favorite(t["path"])
            self.render_library()


if __name__ == "__main__":
    TrackerApp().run()
