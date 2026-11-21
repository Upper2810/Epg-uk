
import gzip
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from pathlib import Path
import re

# Source EPG
SOURCE_URL = (
    "https://raw.githubusercontent.com/waastudios/"
    "Cathy-epg/master/data/epg.xml.gz"
)

# Fuseau horaire français
PARIS = ZoneInfo("Europe/Paris")

# Les 12 chaînes de notre EPG
CHANNELS = {
    "virgin_uk.2258": "SKY ULTRA",
    "virgin_uk.2265": "SKY ULTRA 2",
    "ee_uk.419": "SKY SPORTS MAIN EVENT",
    "ee_uk.420": "SKY SPORTS PL",
    "ee_uk.433": "TNT SPORTS ULTIMATE",
    "ee_uk.408": "TNT SPORTS 1",
    "ee_uk.409": "TNT SPORTS 2",
    "ee_uk.410": "TNT SPORTS 3",
    "ee_uk.411": "TNT SPORTS 4",
    "ee_uk.450": "TNT SPORTS 5",
    "ee_uk.451": "TNT SPORTS 6",
    "ee_uk.452": "TNT SPORTS 7",
}


def download_epg():
    print("Téléchargement de la source EPG...")

    request = urllib.request.Request(
        SOURCE_URL,
        headers={"User-Agent": "EPG-UK-4K/1.0"}
    )

    with urllib.request.urlopen(request, timeout=120) as response:
        compressed = response.read()

    return gzip.decompress(compressed)


def convert_time(value):
    match = re.fullmatch(
        r"(\d{14})(?:\s*([+-]\d{4}))?",
        value
    )

    if not match:
        raise ValueError(f"Horaire XMLTV invalide : {value}")

    date_part, offset = match.groups()

    if offset:
        dt = datetime.strptime(
            date_part + " " + offset,
            "%Y%m%d%H%M%S %z"
        )
    else:
        dt = datetime.strptime(
            date_part,
            "%Y%m%d%H%M%S"
        ).replace(tzinfo=timezone.utc)

    return dt.astimezone(PARIS).strftime(
        "%Y%m%d%H%M%S %z"
    )


def main():
    xml_data = download_epg()
    root = ET.fromstring(xml_data)

    print("Filtrage des 12 chaînes...")

    found_channels = set()

    # Supprimer les chaînes inutiles
    for channel in list(root.findall("channel")):
        channel_id = channel.get("id")

        if channel_id not in CHANNELS:
            root.remove(channel)
        else:
            found_channels.add(channel_id)

            for name in list(channel.findall("display-name")):
                channel.remove(name)

            ET.SubElement(
                channel,
                "display-name"
            ).text = CHANNELS[channel_id]

    missing = set(CHANNELS) - found_channels

    if missing:
        raise RuntimeError(
            "Chaînes absentes de la source : "
            + ", ".join(sorted(missing))
        )

    # Garder uniquement les programmes des 12 chaînes
    programme_count = 0

    for programme in list(root.findall("programme")):
        channel_id = programme.get("channel")

        if channel_id not in CHANNELS:
            root.remove(programme)
            continue

        programme.set(
            "start",
            convert_time(programme.get("start"))
        )

        programme.set(
            "stop",
            convert_time(programme.get("stop"))
        )

        programme_count += 1

    if programme_count == 0:
        raise RuntimeError("Aucun programme récupéré !")

    # Trier les programmes par horaire
    programmes = root.findall("programme")
    programmes.sort(key=lambda p: p.get("start"))

    for programme in list(root.findall("programme")):
        root.remove(programme)

    for programme in programmes:
        root.append(programme)

    # Générer le XML final
    ET.indent(root, space="  ")

    output = Path("epg.xml")

    tree = ET.ElementTree(root)
    tree.write(
        output,
        encoding="UTF-8",
        xml_declaration=True
    )

    print("--------------------------------")
    print("EPG UK 4K généré avec succès !")
    print(f"Chaînes : {len(found_channels)}")
    print(f"Programmes : {programme_count}")
    print(f"Fichier : {output}")
    print("--------------------------------")


if __name__ == "__main__":
    main()
