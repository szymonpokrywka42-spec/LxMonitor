import json
import os
from PyQt6.QtCore import QLocale

class LanguageHandler:
    def __init__(self, parent=None, config_lang="system"):
        self.parent = parent
        
        # LxMonitor/core/language_handler.py -> assets/languages/
        current_file_path = os.path.abspath(__file__)
        self.base_dir = os.path.dirname(os.path.dirname(current_file_path))
        self.lang_dir = os.path.join(self.base_dir, "assets", "languages")
        # Fallback dla starej struktury
        self.legacy_lang_dir = os.path.join(self.base_dir, "assets", "language")
        
        self.current_data = {}
        self.current_lang = "en-us" # Domyślny backup
        self.selected_lang = config_lang or "system"
        self.fallback_data = {}
        self.language_names = {
            "system": "System",
            "en-us": "English (US)",
            "pl-pl": "Polski",
            "de-de": "Deutsch",
            "fr-fr": "Français",
            "es-es": "Español",
            "it-it": "Italiano",
            "pt-br": "Português (Brasil)",
            "ru-ru": "Русский",
            "uk-ua": "Українська",
            "tr-tr": "Türkçe",
            "ja-jp": "日本語",
            "ko-kr": "한국어",
            "zh-cn": "中文 (简体)",
            "cs-cz": "Čeština",
            "nl-nl": "Nederlands",
            "sv-se": "Svenska",
        }
        self._load_fallback_en()
        
        # Wybór języka
        if config_lang == "system":
            target_lang = self.get_system_language()
        else:
            target_lang = config_lang

        # Próba załadowania, w razie wtopy -> fallback do en-us
        if not self.load_language(target_lang):
            print(f"[WARN] Could not load {target_lang}, falling back to en-us")
            self.load_language("en-us")

    def _load_fallback_en(self):
        file_name = "en-us.json"
        candidates = [
            os.path.join(self.lang_dir, file_name),
            os.path.join(self.legacy_lang_dir, file_name),
        ]
        for file_path in candidates:
            if not os.path.exists(file_path):
                continue
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    self.fallback_data = json.load(f)
                return
            except Exception:
                pass
        self.fallback_data = {}

    def get_system_language(self):
        """Sprawdza język systemu i dopasowuje go do dostępnych plików .json."""
        sys_locale = QLocale.system().name().lower().replace('_', '-') 
        available = self.get_available_languages()

        # 1. Dokładne dopasowanie (pl-pl)
        if sys_locale in available:
            return sys_locale
        
        # 2. Dopasowanie częściowe (pl-pl -> pl)
        short_code = sys_locale.split('-')[0]
        for lang in available:
            if lang.startswith(short_code):
                return lang
        
        return "en-us"

    def load_language(self, lang_code):
        """Wczytuje słownik tłumaczeń z pliku JSON."""
        file_name = f"{lang_code.lower()}.json"
        candidates = [
            os.path.join(self.lang_dir, file_name),
            os.path.join(self.legacy_lang_dir, file_name),
        ]

        for file_path in candidates:
            if not os.path.exists(file_path):
                continue
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    self.current_data = json.load(f)
                self.current_lang = lang_code.lower()
                return True
            except Exception as e:
                print(f"[ERROR] Error loading language file {lang_code}: {e}")
                return False
        return False

    def get_available_languages(self):
        """Zwraca listę dostępnych plików językowych bez rozszerzenia .json."""
        langs = set()
        for directory in [self.lang_dir, self.legacy_lang_dir]:
            if not os.path.exists(directory):
                continue
            for file_name in os.listdir(directory):
                if file_name.endswith('.json'):
                    langs.add(file_name.replace('.json', ''))
        if not langs:
            return ["en-us"]
        return sorted(langs)

    def set_language(self, lang_code):
        code = (lang_code or "system").lower()
        self.selected_lang = code
        if code == "system":
            return self.load_language(self.get_system_language())
        return self.load_language(code)

    def get_language_choices(self):
        available = set(self.get_available_languages())
        prioritized = [
            "en-us", "pl-pl", "de-de", "fr-fr", "es-es", "it-it", "pt-br",
            "ru-ru", "uk-ua", "tr-tr", "ja-jp", "ko-kr", "zh-cn", "cs-cz",
            "nl-nl", "sv-se",
        ]
        out = [("system", self.get_language_display_name("system"))]
        for code in prioritized:
            if code in available:
                out.append((code, self.get_language_display_name(code)))
        for code in sorted(available):
            if code in {c for c, _ in out}:
                continue
            out.append((code, self.get_language_display_name(code)))
        return out

    def get_language_display_name(self, code):
        return self.language_names.get(code.lower(), code)

    def tr(self, key):
        """Główna metoda tłumacząca dla UI (skrót od translate)."""
        if key in self.current_data:
            return self.current_data[key]
        return self.fallback_data.get(key, key)

    def get(self, key):
        """Alias dla tr(), używany w niektórych modułach logicznych."""
        return self.tr(key)
