
import gzip
import json
import os
import re
import shutil
import urllib.request
import xml.etree.ElementTree as ET

from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo


# ============================================================
# EPG UK 4K V2 - PYTHON 3.12
# ============================================================

SOURCE_URL = (
    "https://raw.githubusercontent.com/waastudios/"
    "Cathy-epg/master/data/epg.xml.gz"
)

PARIS = ZoneInfo("Europe/Paris")

OUTPUT_FILE = Path("epg.xml")
BACKUP_FILE = Path("epg.xml.backup")
TEMP_FILE = Path("epg.xml.tmp")

MATCHES_FILE = Path("confirmed_matches.json")

WINDOW_DAYS = 7
DOWNLOAD_TIMEOUT = 120


# ============================================================
# LES 12 CHAINES
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

SKY_CHANNELS = {
    "virgin_uk.2258",
    "virgin_uk.2265",
    "ee_uk.419",
    "ee_uk.420",
}

TNT_CHANNELS = set(CHANNELS) - SKY_CHANNELS

OFFICIAL_DOMAINS = {
    "sky": {
        "sky.com",
        "skysports.com",
    },
    "tnt": {
        "tntsports.co.uk",
    },
}


# ============================================================
# TITRES GENERIQUES AUTORISES AU REMPLACEMENT
# ============================================================

GENERIC_TITLES = {
    "live fnf",
    "live football",
    "football live",
    "live premier league",
    "premier league live",
    "live champions league",
    "champions league live",
    "uefa champions league live",
    "live fa cup",
    "fa cup live",
    "live carabao cup",
    "carabao cup live",
    "live sport",
    "live sports",
    "sport live",
    "sports live",
    "football",
    "tbc",
}


def is_generic_title(title):

    if not title:
        return False

    normalized = " ".join(title.strip().lower().split())

    return normalized in GENERIC_TITLES


# ============================================================
# TELECHARGEMENT SOURCE EPG
# ============================================================

def download_epg():

    print("Téléchargement de la source EPG...")

    request = urllib.request.Request(
        SOURCE_URL,
        headers={
            "User-Agent": "EPG-UK-4K/2.0"
        }
    )

    with urllib.request.urlopen(
        request,
        timeout=DOWNLOAD_TIMEOUT
    ) as response:

        data = response.read()

    if not data:
        raise RuntimeError("Source EPG vide.")

    # Accepte gzip ou XML non compressé.
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)

    return data


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

        result = datetime.strptime(
            date_part + " " + offset,
            "%Y%m%d%H%M%S %z"
        )

    else:

        # Convention du générateur original :
        # horaire sans décalage = UTC.

        result = datetime.strptime(
            date_part,
            "%Y%m%d%H%M%S"
        ).replace(tzinfo=timezone.utc)

    return result


def convert_time(value):

    dt = parse_xmltv_time(value)

    return dt.astimezone(PARIS).strftime(
        "%Y%m%d%H%M%S %z"
    )


# ============================================================
# FENETRE GLISSANTE DE 7 JOURS
# ============================================================

def get_window():

    now = datetime.now(PARIS)

    end = now + timedelta(days=WINDOW_DAYS)

    return (
        now.astimezone(timezone.utc),
        end.astimezone(timezone.utc)
    )


def programme_in_window(programme, start, end):

    programme_start = parse_xmltv_time(
        programme.get("start")
    ).astimezone(timezone.utc)

    programme_stop = parse_xmltv_time(
        programme.get("stop")
    ).astimezone(timezone.utc)

    return (
        programme_stop > start
        and programme_start < end
    )


# ============================================================
# CHARGEMENT DES MATCHS CONFIRMES
# ============================================================

def load_confirmed_matches():

    if not MATCHES_FILE.exists():

        print(
            "ATTENTION : fichier des matchs absents."
        )

        print(
            "Aucun remplacement sportif ne sera effectué."
        )

        return {}

    with MATCHES_FILE.open(
        "r",
        encoding="utf-8"
    ) as file:

        matches = json.load(file)

    if not isinstance(matches, list):

        raise ValueError(
            "confirmed_matches.json doit contenir une liste."
        )

    confirmed = {}

    for match in matches:

        channel = match.get("channel")
        title = match.get("title")
        broadcaster = match.get("broadcaster")
        evidence = match.get("evidence_url")

        start = match.get("start_utc")
        stop = match.get("stop_utc")

        if channel not in CHANNELS:

            raise ValueError(
                f"Chaîne inconnue : {channel}"
            )

        if not all([
            title,
            broadcaster,
            evidence,
            start,
            stop
        ]):

            raise ValueError(
                "Confirmation incomplète : "
                + str(match)
            )

        if not isinstance(title, str) or not title.strip():
            raise ValueError("Titre de match invalide.")

        if not isinstance(broadcaster, str):
            raise ValueError("Diffuseur invalide.")

        broadcaster = broadcaster.strip().lower()

        if broadcaster == "sky sports":

            provider = "sky"

            if channel not in SKY_CHANNELS:
                raise ValueError(
                    "Incohérence entre diffuseur Sky et chaîne."
                )

        elif broadcaster == "tnt sports":

            provider = "tnt"

            if channel not in TNT_CHANNELS:
                raise ValueError(
                    "Incohérence entre diffuseur TNT et chaîne."
                )

        else:

            raise ValueError(
                f"Diffuseur non reconnu : {broadcaster}"
            )

        parsed_url = urlparse(evidence)

        if parsed_url.scheme != "https":
            raise ValueError("La preuve doit être en HTTPS.")

        hostname = (parsed_url.hostname or "").lower()

        allowed = OFFICIAL_DOMAINS[provider]

        if not any(
            hostname == domain
            or hostname.endswith("." + domain)
            for domain in allowed
        ):

            raise ValueError(
                f"Source non officielle ou non autorisée : {hostname}"
            )

        try:

            start_dt = datetime.fromisoformat(
                start.replace("Z", "+00:00")
            )

            stop_dt = datetime.fromisoformat(
                stop.replace("Z", "+00:00")
            )

            if not start_dt.tzinfo or not stop_dt.tzinfo:
                raise ValueError(
                    "Les horaires doivent comporter un fuseau."
                )

            start_dt = start_dt.astimezone(timezone.utc)
            stop_dt = stop_dt.astimezone(timezone.utc)

            if stop_dt <= start_dt:
                raise ValueError(
                    "Durée de match invalide."
                )

        except (TypeError, ValueError) as error:

            raise ValueError(
                f"Dates incorrectes : {match}"
            ) from error

        key = (
            channel,
            start_dt.strftime("%Y%m%d%H%M%S"),
            stop_dt.strftime("%Y%m%d%H%M%S"),
        )

        if key in confirmed:

            raise ValueError(
                f"Confirmation en double : {key}"
            )

        confirmed[key] = title.strip()

    print(
        f"Matchs confirmés chargés : {len(confirmed)}"
    )

    # Attention : l'URL est contrôlée, mais son contenu
    # doit avoir été vérifié humainement avant inscription
    # dans ce fichier.

    return confirmed


# ============================================================
# FILTRAGE DES 12 CHAINES
# ============================================================

def filter_channels(root):

    print("Vérification des 12 chaînes...")

    found = set()

    for channel in list(root.findall("channel")):

        channel_id = channel.get("id")

        if channel_id not in CHANNELS:

            root.remove(channel)
            continue

        if channel_id in found:

            raise RuntimeError(
                f"Chaîne dupliquée : {channel_id}"
            )

        found.add(channel_id)

        for name in list(
            channel.findall("display-name")
        ):

            channel.remove(name)

        ET.SubElement(
            channel,
            "display-name"
        ).text = CHANNELS[channel_id]

    missing = set(CHANNELS) - found

    if missing:

        raise RuntimeError(
            "Chaînes absentes : "
            + ", ".join(sorted(missing))
        )

    return found


# ============================================================
# TRAITEMENT DES PROGRAMMES
# ============================================================

def process_programmes(root, confirmed):

    print("Filtrage de la fenêtre de 7 jours...")

    window_start, window_end = get_window()

    programme_count = 0
    replacements = 0
    ignored = 0

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

        start_dt = parse_xmltv_time(start_value)
        stop_dt = parse_xmltv_time(stop_value)

        if stop_dt <= start_dt:

            raise RuntimeError(
                f"Durée invalide : {start_value}"
            )

        # Fenêtre glissante : 7 jours à partir de maintenant.
        if not programme_in_window(
            programme,
            window_start,
            window_end
        ):

            root.remove(programme)
            continue

        start_utc = start_dt.astimezone(
            timezone.utc
        ).strftime("%Y%m%d%H%M%S")

        stop_utc = stop_dt.astimezone(
            timezone.utc
        ).strftime("%Y%m%d%H%M%S")

        key = (
            channel,
            start_utc,
            stop_utc
        )

        # Aucun ajout de match manquant.
        # Aucun changement sans correspondance exacte.
        if key in confirmed:

            titles = programme.findall("title")

            if titles and is_generic_title(titles[0].text):

                new_title = confirmed[key]

                titles[0].text = new_title

                replacements += 1

                print(
                    f"CONFIRMÉ : {new_title} "
                    f"sur {CHANNELS[channel]}"
                )

            else:

                ignored += 1

        # Conversion en heure française.
        programme.set(
            "start",
            convert_time(start_value)
        )

        programme.set(
            "stop",
            convert_time(stop_value)
        )

        programme_count += 1

    if programme_count == 0:

        raise RuntimeError(
            "Aucun programme dans la fenêtre demandée."
        )

    # Tri chronologique.
    programmes = root.findall("programme")

    programmes.sort(
        key=lambda p: parse_xmltv_time(
            p.get("start")
        ).astimezone(timezone.utc)
    )

    for programme in list(root.findall("programme")):
        root.remove(programme)

    for programme in programmes:
        root.append(programme)

    return (
        programme_count,
        replacements,
        ignored
    )


# ============================================================
# VALIDATION DU XML
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

        start = parse_xmltv_time(
            programme.get("start")
        )

        stop = parse_xmltv_time(
            programme.get("stop")
        )

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

    ET.indent(
        root,
        space="  "
    )

    tree = ET.ElementTree(root)

    tree.write(
        TEMP_FILE,
        encoding="UTF-8",
        xml_declaration=True
    )

    # Vérification avant publication.
    validated_count = validate_xml(TEMP_FILE)

    print(
        f"Validation XML réussie : {validated_count} programmes."
    )

    # Sauvegarde de l'ancien XML.
    if OUTPUT_FILE.exists():

        shutil.copy2(
            OUTPUT_FILE,
            BACKUP_FILE
        )

        print("Ancien XML sauvegardé.")

    # Remplacement atomique.
    os.replace(
        TEMP_FILE,
        OUTPUT_FILE
    )


# ============================================================
# MAIN
# ============================================================

def main():

    try:

        print()
        print("================================")
        print("       EPG UK 4K V2")
        print("================================")

        xml_data = download_epg()

        print("Lecture du XML source...")

        root = ET.fromstring(xml_data)

        confirmed = load_confirmed_matches()

        found_channels = filter_channels(root)

        (
            programme_count,
            replacements,
            ignored
        ) = process_programmes(
            root,
            confirmed
        )

        save_epg(root)

        print()
        print("================================")
        print("       GENERATION REUSSIE")
        print("================================")

        print(f"Chaînes : {len(found_channels)}")
        print(f"Programmes : {programme_count}")
        print(f"Matchs corrigés : {replacements}")
        print(f"Correspondances ignorées : {ignored}")
        print(f"Fenêtre : {WINDOW_DAYS} jours")
        print(f"Fuseau : {PARIS}")
        print(f"Fichier : {OUTPUT_FILE}")

        print("================================")

    except Exception as error:

        if TEMP_FILE.exists():
            TEMP_FILE.unlink()

        print()
        print("================================")
        print("       ERREUR EPG V2")
        print("================================")

        print(str(error))

        print(
            "L'ancien epg.xml n'a pas été remplacé."
        )

        raise


if __name__ == "__main__":
    main()
