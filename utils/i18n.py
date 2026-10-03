from __future__ import annotations

import adsk.core

_LANG_CACHE = None

STRINGS = {
    "en": {
        "deps_missing_msg": (
            "Airfoil Splines requires external libraries (numpy, scipy).\n\n"
            "They were not found in the 'lib' folder.\n"
            "Would you like to attempt a local installation into the add-in folder?"
        ),
        "deps_missing_title": "Dependencies Missing",
        "deps_install_started": (
            "Installation has started in a separate window.\n\n"
            "Please wait for it to complete, then restart Fusion."
        ),
        "deps_install_complete": "Installation complete. Please restart Fusion.",
        "deps_install_failed": (
            "Resilient installation failed: {error}\n\n"
            "Please manually install dependencies."
        ),
        "cmd_button_name": "Insert Airfoil",
        "cmd_button_desc": "Fit a spline to an airfoil .dat file in Selig or Lednicer format",
        "failed_to_start": "Failed to start:\n{error}",
        "update_available": (
            "A newer version of Airfoil Splines is available.\n\n"
            "Installed version: {local_version}\n"
            "Latest version: {remote_version}\n\n"
            "Download it from the Autodesk App Store:\n{app_store_url}"
        ),
        "select_chord_line": "Chord Line",
        "select_chord_line_help": "Select a construction line",
        "select_airfoil": "Input File",
        "selected_file": "Selected File",
        "fitter_settings": "Fitter Settings",
        "initial_cp_count": "Initial Control Points",
        "cp_count_upper": "Points Upper",
        "cp_count_lower": "Points Lower",
        "reset": "Reset",
        "smoothness_penalty": "Smoothness",
        "le_continuity": "Continuity",
        "import_settings": "Import Settings",
        "turn_90": "Turn 90\u00b0",
        "flip": "Flip",
        "te_thickness": "TE Thickness",
        "curvature_comb": "Curvature comb",
        "comb_scale": "Comb Scale",
        "comb_density": "Comb Density",
        "show_input_data": "Show Input Data",
        "ui_creation_failed": "UI Creation Failed:\n{error}",
        "command_created_failed": "Command Created Failed:\n{error}",
        "execution_error": "Execution Error:\n{error}",
        "file_filter": "Airfoil (*.dat);;All Files (*.*)",
        "failed_load_airfoil_data": "Failed to load airfoil data, please check the file path and try again.",
        "failed_fit_airfoil": "Failed to fit airfoil, please check the input parameters and try again.",
        "failed_insert_knot": "Failed to insert knot on {surface} surface.",
        "failed_refit_surface": "Failed to re-fit {surface} surface with reduced control points.",
        "failed_create_airfoil_plane": (
            "Could not create a sketch plane for the airfoil.\n\n"
            "{error}\n\n"
            "See the Text Commands log (Ctrl+Alt+C) for details."
        ),
        "generic_error": "An error occurred, please check the log for more details.",
    },
    "de": {
        "deps_missing_msg": (
            "Airfoil Splines benoetigt externe Bibliotheken (numpy, scipy).\n\n"
            "Diese wurden im Ordner 'lib' nicht gefunden.\n"
            "Moechten Sie eine lokale Installation im Add-in-Ordner versuchen?"
        ),
        "deps_missing_title": "Abhaengigkeiten fehlen",
        "deps_install_started": (
            "Die Installation wurde in einem separaten Fenster gestartet.\n\n"
            "Bitte warten Sie, bis sie abgeschlossen ist, und starten Sie Fusion dann neu."
        ),
        "deps_install_complete": "Installation abgeschlossen. Bitte Fusion neu starten.",
        "deps_install_failed": (
            "Fehlgeschlagene Installation: {error}\n\n"
            "Bitte installieren Sie die Abhaengigkeiten manuell."
        ),
        "cmd_button_name": "Profil einfuegen",
        "cmd_button_desc": "Spline an eine .dat-Profildatei im Selig- oder Lednicer-Format anpassen",
        "failed_to_start": "Start fehlgeschlagen:\n{error}",
        "update_available": (
            "Eine neuere Version von Airfoil Splines ist verfuegbar.\n\n"
            "Installierte Version: {local_version}\n"
            "Neueste Version: {remote_version}\n\n"
            "Download im Autodesk App Store:\n{app_store_url}"
        ),
        "select_chord_line": "Sehnenlinie auswaehlen",
        "select_chord_line_help": "Waehlen Sie eine Linie aus",
        "select_airfoil": "Datei auswaehlen",
        "selected_file": "Ausgewaehlte Datei",
        "fitter_settings": "Fitter Einstellungen",
        "initial_cp_count": "Initiale Kontrollpunkte",
        "cp_count_upper": "Punkte Oberseite",
        "cp_count_lower": "Punkte Unterseite",
        "reset": "Zuruecksetzen",
        "smoothness_penalty": "Glaettung",
        "le_continuity": "Kontinuitaet",
        "import_settings": "Import Einstellungen",
        "turn_90": "Um 90\u00b0 drehen",
        "flip": "Spiegeln",
        "te_thickness": "Dicke Endleiste",
        "curvature_comb": "Kurvenkamm",
        "comb_scale": "Kamm-Skalierung",
        "comb_density": "Kamm-Dichte",
        "show_input_data": "Rohdaten anzeigen",
        "ui_creation_failed": "UI-Erstellung fehlgeschlagen:\n{error}",
        "command_created_failed": "Befehlserstellung fehlgeschlagen:\n{error}",
        "execution_error": "Ausfuehrungsfehler:\n{error}",
        "file_filter": "Profil (*.dat);;Alle Dateien (*.*)",
        "failed_load_airfoil_data": "Profildaten konnten nicht geladen werden. Bitte Dateipfad pruefen und erneut versuchen.",
        "failed_fit_airfoil": "Profilanpassung fehlgeschlagen. Bitte Eingabeparameter pruefen und erneut versuchen.",
        "failed_insert_knot": "Knoten konnte auf der {surface}-Flaeche nicht eingefuegt werden.",
        "failed_refit_surface": "Neu-Anpassung der {surface}-Flaeche mit reduzierter Kontrollpunktzahl fehlgeschlagen.",
        "failed_create_airfoil_plane": (
            "Die Skizzenebene fuer das Profil konnte nicht erstellt werden.\n\n"
            "{error}\n\n"
            "Details stehen im Textbefehlsprotokoll (Strg+Alt+C)."
        ),
        "generic_error": "Ein Fehler ist aufgetreten. Bitte pruefen Sie das Protokoll fuer Details.",
    },
    "it": {
        "deps_missing_msg": (
            "Airfoil Splines richiede librerie esterne (numpy, scipy).\n\n"
            "Non sono presenti nella cartella 'lib'.\n"
            "Vuoi provare a installarle automaticamente nella cartella dell'add-in?"
        ),
        "deps_missing_title": "Dipendenze mancanti",
        "deps_install_started": (
            "L'installazione e' stata avviata in una nuova finestra.\n\n"
            "Attendi che venga completata, poi riavvia Fusion."
        ),
        "deps_install_complete": "Installazione completata. Riavvia Fusion.",
        "deps_install_failed": (
            "Installazione non riuscita: {error}\n\n"
            "Installa le dipendenze manualmente."
        ),
        "cmd_button_name": "Inserisci profilo",
        "cmd_button_desc": "Adatta una spline a un profilo .dat in formato Selig o Lednicer",
        "failed_to_start": "Avvio non riuscito:\n{error}",
        "update_available": (
            "E disponibile una versione piu recente di Airfoil Splines.\n\n"
            "Versione installata: {local_version}\n"
            "Versione piu recente: {remote_version}\n\n"
            "Scaricala da Autodesk App Store:\n{app_store_url}"
        ),
        "select_chord_line": "Linea di corda",
        "select_chord_line_help": "Seleziona una linea di costruzione",
        "select_airfoil": "File di input",
        "selected_file": "File selezionato",
        "fitter_settings": "Impostazioni del fitting",
        "initial_cp_count": "Punti di controllo iniziali",
        "cp_count_upper": "Punti superiori",
        "cp_count_lower": "Punti inferiori",
        "reset": "Reimposta",
        "smoothness_penalty": "Uniformità",
        "le_continuity": "Continuità",
        "import_settings": "Impostazioni di importazione",
        "turn_90": "Ruota di 90\u00b0",
        "flip": "Specchia",
        "te_thickness": "Spessore del bordo d'uscita",
        "curvature_comb": "Pettine di curvatura",
        "comb_scale": "Scala del pettine",
        "comb_density": "Densità del pettine",
        "show_input_data": "Mostra dati di input",
        "ui_creation_failed": "Creazione dell'interfaccia non riuscita:\n{error}",
        "command_created_failed": "Creazione del comando non riuscita:\n{error}",
        "execution_error": "Errore di esecuzione:\n{error}",
        "file_filter": "Profili (*.dat);;Tutti i file (*.*)",
        "failed_load_airfoil_data": "Impossibile caricare i dati del profilo. Controlla il percorso del file e riprova.",
        "failed_fit_airfoil": "Impossibile adattare il profilo. Controlla i parametri di input e riprova.",
        "failed_insert_knot": "Impossibile inserire il nodo sulla superficie {surface}.",
        "failed_refit_surface": "Impossibile riadattare la superficie {surface} con un numero ridotto di punti di controllo.",
        "failed_create_airfoil_plane": (
            "Impossibile creare il piano dello schizzo per il profilo.\n\n"
            "{error}\n\n"
            "Consulta il registro dei comandi di testo (Ctrl+Alt+C) per i dettagli."
        ),
        "generic_error": "Si e' verificato un errore. Controlla il log per maggiori dettagli.",
    }
}


def _enum_name_for_value(enum_type, value):
    try:
        for name in dir(enum_type):
            if name.startswith("_"):
                continue
            try:
                if getattr(enum_type, name) == value:
                    return name
            except Exception:
                continue
    except Exception:
        pass
    return None


def _extract_language_code(value) -> str | None:
    if value is None:
        return None
    # Handle numeric language enums.
    if isinstance(value, int):
        try:
            enum_type = getattr(adsk.core, "UserLanguages", None)
            if enum_type:
                enum_name = _enum_name_for_value(enum_type, value)
                if enum_name:
                    value = enum_name
        except Exception:
            pass
    text = str(value).strip().lower()
    if not text:
        return None
    text = text.replace("_", "-")
    if text.startswith("de") or "german" in text or "deutsch" in text:
        return "de"
    if text.startswith("it") or "italian" in text or "italiano" in text:
        return "it"
    if text.startswith("en") or "english" in text:
        return "en"
    return None


def _get_fusion_language_code() -> str | None:
    try:
        app = adsk.core.Application.get()
    except Exception:
        return None

    # Prefer the documented preferences.generalPreferences.userLanguage.
    candidates = []
    try:
        prefs = getattr(app, "preferences", None)
        gp = getattr(prefs, "generalPreferences", None) if prefs else None
        if gp:
            candidates.append(getattr(gp, "userLanguage", None))
            candidates.extend([
                getattr(gp, "language", None),
                getattr(gp, "defaultLanguage", None),
                getattr(gp, "locale", None),
            ])
    except Exception:
        pass

    # Some builds expose a direct language on the app
    candidates.append(getattr(app, "language", None))

    for value in candidates:
        code = _extract_language_code(value)
        if code:
            return code
    return None


def get_language_code() -> str:
    global _LANG_CACHE
    if _LANG_CACHE:
        return _LANG_CACHE
    code = _get_fusion_language_code()
    _LANG_CACHE = code if code in STRINGS else "en"
    return _LANG_CACHE


def t(key: str, **kwargs) -> str:
    lang = get_language_code()
    table = STRINGS.get(lang, STRINGS["en"])
    text = table.get(key, STRINGS["en"].get(key, key))
    try:
        return text.format(**kwargs)
    except Exception:
        return text
