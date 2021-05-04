import json
import logging
from pathlib import Path
from typing import List

import requests
from bs4 import BeautifulSoup
from bs4.element import NavigableString, ResultSet
from ulauncher.api.client.EventListener import EventListener
from ulauncher.api.client.Extension import Extension
from ulauncher.api.shared.action.HideWindowAction import HideWindowAction
from ulauncher.api.shared.action.RenderResultListAction import RenderResultListAction
from ulauncher.api.shared.event import (
    KeywordQueryEvent,
    PreferencesEvent,
    PreferencesUpdateEvent,
)
from ulauncher.api.shared.item.ExtensionResultItem import ExtensionResultItem

BASE_URL = "https://dle.rae.es"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/70.0.3538.77 Safari/537.36"
}
CHARACTERS_PER_LINE = 80
NUMERIC_PREFERENCES = {"max_suggested_items", "max_shown_definitions"}

p = (
    Path.home()
    / ".local"
    / "share"
    / "ulauncher"
    / "extensions"
    / "rae"
    / "manifest.json"
)
with p.open("r") as f:
    DEFAULT_MANIFEST = json.load(f)
DEFAULT_PREFERENCES = {
    x["id"]: x["default_value"] for x in DEFAULT_MANIFEST["preferences"]
}

logger = logging.getLogger(__name__)

# TODO: Ctrl+C copies definition.
# TODO: Enter goes to the webapge of defined word.
# TODO: Enter updates the search term to the one selected (when approx result).


def chunkize_sentence(sentence: str, max_characters_per_chunk: int) -> List[str]:
    """Splits a given sentence into chunks of at most max_characters_per_chunk, counting spaces.

    The method guarantees that each element of the output is an intelligible sentence with whole words.

    This is not the same as splitting into max_characters_per_chunk, because words could end up truncated.

    Args:
        sentence (str): Sentence to be split.
        max_characters_per_chunk (int): Maximum number of characters allower per chunk, spaces included. Chunks could end up being significantly shorter, depending on the length of words.

    Returns:
        List[str]: List of chunks (i.e: lines) with length at most max_characters_per_chunk.
    """
    words = sentence.split(" ")
    lines = []

    word_idx, anchor = 1, 0
    while anchor <= len(words):
        partial = " ".join(words[anchor : anchor + word_idx])

        if len(partial) > max_characters_per_chunk:
            lines.append(" ".join(words[anchor : anchor + word_idx - 1]))
            anchor += word_idx - 1
            word_idx = 1
            continue

        if anchor + word_idx == len(words):
            lines.append(partial)
            break
        word_idx += 1
    return lines


class RAE(Extension):
    def __init__(self):
        super().__init__()
        self.subscribe(
            KeywordQueryEvent, KeywordQueryEventListener()
        )  # Handle user input via ulauncher.
        self.subscribe(
            PreferencesUpdateEvent, PreferencesUpdateListener()
        )  # Handle preferences update via UI.
        self.subscribe(
            PreferencesEvent, PreferencesEventListener()
        )  # To force reset toggle to be off by default.

    @staticmethod
    def handle_empty_word() -> List[ExtensionResultItem]:
        """Returns the elements to display when an empty word is given to the extension.

        Returns:
            List[ExtensionResultItem]: All elements to be shown by the extension.
        """
        return [
            ExtensionResultItem(
                icon="images/icon.png",
                name="Palabra vacía",
                description="Ingrese una palabra para buscar en el diccionario.",
                on_enter=HideWindowAction(),
            )
        ]

    @staticmethod
    def handle_approx_results(
        approx_results: ResultSet, max_suggested_items: int
    ) -> List[ExtensionResultItem]:
        """All elements to be displayed by the extension when an approximate result is found (i.e.: no exact match for given word is found).

        Args:
            approx_results (ResultSet): The soup ResultSet containing all approximated results.
            max_suggested_items (int): Show, at most, this many of the approximated results in approx_results.

        Returns:
            List[ExtensionResultItem]: All elements to be shown by the extension.
        """
        return [
            ExtensionResultItem(
                icon="images/icon.png",
                name=i.text,  # TODO: This leaves the superscript characters.
                description="Sugerencia RAE",
                on_enter=HideWindowAction(),
            )
            for i in approx_results[:max_suggested_items]
        ]
        # TODO: On ENTER, replace word in ulauncher with the one selected.

    @staticmethod
    def handle_multiple_defs(
        word: str, soup: BeautifulSoup, max_shown_definitions: int
    ) -> List[ExtensionResultItem]:
        """All elements to be displayed by the extension when an exact definition is found.

        Args:
            word (str): Word to which the definitions belong.
            soup (BeautifulSoup): Whole page soup.
            max_shown_definitions (int): Show, at most, this many of the definitions in soup.

        Returns:
            List[ExtensionResultItem]: All elements to be shown by the extension.
        """
        items = []

        resultados = soup.find("div", {"id": "resultados"})
        definitions = resultados.find_all("p", {"class": "j"})

        for definition in definitions[:max_shown_definitions]:
            abbrs = " ".join(abbr.text for abbr in definition.find_all("abbr"))

            words = ""
            for child in definition.children:
                if child.name not in {"span", "abbr"}:
                    if isinstance(child, NavigableString):
                        words += child
                    else:
                        words += child.get_text()
                # words = ' '.join(mark.text for mark in definition.find_all('mark'))
            words = words.strip()
            chunks = chunkize_sentence(words, CHARACTERS_PER_LINE)
            definition_in_lines = "\n".join(chunks)

            items.append(
                ExtensionResultItem(
                    icon="images/icon.png",
                    name=f"{word} [{abbrs}]",
                    description=definition_in_lines,
                    on_enter=HideWindowAction(),
                )
            )
        return items


class KeywordQueryEventListener(EventListener):
    def on_event(
        self, event: KeywordQueryEvent, extension: Extension
    ) -> RenderResultListAction:
        """Handle the user calling the extension via ulauncher.

        Args:
            event (KeywordQueryEvent): The KeywordQueryEvent generated by the user (docs.ulauncher.io/en/latest/extensions/events.html?highlight=KeywordQueryEvent).
            extension (Extension): The Extension.

        Returns:
            RenderResultListAction: Results ready to be displayed by ulauncher.
        """
        items = []

        max_suggested_items = int(extension.preferences["max_suggested_items"])
        max_shown_definitions = int(extension.preferences["max_shown_definitions"])
        print(f"{max_suggested_items=}, {max_shown_definitions=}")

        logger.info(f"max_suggested_items={max_suggested_items}")
        logger.info(f"max_shown_definitions={max_shown_definitions}")

        word = event.get_argument()
        logger.info(f"word={word}")

        if word is None:
            items = RAE.handle_empty_word()
        else:
            req = requests.get(f"{BASE_URL}/{word}", headers=HEADERS)
            soup = BeautifulSoup(req.text, "html.parser")

            approx_results = soup.find_all("a", {"data-acc": "LISTA APROX"})
            if len(approx_results) != 0:
                # Case with no exact match. Items are suggestions.
                items = RAE.handle_approx_results(approx_results, max_suggested_items)
            else:
                # Case with exact match.
                items = RAE.handle_multiple_defs(word, soup, max_shown_definitions)

        return RenderResultListAction(items)


class PreferencesEventListener(EventListener):
    def on_event(self, event: PreferencesEvent, extension: Extension):
        """Set this session's preferences to those of the last session, except for the reset toggle, which is reset to the default.

        Args:
            event (PreferencesEvent): The PreferencesEvent triggered once when the application starts (docs.ulauncher.io/en/latest/extensions/events.html?highlight=PreferencesEvent#preferencesevent).
            extension (Extension): The Extension.
        """
        extension.preferences.update(event.preferences)
        extension.preferences["reset_to_default"] = "-"
        # FIXME: Doesn't set to '-'.


class PreferencesUpdateListener(EventListener):
    def on_event(self, event: PreferencesUpdateEvent, extension: Extension):
        """Update extension preferences when the user saves new ones from the UI.

        Args:
            event (PreferencesUpdateEvent): The PreferencesUpdateEvent triggered when the user clicks SAVE in the Extension preference's page (docs.ulauncher.io/en/latest/extensions/events.html?highlight=PreferencesUpdateEvent#preferencesupdateevent).
            extension (Extension): The extension.
        """
        if event.id in NUMERIC_PREFERENCES:
            if float(event.new_value).is_integer():
                # Don't do the typical try/catch cause 4.2 (not "4.2") would be truncated to 4 and silently change the value to 4, instead of throwing an error.
                extension.preferences[event.id] = int(event.new_value)
                logger.info(
                    f"{event.id} changed from {event.old_value} to {event.new_value}."
                )
            else:
                extension.preferences[event.id] = int(event.old_value)
                logger.info(
                    f"{event.id} failed to change. Reverting to previous value of {event.old_value}. Given: {event.new_value}. Try an integer."
                )
        elif event.id == "reset_to_default" and event.new_value == "Reset":
            for id_, val in DEFAULT_PREFERENCES.items():
                old_val = extension.preferences[id_]
                extension.preferences[id_] = val
                logger.info(
                    f"{id_} was reset from {old_val} to its default value of {val}."
                )
        else:
            extension.preferences[event.id] = event.new_value
            logger.info(
                f"{event.id} changed from {event.old_value} to {event.new_value}."
            )


if __name__ == "__main__":
    RAE().run()
