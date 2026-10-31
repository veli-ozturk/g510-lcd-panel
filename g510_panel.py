"""Logitech G510 LCD paneli ve RGB ışığı: sistem, medya, RGB, hava+kur, animasyon.

Tuşlar: 1 = önceki sayfa, 2 = sonraki sayfa, 3/4 = sayfaya özel
  medya:     3 = oynat/duraklat, 4 = sonraki parça
  RGB:       3 = mod değiştir, 4 = renk değiştir (sabit modda)
  animasyon: 3 = yeniden başlat, 4 = animasyonu değiştir
Çalıştır:  python g510_panel.py   (konsolsuz: pythonw g510_panel.py)
Önizleme:  python g510_panel.py --onizleme   (LCD'siz ve ışığa dokunmadan sayfaları PNG olarak kaydeder)
"""
import asyncio, base64, colorsys, ctypes, datetime as dt, email.utils, functools, html, io, json, math, os, queue
import random, re
import shutil, struct, subprocess, sys, tempfile, threading, time, unicodedata, urllib.parse, urllib.request, webbrowser
import xml.etree.ElementTree as ET
from collections import deque
from itertools import zip_longest

import psutil
from PIL import Image, ImageDraw, ImageFont, ImageOps

SURUM = "1.3.6"
GITHUB_DEPO = "veli-ozturk/g510-lcd-panel"
DLL = r"C:\Program Files\Logitech Gaming Software\SDK\LCD\x64\LogitechLcd.dll"
LED_DLL = r"C:\Program Files\Logitech Gaming Software\SDK\LED\x64\LogitechLed.dll"
# exe olarak paketlendiğinde __file__ geçici açılma klasörünü gösterir; ayarlar ve kayıt exe'nin yanında durmalı
KLASOR = os.path.dirname(sys.executable if getattr(sys, "frozen", False) else os.path.abspath(__file__))
AYAR_DOSYASI = os.path.join(KLASOR, "ayarlar.json")
KAYIT_DOSYASI = os.path.join(KLASOR, "g510_panel.log")
SEHIR = ""  # boş: konum Windows'tan otomatik; elle vermek için örn. "İzmir"
HABER_KAYNAKLARI = [("TÜRKİYE", "BBC Türkçe", "https://feeds.bbci.co.uk/turkce/rss.xml"),
                    ("TEKNOLOJİ", "Techolay", "https://techolay.net/feed/"),
                    ("TEKNOLOJİ", "Webtekno", "https://www.webtekno.com/rss.xml")]
HABER_SN = 10      # haberler sayfasında bir başlığın ekranda kalma süresi
ARA_SN = 10        # medya yokken ana sayfa Haberler; her dakikanın sonunda bu kadar Hava, sonra Sistem
BOSTA_SN = 180     # varsayılan: klavye-fare bu kadar dokunulmazsa ve medya yoksa animasyona geç (tepsiden değişir)
MANUEL_SN = 60     # LCD tuşuna basıldıktan sonra otomatik geçişlerin bekleme süresi
MEDYA_BEKLE_SN = 5   # medya durunca dönüşe başlamadan önce Medya sayfasında kalma süresi
ANIM_DEGISIM_SN = 60  # boştayken animasyonların değişme aralığı
W, H = 160, 43
BTN = (0x1, 0x2, 0x4, 0x8)

class _TekRenkFont(ImageFont.FreeTypeFont):
    """Genişliği ekrana çizildiği gibi (kenar yumuşatmasız, fontmode "1") ölçer;
    varsayılan ölçüm küçük puntoda %20'ye kadar dar çıkıp yazıları üst üste bindiriyordu."""

    def getlength(self, text, mode="1", *args, **kwargs):
        return super().getlength(text, mode, *args, **kwargs)


FONT = _TekRenkFont(r"C:\Windows\Fonts\tahoma.ttf", 11)
FONT_KUCUK = _TekRenkFont(r"C:\Windows\Fonts\tahoma.ttf", 9)
FONT_BUYUK = _TekRenkFont(r"C:\Windows\Fonts\tahomabd.ttf", 22)
FONT_KALIN = _TekRenkFont(r"C:\Windows\Fonts\tahomabd.ttf", 12)
BILDIRIM_SN = 12  # bildirimin ekranda kalma süresi (LCD tuşuyla erken kapanır)
GUNLER = "Pzt Sal Çrş Prş Cum Cmt Paz".split()
AYLAR = "Oca Şub Mar Nis May Haz Tem Ağu Eyl Eki Kas Ara".split()

# medya kaynağı: uygulama kimliğinde ya da tarayıcı pencere başlığında (küçük harf) aranan metin -> ikon.
# Sıra önemli: "… / X" geçen bir YouTube başlığı önce YouTube'a eşleşsin.
SITELER = (("youtube", "youtube"), ("netflix", "netflix"), ("twitch", "twitch"), ("spotify", "spotify"),
           ("instagram", "instagram"), ("facebook", "facebook"), ("tiktok", "tiktok"),
           ("prime video", "prime"), ("primevideo", "prime"), ("disney", "disney"), ("soundcloud", "soundcloud"),
           (" - kick", "kick"), (" / x", "x"), (" on x:", "x"))  # X'in sekme başlıkları "… / X" ile biter
# tarayıcının medya uygulama kimliği -> pencere başlığındaki adı (308046...: Firefox'un kimliği)
TARAYICILAR = {"chrome": "chrome", "msedge": "edge", "firefox": "firefox", "308046b0af4a39cb": "firefox",
               "opera": "opera", "brave": "brave", "vivaldi": "vivaldi"}

# hazır RGB modları: (ad, tür, parametre); renkler yüzde (0-100)
RGB_MODLAR = [("Gökkuşağı", "dongu", 30), ("Yavaş gökkuşağı", "dongu", 120),
              ("Nefes: Mavi", "nefes", (0, 20, 100)), ("Nefes: Kırmızı", "nefes", (100, 0, 0)),
              ("Sistem yükü", "yuk", None), ("GPU sıcaklığı", "gpu_isi", None), ("Medya", "medya", None),
              ("Beyaz", "sabit", (100, 100, 100)), ("Kırmızı", "sabit", (100, 0, 0)), ("Turuncu", "sabit", (100, 35, 0)),
              ("Sarı", "sabit", (100, 85, 0)), ("Yeşil", "sabit", (0, 100, 0)), ("Camgöbeği", "sabit", (0, 100, 100)),
              ("Mavi", "sabit", (0, 20, 100)), ("Mor", "sabit", (55, 0, 100)), ("Pembe", "sabit", (100, 10, 50)),
              ("Kapalı (LGS)", "kapali", None)]
MARKA_RENKLERI = {"youtube": (100, 0, 0), "netflix": (100, 5, 5), "twitch": (57, 27, 100), "spotify": (11, 84, 38),
                  "x": (100, 100, 100), "instagram": (90, 10, 60), "facebook": (10, 47, 95), "tiktok": (0, 95, 93),
                  "kick": (33, 99, 9), "prime": (0, 66, 88), "disney": (7, 30, 90), "soundcloud": (100, 33, 0),
                  "tarayici": (100, 100, 100), "muzik": (60, 30, 100)}  # yüzde (0-100)
# bildirim gönderen uygulamanın adında aranan metin -> klavyenin yanıp söneceği renk
BILDIRIM_RENKLERI = {"whatsapp": (15, 85, 35), "discord": (35, 40, 100), "telegram": (15, 65, 95),
                     "outlook": (0, 45, 100), "posta": (0, 45, 100), "mail": (0, 45, 100), "teams": (35, 35, 80),
                     "slack": (90, 15, 60), "g510": (100, 60, 0)}
# tam ekran olsa da oyun sayılmayan işlemler (masaüstü, tarayıcıda tam ekran video, oynatıcılar)
OYUN_DEGIL = {"explorer.exe", "chrome.exe", "msedge.exe", "firefox.exe", "opera.exe", "brave.exe", "vivaldi.exe",
              "vlc.exe", "mpc-hc64.exe", "mpc-be64.exe", "applicationframehost.exe", "searchhost.exe",
              "startmenuexperiencehost.exe", "shellexperiencehost.exe", "lockapp.exe", "textinputhost.exe"}

veri = {"cpu": 0, "cekirdek": [], "mhz": None, "gpu": None, "ram": 0, "disk": 0, "islemler": [], "medya": None,
        "konum": None, "hava": None, "tahmin": None, "kur": None, "haberler": [], "oyun": None, "oyun_ikon": None,
        "ses": None,
        "mik_sessiz": False, "guncelleme": None, "cpu_isi": None, "fps": None}
VARSAYILAN_AYARLAR = {"rgb_mod": 0, "otomatik": True, "oyun_modu": True, "bildirim": True, "bosta_dk": BOSTA_SN // 60}
ayarlar = dict(VARSAYILAN_AYARLAR)
rgb = {"renk": [0.0, 0.0, 0.0], "led": None, "aktif": False, "flas": None}
gorunum = {"rgb_imlec": None, "sistem_detay": False, "hava_tahmin": False,  # sayfa içi durumlar (kaydedilmez)
           "haber_i": 0, "haber_t": 0.0, "haber_son": 0.0, "ses_bitis": 0.0, "bildirim": None}
bildirimler = deque(maxlen=5)  # gösterilmeyi bekleyen (uygulama, başlık, metin)
komutlar = queue.SimpleQueue()
yenile = threading.Event()
cikis = threading.Event()  # tepsi menüsünden çıkış / yeniden başlatma
yeniden_baslat = threading.Event()


def ayar_yukle():
    try:
        with open(AYAR_DOSYASI, encoding="utf-8") as f:
            ayarlar.update(json.load(f))
    except (OSError, ValueError):
        pass
    for anahtar, varsayilan in VARSAYILAN_AYARLAR.items():  # elle bozulmuş dosyaya karşı
        if type(ayarlar.get(anahtar)) is not type(varsayilan):
            ayarlar[anahtar] = varsayilan
    ayarlar["rgb_mod"] %= len(RGB_MODLAR)


def ayar_kaydet():
    try:
        with open(AYAR_DOSYASI, "w", encoding="utf-8") as f:
            json.dump(ayarlar, f)
    except OSError as e:
        print("ayar kaydedilemedi:", e)


# ---------- arka plan veri toplayıcıları ----------

class CpuFrekans:
    """Anlık CPU frekansı: Windows performans sayacı (% taban frekans) x taban frekans.
    psutil.cpu_freq() Windows'ta hep taban frekansı döndürüyor."""

    class _Deger(ctypes.Structure):
        _fields_ = [("durum", ctypes.c_ulong), ("deger", ctypes.c_double)]

    def __init__(self):
        self.pdh = ctypes.windll.pdh
        self.sorgu, self.sayac = ctypes.c_void_p(), ctypes.c_void_p()
        self.taban = psutil.cpu_freq().max
        if self.pdh.PdhOpenQueryW(None, None, ctypes.byref(self.sorgu)) or self.pdh.PdhAddEnglishCounterW(
                self.sorgu, "\\Processor Information(_Total)\\% Processor Performance", None, ctypes.byref(self.sayac)):
            raise OSError("CPU frekans sayacı açılamadı")
        self.pdh.PdhCollectQueryData(self.sorgu)

    def oku(self):
        self.pdh.PdhCollectQueryData(self.sorgu)
        d = self._Deger()
        if self.pdh.PdhGetFormattedCounterValue(self.sayac, 0x200, None, ctypes.byref(d)):  # 0x200 = PDH_FMT_DOUBLE
            return None
        return d.deger / 100 * self.taban


def gpu_oku():
    """NVIDIA: (sıcaklık °C, yük %, VRAM kullanılan MB, VRAM toplam MB); yoksa None."""
    try:
        r = subprocess.run(["nvidia-smi", "--query-gpu=temperature.gpu,utilization.gpu,memory.used,memory.total",
                            "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=5,
                           creationflags=subprocess.CREATE_NO_WINDOW)  # pythonw altında konsol penceresi açılmasın
        return tuple(float(v) for v in r.stdout.splitlines()[0].split(","))
    except (OSError, ValueError, IndexError, subprocess.TimeoutExpired):
        return None


_surecler = {}


def en_yogun_islemler(adet=3):
    """CPU'yu en çok kullanan işlemler: [(ad, yüzde)]; yüzde tüm çekirdeklere göre."""
    goruldu, liste = set(), []
    for p in psutil.process_iter(["name"]):
        if p.pid == 0:  # System Idle Process
            continue
        goruldu.add(p.pid)
        p = _surecler.setdefault(p.pid, p)  # cpu_percent önceki çağrıya göre ölçer: aynı nesne tutulmalı
        try:
            liste.append((p.cpu_percent() / psutil.cpu_count(), p.info["name"] or "?"))
        except psutil.Error:
            pass
    for pid in set(_surecler) - goruldu:
        del _surecler[pid]
    return [(ad.removesuffix(".exe"), y) for y, ad in sorted(liste, key=lambda s: s[0], reverse=True)[:adet]]


def olcum_dongusu():
    try:
        frekans = CpuFrekans()
    except Exception as e:
        print("frekans:", e)
        frekans = None
    tur = 0
    while True:
        time.sleep(1)
        veri["cpu"] = psutil.cpu_percent()
        c = psutil.cpu_percent(percpu=True)
        veri["cekirdek"] = [sum(c[i:i + 2]) / len(c[i:i + 2]) for i in range(0, len(c), 2)]  # SMT ikizleri yan yana
        veri["ram"] = psutil.virtual_memory().percent
        veri["disk"] = psutil.disk_usage("C:\\").percent
        if frekans:
            veri["mhz"] = frekans.oku()
        if tur % 2 == 0:
            veri["gpu"] = gpu_oku()
        ab = afterburner_oku()
        veri["cpu_isi"], veri["fps"] = ab.get("CPU temperature"), ab.get("Framerate")
        if gorunum["sistem_detay"]:
            veri["islemler"] = en_yogun_islemler()
        try:
            oyun = tam_ekran_oyun()
            anahtar = oyun_anahtari(*oyun) if oyun else None
            veri["oyun_ikon"] = (gomulu_ikon(anahtar) if anahtar else oyun_ikonu(oyun[1]) if oyun[1] else None
                                 ) if oyun else None
            veri["oyun"] = OYUN_ADLARI.get(anahtar, oyun[0]) if oyun else None
        except Exception as e:
            print("oyun:", e)
        tur += 1


class _Dikdortgen(ctypes.Structure):
    _fields_ = [("sol", ctypes.c_long), ("ust", ctypes.c_long), ("sag", ctypes.c_long), ("alt", ctypes.c_long)]


class _MonitorBilgi(ctypes.Structure):
    _fields_ = [("boyut", ctypes.c_ulong), ("ekran", _Dikdortgen), ("calisma", _Dikdortgen), ("bayrak", ctypes.c_ulong)]


_u32 = ctypes.windll.user32
_u32.GetForegroundWindow.restype = ctypes.c_void_p  # 64 bit pencere tutamaçları int'e sığmaz
_u32.MonitorFromWindow.restype = ctypes.c_void_p
_u32.MonitorFromWindow.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
_u32.GetWindowRect.argtypes = _u32.GetMonitorInfoW.argtypes = _u32.GetWindowThreadProcessId.argtypes = \
    [ctypes.c_void_p, ctypes.c_void_p]


def tam_ekran_oyun():
    """Öndeki pencere bulunduğu ekranı tamamen kaplıyorsa ve OYUN_DEGIL'de değilse (ad, exe yolu ya da None),
    yoksa None. Hile korumalı oyunlar exe yolunu okumaya izin vermeyebilir."""
    h = _u32.GetForegroundWindow()
    p, m = _Dikdortgen(), _MonitorBilgi()
    m.boyut = ctypes.sizeof(m)
    if not h or not _u32.GetWindowRect(h, ctypes.byref(p)) or not _u32.GetMonitorInfoW(
            _u32.MonitorFromWindow(h, 2), ctypes.byref(m)):  # 2 = MONITOR_DEFAULTTONEAREST
        return None
    e = m.ekran
    if not (p.sol <= e.sol and p.ust <= e.ust and p.sag >= e.sag and p.alt >= e.alt):
        return None
    pid = ctypes.c_ulong()
    _u32.GetWindowThreadProcessId(h, ctypes.byref(pid))
    try:
        islem = psutil.Process(pid.value)
        ad = islem.name()
    except psutil.Error:
        return None
    if ad.lower() in OYUN_DEGIL or pid.value == os.getpid():
        return None
    try:
        exe = islem.exe()
    except psutil.Error:
        exe = None
    return os.path.splitext(ad)[0], exe


_oyun_ikonlari = {}  # exe yolu -> 32x32 tek renkli ikon ya da None (çıkarılamadı); her oyun için bir kez


# 256 px ikon (SHDefExtractIcon); olmazsa 32 px ExtractAssociatedIcon. Yol ortam değişkeniyle: tırnak sorunu olmasın
_IKON_BETIGI = (
    "Add-Type -AssemblyName System.Drawing; Add-Type -TypeDefinition 'using System;using System.Runtime.InteropServices;"
    "public static class G510Ikon{[DllImport(\"shell32.dll\",CharSet=CharSet.Unicode)]public static extern int "
    "SHDefExtractIcon(string p,int i,uint f,out IntPtr b,out IntPtr k,uint s);}'; $b=[IntPtr]::Zero; $k=[IntPtr]::Zero; "
    "if ([G510Ikon]::SHDefExtractIcon($env:G510_EXE,0,0,[ref]$b,[ref]$k,1048832) -eq 0 -and $b -ne [IntPtr]::Zero) "
    "{ [System.Drawing.Icon]::FromHandle($b).ToBitmap().Save($env:G510_PNG) } "
    "else { [System.Drawing.Icon]::ExtractAssociatedIcon($env:G510_EXE).ToBitmap().Save($env:G510_PNG) }")


def atkinson(gri):
    """Atkinson titreştirmesi: hatanın 6/8'ini dağıtır; küçük ikonlarda Floyd-Steinberg'den az gürültülü."""
    w, h = gri.size
    p = list(gri.getdata())
    for y in range(h):
        for x in range(w):
            i = y * w + x
            eski, p[i] = p[i], 255 if p[i] >= 128 else 0
            hata = (eski - p[i]) >> 3
            for dx, dy in ((1, 0), (2, 0), (-1, 1), (0, 1), (1, 1), (0, 2)):
                if hata and 0 <= x + dx < w and y + dy < h:
                    p[(y + dy) * w + x + dx] += hata
    sonuc = Image.new("L", (w, h))
    sonuc.putdata([min(255, max(0, v)) for v in p])
    return sonuc


# gömülü ikonu olan oyunların ekranda görünecek adı (exe adı yerine: PUBG'nin exe'si TslGame)
OYUN_ADLARI = {"pubg": "PUBG: Battlegrounds", "oni": "Onimusha", "counterstrike": "Counter-Strike 2",
               "dota2": "Dota 2", "leagueoflegends": "League of Legends", "valorant": "VALORANT", "roblox": "Roblox"}


def oyun_anahtari(ad, exe):
    """Exe adı ya da yolundan gömülü ikon anahtarı (oyun_ikonlari.ESLESMELER); yoksa None."""
    import oyun_ikonlari
    metin = f"{ad}.exe {exe or ''}".lower()
    return next((i for a, i in oyun_ikonlari.ESLESMELER if a in metin), None)


def gomulu_ikon(anahtar):
    """Gömülü net logo (oyun_ikonlari.py), 32x32."""
    import oyun_ikonlari
    if anahtar not in _oyun_ikonlari:
        with Image.open(io.BytesIO(base64.b64decode(oyun_ikonlari.IKONLAR[anahtar]))) as r:
            _oyun_ikonlari[anahtar] = r.convert("L")
    return _oyun_ikonlari[anahtar]


def oyun_ikonu(exe):
    """Exe'nin ikonu, tek renkli ekrana titreştirilmiş 32x32 (256 px'ten küçültülür, Atkinson)."""
    if exe in _oyun_ikonlari:
        return _oyun_ikonlari[exe]
    resim = None
    try:
        hedef = os.path.join(tempfile.gettempdir(), "g510_oyun_ikonu.png")
        subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", _IKON_BETIGI],
                       env={**os.environ, "G510_EXE": exe, "G510_PNG": hedef},
                       capture_output=True, timeout=20, check=True, creationflags=subprocess.CREATE_NO_WINDOW)
        with Image.open(hedef) as ham:
            rgba = ham.convert("RGBA")
        zemin = Image.new("RGBA", rgba.size, (0, 0, 0, 255))
        zemin.alpha_composite(rgba)
        resim = atkinson(ImageOps.autocontrast(zemin.convert("L"), cutoff=1).resize((32, 32), Image.LANCZOS))
    except Exception as e:
        print("oyun ikonu çıkarılamadı:", exe, e)
    _oyun_ikonlari[exe] = resim
    return resim


_k32 = ctypes.windll.kernel32
_k32.OpenFileMappingW.restype = _k32.MapViewOfFile.restype = ctypes.c_void_p
_k32.MapViewOfFile.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_size_t]
_k32.UnmapViewOfFile.argtypes = _k32.CloseHandle.argtypes = [ctypes.c_void_p]


def afterburner_oku():
    """MSI Afterburner'ın paylaşılan belleğindeki ölçümler {ad: değer}; Afterburner kapalıysa {}.
    Ryzen sıcaklığı sürücü ister: Afterburner yönetici olarak okur, biz yönetici olmadan buradan alırız.
    Düzen: SDK/Include/MAHMSharedMemory.h (başlık: imza 'MAHM', sürüm, başlık boyu, kayıt sayısı, kayıt boyu;
    kayıtta ad 260 bayt ilk alan, değer 1300. bayttaki float). 'Framerate' yalnız RTSS bir oyunu izlerken vardır."""
    h = _k32.OpenFileMappingW(0x0004, False, "MAHMSharedMemory")  # FILE_MAP_READ
    if not h:
        return {}
    try:
        adres = _k32.MapViewOfFile(h, 0x0004, 0, 0, 0)
        if not adres:
            return {}
        try:
            imza, _, baslik, sayi, boyut = struct.unpack("<5I", ctypes.string_at(adres, 20))
            if imza != 0x4D41484D or boyut < 1304:  # 'MAHM'; Afterburner kapanırken imza silinir
                return {}
            olcumler = {}
            for i in range(min(sayi, 512)):
                kayit = ctypes.string_at(adres + baslik + i * boyut, 1304)
                deger, = struct.unpack("<f", kayit[1300:1304])
                if deger < 1e30:  # geçersiz değer FLT_MAX olarak yazılıyor
                    olcumler[kayit[:260].split(b"\0")[0].decode("latin-1")] = deger
            return olcumler
        finally:
            _k32.UnmapViewOfFile(adres)
    finally:
        _k32.CloseHandle(h)


def bildirim_rengi(uygulama):
    return next((r for ad, r in BILDIRIM_RENKLERI.items() if ad in uygulama.lower()), (100, 100, 100))


async def _bildirim_async():
    from winrt.windows.ui.notifications import KnownNotificationBindings, NotificationKinds
    from winrt.windows.ui.notifications.management import UserNotificationListener
    dinleyici = UserNotificationListener.current
    if await dinleyici.request_access_async() != 1:  # 1 = ALLOWED
        print("bildirim erişimi yok: Ayarlar > Gizlilik ve güvenlik > Bildirimler'den izin ver")
        return
    goruldu = None  # ilk turda var olanlar gösterilmez
    while True:
        try:
            liste = await dinleyici.get_notifications_async(NotificationKinds.TOAST)
            if goruldu is not None and ayarlar["bildirim"]:
                for n in liste:
                    if n.id in goruldu:
                        continue
                    uygulama = temizle(n.app_info.display_info.display_name) if n.app_info else "Bildirim"
                    baglama = n.notification.visual.get_binding(KnownNotificationBindings.toast_generic)
                    metinler = [temizle(m.text) for m in baglama.get_text_elements()] if baglama else []
                    bildirimler.append((uygulama, metinler[0] if metinler else "", " ".join(metinler[1:])))
            goruldu = {n.id for n in liste}
        except Exception as e:
            print("bildirim:", e)
        await asyncio.sleep(1)


def bildirim_dongusu():
    asyncio.run(_bildirim_async())


def ses_dongusu():
    """Hoparlör seviyesi/sessiz ve mikrofonun sessizde olup olmadığı; seviye değişince ses göstergesi açılır."""
    # MTA: COM nesnelerini Python'un çöp toplayıcısı başka iş parçacığında (ör. LCD çizerken) bırakabiliyor;
    # varsayılan STA'da bu erişim hatasıyla bütün applet'i çökertiyordu. comtypes bu bayrağı içe aktarılırken okur.
    sys.coinit_flags = 0  # COINIT_MULTITHREADED
    from pycaw.pycaw import AudioUtilities
    hoparlor = mikrofon = onceki = None
    tur = 0
    while True:
        try:
            if tur % 60 == 0:  # ~10 sn'de bir: varsayılan aygıt değişmiş olabilir
                hoparlor = AudioUtilities.GetSpeakers().EndpointVolume
                m = AudioUtilities.CreateDevice(AudioUtilities.GetMicrophone())
                mikrofon = m.EndpointVolume if m else None
            ses = (round(hoparlor.GetMasterVolumeLevelScalar() * 100), bool(hoparlor.GetMute()))
            if onceki is not None and ses != onceki:
                gorunum["ses_bitis"] = time.monotonic() + 2
            onceki = veri["ses"] = ses
            veri["mik_sessiz"] = bool(mikrofon and mikrofon.GetMute())
            tur += 1
        except Exception as e:
            print("ses:", e)
            tur = 0
            time.sleep(5)
        time.sleep(0.15)


# ---------- güncelleme (GitHub sürümleri) ----------

def github_istek(yol, ikili=False):
    istek = urllib.request.Request(f"https://api.github.com/repos/{GITHUB_DEPO}{yol}", headers={
        "User-Agent": "g510-panel", "Accept": "application/octet-stream" if ikili else "application/vnd.github+json"})
    with urllib.request.urlopen(istek, timeout=120) as r:
        return r.read() if ikili else json.load(r)


def surum_sayi(s):
    return tuple(int(x) for x in re.findall(r"\d+", s))


def guncelleme_denetle():
    son = github_istek("/releases/latest")
    varlik = next((a for a in son["assets"] if a["name"].lower() == "g510-panel.exe"), None)
    if varlik and surum_sayi(son["tag_name"]) > surum_sayi(SURUM) and veri["guncelleme"] is None:
        veri["guncelleme"] = (son["tag_name"], varlik["id"])
        bildirimler.append(("G510 Panel", f"Yeni sürüm: {son['tag_name']}", "Tepsi simgesinden Güncelle'yi seç."))


def guncelleme_dongusu():
    while not cikis.is_set():
        try:
            guncelleme_denetle()
        except Exception as e:
            print("güncelleme denetlenemedi:", e)
        cikis.wait(6 * 3600)


_guncelleme_kilidi = threading.Lock()


def guncelle():
    """Yeni exe'yi indirir, kendini değiştirmesi için onu --guncelleme-bitir ile başlatır ve kapanır."""
    if not getattr(sys, "frozen", False):
        print("güncelleme yalnız exe sürümünde yapılır")
        return
    # indirme ~30 MB sürerken ikinci tık aynı dosyaya yazıp "Permission denied" veriyordu
    if not _guncelleme_kilidi.acquire(blocking=False):
        bildirimler.append(("G510 Panel", "Güncelleme zaten indiriliyor", "Bitince kendiliğinden yeniden başlar."))
        return
    try:
        etiket, varlik = veri["guncelleme"]
        bildirimler.append(("G510 Panel", f"{etiket} indiriliyor…", "Bitince kendiliğinden yeniden başlar."))
        icerik = github_istek(f"/releases/assets/{varlik}", ikili=True)
        if len(icerik) < 1_000_000 or icerik[:2] != b"MZ":
            raise ValueError("indirilen dosya exe değil")
        yeni = os.path.join(KLASOR, "G510 Panel.yeni.exe")
        if os.path.exists(yeni):  # önceki yarım denemeden kalmış olabilir
            os.remove(yeni)
        with open(yeni, "wb") as f:
            f.write(icerik)
        subprocess.Popen([yeni, "--guncelleme-bitir", sys.executable])
        cikis.set()
    finally:
        _guncelleme_kilidi.release()


def guncellemeyi_bitir(eski):
    """Yeni exe'den çalışır: eski exe kapanınca (dosya kilidi kalkınca) üzerine kopyalanır ve onu başlatır."""
    for _ in range(120):
        try:
            shutil.copyfile(sys.executable, eski)
            break
        except OSError:
            time.sleep(0.5)
    else:
        print("güncelleme: eski exe değiştirilemedi")
        return
    subprocess.Popen([eski])


def rgb_hedef(t):
    """Seçili moda göre klavye rengi, yüzde (0-100)."""
    _, tur, p = RGB_MODLAR[ayarlar["rgb_mod"]]
    if tur == "sabit":
        return p
    if tur == "nefes":  # 4 saniyelik yavaş nefes, hiç tam sönmeden
        parlaklik = 0.1 + 0.9 * (1 - math.cos(t * math.pi / 2)) / 2
        return tuple(v * parlaklik for v in p)
    if tur == "yuk":  # yeşil -> sarı -> kırmızı
        yuk = max(veri["cpu"], veri["gpu"][1] if veri["gpu"] else 0) / 100
        ton = (1 - min(yuk, 1)) / 3
    elif tur == "gpu_isi":  # 35°C mavi -> 85°C kırmızı
        oran = min(max(((veri["gpu"][0] if veri["gpu"] else 35) - 35) / 50, 0), 1)
        ton = (1 - oran) * 2 / 3
    elif tur == "medya" and veri["medya"] and veri["medya"][4]:
        return MARKA_RENKLERI.get(veri["medya"][5], (100, 100, 100))
    else:  # gökkuşağı; medya modunda çalan bir şey yokken yavaş gökkuşağı
        ton = (t / (p if tur == "dongu" else 120)) % 1
    return tuple(v * 100 for v in colorsys.hsv_to_rgb(ton, 1, 1))


def rgb_dongusu():
    """Klavye ışığını 20 Hz'de yumuşak geçişle günceller; yalnız renk değişince SDK'ya yazar."""
    led = ctypes.WinDLL(LED_DLL)
    led.LogiLedInit.restype = led.LogiLedSetLighting.restype = ctypes.c_bool
    rgb["led"] = led
    son = None
    while True:
        try:
            if RGB_MODLAR[ayarlar["rgb_mod"]][1] == "kapali":
                if rgb["aktif"]:  # ışığı LGS profiline geri ver
                    led.LogiLedRestoreLighting()
                    led.LogiLedShutdown()
                    rgb["aktif"], son = False, None
                rgb["renk"] = [0.0, 0.0, 0.0]
            else:
                if not rgb["aktif"]:
                    if not led.LogiLedInit():  # LGS henüz hazır değil
                        time.sleep(5)
                        continue
                    led.LogiLedSetTargetDevice(2)  # LOGI_DEVICETYPE_RGB
                    led.LogiLedSaveCurrentLighting()
                    rgb["aktif"] = True
                simdi = time.monotonic()
                if rgb["flas"] and simdi < rgb["flas"][1]:  # bildirim: uygulamanın renginde yanıp sön
                    rgb["renk"] = list(rgb["flas"][0] if int(simdi * 4) % 2 == 0 else (0, 0, 0))
                else:
                    rgb["renk"] = [a + (b - a) * 0.15 for a, b in zip(rgb["renk"], rgb_hedef(simdi))]
                yeni = tuple(round(v) for v in rgb["renk"])
                if yeni != son:
                    led.LogiLedSetLighting(*yeni)
                    son = yeni
        except Exception as e:
            print("rgb:", e)
            time.sleep(1)
        time.sleep(0.05)


def rgb_kapat():
    if rgb["aktif"]:
        rgb["led"].LogiLedRestoreLighting()
        rgb["led"].LogiLedShutdown()
        rgb["aktif"] = False


def hava_metni(kod):  # WMO hava kodları
    for sinir, ad in ((0, "Açık"), (1, "Az bulutlu"), (2, "Parçalı bulutlu"), (3, "Kapalı"), (48, "Sisli"),
                      (57, "Çisenti"), (67, "Yağmurlu"), (77, "Karlı"), (82, "Sağanak"), (86, "Kar sağanağı"), (99, "Fırtına")):
        if kod <= sinir:
            return ad
    return "?"


def hava_ikonu(kod, gunduz=True):  # WMO kodu -> HAVA_IKONLARI anahtarı
    for sinir, ad in ((0, "gunes" if gunduz else "ay"), (2, "parcali"), (3, "bulut"), (48, "sis"), (67, "yagmur"),
                      (77, "kar"), (82, "yagmur"), (86, "kar"), (99, "firtina")):
        if kod <= sinir:
            return ad
    return "bulut"


def http_oku(url):
    istek = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 g510-panel"})
    with urllib.request.urlopen(istek, timeout=10) as r:
        return r.read()


def http_json(url):
    return json.loads(http_oku(url))


def rss_oku(url, adet=10):
    """[(başlık, bağlantı, yayın zamanı ya da None)]"""
    haberler = []
    for item in ET.fromstring(http_oku(url)).iter("item"):
        baslik = temizle(html.unescape(item.findtext("title") or ""))
        link = (item.findtext("link") or "").strip()
        try:
            zaman = email.utils.parsedate_to_datetime(item.findtext("pubDate"))
        except (TypeError, ValueError):
            zaman = None
        if baslik:
            haberler.append((baslik, link, zaman))
        if len(haberler) == adet:
            break
    return haberler


def sirayla(listeler):
    return [h for grup in zip_longest(*listeler) for h in grup if h is not None]


def haber_dongusu():
    """Kaynaklar kendi kategorisinde, kategoriler de birbiriyle sırayla karışır:
    TÜRKİYE, TEKNOLOJİ (Techolay), TÜRKİYE, TEKNOLOJİ (Webtekno)... Tek kategori ekranı doldurmaz."""
    while True:
        kategoriler = {}
        for kategori, kaynak, url in HABER_KAYNAKLARI:
            try:
                kategoriler.setdefault(kategori, []).append([(kategori, kaynak, *h) for h in rss_oku(url)])
            except Exception as e:
                print("haber alınamadı:", kaynak, e)
        karisik = sirayla([sirayla(l) for l in kategoriler.values()])
        if karisik:
            veri["haberler"] = karisik
        time.sleep(600)


async def _windows_konumu():
    from winrt.windows.devices.geolocation import Geolocator
    k = (await Geolocator().get_geoposition_async()).coordinate.point.position
    return k.latitude, k.longitude


def konum_bul():
    """(enlem, boylam, ad). SEHIR boşsa Windows konum servisinden (Wi-Fi/IP), adı OpenStreetMap'ten."""
    if SEHIR:
        g = http_json("https://geocoding-api.open-meteo.com/v1/search?count=1&language=tr&name=" + urllib.parse.quote(SEHIR))
        return g["results"][0]["latitude"], g["results"][0]["longitude"], SEHIR
    enlem, boylam = asyncio.run(_windows_konumu())
    a = http_json("https://nominatim.openstreetmap.org/reverse?format=json&zoom=10&accept-language=tr"
                  f"&lat={enlem:.3f}&lon={boylam:.3f}").get("address", {})
    return enlem, boylam, a.get("province") or a.get("city") or a.get("town") or a.get("state") or "Konum"


def kur_oku(metin):
    """(USD, EUR, gram altın) satış. Servis bazen JSON'u sonundan kesik gönderiyor;
    o zaman ihtiyaç duyulan alanlar (dosyanın başında) ham metinden okunur."""
    anahtarlar = ("USD", "EUR", "gram-altin")
    try:
        k = json.loads(metin)
        return tuple(k[a]["Satış"] for a in anahtarlar)
    except ValueError:
        return tuple(re.search(rf'"{a}":\{{[^}}]*?"Satış":"([^"]+)"', metin).group(1) for a in anahtarlar)


def internet_dongusu():
    konum = None
    while True:
        hata = False
        try:
            if konum is None or yenile.is_set():
                konum = konum_bul()
                veri["konum"] = konum[2]
            h = http_json(f"https://api.open-meteo.com/v1/forecast?latitude={konum[0]}&longitude={konum[1]}"
                          "&current=temperature_2m,weather_code,wind_speed_10m,is_day"
                          "&daily=temperature_2m_max,temperature_2m_min,weather_code&timezone=auto&forecast_days=4")
            c, d = h["current"], h["daily"]
            veri["hava"] = (round(c["temperature_2m"]), hava_metni(c["weather_code"]),
                            round(d["temperature_2m_max"][0]), round(d["temperature_2m_min"][0]), round(c["wind_speed_10m"]),
                            hava_ikonu(c["weather_code"], c.get("is_day", 1)))
            veri["tahmin"] = [(GUNLER[dt.date.fromisoformat(g).weekday()], round(mx), round(mn), hava_ikonu(k))
                              for g, mx, mn, k in zip(d["time"], d["temperature_2m_max"], d["temperature_2m_min"],
                                                      d["weather_code"])][1:]
        except Exception as e:
            print("hava alınamadı:", e)
            hata = True
        try:
            veri["kur"] = kur_oku(http_oku("https://finans.truncgil.com/today.json").decode("utf-8", "replace"))
        except Exception as e:
            print("kur alınamadı:", e)
            hata = True
        yenile.clear()
        yenile.wait(60 if hata else 900)  # 15 dk'da bir (hatada 1 dk sonra) ya da hava sayfasında 3. tuşla hemen


def pencere_basliklari():
    u = ctypes.windll.user32
    basliklar = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def topla(h, _):
        n = u.GetWindowTextLengthW(h)
        if n and u.IsWindowVisible(h):
            b = ctypes.create_unicode_buffer(n + 1)
            u.GetWindowTextW(h, b, n + 1)
            basliklar.append(b.value)
        return True

    u.EnumWindows(topla, 0)
    return basliklar


def site_bul(metin):
    metin = metin.lower()
    return next((ikon for anahtar, ikon in SITELER if anahtar in metin), None)


_kaynaklar = {}  # (uygulama, medya başlığı) -> ikon


def kaynak_bul(uygulama, baslik):
    """Medyanın kaynağı: Spotify gibi uygulamalar kimliğinden, tarayıcıdaki siteler pencere başlığından
    ("Video adı - YouTube - Google Chrome"). Pencere başlığı yalnız öndeki sekmeyi gösterdiği için
    bulunan kaynak medya başlığına göre hatırlanır: başka sekmeye geçince ikon değişmez."""
    tarayici = next((ad for kimlik, ad in TARAYICILAR.items() if kimlik in uygulama.lower()), None)
    if tarayici is None:
        return site_bul(uygulama) or "muzik"
    if (uygulama, baslik) in _kaynaklar:
        return _kaynaklar[uygulama, baslik]
    pencereler = [p for p in pencere_basliklari() if tarayici in p.lower()]
    ikon = next((s for p in pencereler if baslik and baslik in p and (s := site_bul(p))), None)
    if ikon is None:
        # X gibi akışta oynayan videoda sekme başlığı video adını içermez ("Anasayfa / X");
        # o tarayıcıda tanınan tek bir site açıksa kaynak odur
        siteler = {site_bul(p) for p in pencereler} - {None}
        ikon = siteler.pop() if len(siteler) == 1 else "tarayici"
    if ikon != "tarayici":  # emin olunamayanı hatırlama: sekme öne gelince yeniden denensin
        if len(_kaynaklar) > 200:
            _kaynaklar.clear()
        _kaynaklar[uygulama, baslik] = ikon
    return ikon


async def medya_async():
    from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as Yonetici
    yonetici = await Yonetici.request_async()
    while True:
        try:
            s = yonetici.get_current_session()
            while not komutlar.empty():
                k = komutlar.get()
                if s:
                    await (s.try_toggle_play_pause_async() if k == "oynat" else s.try_skip_next_async())
            if s is None:
                veri["medya"] = None
            else:
                p = await s.try_get_media_properties_async()
                z = s.get_timeline_properties()
                calan = s.get_playback_info().playback_status == 4  # PLAYING
                konum = z.position.total_seconds()
                if calan:  # konum yalnız son güncellemede yazılıyor, aradan geçen süreyi ekle
                    son = z.last_updated_time
                    if son.tzinfo is None:
                        son = son.replace(tzinfo=dt.timezone.utc)
                    konum += (dt.datetime.now(dt.timezone.utc) - son).total_seconds()
                veri["medya"] = (temizle(p.title), temizle(p.artist), konum, z.end_time.total_seconds(), calan,
                                 kaynak_bul(s.source_app_user_model_id or "", p.title))
        except Exception as e:
            print("medya:", e)
        await asyncio.sleep(0.5)


def medya_dongusu():
    asyncio.run(medya_async())


# ---------- çizim yardımcıları ----------

_KUTU = bytes(FONT.getmask("\ue000", mode="1"))  # fontta olmayan karakterin çizimi (boş kutu)


@functools.lru_cache(maxsize=4096)
def fontta_var(c):
    return bytes(FONT.getmask(c, mode="1")) != _KUTU


def temizle(metin):
    """Fontta olmayan emoji/simgeleri at; ekranda kutu olarak çıkıyorlar."""
    return " ".join("".join(c for c in unicodedata.normalize("NFC", metin or "") if fontta_var(c)).split())


def yazi(d, xy, metin, font=FONT, renk=255):
    d.text(xy, metin, font=font, fill=renk)


def cubuk(d, x, y, w, h, oran):
    d.rectangle((x, y, x + w - 1, y + h - 1), outline=255)
    if oran > 0:
        d.rectangle((x + 1, y + 1, x + 1 + round((w - 3) * min(oran, 1)), y + h - 2), fill=255)


@functools.lru_cache(maxsize=64)
def kaydirma_adimlari(metin, genislik):
    """Sığmayan metnin her adımda bir kelime kaydırılmış başlangıç indeksleri."""
    adimlar = [0]
    for i, c in enumerate(metin):
        if FONT.getlength(metin[adimlar[-1]:]) <= genislik:
            break
        if c == " ":
            adimlar.append(i + 1)
    return adimlar


def kayan(img, x, y, metin, genislik, t):
    """Sığmayan metni kelime kelime atlatarak kaydırır.
    Piksel piksel kaydırma bu LCD'de iz (ghosting) bırakıyor; her adımda metin duruyor."""
    adimlar = kaydirma_adimlari(metin, genislik)
    sureler = [2.0] + [0.8] * (len(adimlar) - 2) + [2.0] if len(adimlar) > 1 else [1.0]
    kalan = t % sum(sureler)
    for bas, sure in zip(adimlar, sureler):
        if kalan < sure:
            break
        kalan -= sure
    parca = Image.new("L", (genislik, 14), 0)
    d = ImageDraw.Draw(parca)
    d.fontmode = "1"
    yazi(d, (1, 0), metin[bas:])  # 1 px içeride: "A" gibi sola taşan harfler kırpılmasın
    img.paste(parca, (x, y))


def dakika(sn):
    sn = max(0, int(sn))
    return f"{sn // 60}:{sn % 60:02d}"


# ---------- 16x16 ikonlar: (d, x, y, renk); oyuklar zıt renkle çizilir ----------

def ikon_youtube(d, x, y, r):
    d.rounded_rectangle((x, y + 2, x + 15, y + 13), radius=3, fill=r)
    d.polygon(((x + 6, y + 5), (x + 6, y + 10), (x + 10, y + 7)), fill=255 - r)


def ikon_netflix(d, x, y, r):
    d.rectangle((x + 3, y + 1, x + 5, y + 14), fill=r)
    d.rectangle((x + 10, y + 1, x + 12, y + 14), fill=r)
    d.polygon(((x + 3, y + 1), (x + 6, y + 1), (x + 12, y + 14), (x + 9, y + 14)), fill=r)


def ikon_twitch(d, x, y, r):
    d.rectangle((x + 1, y + 1, x + 14, y + 11), outline=r)
    d.polygon(((x + 4, y + 11), (x + 4, y + 15), (x + 8, y + 11)), fill=r)
    d.line((x + 6, y + 4, x + 6, y + 7), fill=r)
    d.line((x + 10, y + 4, x + 10, y + 7), fill=r)


def ikon_spotify(d, x, y, r):
    d.ellipse((x, y, x + 15, y + 15), fill=r)
    for i, (ust, sol, sag) in enumerate(((4, 3, 12), (7, 4, 11), (10, 5, 10))):
        d.line((x + sol, y + ust, x + sag, y + ust + (1 if i < 2 else 0)), fill=255 - r)


def ikon_tarayici(d, x, y, r):
    d.ellipse((x + 1, y + 1, x + 14, y + 14), outline=r)
    d.ellipse((x + 5, y + 1, x + 10, y + 14), outline=r)
    d.line((x + 1, y + 7, x + 14, y + 7), fill=r)


def ikon_muzik(d, x, y, r):
    d.ellipse((x + 2, y + 10, x + 7, y + 14), fill=r)
    d.line((x + 7, y + 1, x + 7, y + 12), fill=r)
    d.line((x + 7, y + 1, x + 12, y + 4), fill=r)
    d.line((x + 7, y + 2, x + 12, y + 5), fill=r)


def ikon_sistem(d, x, y, r):
    d.rectangle((x + 3, y + 3, x + 12, y + 12), outline=r)
    d.rectangle((x + 6, y + 6, x + 9, y + 9), fill=r)
    for k in (5, 8, 10):
        d.line((x + k, y, x + k, y + 2), fill=r)
        d.line((x + k, y + 13, x + k, y + 15), fill=r)
        d.line((x, y + k, x + 2, y + k), fill=r)
        d.line((x + 13, y + k, x + 15, y + k), fill=r)


def ikon_rgb(d, x, y, r):
    for kutu in ((x + 3, y, x + 12, y + 9), (x, y + 6, x + 9, y + 15), (x + 6, y + 6, x + 15, y + 15)):
        d.ellipse(kutu, outline=r)


def ikon_hava(d, x, y, r):
    d.ellipse((x + 1, y + 6, x + 8, y + 13), fill=r)
    d.ellipse((x + 5, y + 3, x + 13, y + 11), fill=r)
    d.rectangle((x + 4, y + 9, x + 14, y + 13), fill=r)


def ikon_animasyon(d, x, y, r):
    d.polygon(((x + 7, y), (x + 9, y + 6), (x + 15, y + 7), (x + 9, y + 9), (x + 7, y + 15),
               (x + 6, y + 9), (x, y + 7), (x + 6, y + 6)), fill=r)


def ikon_x(d, x, y, r):
    d.line((x + 2, y + 1, x + 13, y + 14), fill=r, width=3)
    d.line((x + 13, y + 1, x + 2, y + 14), fill=r)


def ikon_instagram(d, x, y, r):
    d.rounded_rectangle((x + 1, y + 1, x + 14, y + 14), radius=4, outline=r)
    d.ellipse((x + 4, y + 4, x + 11, y + 11), outline=r)
    d.rectangle((x + 11, y + 3, x + 12, y + 4), fill=r)


def ikon_facebook(d, x, y, r):
    d.ellipse((x, y, x + 15, y + 15), fill=r)
    z = 255 - r
    d.rectangle((x + 7, y + 5, x + 9, y + 15), fill=z)  # f'nin gövdesi
    d.rectangle((x + 8, y + 3, x + 11, y + 4), fill=z)
    d.rectangle((x + 5, y + 7, x + 11, y + 8), fill=z)


def ikon_tiktok(d, x, y, r):
    d.rectangle((x + 7, y + 1, x + 9, y + 11), fill=r)
    d.ellipse((x + 2, y + 8, x + 9, y + 14), fill=r)
    d.ellipse((x + 5, y + 10, x + 7, y + 12), fill=255 - r)
    d.line((x + 9, y + 2, x + 13, y + 5), fill=r, width=2)


def ikon_kick(d, x, y, r):
    d.rectangle((x + 2, y + 1, x + 5, y + 14), fill=r)
    d.line((x + 6, y + 8, x + 13, y + 1), fill=r, width=3)
    d.line((x + 6, y + 7, x + 13, y + 14), fill=r, width=3)


def ikon_prime(d, x, y, r):
    d.arc((x, y - 2, x + 15, y + 12), 30, 150, fill=r, width=2)  # gülümseme oku
    d.polygon(((x + 11, y + 8), (x + 15, y + 7), (x + 14, y + 11)), fill=r)


def ikon_disney(d, x, y, r):
    yazi(d, (x, y + 1), "D+", renk=r)


def ikon_soundcloud(d, x, y, r):
    for i, ust in enumerate((9, 7, 6, 5)):
        d.line((x + i * 2, y + ust, x + i * 2, y + 13), fill=r)
    d.ellipse((x + 7, y + 4, x + 15, y + 13), fill=r)
    d.rectangle((x + 7, y + 9, x + 15, y + 13), fill=r)


def ikon_robot(d, x, y, r):
    """Antenli, papyonlu uşak robot (uygulamanın simgesi)."""
    d.rectangle((x + 7, y, x + 8, y + 1), fill=r)  # anten ucu
    d.line((x + 7, y + 2, x + 7, y + 3), fill=r)
    d.rounded_rectangle((x + 2, y + 4, x + 13, y + 10), radius=2, outline=r)
    d.rectangle((x + 5, y + 6, x + 6, y + 7), fill=r)  # gözler
    d.rectangle((x + 9, y + 6, x + 10, y + 7), fill=r)
    d.polygon(((x + 3, y + 12), (x + 3, y + 15), (x + 7, y + 13)), fill=r)  # papyon
    d.polygon(((x + 12, y + 12), (x + 12, y + 15), (x + 8, y + 13)), fill=r)


IKONLAR = {"youtube": ikon_youtube, "netflix": ikon_netflix, "twitch": ikon_twitch, "spotify": ikon_spotify,
           "x": ikon_x, "instagram": ikon_instagram, "facebook": ikon_facebook, "tiktok": ikon_tiktok,
           "kick": ikon_kick, "prime": ikon_prime, "disney": ikon_disney, "soundcloud": ikon_soundcloud,
           "tarayici": ikon_tarayici, "muzik": ikon_muzik}


def ikon_oyun(d, x, y, r):  # oyun kolu
    d.rounded_rectangle((x, y + 4, x + 15, y + 12), radius=3, fill=r)
    z = 255 - r
    d.line((x + 3, y + 8, x + 7, y + 8), fill=z)
    d.line((x + 5, y + 6, x + 5, y + 10), fill=z)
    d.point(((x + 11, y + 7), (x + 13, y + 9)), fill=z)


def ikon_haber(d, x, y, r):  # gazete
    d.rectangle((x + 1, y + 2, x + 14, y + 13), outline=r)
    d.rectangle((x + 3, y + 4, x + 7, y + 8), fill=r)
    for yy in (4, 6, 8):
        d.line((x + 9, y + yy, x + 12, y + yy), fill=r)
    d.line((x + 3, y + 11, x + 12, y + 11), fill=r)


# ---------- hava durumu ikonları (16x16) ----------

def _bulut(d, x, y, r):  # üst yarıya oturan bulut; altına yağış çizilir
    d.ellipse((x + 1, y + 3, x + 8, y + 10), fill=r)
    d.ellipse((x + 5, y, x + 13, y + 8), fill=r)
    d.rectangle((x + 4, y + 6, x + 14, y + 10), fill=r)


def hava_gunes(d, x, y, r):
    d.ellipse((x + 4, y + 4, x + 11, y + 11), fill=r)
    for a in range(8):
        aci = a * math.pi / 4
        d.line((x + 7.5 + 5.5 * math.cos(aci), y + 7.5 + 5.5 * math.sin(aci),
                x + 7.5 + 7.5 * math.cos(aci), y + 7.5 + 7.5 * math.sin(aci)), fill=r)


def hava_ay(d, x, y, r):
    d.ellipse((x + 2, y + 2, x + 13, y + 13), fill=r)
    d.ellipse((x + 6, y, x + 16, y + 10), fill=255 - r)


def hava_parcali(d, x, y, r):
    d.ellipse((x + 8, y + 1, x + 15, y + 8), fill=r)  # bulutun arkasındaki güneş
    d.ellipse((x - 1, y + 6, x + 8, y + 15), fill=255 - r)  # bulutun çevresini aç ki güneşten ayrılsın
    d.ellipse((x + 3, y + 3, x + 12, y + 12), fill=255 - r)
    d.ellipse((x, y + 7, x + 7, y + 14), fill=r)
    d.ellipse((x + 4, y + 4, x + 11, y + 11), fill=r)
    d.rectangle((x + 3, y + 10, x + 13, y + 14), fill=r)


def hava_bulut(d, x, y, r):
    ikon_hava(d, x, y, r)


def hava_yagmur(d, x, y, r):
    _bulut(d, x, y, r)
    for k in (4, 8, 12):
        d.line((x + k, y + 12, x + k - 2, y + 15), fill=r)


def hava_kar(d, x, y, r):
    _bulut(d, x, y, r)
    for k, yy in ((3, 12), (8, 14), (13, 12)):
        d.point(((x + k, y + yy), (x + k - 1, y + yy), (x + k + 1, y + yy), (x + k, y + yy - 1), (x + k, y + yy + 1)),
                fill=r)


def hava_sis(d, x, y, r):
    for i, yy in enumerate((3, 6, 9, 12)):
        d.line((x + (2 if i % 2 else 0), y + yy, x + (15 if i % 2 else 13), y + yy), fill=r)


def hava_firtina(d, x, y, r):
    _bulut(d, x, y, r)
    d.polygon(((x + 8, y + 9), (x + 5, y + 13), (x + 8, y + 13), (x + 6, y + 16), (x + 11, y + 11), (x + 8, y + 11),
               (x + 10, y + 9)), fill=r)


HAVA_IKONLARI = {"gunes": hava_gunes, "ay": hava_ay, "parcali": hava_parcali, "bulut": hava_bulut,
                 "yagmur": hava_yagmur, "kar": hava_kar, "sis": hava_sis, "firtina": hava_firtina}


# ---------- sayfalar ----------

def panel(d, x0, x1, baslik):
    """Çerçeveli sütun ve ters renk başlık bandı."""
    d.rectangle((x0, 0, x1, H - 1), outline=255)
    d.rectangle((x0, 0, x1, 10), fill=255)
    yazi(d, (x0 + 3, 0), baslik, FONT_KUCUK, renk=0)


def olcu_satiri(d, x, y, ad, yuzde, w):
    """Ad solda, yüzde sağda, altında ince çubuk."""
    metin = f"{yuzde:.0f}%"
    if FONT_KUCUK.getlength(ad) + FONT_KUCUK.getlength(metin) + 4 > w:  # "VRAM 100%" gibi sığmayanlarda % düşer
        metin = metin[:-1]
    yazi(d, (x, y), ad, FONT_KUCUK)
    yazi(d, (x + w - FONT_KUCUK.getlength(metin), y), metin, FONT_KUCUK)
    cubuk(d, x, y + 10, w, 4, yuzde / 100)


def sayfa_islemler(d):
    panel(d, 0, W - 1, "En çok CPU kullananlar")
    if not veri["islemler"]:
        yazi(d, (3, 14), "ölçülüyor...", FONT_KUCUK)
    for i, (ad, yuzde) in enumerate(veri["islemler"]):
        y = 12 + i * 10
        while FONT_KUCUK.getlength(ad) > 92:
            ad = ad[:-1]
        yazi(d, (3, y), ad, FONT_KUCUK)
        cubuk(d, 98, y + 2, 30, 5, yuzde / 100)
        metin = f"{yuzde:.1f}%"
        yazi(d, (W - 3 - FONT_KUCUK.getlength(metin), y), metin, FONT_KUCUK)


def sayfa_sistem(img, d, t):
    if gorunum["sistem_detay"]:
        return sayfa_islemler(d)
    # CPU: sıcaklık (Afterburner açıksa) ya da yük, anlık frekans, çekirdek başına dikey çubuklar
    if veri["cpu_isi"] is not None:
        panel(d, 0, 58, f"CPU {veri['cpu_isi']:.0f}°C")
        yazi(d, (3, 12), f"{veri['cpu']:.0f}% {(veri['mhz'] or 0) / 1000:.2f}G", FONT_KUCUK)  # MHz sığmıyor
    else:
        panel(d, 0, 58, f"CPU {veri['cpu']:.0f}%")
        if veri["mhz"]:
            yazi(d, (3, 12), f"{veri['mhz']:.0f} MHz", FONT_KUCUK)
    cekirdek = veri["cekirdek"]
    if cekirdek:
        bw = 55 // len(cekirdek)
        for i, yuk in enumerate(cekirdek):
            x = 3 + i * bw
            d.rectangle((x, 22, x + bw - 3, 40), outline=255)
            h = round(17 * min(yuk, 100) / 100)
            if h:
                d.rectangle((x + 1, 40 - h, x + bw - 4, 39), fill=255)
    # GPU: sıcaklık, yük, VRAM
    g = veri["gpu"]
    panel(d, 60, 112, f"GPU {g[0]:.0f}°C" if g else "GPU")
    if g:
        olcu_satiri(d, 63, 12, "Yük", g[1], 48)
        olcu_satiri(d, 63, 27, "VRAM", g[2] / g[3] * 100, 48)
    else:
        yazi(d, (63, 12), "veri yok", FONT_KUCUK)
    # saat, RAM, disk
    panel(d, 114, W - 1, dt.datetime.now().strftime("%H:%M:%S"))
    olcu_satiri(d, 116, 12, "RAM", veri["ram"], 42)
    olcu_satiri(d, 116, 27, "C:", veri["disk"], 42)


def sayfa_medya(img, d, t):
    m = veri["medya"]
    if not m:
        yazi(d, (0, 14), "Çalan medya yok")
        return
    baslik, sanatci, konum, sure, calan, kaynak = m
    IKONLAR[kaynak](d, 0, 5, 255)
    kayan(img, 20, 0, baslik or "?", W - 20, t)
    kayan(img, 20, 13, sanatci, W - 20, t)
    if calan:
        d.polygon(((0, 30), (0, 40), (6, 35)), fill=255)
    else:
        d.rectangle((0, 30, 1, 40), fill=255)
        d.rectangle((4, 30, 5, 40), fill=255)
    if sure > 0:
        yazi(d, (10, 28), dakika(min(konum, sure)))
        cubuk(d, 38, 31, 90, 8, konum / sure)
        yazi(d, (132, 28), dakika(sure))


def rgb_imleci():
    if gorunum["rgb_imlec"] is None:  # sayfaya her girişte imleç etkin moddan başlar
        gorunum["rgb_imlec"] = ayarlar["rgb_mod"]
    return gorunum["rgb_imlec"]


def sayfa_rgb(img, d, t):
    """Solda kayan mod listesi (imleç ters renk, etkin mod noktalı), sağda anlık R/G/B çubukları."""
    imlec = rgb_imleci()
    bas = min(max(imlec - 1, 0), len(RGB_MODLAR) - 3)  # imleci ortada tutan 3 satırlık pencere
    for i in range(3):
        n, y = bas + i, i * 14
        renk = 0 if n == imlec else 255
        if n == imlec:
            d.rectangle((0, y, 113, y + 13), fill=255)
        if n == ayarlar["rgb_mod"]:
            d.ellipse((3, y + 4, 7, y + 8), fill=renk)
        yazi(d, (11, y), RGB_MODLAR[n][0], renk=renk)
    for i, (harf, deger) in enumerate(zip("RGB", rgb["renk"])):
        x = 120 + i * 14
        d.rectangle((x, 0, x + 9, 32), outline=255)
        h = round(31 * min(deger, 100) / 100)
        if h:
            d.rectangle((x + 1, 32 - h, x + 8, 31), fill=255)
        yazi(d, (x + 2, 33), harf, FONT_KUCUK)


def sayfa_hava(img, d, t):
    if gorunum["hava_tahmin"]:  # 3 sütun: gün, ikon, en yüksek/en düşük
        if not veri["tahmin"]:
            yazi(d, (0, 14), "Tahmin bekleniyor...")
        for i, (gun, en_yuksek, en_dusuk, ikon) in enumerate((veri["tahmin"] or [])[:3]):
            orta = 26 + i * 54
            yazi(d, (orta - FONT.getlength(gun) // 2, -1), gun)
            HAVA_IKONLARI[ikon](d, orta - 8, 13, 255)
            metin = f"{en_yuksek}° / {en_dusuk}°"
            yazi(d, (orta - FONT_KUCUK.getlength(metin) // 2, 32), metin, FONT_KUCUK)
            if i:
                d.line((orta - 27, 2, orta - 27, 40), fill=255)
        return
    h, k = veri["hava"], veri["kur"]
    if h:
        HAVA_IKONLARI[h[5]](d, 0, 5, 255)
        kayan(img, 20, -1, f"{veri['konum'] or 'Konum'} {h[0]}° {h[1]}", W - 20, t)
        yazi(d, (20, 13), f"↑{h[2]}° ↓{h[3]}°  Rüzgar {h[4]} km/s")
    else:
        yazi(d, (0, 0), "Hava durumu bekleniyor...")
    if k:
        usd, eur = (s.split(",")[0] + "," + (s.split(",") + ["00"])[1][:2] for s in k[:2])  # 2 ondalık
        yazi(d, (0, 28), f"${usd}  €{eur}  Au {k[2].split(',')[0]}")


def sar(metin, font, genislik, en_cok):
    """Metni kelime kelime satırlara böler; en_cok satırı aşarsa son satır '…' ile kesilir."""
    satirlar = [""]
    for kelime in metin.split():
        aday = f"{satirlar[-1]} {kelime}".strip()
        if font.getlength(aday) <= genislik or not satirlar[-1]:
            satirlar[-1] = aday
        else:
            satirlar.append(kelime)
    if len(satirlar) > en_cok:
        son = " ".join(satirlar[en_cok - 1:])
        while font.getlength(son + "…") > genislik:
            son = son[:-1]
        satirlar = satirlar[:en_cok - 1] + [son.rstrip() + "…"]
    return satirlar


def once(zaman):
    if zaman is None:
        return ""
    dakika_ = int((dt.datetime.now(dt.timezone.utc) - zaman).total_seconds() // 60)
    return f"{dakika_} dk" if dakika_ < 60 else f"{dakika_ // 60} sa" if dakika_ < 1440 else f"{dakika_ // 1440} gün"


def secili_haber():
    haberler = veri["haberler"]
    return haberler[gorunum["haber_i"] % len(haberler)] if haberler else None


def sayfa_haber(img, d, t):
    """Üstte kategori bandı, kaynak, ne kadar önce ve sıra no; altta başlık (sığmazsa küçük font, 3 satır)."""
    if not veri["haberler"]:
        yazi(d, (0, 14), "Haberler yükleniyor...")
        return
    if t - gorunum["haber_son"] > 1:  # sayfa ekranda değildi: o süre sayılmasın, haber kaldığı yerden sürsün
        gorunum["haber_t"] += t - gorunum["haber_son"]
    gorunum["haber_son"] = t
    if t - gorunum["haber_t"] >= HABER_SN:
        gorunum["haber_i"] += 1
        gorunum["haber_t"] = t
    kategori, kaynak, baslik, _, zaman = secili_haber()
    kw = int(FONT_KUCUK.getlength(kategori)) + 5
    d.rectangle((0, 0, kw, 9), fill=255)
    yazi(d, (3, -1), kategori, FONT_KUCUK, renk=0)
    sira = f"{gorunum['haber_i'] % len(veri['haberler']) + 1}/{len(veri['haberler'])}"
    yazi(d, (W - FONT_KUCUK.getlength(sira), -1), sira, FONT_KUCUK)
    yer = W - FONT_KUCUK.getlength(sira) - kw - 8  # sayaçla çakışmasın: sığmazsa önce zaman düşer
    bilgi = next((b for b in (" · ".join(s for s in (kaynak, once(zaman)) if s), kaynak)
                  if FONT_KUCUK.getlength(b) <= yer), kaynak)
    while bilgi and FONT_KUCUK.getlength(bilgi) > yer:
        bilgi = bilgi[:-1]
    yazi(d, (kw + 4, -1), bilgi, FONT_KUCUK)
    satirlar = sar(baslik, FONT, W, 2)
    if satirlar[-1].endswith("…") and len(sar(baslik, FONT_KUCUK, W, 3)) == 3:  # büyük fontta kesiliyorsa küçüğe geç
        for i, s in enumerate(sar(baslik, FONT_KUCUK, W, 3)):
            yazi(d, (0, 11 + i * 10), s, FONT_KUCUK)
    else:
        for i, s in enumerate(satirlar):
            yazi(d, (0, 12 + i * 14), s)


def sayfa_oyun(img, d, t):
    """Tam ekran oyun: solda oyunun ikonu, büyük FPS (yoksa GPU sıcaklığı), GPU ve CPU yükü ile sıcaklıkları."""
    saat = dt.datetime.now().strftime("%H:%M")
    ad = veri["oyun"] or "Oyun modu"
    while ad and FONT_KUCUK.getlength(ad) > W - FONT_KUCUK.getlength(saat) - 12:
        ad = ad[:-1]
    panel(d, 0, W - 1, ad)
    yazi(d, (W - 3 - FONT_KUCUK.getlength(saat), 0), saat, FONT_KUCUK, renk=0)
    if veri["oyun_ikon"]:
        img.paste(veri["oyun_ikon"], (2, 11))
    else:
        ikon_oyun(d, 10, 19, 255)
    g, fps, cpu_isi = veri["gpu"], veri["fps"], veri["cpu_isi"]
    if fps is not None:  # RTSS oyunu izliyor
        yazi(d, (38, 9), f"{fps:.0f}", FONT_BUYUK)
        yazi(d, (40, 33), "FPS", FONT_KUCUK)
    else:
        yazi(d, (38, 9), f"{g[0]:.0f}°" if g else "--°", FONT_BUYUK)
        yazi(d, (40, 33), "GPU", FONT_KUCUK)
    if g:
        olcu_satiri(d, 84, 12, f"GPU {g[0]:.0f}°" if fps is not None else "GPU yük", g[1], 73)
    olcu_satiri(d, 84, 27, f"CPU {cpu_isi:.0f}°" if cpu_isi is not None else "CPU", veri["cpu"], 73)


def bildirim_ciz(img, d, bildirim, t):
    """Tüm ekranı kaplayan bildirim kartı: üstte ortada kalın uygulama adı, altında başlık ve metin;
    sığmayan satır kelime kelime kayar (bildirim açıldığında baştan başlar)."""
    uygulama, baslik, metin = bildirim[:3]
    gecen = t - (bildirim[3] - BILDIRIM_SN) if len(bildirim) > 3 else 0.0
    d.rectangle((0, 0, W - 1, H - 1), fill=0)
    d.rectangle((0, 0, W - 1, 14), fill=255)
    ad = sar(uygulama, FONT_KALIN, W - 6, 1)[0]
    yazi(d, ((W - FONT_KALIN.getlength(ad)) // 2, 0), ad, FONT_KALIN, renk=0)
    satirlar = [s for s in (baslik, metin) if s]
    for i, s in enumerate(satirlar[:2]):
        kayan(img, 0, 15 + i * 14, s, W, gecen)


def ses_ciz(d, ses):
    """Ses seviyesi değişince ortada beliren gösterge."""
    seviye, sessiz = ses
    d.rounded_rectangle((10, 6, 150, 36), radius=5, fill=0)
    d.rounded_rectangle((11, 7, 149, 35), radius=4, fill=255)
    d.rectangle((17, 17, 20, 25), fill=0)  # hoparlör
    d.polygon(((20, 17), (25, 12), (25, 30), (20, 25)), fill=0)
    if sessiz:
        d.line((29, 15, 35, 27), fill=0, width=2)
        d.line((35, 15, 29, 27), fill=0, width=2)
        yazi(d, (44, 14), "Sessiz", renk=0)
        return
    d.rectangle((31, 17, 116, 25), outline=0)
    if seviye:
        d.rectangle((33, 19, 33 + round(81 * seviye / 100), 23), fill=0)
    metin = f"{seviye}%"
    yazi(d, (145 - FONT.getlength(metin), 14), metin, renk=0)


def mikrofon_isareti(d):
    """Mikrofon sessizdeyken sağ üst köşede üstü çizili mikrofon."""
    x = W - 10
    d.rectangle((x, 0, W - 1, 11), fill=255)
    d.rounded_rectangle((x + 3, 1, x + 6, 6), radius=1, fill=0)
    d.arc((x + 2, 3, x + 7, 8), 0, 180, fill=0)
    d.line((x + 4, 8, x + 4, 10), fill=0)
    d.line((x + 1, 10, x + 8, 1), fill=0)


class Hayat:
    """Conway'in Hayat Oyunu, 2x2 piksellik hücreler."""
    GW, GH = W // 2, (H + 1) // 2

    def __init__(self):
        self.sifirla()

    def sifirla(self):
        self.h = [[random.random() < 0.3 for _ in range(self.GW)] for _ in range(self.GH)]
        self.gecmis = deque(maxlen=4)
        self.nesil = 0

    def ciz(self, img, d, t):
        for y, satir in enumerate(self.h):
            for x, c in enumerate(satir):
                if c:
                    d.rectangle((x * 2, y * 2, x * 2 + 1, y * 2 + 1), fill=255)
        h, gw, gh = self.h, self.GW, self.GH
        self.h = [[(n := sum(h[(y + dy) % gh][(x + dx) % gw] for dy in (-1, 0, 1) for dx in (-1, 0, 1)) - h[y][x]) == 3
                   or (h[y][x] and n == 2) for x in range(gw)] for y in range(gh)]
        anahtar = tuple(map(tuple, self.h))
        self.nesil += 1
        if anahtar in self.gecmis or self.nesil > 1500:  # durağanlaştı ya da yeterince sürdü
            self.sifirla()
        self.gecmis.append(anahtar)


class Yildizlar:
    """Ekrana doğru akan yıldız alanı."""

    def __init__(self):
        self.sifirla()

    def sifirla(self):
        self.y = [[random.uniform(-1, 1), random.uniform(-1, 1), random.uniform(0.1, 1)] for _ in range(70)]

    def ciz(self, img, d, t):
        for s in self.y:
            s[2] -= 0.02
            px, py = W / 2 + s[0] / s[2] * 50, H / 2 + s[1] / s[2] * 25
            if s[2] <= 0.02 or not (0 <= px < W and 0 <= py < H):
                s[:] = [random.uniform(-1, 1), random.uniform(-1, 1), 1]
                continue
            r = 1 if s[2] < 0.3 else 0
            d.rectangle((px, py, px + r, py + r), fill=255)


# 4x4 Bayer eşikleri: gri tonları tek renkli ekranda nokta deseniyle göstermek için
_ESIK = [[(v + 0.5) / 16 for v in satir] for satir in ((0, 8, 2, 10), (12, 4, 14, 6), (3, 11, 1, 9), (15, 7, 13, 5))]


def titrek_bas(img, satirlar):
    """satirlar[y][x] (0-1) değerlerini Bayer titreştirmesiyle img'ye basar."""
    buf = bytearray(W * H)
    for y in range(H):
        esik, satir, bas = _ESIK[y & 3], satirlar[y], y * W
        for x in range(W):
            if satir[x] > esik[x & 3]:
                buf[bas + x] = 255
    img.paste(Image.frombytes("L", (W, H), bytes(buf)))


@functools.lru_cache(maxsize=1)
def robot_resmi():
    """Robot simgesi, 2 kat büyütülmüş (32x32)."""
    robot = Image.new("L", (16, 16), 0)
    ikon_robot(ImageDraw.Draw(robot), 0, 0, 255)
    return robot.resize((32, 32), Image.NEAREST)


class AnalogSaat:
    """Ortada analog saat; solda dijital saat ve tarih, sağda hava durumu."""

    def sifirla(self):
        pass

    def ciz(self, img, d, t):
        s = dt.datetime.now()
        cx, cy, r = 80, 21, 20
        d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=255)
        for i in range(12):
            a, ic = i * math.pi / 6, r - (5 if i % 3 == 0 else 3)
            d.line((cx + ic * math.sin(a), cy - ic * math.cos(a), cx + (r - 1) * math.sin(a), cy - (r - 1) * math.cos(a)),
                   fill=255)
        for oran, boy, kalin in (((s.hour % 12 + s.minute / 60) / 12, 10, 2), ((s.minute + s.second / 60) / 60, 16, 1),
                                 (s.second / 60, 18, 1)):
            a = oran * 2 * math.pi
            d.line((cx, cy, cx + boy * math.sin(a), cy - boy * math.cos(a)), fill=255, width=kalin)
        yazi(d, (0, 4), s.strftime("%H:%M"))
        yazi(d, (0, 19), f"{s.day} {AYLAR[s.month - 1]}", FONT_KUCUK)
        yazi(d, (0, 29), GUNLER[s.weekday()], FONT_KUCUK)
        if veri["hava"]:
            HAVA_IKONLARI[veri["hava"][5]](d, 130, 4, 255)
            metin = f"{veri['hava'][0]}°C"
            yazi(d, (138 - FONT_KUCUK.getlength(metin) // 2, 24), metin, FONT_KUCUK)


class Plazma:
    """Dalgalanan sinüs plazması."""

    def __init__(self):
        self.uzaklik = [[math.hypot(x - W / 2, y - H / 2) / 7 for x in range(W)] for y in range(H)]

    def sifirla(self):
        pass

    def ciz(self, img, d, t):
        s = math.sin
        kolon = [s(x / 9 + t) for x in range(W)]
        satirlar = []
        for y in range(H):
            a, u = s(y / 6 + t * 1.1), self.uzaklik[y]
            satirlar.append([(kolon[x] + a + s((x + y) / 12 + t * 0.7) + s(u[x] - t * 1.5) + 4) / 8 for x in range(W)])
        titrek_bas(img, satirlar)


class Matrix:
    """Filmdeki gibi: karakterler sabit ızgarada durur (aynalı yarım genişlik katakana + rakam), her sütunda
    hücre hücre düşen kalın bir baş ve arkasında titreştirmeyle giderek sönen iz; karakterler ara ara değişir."""
    KARAKTER = "ｦｱｲｳｴｵｶｷｸｹｺｻｼｽｾｿﾀﾁﾂﾃﾄﾅﾆﾇﾈﾊﾋﾌﾍﾎﾏﾐﾑﾒﾓﾔﾕﾗﾘﾜ0123456789Z:.=*+-<>¦"
    HW, HH = 6, 9  # hücre; 10 px'lik glifin boş üst satırı komşu hücreyle çakışır
    SUTUN, SATIR = W // HW, -(-H // HH)

    def __init__(self):
        font = ImageFont.truetype(r"C:\Windows\Fonts\msgothic.ttc", 10)  # Tahoma'da katakana yok
        self.glifler = []
        for c in self.KARAKTER:
            g = Image.new("L", (self.HW, 12), 0)
            gd = ImageDraw.Draw(g)
            gd.fontmode = "1"
            gd.text((0, -1), c, font=font, fill=255)
            px = ImageOps.mirror(g).load()
            self.glifler.append([(x, y) for y in range(10) for x in range(self.HW) if px[x, y]])
        self.sifirla()

    @staticmethod
    def _damla(bas):  # [baş satırı, hız (hücre/kare), iz uzunluğu]
        return [bas, random.uniform(0.15, 0.55), random.randint(3, 9)]

    def sifirla(self):
        self.izgara = [[random.randrange(len(self.glifler)) for _ in range(self.SATIR)] for _ in range(self.SUTUN)]
        self.damlalar = [[self._damla(random.uniform(-8, self.SATIR))] if random.random() < 0.7 else []
                         for _ in range(self.SUTUN)]

    def ciz(self, img, d, t):
        n = len(self.glifler)
        for _ in range(4):  # ara ara değişen karakterler
            self.izgara[random.randrange(self.SUTUN)][random.randrange(self.SATIR)] = random.randrange(n)
        buf = bytearray(W * H)
        for s, damlalar in enumerate(self.damlalar):
            parlaklik = [0.0] * self.SATIR
            for dm in damlalar:
                dm[0] += dm[1]
                bas = int(dm[0])
                for r in range(max(bas - dm[2], 0), min(bas + 1, self.SATIR)):
                    k = bas - r
                    parlaklik[r] = max(parlaklik[r], 1.0 if k == 0 else 0.95 * (1 - k / (dm[2] + 1)))
                if 0 <= bas < self.SATIR and random.random() < 0.5:  # baştaki karakter hızla değişir
                    self.izgara[s][bas] = random.randrange(n)
            damlalar[:] = [dm for dm in damlalar if dm[0] - dm[2] < self.SATIR]
            if (not damlalar and random.random() < 0.08) or (
                    len(damlalar) == 1 and damlalar[0][0] - damlalar[0][2] > 1 and random.random() < 0.03):
                damlalar.append(self._damla(random.uniform(-3, -1)))
            x0 = s * self.HW
            for r, p in enumerate(parlaklik):
                if p <= 0:
                    continue
                y0 = r * self.HH
                for dx, dy in self.glifler[self.izgara[s][r]]:
                    x, y = x0 + dx, y0 + dy
                    if y < H and (p == 1.0 or p > _ESIK[y & 3][x & 3]):
                        buf[y * W + x] = 255
                        if p == 1.0 and dx + 1 < self.HW:  # baş kalın: "parlak" görünsün
                            buf[y * W + x + 1] = 255
        img.paste(Image.frombytes("L", (W, H), bytes(buf)))


_KUP_KOSE = [(x, y, z) for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)]
_KUP_KENAR = [(a, b) for a in range(8) for b in range(a + 1, 8)
              if sum(p != q for p, q in zip(_KUP_KOSE[a], _KUP_KOSE[b])) == 1]


class Kupler:
    """Ortada büyük, yanlarda küçük, farklı hızlarda dönen tel kafes küpler."""

    def sifirla(self):
        pass

    @staticmethod
    def kup(d, cx, cy, olcek, ax, ay):
        noktalar = []
        for x, y, z in _KUP_KOSE:
            y, z = y * math.cos(ax) - z * math.sin(ax), y * math.sin(ax) + z * math.cos(ax)
            x, z = x * math.cos(ay) + z * math.sin(ay), -x * math.sin(ay) + z * math.cos(ay)
            f = olcek / (z + 4)
            noktalar.append((cx + x * f, cy + y * f))
        for a, b in _KUP_KENAR:
            d.line(noktalar[a] + noktalar[b], fill=255)

    def ciz(self, img, d, t):
        self.kup(d, 80, 21, 26, t * 0.8, t * 1.1)
        self.kup(d, 22, 21, 13, -t * 1.3, t * 0.6)
        self.kup(d, 138, 21, 13, t * 0.5, -t * 1.4)


class Ates:
    """Alttan yükselen, titreştirmeyle çizilen alevler."""

    def __init__(self):
        self.sifirla()

    def sifirla(self):
        self.isi = [[0.0] * W for _ in range(H + 2)]

    def ciz(self, img, d, t):
        isi = self.isi
        isi[H + 1] = [random.choice((0.0, 1.0, 1.0)) for _ in range(W)]  # yakıt satırı
        for y in range(H + 1):  # üstten alta: her satır bir önceki karedeki alt satırlardan beslenir
            alt, alt2, satir = isi[y + 1], isi[min(y + 2, H + 1)], isi[y]
            for x in range(W):
                satir[x] = max((alt[x - 1] + alt[x] + alt[(x + 1) % W] + alt2[x]) / 4 - 0.022, 0.0)  # soğuma
        titrek_bas(img, [[min(v * 1.4, 1) for v in satir] for satir in isi[:H]])


class Robot:
    """Ekranda seken robot."""

    def __init__(self):
        self.sifirla()

    def sifirla(self):
        self.x, self.y, self.vx, self.vy = 10.0, 3.0, 1.6, 0.6

    def ciz(self, img, d, t):
        self.x += self.vx
        self.y += self.vy
        if not 0 <= self.x <= W - 32:
            self.vx, self.x = -self.vx, min(max(self.x, 0), W - 32)
        if not 0 <= self.y <= H - 32:
            self.vy, self.y = -self.vy, min(max(self.y, 0), H - 32)
        img.paste(robot_resmi(), (int(self.x), int(self.y)))


animasyonlar = [AnalogSaat(), Plazma(), Matrix(), Kupler(), Ates(), Robot(), Yildizlar(), Hayat()]
secili_anim = 0


def sayfa_animasyon(img, d, t):
    animasyonlar[secili_anim].ciz(img, d, t)


# (çizim, ad, ikon, 3/4 tuşlarının işi)
SAYFALAR = [(sayfa_sistem, "Sistem", ikon_sistem, "3: Görev Yöneticisi   4: işlemler"),
            (sayfa_medya, "Medya", ikon_muzik, "3: oynat/duraklat   4: sonraki"),
            (sayfa_rgb, "RGB", ikon_rgb, "3: aşağı   4: seç"),
            (sayfa_hava, "Hava & Piyasa", ikon_hava, "3: yenile   4: 3 günlük"),
            (sayfa_haber, "Haberler", ikon_haber, "3: sonraki   4: tarayıcıda aç"),
            (sayfa_oyun, "Oyun", ikon_oyun, "3: oyun modu aç/kapat"),
            (sayfa_animasyon, "Animasyon", ikon_animasyon, "3: baştan   4: değiştir")]
SAYFA_NO = {s[0]: i for i, s in enumerate(SAYFALAR)}


def sayfa_etiketi(d, sayfa):
    """Sayfa değişince ortada beliren ikonlu ad etiketi (ters renk)."""
    _, ad, ikon, ipucu = SAYFALAR[sayfa]
    kw = int(max(FONT.getlength(ad) + 30, FONT_KUCUK.getlength(ipucu) + 12))
    x0 = (W - kw) // 2
    d.rounded_rectangle((x0 - 1, 3, x0 + kw + 1, 39), radius=5, fill=0)  # etiketin çevresini temizle
    d.rounded_rectangle((x0, 4, x0 + kw, 38), radius=4, fill=255)
    ikon(d, x0 + 6, 6, 0)
    yazi(d, (x0 + 25, 7), ad, renk=0)
    yazi(d, (x0 + (kw - FONT_KUCUK.getlength(ipucu)) // 2, 26), ipucu, FONT_KUCUK, renk=0)  # 3/4 tuşlarının işi


def acilis(img, d):
    img.paste(robot_resmi(), (22, 5))
    for metin, font, y in (("G510", FONT_BUYUK, 0), ("P A N E L", FONT, 28)):
        yazi(d, (105 - font.getlength(metin) // 2, y), metin, font)
    d.line((75, 26, 135, 26), fill=255)


def ciz(sayfa, t, etiket=False, acilista=False, bildirim=None, ses=None):
    """Sayfa ve üstündeki katmanlar: sayfa etiketi < ses göstergesi < bildirim; mikrofon sessizse köşe işareti."""
    img = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(img)
    d.fontmode = "1"  # kenar yumuşatma yok: tek renkli ekranda net görünsün
    if acilista:
        acilis(img, d)
        return img
    SAYFALAR[sayfa][0](img, d, t)
    if etiket:
        sayfa_etiketi(d, sayfa)
    if ses:
        ses_ciz(d, ses)
    if bildirim:
        bildirim_ciz(img, d, bildirim, t)
    if veri["mik_sessiz"]:
        mikrofon_isareti(d)
    return img


def sayfa_tusu(sayfa, tus):
    """tus: 2 = ekranın 3. tuşu, 3 = 4. tuşu."""
    global secili_anim
    sf = SAYFALAR[sayfa][0]
    if sf is sayfa_sistem:
        if tus == 2:
            try:
                os.startfile("taskmgr.exe")  # startfile: Görev Yöneticisi yönetici izni isterse Windows sorar
            except OSError as e:
                print("görev yöneticisi:", e)
        else:
            gorunum["sistem_detay"] = not gorunum["sistem_detay"]
            veri["islemler"] = []
    elif sf is sayfa_medya:
        komutlar.put("oynat" if tus == 2 else "sonraki")
    elif sf is sayfa_rgb:
        if tus == 2:
            gorunum["rgb_imlec"] = (rgb_imleci() + 1) % len(RGB_MODLAR)
        else:
            ayarlar["rgb_mod"] = rgb_imleci()
            ayar_kaydet()
    elif sf is sayfa_hava:
        if tus == 2:
            yenile.set()
        else:
            gorunum["hava_tahmin"] = not gorunum["hava_tahmin"]
    elif sf is sayfa_haber:
        if tus == 2:
            gorunum["haber_i"] += 1
            gorunum["haber_t"] = time.monotonic()
        elif (haber := secili_haber()) and haber[3].startswith(("https://", "http://")):
            webbrowser.open(haber[3])
    elif sf is sayfa_oyun:
        if tus == 2:
            ayarlar["oyun_modu"] = not ayarlar["oyun_modu"]
            ayar_kaydet()
    elif sf is sayfa_animasyon:
        if tus == 2:
            animasyonlar[secili_anim].sifirla()
        else:
            animasyon_degistir()


def animasyon_degistir():
    global secili_anim
    secili_anim = (secili_anim + 1) % len(animasyonlar)
    animasyonlar[secili_anim].sifirla()


# ---------- otomatik sayfa geçişleri ----------

class _SonGirdi(ctypes.Structure):
    _fields_ = [("boyut", ctypes.c_uint), ("zaman", ctypes.c_uint)]


def bosta_sure():
    """Klavye ya da fareye en son dokunulmasından bu yana geçen saniye."""
    g = _SonGirdi(ctypes.sizeof(_SonGirdi), 0)
    ctypes.windll.user32.GetLastInputInfo(ctypes.byref(g))
    return ((ctypes.windll.kernel32.GetTickCount() - g.zaman) & 0xFFFFFFFF) / 1000  # 49 günde bir başa sarar


def yeni_oto():
    return {"calan": False, "medya_son": -1e9, "manuel": -1e9, "anim": 0.0}


def otomatik_sayfa(simdi, sayfa, oto, medya, bosta, saniye, oyun=None):
    """Gösterilecek sayfa. saniye: saatin o anki saniyesi (0-59); oyun: tam ekran oyunun adı ya da None.
    Öncelik: oyun -> Oyun (tuş beklemesi dışında); medya çalmaya başladı -> Medya (tuş beklemesine bakmadan);
    LCD tuşuna yeni basıldıysa dokunma; medya çalıyor -> Medya; kullanıcı boşta -> Animasyon (dakikada bir
    değişir); medya yeni durduysa bekle; yoksa Haberler, her dakikanın sonunda 10 sn Hava ve 10 sn Sistem."""
    calan = bool(medya and medya[4])
    basladi, oto["calan"] = calan and not oto["calan"], calan  # aynı listede parça değişimi sayılmaz
    if calan:
        oto["medya_son"] = simdi
    elle = simdi - oto["manuel"] < MANUEL_SN
    if oyun and not elle:  # oyunda kumanda kullanılınca klavye "boşta" görünür: animasyona geçmesin
        return SAYFA_NO[sayfa_oyun]
    if basladi:
        return SAYFA_NO[sayfa_medya]
    if elle:
        return sayfa
    if calan:
        return SAYFA_NO[sayfa_medya]
    anim = SAYFA_NO[sayfa_animasyon]
    if ayarlar["bosta_dk"] and bosta >= ayarlar["bosta_dk"] * 60:
        if sayfa != anim:
            oto["anim"] = simdi
        elif simdi - oto["anim"] >= ANIM_DEGISIM_SN:
            animasyon_degistir()
            oto["anim"] = simdi
        return anim
    if simdi - oto["medya_son"] < MEDYA_BEKLE_SN:
        return sayfa
    if saniye >= 60 - ARA_SN:
        return SAYFA_NO[sayfa_sistem]
    if saniye >= 60 - 2 * ARA_SN:
        return SAYFA_NO[sayfa_hava]
    return SAYFA_NO[sayfa_haber]


# ---------- ana döngü ----------

def onizleme():
    assert temizle("Şarkı 😀🎵 ️ 中 ♪ Adı") == "Şarkı ♪ Adı", temizle("Şarkı 😀🎵 ️ 中 ♪ Adı")
    assert kaydirma_adimlari("kısa", W) == [0]
    assert kaynak_bul("Spotify.exe", "x") == "spotify" and kaynak_bul("foobar2000", "x") == "muzik"
    for metin, beklenen in (('Elon on X: "selam" / X - Google Chrome', "x"), ("(3) Ana sayfa / X - Opera", "x"),
                            ("Instagram - Microsoft Edge", "instagram"), ("Bir video / X - YouTube - Chrome", "youtube"),
                            ("xqc - Kick - Brave", "kick"), ("Firefox", None), ("AmazonVideo.PrimeVideo", "prime")):
        assert site_bul(metin) == beklenen, (metin, site_bul(metin))
    assert set(IKONLAR) >= {i for _, i in SITELER}
    gercek = globals()["pencere_basliklari"]
    try:
        globals()["pencere_basliklari"] = lambda: ["(1) Anasayfa / X - Google Chrome", "rapor - Word"]
        assert kaynak_bul("Chrome", "gönderi metni") == "x"
        globals()["pencere_basliklari"] = lambda: ["Anasayfa / X - Google Chrome", "Klip - YouTube - Google Chrome"]
        assert kaynak_bul("Chrome", "Klip") == "youtube" and kaynak_bul("Chrome", "başka") == "tarayici"
        globals()["pencere_basliklari"] = lambda: ["GitHub - Google Chrome"]  # YouTube çalarken başka sekmeye geçildi
        assert kaynak_bul("Chrome", "Klip") == "youtube"
        globals()["pencere_basliklari"] = lambda: ["Ana sayfa / X - Google Chrome"]
        assert kaynak_bul("Chrome", "Klip") == "youtube"  # öndeki X sekmesi ikonu değiştirmez
        _kaynaklar.clear()
    finally:
        globals()["pencere_basliklari"] = gercek
    for i in range(len(RGB_MODLAR) - 1):  # "Kapalı" dışındakiler
        ayarlar["rgb_mod"] = i
        assert all(0 <= v <= 100 for v in rgb_hedef(12.3)), RGB_MODLAR[i]
    ayarlar["rgb_mod"] = next(i for i, m in enumerate(RGB_MODLAR) if m[1] == "yuk")
    veri["cpu"], veri["gpu"] = 0, None
    assert [round(v) for v in rgb_hedef(0)] == [0, 100, 0]  # boşta yeşil
    veri["cpu"] = 100
    assert [round(v) for v in rgb_hedef(0)] == [100, 0, 0]  # tam yükte kırmızı
    ayarlar["rgb_mod"] = next(i for i, m in enumerate(RGB_MODLAR) if m[1] == "gpu_isi")
    veri["gpu"] = (85, 0, 0, 1)
    assert [round(v) for v in rgb_hedef(0)] == [100, 0, 0]  # 85°C kırmızı
    ayarlar["rgb_mod"] = 0
    rgb["renk"] = list(rgb_hedef(4))  # önizlemede ışığa dokunulmaz; RGB sayfası örnek renkle çizilir
    assert hava_ikonu(0) == "gunes" and hava_ikonu(0, False) == "ay" and hava_ikonu(63) == "yagmur"
    assert hava_ikonu(95) == "firtina" and set(HAVA_IKONLARI) >= {hava_ikonu(k) for k in range(100)}
    assert sar("bir iki üç", FONT, W, 2) == ["bir iki üç"]
    uzun = sar("kelime " * 40, FONT, W, 2)
    assert len(uzun) == 2 and uzun[-1].endswith("…") and all(FONT.getlength(s) <= W for s in uzun)
    medya_s, rgb_s, anim_s = SAYFA_NO[sayfa_medya], SAYFA_NO[sayfa_rgb], SAYFA_NO[sayfa_animasyon]
    calan, duran = ("şarkı", "", 0, 100, True, "muzik"), ("şarkı", "", 0, 100, False, "muzik")
    oto = yeni_oto()
    tam = '{"USD":{"Alış":"1","Satış":"49,84"},"EUR":{"Satış":"55,69"},"gram-altin":{"Satış":"6.458,10"},"X":{"a":"b"}}'
    assert kur_oku(tam) == ("49,84", "55,69", "6.458,10")
    assert kur_oku(tam[:-12]) == ("49,84", "55,69", "6.458,10")  # sonu kesik JSON
    haber_s, hava_s, sistem_s = SAYFA_NO[sayfa_haber], SAYFA_NO[sayfa_hava], SAYFA_NO[sayfa_sistem]
    assert otomatik_sayfa(100, rgb_s, oto, None, 0, 5) == haber_s  # medya yok: ana sayfa haberler
    assert otomatik_sayfa(101, haber_s, oto, None, 0, 60 - 2 * ARA_SN - 1) == haber_s
    assert otomatik_sayfa(102, haber_s, oto, None, 0, 60 - 2 * ARA_SN) == hava_s  # dakika sonu: hava
    assert otomatik_sayfa(103, hava_s, oto, None, 0, 60 - ARA_SN) == sistem_s  # sonra sistem
    assert otomatik_sayfa(104, sistem_s, oto, None, 0, 0) == haber_s  # yeni dakika: haberlere dön
    assert otomatik_sayfa(117, haber_s, oto, calan, 0, 5) == medya_s  # medya başladı
    assert otomatik_sayfa(117 + MEDYA_BEKLE_SN - 1, medya_s, oto, duran, 0, 5) == medya_s  # durdu: biraz bekle
    assert otomatik_sayfa(117 + MEDYA_BEKLE_SN, medya_s, oto, duran, 0, 5) == haber_s
    assert otomatik_sayfa(150, haber_s, oto, None, BOSTA_SN, 5) == anim_s  # boşta
    oto["manuel"] = 160
    assert otomatik_sayfa(170, rgb_s, oto, None, 0, 5) == rgb_s  # elle seçim 60 sn korunur...
    assert otomatik_sayfa(171, rgb_s, oto, calan, 0, 5) == medya_s  # ...ama medya başlayınca yine geçer
    assert otomatik_sayfa(172, rgb_s, oto, calan, 0, 5) == rgb_s  # çalarken elle başka sayfaya geçilebilir
    assert otomatik_sayfa(221, rgb_s, oto, calan, 0, 5) == medya_s
    oyun_s = SAYFA_NO[sayfa_oyun]
    assert otomatik_sayfa(230, medya_s, oto, calan, BOSTA_SN, 5, "eldenring") == oyun_s  # oyun her şeyden önce
    oto["manuel"] = 240
    assert otomatik_sayfa(250, rgb_s, oto, None, 0, 5, "eldenring") == rgb_s  # elle seçim oyunda da korunur
    ayarlar["bosta_dk"] = 0
    assert otomatik_sayfa(400, haber_s, oto, None, 10 ** 6, 5) == haber_s  # boşta animasyon kapalı
    ayarlar["bosta_dk"] = VARSAYILAN_AYARLAR["bosta_dk"]
    assert surum_sayi("v1.10") > surum_sayi("1.3.1") > surum_sayi("v1.3") > surum_sayi("v1.2")
    assert surum_sayi("v" + SURUM) == surum_sayi(SURUM)
    assert bildirim_rengi("WhatsApp") == BILDIRIM_RENKLERI["whatsapp"] and bildirim_rengi("Foo") == (100, 100, 100)
    assert tam_ekran_oyun() is None or isinstance(tam_ekran_oyun()[0], str)
    ikon = oyun_ikonu(r"C:\Windows\System32\notepad.exe")
    assert ikon is not None and ikon.size == (32, 32) and oyun_ikonu(r"C:\Windows\System32\notepad.exe") is ikon
    assert oyun_ikonu(r"C:\yok\olmayan.exe") is None
    assert oyun_anahtari("TslGame", None) == "pubg"  # hile koruması exe yolunu gizlese de adından
    assert oyun_anahtari("Game", r"D:\SteamLibrary\steamapps\common\OnimushaWotS\Game.exe") == "oni"
    assert oyun_anahtari("notepad", r"C:\Windows\System32\notepad.exe") is None
    import oyun_ikonlari
    for anahtar in oyun_ikonlari.IKONLAR:
        assert gomulu_ikon(anahtar).size == (32, 32), anahtar
    assert gomulu_ikon("pubg") is gomulu_ikon("pubg")
    veri["haberler"] = [("T", "K", f"haber {i}", "", None) for i in range(5)]
    gorunum.update(haber_i=0, haber_t=0.0, haber_son=0.0)
    def goster(bas, son):  # ana döngü gibi 0.1 sn'de bir çiz
        for k in range(round((son - bas) * 10) + 1):
            ciz(haber_s, bas + k / 10)

    goster(100, 104)  # 4 sn gösterildi, sonra 20 sn başka sayfa
    goster(124, 129.5)  # döndü: aynı haber ~6 sn daha sürer
    assert gorunum["haber_i"] == 0, gorunum
    goster(129.6, 131)
    assert gorunum["haber_i"] == 1, gorunum
    veri["haberler"] = []
    en_yogun_islemler()
    time.sleep(8)  # ölçüm, internet ve haber verisinin gelmesini bekle
    veri["islemler"] = en_yogun_islemler()
    assert 0 < len(veri["islemler"]) <= 3
    for _ in range(40):
        ciz(len(SAYFALAR) - 1, 0)
    resimler = [(f"{i + 1}_{s[1]}", ciz(i, time.monotonic())) for i, s in enumerate(SAYFALAR)]
    resimler += [(f"etiket_{s[1]}", ciz(i, time.monotonic(), etiket=True)) for i, s in enumerate(SAYFALAR)]
    resimler.append(("acilis", ciz(0, 0, acilista=True)))
    resimler.append(("bildirim", ciz(0, 0, bildirim=("WhatsApp", "Ahmet", "Akşam maça geliyor musun? Saat sekizde "
                                                                      "kapıda buluşalım, biletler bende."))))
    resimler.append(("ses", ciz(0, 0, ses=(63, False))))
    resimler.append(("ses_sessiz", ciz(0, 0, ses=(63, True))))
    veri["mik_sessiz"] = True
    resimler.append(("mikrofon", ciz(SAYFA_NO[sayfa_haber], 0)))
    veri["mik_sessiz"] = False
    veri["oyun"] = "eldenring"
    resimler.append(("oyun_ikonsuz", ciz(SAYFA_NO[sayfa_oyun], 0)))
    veri["oyun_ikon"] = oyun_ikonu(r"C:\Program Files\Logitech Gaming Software\LCore.exe")
    resimler.append(("oyun_ikonlu", ciz(SAYFA_NO[sayfa_oyun], 0)))
    veri["oyun"] = veri["oyun_ikon"] = None
    for anahtar in ("sistem_detay", "hava_tahmin"):
        gorunum[anahtar] = True
        resimler.append((anahtar, ciz(SAYFA_NO[sayfa_sistem if anahtar == "sistem_detay" else sayfa_hava],
                                      time.monotonic())))
    for i, anim in enumerate(animasyonlar):
        anim.sifirla()
        sure = time.perf_counter()
        for kare in range(30):
            img = Image.new("L", (W, H), 0)
            d = ImageDraw.Draw(img)
            d.fontmode = "1"
            anim.ciz(img, d, kare * 0.1)
        print(f"{type(anim).__name__}: kare başına {(time.perf_counter() - sure) / 30 * 1000:.0f} ms")
        resimler.append((f"anim_{i + 1}_{type(anim).__name__}", img))
    for ad, sozluk in (("ikonlar", IKONLAR), ("hava_ikonlari", HAVA_IKONLARI)):
        img = Image.new("L", (W, H), 0)
        d = ImageDraw.Draw(img)
        d.fontmode = "1"
        for i, f in enumerate(sozluk.values()):
            f(d, (i % 8) * 20, (i // 8) * 22, 255)
        resimler.append((ad, img))
    for ad, img in resimler:
        assert img.size == (W, H) and len(img.tobytes()) == W * H
        img.resize((W * 4, H * 4), Image.NEAREST).save(f"onizleme_{ad}.png")
    print("önizlemeler kaydedildi; konum:", veri["konum"], "| tahmin:", veri["tahmin"], "| işlemler:", veri["islemler"])


def kayda_yonlendir():
    """Konsolsuz çalışırken (pythonw / exe) çıktı ve hatalar kaybolmasın: exe'nin yanındaki kayıt dosyasına yaz."""
    if sys.stdout is not None:
        return
    try:
        if os.path.getsize(KAYIT_DOSYASI) > 1_000_000:  # büyümesin
            os.replace(KAYIT_DOSYASI, KAYIT_DOSYASI + ".eski")
    except OSError:
        pass
    sys.stdout = sys.stderr = open(KAYIT_DOSYASI, "a", encoding="utf-8", buffering=1)
    print(f"--- {dt.datetime.now():%Y-%m-%d %H:%M:%S} başladı ---")


def tepsi_resmi():
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    ImageDraw.Draw(img).rounded_rectangle((0, 0, 63, 63), radius=12, fill=(22, 22, 28, 255))
    img.paste((240, 240, 240, 255), (8, 8), robot_resmi().resize((48, 48), Image.NEAREST))
    return img


def tepsi_baslat():
    """Bildirim alanı simgesi: ayarlar, güncelleme, kayıt dosyası, yeniden başlatma ve çıkış."""
    import pystray
    from pystray import Menu, MenuItem as Oge

    def kaydet(simge):
        ayar_kaydet()
        simge.update_menu()  # tik işaretleri yenilensin

    def ac_kapa(ad, anahtar):
        def degistir(simge, oge):
            ayarlar[anahtar] = not ayarlar[anahtar]
            kaydet(simge)
        return Oge(ad, degistir, checked=lambda oge: ayarlar[anahtar])

    def secenek(ad, anahtar, deger):
        def sec(simge, oge):
            ayarlar[anahtar] = deger
            kaydet(simge)
        return Oge(ad, sec, checked=lambda oge: ayarlar[anahtar] == deger, radio=True)

    def guncelle_tikla(simge, oge):
        def is_():  # indirme uzun sürebilir: menü donmasın
            try:
                if veri["guncelleme"]:
                    guncelle()
                else:
                    guncelleme_denetle()
                    if not veri["guncelleme"]:
                        bildirimler.append(("G510 Panel", "Güncelleme yok", f"v{SURUM} en son sürüm."))
                simge.update_menu()
            except Exception as e:
                print("güncelleme:", e)
                bildirimler.append(("G510 Panel", "Güncelleme başarısız", str(e)))
        threading.Thread(target=is_, daemon=True).start()

    def kaydi_ac(simge, oge):
        if os.path.exists(KAYIT_DOSYASI):
            os.startfile(KAYIT_DOSYASI)

    def kapat(yeniden):
        def f(simge, oge):
            if yeniden:
                yeniden_baslat.set()
            cikis.set()
        return f

    simge = pystray.Icon("G510 Panel", tepsi_resmi(), f"G510 Panel v{SURUM}", Menu(
        Oge(f"G510 Panel v{SURUM}", lambda s, o: None, enabled=False),
        Menu.SEPARATOR,
        ac_kapa("Otomatik sayfa geçişi", "otomatik"),
        ac_kapa("Oyun modu", "oyun_modu"),
        ac_kapa("Bildirimler", "bildirim"),
        Oge("Boştayken animasyon", Menu(*(secenek(f"{dk} dk sonra" if dk else "Kapalı", "bosta_dk", dk)
                                          for dk in (0, 1, 3, 5, 10)))),
        Oge("RGB modu", Menu(*(secenek(m[0], "rgb_mod", i) for i, m in enumerate(RGB_MODLAR)))),
        Menu.SEPARATOR,
        Oge(lambda oge: f"Güncelle: {veri['guncelleme'][0]}" if veri["guncelleme"] else "Güncellemeleri denetle",
            guncelle_tikla),
        Oge("Kayıt dosyasını aç", kaydi_ac),
        Oge("Yeniden başlat", kapat(True)),
        Oge("Çıkış", kapat(False))))
    threading.Thread(target=simge.run, daemon=True).start()
    return simge


def yeni_exe_sil():
    """Güncellemeden kalan indirme dosyası; güncelleyici kapanınca silinebilir."""
    yol = os.path.join(KLASOR, "G510 Panel.yeni.exe")
    for _ in range(60):
        try:
            if os.path.exists(yol):
                os.remove(yol)
            return
        except OSError:
            time.sleep(1)


def main():
    kayda_yonlendir()
    if "--guncelleme-bitir" in sys.argv:
        return guncellemeyi_bitir(sys.argv[sys.argv.index("--guncelleme-bitir") + 1])
    ayar_yukle()
    for f in (olcum_dongusu, internet_dongusu, medya_dongusu, haber_dongusu):
        threading.Thread(target=f, daemon=True).start()
    if "--onizleme" in sys.argv:
        return onizleme()

    # tek kopya; yeniden başlatma ya da güncellemede eski kopyanın kapanmasını bekler
    k32 = ctypes.windll.kernel32
    k32.CreateMutexW.restype = ctypes.c_void_p
    k32.CloseHandle.argtypes = [ctypes.c_void_p]
    for _ in range(40):
        kilit = k32.CreateMutexW(None, False, "G510PanelTekKopya")
        if k32.GetLastError() != 183:  # ERROR_ALREADY_EXISTS
            break
        k32.CloseHandle(kilit)
        time.sleep(0.5)
    else:
        sys.exit("G510 Panel zaten çalışıyor.")
    for f in (rgb_dongusu, bildirim_dongusu, ses_dongusu, guncelleme_dongusu, yeni_exe_sil):
        threading.Thread(target=f, daemon=True).start()
    simge = tepsi_baslat()

    lcd = ctypes.WinDLL(DLL)
    lcd.LogiLcdInit.restype = lcd.LogiLcdIsButtonPressed.restype = ctypes.c_bool
    for _ in range(30):  # bilgisayar açılırken LGS henüz hazır olmayabilir
        if lcd.LogiLcdInit(ctypes.c_wchar_p("G510 Panel"), 1):  # 1 = tek renkli LCD
            break
        if cikis.wait(10):
            break
    else:
        simge.stop()
        sys.exit("LCD'ye bağlanılamadı: Logitech Gaming Software açık mı?")
    baslangic, etiket_bitis, menu_guncel = time.monotonic(), 0, False
    sayfa, onceki, oto = 0, [False] * 4, yeni_oto()
    try:
        while not cikis.is_set():
            simdi = time.monotonic()
            basili = [lcd.LogiLcdIsButtonPressed(b) for b in BTN]
            yeni = [b and not o for b, o in zip(basili, onceki)]  # yalnız basıldığı an
            onceki = basili
            if any(yeni):
                oto["manuel"] = simdi
                if gorunum["bildirim"]:  # tuş önce bildirimi kapatır
                    gorunum["bildirim"], yeni = None, [False] * 4
            if gorunum["bildirim"] and simdi >= gorunum["bildirim"][3]:
                gorunum["bildirim"] = None
            if not gorunum["bildirim"] and bildirimler:
                b = bildirimler.popleft()
                gorunum["bildirim"] = (*b, simdi + BILDIRIM_SN)
                rgb["flas"] = (bildirim_rengi(b[0]), simdi + 2.5)
            if veri["guncelleme"] and not menu_guncel:
                simge.update_menu()
                menu_guncel = True
            if yeni[0] or yeni[1]:
                sayfa = (sayfa + (1 if yeni[1] else -1)) % len(SAYFALAR)
                etiket_bitis = simdi + 2  # tuş ipuçları okunabilsin
                gorunum["rgb_imlec"] = None
            for tus in (2, 3):
                if yeni[tus]:
                    sayfa_tusu(sayfa, tus)
            if ayarlar["otomatik"]:
                hedef = otomatik_sayfa(simdi, sayfa, oto, veri["medya"], bosta_sure(), dt.datetime.now().second,
                                       veri["oyun"] if ayarlar["oyun_modu"] else None)
                if hedef != sayfa:
                    if hedef in (SAYFA_NO[sayfa_medya], SAYFA_NO[sayfa_oyun]):
                        etiket_bitis = simdi + 2
                    sayfa = hedef
            img = ciz(sayfa, simdi, etiket=simdi < etiket_bitis, acilista=simdi - baslangic < 2,
                      bildirim=gorunum["bildirim"], ses=veri["ses"] if simdi < gorunum["ses_bitis"] else None)
            lcd.LogiLcdMonoSetBackground((ctypes.c_ubyte * (W * H)).from_buffer_copy(img.tobytes()))
            lcd.LogiLcdUpdate()
            time.sleep(0.1)
    except KeyboardInterrupt:
        pass
    finally:
        lcd.LogiLcdShutdown()
        rgb_kapat()
        simge.stop()
        if yeniden_baslat.is_set():
            subprocess.Popen([sys.executable] if getattr(sys, "frozen", False)
                             else [sys.executable, os.path.abspath(__file__)])


if __name__ == "__main__":
    main()
