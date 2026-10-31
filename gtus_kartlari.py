"""G510 G tuşu atamalarından yazdırılabilir başvuru kartı ve tuş etiketleri üretir.

LGS profilini okur (yalnız okuma), G1-G18 x M1-M3 atamalarını ikonlarla yazar:
  G-tuslari.html                       A4 başvuru kartı + etiketler (tarayıcıdan yazdır)
  G-tuslari-kart.png, -etiket.png      57 mm termal yazıcı (C9 vb.) için 384 px, siyah-beyaz
Kullanım:  python gtus_kartlari.py [profil adı]
Profil adı verilmezse varsayılan profil dışında en çok atama yapılmış profil seçilir.
"""
import base64
import glob
import html
import json
import os
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

LGS = os.path.join(os.environ["LOCALAPPDATA"], "Logitech", "Logitech Gaming Software")
KLASOR = os.path.dirname(os.path.abspath(__file__))
CIKTI = os.path.join(KLASOR, "G-tuslari.html")
# 57 mm termal kağıt: 203 dpi'de yazdırılabilir 48 mm = 384 nokta; 1 mm = 8 px
TERMAL_PX = 384
ETIKET_MM = (13, 9)  # G510 G tuşu üst yüzeyi (en, boy), ölçü şeridiyle bulundu; 13 mm altında yalnız büyük ikon
CHROME = (r"C:\Program Files\Google\Chrome\Application\chrome.exe",
          r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
MODLAR = {"1": "M1", "2": "M2", "3": "M3"}

# 24x24 çizgi ikonlar (currentColor)
SVG = {
    "makas": '<circle cx="6" cy="7" r="3"/><circle cx="6" cy="17" r="3"/><path d="M8.5 8.5 20 19M8.5 15.5 20 5"/>',
    "masaustu": '<rect x="3" y="4" width="18" height="12" rx="1.5"/><path d="M8 20h8M12 16v4"/>',
    "onceki": '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M13 9l-3 3 3 3"/>',
    "sonraki": '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M11 9l3 3-3 3"/>',
    "yeni_sekme": '<path d="M3 19V7a2 2 0 0 1 2-2h5l2 3h7a2 2 0 0 1 2 2v9z"/><path d="M12 11v6M9 14h6"/>',
    "sekme_kapat": '<path d="M3 19V7a2 2 0 0 1 2-2h5l2 3h7a2 2 0 0 1 2 2v9z"/><path d="M9.5 11.5l5 5M14.5 11.5l-5 5"/>',
    "dunya": '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c3 3.5 3 14.5 0 18M12 3c-3 3.5-3 14.5 0 18"/>',
    "terminal": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 9l3 3-3 3M12 15h5"/>',
    "metin": '<path d="M4 18 9 6l5 12M5.8 14h6.4"/><path d="M15 12.5c0-1.5 1.2-2.5 2.6-2.5 1.5 0 2.4 1 2.4 2.5V18M20 14.5c-3.5 0-5 .6-5 2 0 1 .8 1.6 1.9 1.6 1.6 0 3.1-1.2 3.1-3.6"/>',
    "klavye": '<rect x="2" y="6" width="20" height="12" rx="2"/><path d="M6 10h0M10 10h0M14 10h0M18 10h0M7 14h10"/>',
}
# dolgulu marka ikonları
MARKA = {
    "youtube": '<rect x="1.5" y="5" width="21" height="14" rx="4" fill="#ff0000"/><path d="M10 9v6l5-3z" fill="#fff"/>',
    "youtube_music": '<circle cx="12" cy="12" r="10.5" fill="#ff0000"/><circle cx="12" cy="12" r="5.5" fill="none" '
                     'stroke="#fff" stroke-width="1.4"/><path d="M10.5 9.5v5l4-2.5z" fill="#fff"/>',
}
# termal (tek renk) baskıda program ikonu yerine marka logosu: kısayol hedefinde aranan metin -> logolar.json anahtarı
LOGO_ANAHTARLARI = (("music.youtube", "youtubemusic"), ("youtube", "youtube"), ("steam", "steam"),
                    ("epic", "epicgames"), ("xbox", "xbox"), ("openvpn", "openvpn"))
try:
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "logolar.json"), encoding="utf-8") as _f:
        LOGOLAR = json.load(_f)
except (OSError, ValueError):
    LOGOLAR = {}
ISLEVLER = {"showdesktop": ("masaustu", "Masaüstünü göster"), "prevtabinbrowser": ("onceki", "Önceki sekme"),
            "nexttabinbrowser": ("sonraki", "Sonraki sekme"), "web": ("dunya", "Web tarayıcısı")}
KOMBOLAR = {"LCTRL W": ("sekme_kapat", "Ctrl+W"), "LCTRL T": ("yeni_sekme", "Ctrl+T")}
TUS_ADLARI = {"LCTRL": "Ctrl", "RCTRL": "Ctrl", "LSHIFT": "Shift", "RSHIFT": "Shift", "LALT": "Alt", "RALT": "AltGr",
              "LGUI": "Win", "RGUI": "Win"}


def yerel(etiket):
    return etiket.rsplit("}", 1)[-1]


def profilleri_oku():
    """{profil adı: (guid, {G tuşu: {mod: makro öğesi ya da None}})}"""
    sonuc = {}
    for yol in glob.glob(os.path.join(LGS, "profiles", "*.xml")):
        profil = next(p for p in ET.parse(yol).getroot().iter() if yerel(p.tag) == "profile")
        makrolar = {m.get("guid"): m for m in profil.iter() if yerel(m.tag) == "macro"}
        atamalar = {}
        for grup in profil.iter():
            if yerel(grup.tag) == "assignments" and grup.get("devicecategory") == "Logitech.Gaming.Keyboard":
                for a in grup:
                    tus, mod = a.get("contextid") or "", MODLAR.get(a.get("shiftstate"))
                    if re.fullmatch(r"G\d+", tus) and mod and a.get("backup") != "true":  # backup: LGS varsayılanı
                        atamalar.setdefault(tus, {})[mod] = makrolar.get(a.get("macroguid"))
        sonuc[profil.get("name")] = (profil.get("guid"), atamalar)
    return sonuc


def exe_ikonu(yol):
    """Program/kısayol ikonu (PNG base64) ya da None."""
    hedef = os.path.join(tempfile.gettempdir(), "gtus_ikon.png")
    try:
        subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                        "Add-Type -AssemblyName System.Drawing; [System.Drawing.Icon]::ExtractAssociatedIcon("
                        "$env:GTUS_YOL).ToBitmap().Save($env:GTUS_PNG)"],
                       env={**os.environ, "GTUS_YOL": yol, "GTUS_PNG": hedef}, capture_output=True, timeout=20,
                       check=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        with open(hedef, "rb") as f:
            return base64.b64encode(f.read()).decode()
    except (OSError, subprocess.SubprocessError):
        return None


def tus_metni(dizi):
    """'LCTRL LSHIFT S LSHIFT LCTRL' -> 'Ctrl+Shift+S' (basma sırası, tekrarsız)."""
    gorulen = []
    for t in dizi.split():
        t = TUS_ADLARI.get(t, t)
        if t not in gorulen:
            gorulen.append(t)
    return "+".join(gorulen)


def cozumle(makro, mono=False):
    """Makro -> (ikon html, ad, ayrıntı). mono: termal baskı için renkli ikon yerine tek renkli marka logosu."""
    if makro is None:
        return '<span class="bos">—</span>', "Atanmamış", ""
    ad = makro.get("name") or ""
    cocuk = next(iter(makro), None)
    tur = yerel(cocuk.tag) if cocuk is not None else ""
    if tur == "keystroke":
        tuslar = "+".join(TUS_ADLARI.get(k.get("value"), k.get("value")) for k in cocuk.iter() if yerel(k.tag) == "key")
        return f'<span class="tuscap">{html.escape(tuslar)}</span>', ad, ""
    if tur == "textblock":
        return svg("metin"), ad, f"“{''.join(cocuk.itertext()).strip()}” yazar"
    if tur in ("function", "hotkeys"):
        gorev = next((k.get("task") for k in cocuk.iter() if yerel(k.tag) == "do"), "")
        ikon, aciklama = ISLEVLER.get(gorev, ("klavye", gorev))
        return svg(ikon), ad or aciklama, ""
    if tur == "multikey":
        dizi = " ".join(k.get("value") for k in cocuk.iter() if yerel(k.tag) in ("key", "keydown") and k.get("value"))
        ikon, kisa = KOMBOLAR.get(dizi, ("makas" if "LGUI" in dizi and " S" in dizi else "klavye", tus_metni(dizi)))
        return svg(ikon), ad, kisa
    if tur == "shortcut":
        url = next((k.get("url") for k in cocuk.iter() if yerel(k.tag) == "start"), "") or ""
        logo = next((l for a, l in LOGO_ANAHTARLARI if a in url.lower() and l in LOGOLAR), None)
        if mono and logo:
            ayrinti = url.split("//")[-1].strip("/") if url.startswith(("http", "www.")) else os.path.basename(url)
            return f'<svg viewBox="0 0 24 24"><path fill="currentColor" d="{LOGOLAR[logo]}"/></svg>', ad, ayrinti
        if "music.youtube" in url:
            return marka("youtube_music"), ad, "music.youtube.com"
        if "youtube" in url:
            return marka("youtube"), ad, "youtube.com"
        if url.startswith(("http", "www.")):
            return svg("dunya"), ad, url
        if url.lower().endswith((".cmd", ".bat")):
            return svg("terminal"), ad, os.path.basename(url)
        png = exe_ikonu(url) if os.path.exists(url) else None
        ikon = f'<img src="data:image/png;base64,{png}" alt="">' if png else svg("klavye")
        return ikon, ad, os.path.basename(url)
    return svg("klavye"), ad, tur


# çizgi ikon -> Material Icons dolgulu karşılığı (logolar.json "md_*"); küçük boyutta ve termal baskıda daha okunur
DOLGULU = {"metin": "md_key", "makas": "md_content_cut", "masaustu": "md_desktop_windows", "terminal": "md_terminal",
           "sekme_kapat": "md_close", "onceki": "md_arrow_back", "sonraki": "md_arrow_forward", "yeni_sekme": "md_add",
           "dunya": "md_language", "klavye": "md_keyboard"}


KALINLASTIR = {"md_close", "md_add", "md_arrow_back", "md_arrow_forward"}  # ince çizgili olanlar


def svg(ad):
    if DOLGULU.get(ad) in LOGOLAR:
        kalin = ' stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"' if DOLGULU[ad] in KALINLASTIR else ""
        return f'<svg viewBox="0 0 24 24"><path fill="currentColor"{kalin} d="{LOGOLAR[DOLGULU[ad]]}"/></svg>'
    return (f'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" '
            f'stroke-linejoin="round">{SVG[ad]}</svg>')


def marka(ad):
    return f'<svg viewBox="0 0 24 24">{MARKA[ad]}</svg>'


def buyuk_harf(s):
    return s[:1].upper() + s[1:] if s else s


def sayfa(profil_adi, atamalar):
    hucreler, etiketler = [], []
    for n in range(1, 19):
        tus = f"G{n}"
        modlar = {m: cozumle(atamalar.get(tus, {}).get(m)) for m in ("M1", "M2", "M3")}
        ikon, ad, ayrinti = modlar["M1"]
        farkli = [(m, v) for m, v in modlar.items() if m != "M1" and v[1:] != modlar["M1"][1:]]
        ek = "".join(f'<div class="mod"><b>{m}</b> {html.escape(buyuk_harf(v[1]))}'
                     f'{" · " + html.escape(v[2]) if v[2] else ""}</div>' for m, v in farkli)
        bosluk = " grup" if n in (7, 13) else ""
        hucreler.append(f'<div class="hucre{bosluk}"><div class="ikon">{ikon}</div><div class="metin">'
                        f'<div class="ust"><span class="gad">{tus}</span>{html.escape(buyuk_harf(ad))}</div>'
                        f'<div class="ayrinti">{html.escape(ayrinti)}</div>{ek}</div></div>')
        alt = " / ".join(f"{m}: {buyuk_harf(v[1])}" for m, v in farkli)
        etiketler.append(f'<div class="etiket{bosluk}" title="{html.escape(alt)}"><span class="eno">{tus}</span>'
                         f'<div class="eikon">{ikon}</div><div class="ead">{html.escape(buyuk_harf(ad))}</div></div>')
    return SABLON.format(profil=html.escape(profil_adi), hucreler="".join(hucreler), etiketler="".join(etiketler))


SABLON = """<!doctype html>
<html lang="tr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>G510 G Tuşları</title>
<style>
:root {{ --kare: 14mm; --murekkep: #111; --soluk: #666; --cizgi: #bbb; }}
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: #e9e9ec; color: var(--murekkep); font: 11pt/1.3 "Segoe UI", Tahoma, sans-serif; }}
.arac {{ display: flex; gap: 16px; align-items: center; flex-wrap: wrap; padding: 12px 16px; background: #fff;
  border-bottom: 1px solid #ddd; position: sticky; top: 0; z-index: 1; }}
.arac button {{ font: inherit; padding: 6px 14px; border: 1px solid #333; background: #111; color: #fff;
  border-radius: 6px; cursor: pointer; }}
.arac input {{ width: 64px; font: inherit; padding: 4px 6px; }}
.sayfa {{ background: #fff; width: 297mm; min-height: 210mm; margin: 16px auto; padding: 12mm 14mm;
  box-shadow: 0 1px 4px rgba(0,0,0,.15); }}
h1 {{ font-size: 16pt; margin: 0 0 1mm; }}
.alt {{ color: var(--soluk); font-size: 9pt; margin-bottom: 6mm; }}
.izgara {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 3mm 5mm; }}
.hucre {{ display: flex; gap: 3mm; align-items: flex-start; border: 1px solid var(--cizgi); border-radius: 2.5mm;
  padding: 2.5mm 3mm; min-height: 22mm; break-inside: avoid; }}
.hucre.grup, .hucre.grup + .hucre, .hucre.grup + .hucre + .hucre {{ margin-top: 4mm; }}
.ikon {{ flex: 0 0 11mm; height: 11mm; display: grid; place-items: center; }}
.ikon svg, .ikon img {{ width: 10mm; height: 10mm; image-rendering: auto; }}
.ust {{ font-weight: 600; font-size: 11pt; }}
.gad {{ display: inline-block; min-width: 9mm; margin-right: 2mm; padding: 0 1.2mm; border-radius: 1.2mm;
  background: var(--murekkep); color: #fff; font-size: 8.5pt; text-align: center; }}
.ayrinti {{ color: var(--soluk); font-size: 8.5pt; word-break: break-all; }}
.mod {{ font-size: 8.5pt; margin-top: .6mm; }}
.mod b {{ display: inline-block; border: 1px solid var(--murekkep); border-radius: 1mm; padding: 0 .8mm;
  font-size: 7.5pt; margin-right: 1mm; }}
.tuscap {{ display: inline-grid; place-items: center; min-width: 9mm; height: 8mm; padding: 0 1.5mm;
  border: 1.4px solid var(--murekkep); border-bottom-width: 2.6px; border-radius: 1.6mm; font-weight: 700;
  font-size: 9pt; }}
.bos {{ color: var(--soluk); font-size: 14pt; }}
.etiketler {{ display: grid; grid-template-columns: repeat(3, var(--kare)); gap: 3mm; }}
.etiket {{ width: var(--kare); height: var(--kare); border: .3mm dashed #999; position: relative;
  display: flex; flex-direction: column; align-items: center; justify-content: center; overflow: hidden; }}
.etiket.grup, .etiket.grup + .etiket, .etiket.grup + .etiket + .etiket {{ margin-top: 3mm; }}
.eno {{ position: absolute; top: .4mm; left: .7mm; font-size: calc(var(--kare) * .13); color: var(--soluk); }}
.eikon {{ width: calc(var(--kare) * .55); height: calc(var(--kare) * .55); display: grid; place-items: center; }}
.eikon svg, .eikon img {{ width: 100%; height: 100%; }}
.eikon .tuscap {{ min-width: 0; height: auto; padding: .3mm .8mm; font-size: calc(var(--kare) * .2);
  border-width: .25mm; }}
.ead {{ font-size: calc(var(--kare) * .12); line-height: 1.05; text-align: center; padding: 0 .5mm;
  max-height: 2.2em; overflow: hidden; }}
.yan {{ display: flex; gap: 12mm; align-items: flex-start; }}
.not {{ font-size: 9pt; color: var(--soluk); max-width: 120mm; }}
@page {{ size: A4 landscape; margin: 0; }}
@media print {{
  body {{ background: #fff; }}
  .arac {{ display: none; }}
  .sayfa {{ margin: 0; box-shadow: none; page-break-after: always; }}
}}
@media (max-width: 700px) {{ .sayfa {{ width: auto; margin: 8px; padding: 16px; }} .izgara {{ grid-template-columns: 1fr; }} }}
</style></head><body>
<div class="arac">
  <button onclick="print()">Yazdır</button>
  <label>Etiket boyu <input id="kare" type="number" min="8" max="30" step="0.5" value="14"> mm</label>
  <span style="color:#666">Yazdırırken ölçek %100 (gerçek boyut) olmalı; tuşunu cetvelle ölçüp etiket boyunu ayarla.</span>
</div>
<section class="sayfa">
  <h1>G510 G tuşları</h1>
  <div class="alt">Profil: {profil} · M2 / M3 yalnız M1'den farklıysa yazılır</div>
  <div class="izgara">{hucreler}</div>
</section>
<section class="sayfa">
  <h1>Tuş etiketleri</h1>
  <div class="alt">Kesikli çizgiden kes, tuşa yapıştır · M1 görevleri</div>
  <div class="yan"><div class="etiketler">{etiketler}</div>
  <div class="not">Etiketler klavyedeki G tuşu düzeninde dizilidir. M2 / M3'te farklı çalışan tuşlar
  başvuru kartında ayrıca yazılıdır; etiketin üstüne gelince de görünür.</div></div>
</section>
<script>
const kutu = document.getElementById("kare");
function uygula() {{ document.documentElement.style.setProperty("--kare", kutu.value + "mm"); }}
try {{ const k = localStorage.getItem("gtus_kare"); if (k) kutu.value = k; }} catch (e) {{}}
kutu.addEventListener("input", () => {{ uygula(); try {{ localStorage.setItem("gtus_kare", kutu.value); }} catch (e) {{}} }});
uygula();
</script>
</body></html>
"""


def tus_bilgileri(atamalar):
    """[(G tuşu, M1 (ikon, ad, ayrıntı), [(mod, (ikon, ad, ayrıntı)) M1'den farklı olanlar])]"""
    sonuc = []
    for n in range(1, 19):
        tus = f"G{n}"
        modlar = {m: cozumle(atamalar.get(tus, {}).get(m), mono=True) for m in ("M1", "M2", "M3")}
        farkli = [(m, v) for m, v in modlar.items() if m != "M1" and v[1:] != modlar["M1"][1:]]
        sonuc.append((tus, modlar["M1"], farkli))
    return sonuc


TERMAL_SABLON = """<!doctype html><html><head><meta charset="utf-8"><style>
* {{ box-sizing: border-box; margin: 0; }}
html, body {{ width: {px}px; background: #fff; color: #000; font: 600 15px/1.2 "Segoe UI", Tahoma, sans-serif; }}
/* termal kafa gri basamaz: renkli ikonlar gri tona çevrilip sertleştirilir, sonra siyah-beyaza eşiklenir */
img {{ filter: grayscale(1) brightness(.75) contrast(2.2); }}  /* turuncu gibi açık renkler de siyaha düşsün */
svg {{ stroke-width: 2.4; }}
.tuscap {{ display: inline-grid; place-items: center; border: 2.5px solid #000; border-bottom-width: 4px;
  border-radius: 6px; font-weight: 800; padding: 0 4px; }}
{ek}
</style></head><body>{govde}</body></html>"""

KART_CSS = """
body {{ padding: 4px 0 24px; }}
.baslik {{ font-size: 20px; font-weight: 800; border-bottom: 3px solid #000; padding-bottom: 4px; margin-bottom: 6px; }}
.satir {{ display: flex; gap: 8px; align-items: center; padding: 6px 0; border-bottom: 1.5px dashed #000; }}
.gad {{ flex: 0 0 40px; text-align: center; background: #000; color: #fff; font-weight: 800; font-size: 15px;
  border-radius: 5px; padding: 2px 0; }}
.ikon {{ flex: 0 0 44px; height: 44px; display: grid; place-items: center; }}
.ikon svg, .ikon img {{ width: 40px; height: 40px; }}
.ikon .tuscap {{ font-size: 15px; height: 32px; min-width: 38px; }}
.ad {{ font-size: 17px; font-weight: 800; }}
.ayrinti {{ font-size: 13px; font-weight: 600; word-break: break-all; }}
.mod {{ font-size: 13px; }}
.mod b {{ border: 2px solid #000; border-radius: 4px; padding: 0 3px; font-size: 11px; margin-right: 3px; }}
"""

ETIKET_CSS = """
body {{ padding: 16px 0; }}
.izgara {{ display: grid; grid-template-columns: repeat(3, {w}px); column-gap: 24px; row-gap: 16px;
  justify-content: center; }}
.etiket {{ width: {w}px; height: {h}px; outline: 1px dashed #000; position: relative; display: flex;
  flex-direction: column; align-items: center; justify-content: center; gap: 4px; overflow: hidden; }}
.ara {{ grid-column: 1 / -1; height: 8px; }}
.eno {{ position: absolute; top: 3px; left: 5px; font-size: 13px; font-weight: 800; }}
.eikon {{ width: {i}px; height: {i}px; display: grid; place-items: center; }}
.eikon svg, .eikon img {{ width: {i}px; height: {i}px; }}
.eikon .tuscap {{ font-size: {i3}px; height: {i}px; min-width: {i}px; padding: 0 1px; border-width: 2px; }}
.ead {{ font-size: 13px; font-weight: 800; line-height: 1.05; text-align: center; padding: 0 4px;
  max-height: 3.2em; overflow: hidden; }}
{kucuk}
"""


def termal_html(profil_adi, bilgiler):
    """(başvuru kartı html, etiket html) -- 384 px genişlikte."""
    satirlar, etiketler = [f'<div class="baslik">G510 G tuşları · {html.escape(profil_adi)}</div>'], []
    for i, (tus, (ikon, ad, ayrinti), farkli) in enumerate(bilgiler):
        ek = "".join(f'<div class="mod"><b>{m}</b>{html.escape(buyuk_harf(v[1]))}</div>' for m, v in farkli)
        satirlar.append(f'<div class="satir"><div class="gad">{tus}</div><div class="ikon">{ikon}</div><div>'
                        f'<div class="ad">{html.escape(buyuk_harf(ad))}</div>'
                        f'{f"<div class=ayrinti>{html.escape(ayrinti)}</div>" if ayrinti else ""}{ek}</div></div>')
        if i in (6, 12):  # G7 ve G13 öncesi: klavyedeki grup boşluğu
            etiketler.append('<div class="ara"></div>')
        etiketler.append(f'<div class="etiket"><span class="eno">{tus}</span><div class="eikon">{ikon}</div>'
                         f'<div class="ead">{html.escape(buyuk_harf(ad))}</div></div>')
    w, h = ETIKET_MM[0] * 8, ETIKET_MM[1] * 8  # 203 dpi: 1 mm = 8 nokta
    kucuk = min(ETIKET_MM) < 13  # bu boyda ad ve numara sığmıyor, ikona yer kalsın
    i = round(min(w, h) * (0.8 if kucuk else 0.6))
    kart = TERMAL_SABLON.format(px=TERMAL_PX, ek=KART_CSS.format(), govde="".join(satirlar))
    etiket = TERMAL_SABLON.format(px=TERMAL_PX, ek=ETIKET_CSS.format(
        w=w, h=h, i=i, i3=max(i // 3, 9), kucuk=".eno, .ead {{ display: none; }}".format() if kucuk else ""),
                                  govde=f'<div class="izgara">{"".join(etiketler)}</div>')
    return kart, etiket


def termal_png(html_metni, hedef):
    """HTML'i başsız Chrome/Edge ile 384 px genişlikte çeker, alttaki boşluğu kırpar, siyah-beyaz PNG yazar."""
    from PIL import Image
    tarayici = next((t for t in CHROME if os.path.exists(t)), None)
    if not tarayici:
        sys.exit("Chrome ya da Edge bulunamadı; termal PNG üretilemiyor.")
    with tempfile.TemporaryDirectory() as gecici:
        sayfa_yolu, cekim = os.path.join(gecici, "s.html"), os.path.join(gecici, "s.png")
        with open(sayfa_yolu, "w", encoding="utf-8") as f:
            f.write(html_metni)
        # 2 kat çözünürlükte çizip küçültmek ince çizgileri ve logo kenarlarını düzgünleştirir
        subprocess.run([tarayici, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                        "--force-device-scale-factor=2", f"--window-size={TERMAL_PX},4000",
                        f"--user-data-dir={os.path.join(gecici, 'profil')}", f"--screenshot={cekim}",
                        "file:///" + sayfa_yolu.replace("\\", "/")], capture_output=True, timeout=60, check=True)
        with Image.open(cekim) as ham:
            gri = ham.convert("L")
        gri = gri.resize((TERMAL_PX, gri.height * TERMAL_PX // gri.width), Image.LANCZOS)
    kutu = gri.point(lambda v: 255 if v < 250 else 0).getbbox()  # içerik sınırı (beyaz olmayanlar)
    gri = gri.crop((0, 0, TERMAL_PX, min(gri.height, kutu[3] + 24))) if kutu else gri
    gri.point(lambda v: 0 if v < 150 else 255).convert("1").save(hedef, dpi=(203, 203))
    return gri.size


def profil_sec(profiller):
    """LGS'nin varsayılan profili dışında en çok G tuşu atanmış profilin adı (yoksa varsayılan)."""
    try:
        with open(os.path.join(LGS, "settings.json"), encoding="utf-8") as f:
            varsayilan = json.load(f).get("profiler", {}).get("defaultProfile")
    except (OSError, ValueError):
        varsayilan = None
    adaylar = [a for a, (guid, _) in profiller.items() if guid != varsayilan] or list(profiller)
    return max(adaylar, key=lambda a: len(profiller[a][1]))


def main():
    profiller = profilleri_oku()
    ad = sys.argv[1] if len(sys.argv) > 1 else profil_sec(profiller)
    if ad not in profiller:
        sys.exit(f"Profil bulunamadı: {ad}. Var olanlar: {', '.join(profiller)}")
    with open(CIKTI, "w", encoding="utf-8") as f:
        f.write(sayfa(ad, profiller[ad][1]))
    print(f"{ad} profili -> {CIKTI}")
    kart, etiket = termal_html(ad, tus_bilgileri(profiller[ad][1]))
    for metin, ad_ in ((kart, "G-tuslari-kart.png"), (etiket, "G-tuslari-etiket.png")):
        w, h = termal_png(metin, os.path.join(KLASOR, ad_))
        print(f"  {ad_}: {w}x{h} px = {w / 8:.0f}x{h / 8:.0f} mm (203 dpi)")


if __name__ == "__main__":
    main()
