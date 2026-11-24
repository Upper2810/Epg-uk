
import copy
import gzip
import os
import re
import shutil
import urllib.request
import xml.etree.ElementTree as ET

from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


# ============================================================
# EPG UK 4K V2 - FUSION DE 3 SOURCES
# ============================================================

CATHY_URL = (
    "https://raw.githubusercontent.com/waastudios/"
    "Cathy-epg/master/data/epg.xml.gz"
)

SKY_URL = (
    "https://raw.githubusercontent.com/Permanently/"
    "sky-epg-xmltv/main/guides/london_hd.xml"
)

OPEN_EPG_URL = (
    "https://www.open-epg.com/files/unitedkingdom.xml.gz"
)

PARIS = ZoneInfo("Europe/Paris")

OUTPUT_FILE = Path("epg.xml")
BACKUP_FILE = Path("epg.xml.backup")
TEMP_FILE = Path("epg.xml.tmp")

WINDOW_DAYS = 7
DOWNLOAD_TIMEOUT = 120


# ============================================================
# TES 12 CHAINES - IDENTIFIANTS CONSERVES
# ============================================================

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


# ============================================================
# CORRESPONDANCES DES CHAINES EXTERNES
# ============================================================

SKY_MAPPING = {
    "4002.sky.uk": [
        "ee_uk.419",
    ],
    "4010.sky.uk": [
        "ee_uk.420",
        "virgin_uk.2258",
    ],
    "3939.sky.uk": [
        "virgin_uk.2265",
    ],
    "3625.sky.uk": ["ee_uk.408"],
    "3627.sky.uk": ["ee_uk.409"],
    "3629.sky.uk": ["ee_uk.410"],
    "4040.sky.uk": ["ee_uk.411"],
}

OPEN_MAPPING = {
    "SkySportsMainEvent.uk": ["ee_uk.419"],
    "SkySportsPremierLeague.uk": [
        "ee_uk.420",
        "virgin_uk.2258",
    ],
    "SkySportsFootball.uk": [
        "virgin_uk.2265",
    ],
    "SkySportsUHD1.uk": ["virgin_uk.2258"],
    "SkySportsUHD2.uk": ["virgin_uk.2265"],
    "TNTSportsUltimate.uk": ["ee_uk.433"],
    "TNTSports1.uk": ["ee_uk.408"],
    "TNTSports2.uk": ["ee_uk.409"],
    "TNTSports3.uk": ["ee_uk.410"],
    "TNTSports4.uk": ["ee_uk.411"],
    "TNTSports5.uk": ["ee_uk.450"],
    "TNTSports6.uk": ["ee_uk.451"],
    "TNTSports7.uk": ["ee_uk.452"],
}

# ============================================================
# TITRES GENERIQUES
# ============================================================

GENERIC_TITLES = {
    "live fnf",
    "live football",
    "football live",
    "live premier league",
    "premier league live",
    "premier league weekend",
    "premier league weekend live",
    "live champions league",
    "champions league live",
    "uefa champions league live",
    "live uefa champions league",
    "live fa cup",
    "fa cup live",
    "live carabao cup",
    "carabao cup live",
    "live sport",
    "live sports",
    "sport live",
    "sports live",
    "football",
    "live: snf",
    "live snf",
    "tbc",
    "live: wsl",
    "live: saturday night football",
    "live: efl championship",
    "live super sunday",
    "super sunday",

}


def normalize_title(title):
    return " ".join((title or "").strip().lower().split())


def is_generic_title(title):
    normalized = normalize_title(title)

    if not normalized:
        return True

    if normalized in GENERIC_TITLES:
        return True

    if normalized.startswith("this is "):
        return True

    if normalized.startswith("welcome to "):
        return True

    return False


def get_title(programme):
    title = programme.find("title")

    if title is None or not title.text:
        return ""

    return title.text.strip()


# ============================================================
# TELECHARGEMENT
# ============================================================

def download_xml(url, source_name):
    print(f"Téléchargement : {source_name}")

    request = urllib.request.Request(
        url,
        headers={"User-Agent": "EPG-UK-4K/3.0"}
    )

    with urllib.request.urlopen(
        request,
        timeout=DOWNLOAD_TIMEOUT
    ) as response:
        data = response.read()

    if not data:
        raise RuntimeError(
            f"La source {source_name} est vide."
        )

    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)

    root = ET.fromstring(data)

    if root.tag != "tv":
        raise RuntimeError(
            f"XMLTV incorrect pour {source_name}."
        )

    print(f"Source {source_name} chargée.")

    return root


# ============================================================
# HORAIRES XMLTV
# ============================================================

def parse_xmltv_time(value):
    match = re.fullmatch(
        r"(\d{14})(?:\s*([+-]\d{4}))?",
        value or ""
    )

    if not match:
        raise ValueError(
            f"Horaire XMLTV invalide : {value}"
        )

    date_part, offset = match.groups()

    if offset:
        return datetime.strptime(
            date_part + " " + offset,
            "%Y%m%d%H%M%S %z"
        )

    return datetime.strptime(
        date_part,
        "%Y%m%d%H%M%S"
    ).replace(tzinfo=timezone.utc)


def utc_time(value):
    return parse_xmltv_time(value).astimezone(timezone.utc)


def convert_time(value):
    return utc_time(value).astimezone(PARIS).strftime(
        "%Y%m%d%H%M%S %z"
    )


# ============================================================
# FENETRE DE 7 JOURS
# ============================================================

def get_window():
    now = datetime.now(PARIS)
    end = now + timedelta(days=WINDOW_DAYS)

    return (
        now.astimezone(timezone.utc),
        end.astimezone(timezone.utc)
    )


def in_window(programme, start, end):
    p_start = utc_time(programme.get("start"))
    p_stop = utc_time(programme.get("stop"))

    return p_stop > start and p_start < end


# ============================================================
# FILTRAGE DES CHAINES CATHY
# ============================================================

def filter_cathy(root):
    print("Filtrage des 12 chaînes Cathy...")

    found = set()

    for channel in list(root.findall("channel")):
        channel_id = channel.get("id")

        if channel_id not in CHANNELS:
            root.remove(channel)
            continue

        if channel_id in found:
            raise RuntimeError(
                f"Chaîne Cathy dupliquée : {channel_id}"
            )

        found.add(channel_id)

        for name in list(channel.findall("display-name")):
            channel.remove(name)

        ET.SubElement(
            channel,
            "display-name"
        ).text = CHANNELS[channel_id]

    missing = set(CHANNELS) - found

    if missing:
        raise RuntimeError(
            "Chaînes absentes de Cathy : "
            + ", ".join(sorted(missing))
        )

    for programme in list(root.findall("programme")):
        if programme.get("channel") not in CHANNELS:
            root.remove(programme)

    return found


# ============================================================
# FUSION DES PROGRAMMES EXTERNES
# ============================================================


def merge_source(
    root,
    source_root,
    mapping,
    source_name,
    window_start,
    window_end
):
    added = 0
    enriched = 0
    ignored = 0

    by_channel = {}

    for programme in root.findall("programme"):
        channel = programme.get("channel")
        by_channel.setdefault(channel, []).append(programme)

    for external in source_root.findall("programme"):

        source_channel = external.get("channel")
        targets = mapping.get(source_channel)

        if not targets:
            continue

        if isinstance(targets, str):
            targets = [targets]

        start_value = external.get("start")
        stop_value = external.get("stop")

        if not start_value or not stop_value:
            continue

        start = utc_time(start_value)
        stop = utc_time(stop_value)

        if stop <= start:
            continue

        if stop <= window_start or start >= window_end:
            continue

        title = get_title(external)

        if is_generic_title(title):
            ignored += 1
            continue

        for target_channel in targets:

            if target_channel not in CHANNELS:
                continue

            channel_programmes = by_channel.setdefault(
                target_channel,
                []
            )

            overlapping = []

            for current in channel_programmes:

                current_start = utc_time(
                    current.get("start")
                )

                current_stop = utc_time(
                    current.get("stop")
                )

                if (
                    current_stop > start
                    and current_start < stop
                ):
                    overlapping.append(current)

            same_start = [
                p for p in overlapping
                if utc_time(p.get("start")) == start
            ]

            if same_start:

                current = same_start[0]
                current_title = get_title(current)

                if is_generic_title(current_title):

                    title_element = current.find("title")

                    if title_element is None:
                        title_element = ET.SubElement(
                            current,
                            "title"
                        )

                    title_element.text = title
                    enriched += 1

                    print(
                        f"TITRE ENRICHI : {title} "
                        f"sur {CHANNELS[target_channel]} "
                        f"({source_name})"
                    )

                else:
                    ignored += 1

                continue

            if overlapping:
                ignored += 1
                continue

            new_programme = copy.deepcopy(external)
            new_programme.set("channel", target_channel)

            channel_programmes.append(new_programme)
            root.append(new_programme)

            added += 1

    print(
        f"{source_name} : "
        f"{added} ajoutés, "
        f"{enriched} titres enrichis, "
        f"{ignored} ignorés."
    )

    return added, enriched, ignored


# ============================================================
# NETTOYAGE ET TRI FINAL
# ============================================================

def finalize_programmes(root):
    print("Nettoyage et conversion des horaires...")

    window_start, window_end = get_window()

    programmes = []

    for programme in list(root.findall("programme")):

        channel = programme.get("channel")

        if channel not in CHANNELS:
            root.remove(programme)
            continue

        start_value = programme.get("start")
        stop_value = programme.get("stop")

        if not start_value or not stop_value:
            raise RuntimeError(
                "Programme sans horaire."
            )

        start = utc_time(start_value)
        stop = utc_time(stop_value)

        if stop <= start:
            raise RuntimeError(
                f"Durée invalide : {start_value}"
            )

        if stop <= window_start or start >= window_end:
            root.remove(programme)
            continue

        programme.set(
            "start",
            convert_time(start_value)
        )

        programme.set(
            "stop",
            convert_time(stop_value)
        )

        programmes.append(programme)

    programmes.sort(
        key=lambda p: utc_time(p.get("start"))
    )

    for programme in list(root.findall("programme")):
        root.remove(programme)

    for programme in programmes:
        root.append(programme)

    if not programmes:
        raise RuntimeError(
            "Aucun programme dans la fenêtre de 7 jours."
        )

    return len(programmes)


# ============================================================
# VALIDATION XML
# ============================================================

def validate_xml(path):
    tree = ET.parse(path)
    root = tree.getroot()

    if root.tag != "tv":
        raise RuntimeError(
            "Structure XMLTV incorrecte."
        )

    channels = {
        channel.get("id")
        for channel in root.findall("channel")
    }

    if channels != set(CHANNELS):
        raise RuntimeError(
            "Validation des 12 chaînes échouée."
        )

    programmes = root.findall("programme")

    if not programmes:
        raise RuntimeError(
            "XML final sans programmes."
        )

    for programme in programmes:

        if programme.get("channel") not in CHANNELS:
            raise RuntimeError(
                "Programme associé à une chaîne inconnue."
            )

        start = utc_time(programme.get("start"))
        stop = utc_time(programme.get("stop"))

        if stop <= start:
            raise RuntimeError(
                "Horaire de programme incorrect."
            )

        if not programme.findall("title"):
            raise RuntimeError(
                "Programme sans titre."
            )

    return len(programmes)


# ============================================================
# SAUVEGARDE SECURISEE
# ============================================================

def save_epg(root):
    print("Écriture du XML temporaire...")

    ET.indent(root, space="  ")

    tree = ET.ElementTree(root)

    tree.write(
        TEMP_FILE,
        encoding="UTF-8",
        xml_declaration=True
    )

    validated_count = validate_xml(TEMP_FILE)

    print(
        f"Validation réussie : {validated_count} programmes."
    )

    if OUTPUT_FILE.exists():
        shutil.copy2(
            OUTPUT_FILE,
            BACKUP_FILE
        )

        print("Ancien XML sauvegardé.")

    os.replace(TEMP_FILE, OUTPUT_FILE)


# ============================================================
# MAIN
# ============================================================

def main():
    try:
        print()
        print("======================================")
        print("          EPG UK 4K V2")
        print("       FUSION DE 3 SOURCES")
        print("======================================")

        window_start, window_end = get_window()

        # 1. Cathy : source principale
        cathy = download_xml(
            CATHY_URL,
            "Cathy"
        )

        found_channels = filter_cathy(cathy)

        # 2. Sky London
        sky = download_xml(
            SKY_URL,
            "Sky London"
        )

        # 3. Open-EPG
        open_epg = download_xml(
            OPEN_EPG_URL,
            "Open-EPG UK"
        )

        # Fusion Sky London
        sky_stats = merge_source(
            cathy,
            sky,
            SKY_MAPPING,
            "Sky London",
            window_start,
            window_end
        )

        # Fusion Open-EPG
        open_stats = merge_source(
            cathy,
            open_epg,
            OPEN_MAPPING,
            "Open-EPG",
            window_start,
            window_end
        )

        # Nettoyage final
        programme_count = finalize_programmes(cathy)

        # Publication sécurisée
        save_epg(cathy)

        print()
        print("======================================")
        print("          GENERATION REUSSIE")
        print("======================================")

        print(f"Chaînes : {len(found_channels)}")
        print(f"Programmes finaux : {programme_count}")

        print(
            f"Sky London : {sky_stats[0]} ajouts, "
            f"{sky_stats[1]} enrichissements"
        )

        print(
            f"Open-EPG : {open_stats[0]} ajouts, "
            f"{open_stats[1]} enrichissements"
        )

        print(f"Fenêtre : {WINDOW_DAYS} jours")
        print(f"Fuseau : {PARIS}")
        print(f"Fichier : {OUTPUT_FILE}")

        print("======================================")

    except Exception as error:

        if TEMP_FILE.exists():
            TEMP_FILE.unlink()

        print()
        print("======================================")
        print("            ERREUR EPG")
        print("======================================")

        print(str(error))
        print("L'ancien epg.xml n'a pas été remplacé.")

        raise


if __name__ == "__main__":
    main()
