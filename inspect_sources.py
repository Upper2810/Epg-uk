
import urllib.request
import gzip
import xml.etree.ElementTree as ET

SOURCES = {
    "SKY LONDON": (
        "https://raw.githubusercontent.com/Permanently/"
        "sky-epg-xmltv/main/guides/london_hd.xml"
    ),
    "OPEN EPG UK": (
        "https://www.open-epg.com/files/unitedkingdom.xml.gz"
    ),
}

TARGETS = {
    "SKY LONDON": [
        "4002.sky.uk",  # Sky Sports Main Event
        "4010.sky.uk",  # Sky Sports PL
        "3939.sky.uk",  # Sky Sports Football
        "3625.sky.uk",  # TNT Sports 1
        "3627.sky.uk",  # TNT Sports 2
        "3629.sky.uk",  # TNT Sports 3
        "4040.sky.uk",  # TNT Sports 4
    ],
    "OPEN EPG UK": [
        "SkySportsMainEvent.uk",
        "SkySportsPremierLeague.uk",
        "SkySportsFootball.uk",
        "SkySportsUHD1.uk",
        "SkySportsUHD2.uk",
        "TNTSports1.uk",
        "TNTSports2.uk",
        "TNTSports3.uk",
        "TNTSports4.uk",
        "TNTSports5.uk",
        "TNTSports6.uk",
        "TNTSports7.uk",
        "TNTSportsUltimate.uk",
    ],
}

DATE = "20261121"

for name, url in SOURCES.items():
    print("\n" + "=" * 65)
    print(name)
    print("=" * 65)

    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "Mozilla/5.0"}
        )

        with urllib.request.urlopen(req, timeout=120) as response:
            data = response.read()

        if data[:2] == b"\x1f\x8b":
            data = gzip.decompress(data)

        root = ET.fromstring(data)

        for cid in TARGETS[name]:
            channel = root.find(
                f"./channel[@id='{cid}']"
            )

            if channel is None:
                print(f"\n{cid} : CHAINE INTROUVABLE")
                continue

            display = " / ".join(
                x.text or ""
                for x in channel.findall("display-name")
            )

            print(f"\n--- {display} ({cid}) ---")

            programmes = [
                p for p in root.findall("programme")
                if p.get("channel") == cid
                and p.get("start", "").startswith(DATE)
            ]

            if not programmes:
                print("AUCUN PROGRAMME")
                continue

            for p in programmes:
                start = p.get("start", "")
                stop = p.get("stop", "")
                title = p.findtext("title", "")
                subtitle = p.findtext("sub-title", "")

                print(
                    f"{start} -> {stop} | "
                    f"{title} | {subtitle}"
                )

    except Exception as e:
        print("ERREUR :", e)

print("\nDIAGNOSTIC TERMINE")
