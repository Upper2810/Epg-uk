
import gzip
import urllib.request
import xml.etree.ElementTree as ET

sources = {
    "SKY": (
        "https://raw.githubusercontent.com/Permanently/sky-epg-xmltv/main/guides/london_hd.xml",
        ["4010.sky.uk", "3939.sky.uk"]
    ),
    "OPEN": (
        "https://www.open-epg.com/files/unitedkingdom.xml.gz",
        [
            "SkySportsPremierLeague.uk",
            "SkySportsFootball.uk",
            "SkySportsUHD1.uk",
            "SkySportsUHD2.uk"
        ]
    )
}

for name, (url, ids) in sources.items():
    print("\n==========", name, "==========")

    try:
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "EPG-UK-4K/3.0"}
        )

        with urllib.request.urlopen(request, timeout=120) as response:
            data = response.read()

        if data[:2] == b"\x1f\x8b":
            data = gzip.decompress(data)

        root = ET.fromstring(data)

        for channel in ids:
            print("\n###", channel)

            for p in root.findall("programme"):
                if (
                    p.get("channel") == channel
                    and p.get("start", "").startswith("20261122")
                ):
                    print(
                        p.get("start"),
                        "->",
                        p.get("stop"),
                        "|",
                        p.findtext("title", "")
                    )

    except Exception as error:
        print("ERREUR :", error)
