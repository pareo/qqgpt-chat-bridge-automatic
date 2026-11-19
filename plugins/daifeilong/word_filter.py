"""Local phrase matching for outgoing QQ text."""
from pathlib import Path
import unicodedata


BLOCKED_NOTICE = '这条回复触发了发言过滤'
UNAVAILABLE_NOTICE = '发言过滤模块不可用，请排查'


def normalize(text: str) -> str:
    text = unicodedata.normalize('NFKC', text).casefold()
    return ''.join(char for char in text if unicodedata.category(char) != 'Cf').strip()


class WordFilter:
    def __init__(self, path: Path):
        self.path = path
        self.revision = None
        self.words: tuple[str, ...] = ()

    def notice(self, text: str) -> str | None:
        if not text.strip() or text.strip() in (BLOCKED_NOTICE, UNAVAILABLE_NOTICE):
            return None

        try:
            stat = self.path.stat()
            revision = (stat.st_ino, stat.st_size, stat.st_mtime_ns)
            if revision != self.revision:
                lines = self.path.read_text(encoding='utf-8-sig').splitlines()
                words = tuple(dict.fromkeys(
                    word for line in lines if (word := normalize(line)) and not word.startswith('#')
                ))
                if words:
                    self.words = words
                self.revision = revision
        except (OSError, UnicodeError):
            # Editors may replace the file while saving. Keep the last usable list.
            pass

        if not self.words:
            return UNAVAILABLE_NOTICE
        normalized = normalize(text)
        if any(word in normalized for word in self.words):
            return BLOCKED_NOTICE
        return None
