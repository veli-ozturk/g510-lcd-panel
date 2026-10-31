"""Geliştirici aracı: oyun ve yayıncı logolarından 32x32 tek renkli ikonlar üretip oyun_ikonlari.py'ye gömer.

Logolar Simple Icons'tan (CC0) indirilir, Chrome'da 256 px çizilip 32 px'e küçültülür ve eşiklenir (LCD'de net).
Onimusha için Capcom logosu yok: oyunun simgesi olan 鬼 (oni) kanjisi kalın Japonca fontla çizilir.
Kullanım:  python oyun_ikonlari_uret.py   (Chrome gerekir; çıktı applet'e import ile girer)
"""
import base64
import io
import os
import re
import subprocess
import tempfile
import urllib.request

from PIL import Image, ImageDraw, ImageFont

KLASOR = os.path.dirname(os.path.abspath(__file__))
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
# ikon adı -> Simple Icons sürümü (bazı logolar yeni sürümlerden kaldırıldı)
LOGOLAR = {"pubg": "13.21.0", "counterstrike": "13.21.0", "dota2": "13.21.0", "leagueoflegends": "13.21.0",
           "valorant": "13.21.0", "riotgames": "13.21.0", "roblox": "13.21.0", "rockstargames": "13.21.0",
           "ea": "13.21.0", "ubisoft": "13.21.0", "battledotnet": "13.21.0", "playstation": "13.21.0",
           "steam": "13.21.0", "epicgames": "13.21.0", "xbox": "9.21.0"}  # minecraft/valve yazı logo: 32 px'de okunmuyor
# exe adı ya da yolu içinde (küçük harf) aranan metin -> ikon; sıra önemli, özelden genele
ESLESMELER = (("tslgame", "pubg"), ("\\pubg\\", "pubg"), ("onimusha", "oni"), ("cs2.exe", "counterstrike"),
              ("csgo", "counterstrike"), ("counter-strike", "counterstrike"), ("dota2", "dota2"),
              ("league of legends", "leagueoflegends"), ("leagueclient", "leagueoflegends"),
              ("valorant", "valorant"), ("riot games", "riotgames"), ("roblox", "roblox"),
              ("gta5", "rockstargames"), ("rdr2", "rockstargames"), ("rockstar", "rockstargames"),
              ("\\ea games\\", "ea"), ("\\electronic arts\\", "ea"), ("ubisoft", "ubisoft"),
              ("battle.net", "battledotnet"), ("blizzard", "battledotnet"), ("xboxgames", "xbox"),
              ("\\steamapps\\common\\", "steam"), ("\\epic games\\", "epicgames"))
BOY = 256


def svg_yollari():
    yollar = {}
    for ad, surum in LOGOLAR.items():
        svg = urllib.request.urlopen(f"https://cdn.jsdelivr.net/npm/simple-icons@{surum}/icons/{ad}.svg",
                                     timeout=20).read().decode()
        yollar[ad] = re.search(r'<path d="([^"]+)"', svg).group(1)
    return yollar


def chrome_ciz(yollar):
    """Bütün logoları yan yana 256 px karelerde çizer; {ad: 256x256 "L" görsel}."""
    adlar = list(yollar)
    hucreler = "".join(f'<svg width="{BOY}" height="{BOY}" viewBox="-1 -1 26 26" style="display:block;float:left">'
                       f'<path d="{yollar[a]}" fill="#000"/></svg>' for a in adlar)
    sayfa = f'<html><body style="margin:0;background:#fff;width:{BOY * len(adlar)}px">{hucreler}</body></html>'
    with tempfile.TemporaryDirectory() as g:
        h, p = os.path.join(g, "s.html"), os.path.join(g, "s.png")
        open(h, "w", encoding="utf-8").write(sayfa)
        subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=1",
                        f"--window-size={BOY * len(adlar)},{BOY}", f"--user-data-dir={os.path.join(g, 'pr')}",
                        f"--screenshot={p}", "file:///" + h.replace("\\", "/")], capture_output=True, timeout=60, check=True)
        serit = Image.open(p).convert("L")
    return {a: serit.crop((i * BOY, 0, (i + 1) * BOY, BOY)) for i, a in enumerate(adlar)}


def oni():
    img = Image.new("L", (BOY, BOY), 255)
    f = ImageFont.truetype(r"C:\Windows\Fonts\YuGothB.ttc", 220)
    d = ImageDraw.Draw(img)
    kutu = d.textbbox((0, 0), "鬼", font=f)
    d.text(((BOY - kutu[2] - kutu[0]) / 2, (BOY - kutu[3] - kutu[1]) / 2), "鬼", font=f, fill=0)
    return img


def tek_renk_32(gri):
    """256 px gri -> 32x32, siyah logo LCD'de yanan (beyaz) piksel olacak şekilde ters çevrilip eşiklenir."""
    kucuk = gri.resize((32, 32), Image.LANCZOS)
    return kucuk.point(lambda v: 255 if v < 140 else 0).convert("1")


def main():
    resimler = chrome_ciz(svg_yollari())
    resimler["oni"] = oni()
    kodlu = {}
    for ad, gri in sorted(resimler.items()):
        tampon = io.BytesIO()
        tek_renk_32(gri).save(tampon, "PNG", optimize=True)
        kodlu[ad] = base64.b64encode(tampon.getvalue()).decode()
    satirlar = ["# Otomatik üretildi: python oyun_ikonlari_uret.py  (logolar: Simple Icons, CC0; oni: Yu Gothic)",
                "# 32x32 tek renkli PNG (base64), LCD'de yanan pikseller beyaz.", "IKONLAR = {"]
    satirlar += [f'    "{a}": "{v}",' for a, v in kodlu.items()]
    satirlar += ["}", "ESLESMELER = " + repr(ESLESMELER), ""]
    with open(os.path.join(KLASOR, "oyun_ikonlari.py"), "w", encoding="utf-8") as f:
        f.write("\n".join(satirlar))
    onizleme = Image.new("L", (40 * len(kodlu), 32), 0)
    for i, ad in enumerate(kodlu):
        onizleme.paste(Image.open(io.BytesIO(base64.b64decode(kodlu[ad]))).convert("L"), (i * 40, 0))
    onizleme.resize((onizleme.width * 3, 96), Image.NEAREST).save(os.path.join(tempfile.gettempdir(), "oyun_ikonlari.png"))
    print(len(kodlu), "ikon ->", os.path.join(KLASOR, "oyun_ikonlari.py"), "| önizleme:", tempfile.gettempdir())


if __name__ == "__main__":
    main()
